# -*- coding: utf-8 -*-
"""
素材打标：把背景图和 CG 弹窗喂给视觉模型，产出中文语义标签，存进 aa_assets.db。

这是一次性成本。跑完一次，把 aa_assets.db 拷给别人就行——别人不用再让 AI 看一遍图。
断点续跑：已经标过的会跳过，中途 Ctrl+C 也不会丢已完成的部分。

用法:
  python label_assets.py --init                  只建库、灌已知信息、按命名推断背景
  python label_assets.py --bg                    看图标注背景（跳过已标注的）
  python label_assets.py --popup                 看图标注 CG 弹窗
  python label_assets.py --sound                 按命名翻译音效（不看图，纯文本）
  python label_assets.py --all --limit 20        全部，但只处理 20 条（试水）
  python label_assets.py --export                导出 aa_resources.json 供转换器使用
"""
import argparse, io, json, os, sys, time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aapaths                                                # noqa: E402
import assetdb                                                # noqa: E402
from llm import make_provider, LLMError                       # noqa: E402



BG_SYS = """你在为一个蔚蓝档案（Blue Archive）同人剧情制作工具建立背景素材库。
用户会给你若干张游戏背景图，每张图前面有一行 [文件名] 标出它的标识。
为每张图输出中文标注，供后续自动选背景时检索。

要求：
- label：4-10 字的中文场景名，如「商业街入口」「废弃教室」「夕阳下的天台」
- place：只能填「室内」「室外」「其它」三者之一
- time：只能填「白天」「黄昏」「夜晚」「不明」四者之一
- mood：氛围，如「日常」「紧张」「温馨」「肃穆」「荒凉」「欢快」
- tags：3-6 个中文检索词，逗号分隔，写画面里的具体元素（课桌、樱花、霓虹灯、废墟）
- descr 和 chars 一律留空串

只描述你真正看到的内容，不要根据文件名猜测。"""

POPUP_SYS = """你在为一个蔚蓝档案（Blue Archive）同人剧情制作工具建立 CG 素材库。
用户会给你若干张剧情 CG（立绘特写/事件插图），每张图前面有一行 [文件名] 标出标识。

要求：
- label：4-12 字的中文 CG 名，概括画面在演什么
- descr：一句话描述构图与动作
- chars：画面里出现的角色数量与特征，如「两名少女」「一名短发少女与老师」。认不出具体角色就描述外形，不要瞎猜名字
- tags：3-6 个中文检索词，逗号分隔
- place / time / mood 一律留空串

只描述你真正看到的内容。"""

SOUND_SYS = """你在为一个蔚蓝档案同人剧情工具整理音效库。用户会给你一批音效文件名。
根据命名推断用途，输出中文标注。

- label：4-10 字中文，如「开门声」「键盘打字」「警报响起」
- tags：2-4 个中文使用场景词，逗号分隔，如「室内,进出」
- 其余字段留空串

看不懂的命名，label 填「不明」。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "place": {"type": "string"},
                    "time": {"type": "string"},
                    "mood": {"type": "string"},
                    "descr": {"type": "string"},
                    "chars": {"type": "string"},
                    "tags": {"type": "string"},
                },
                "required": ["key", "label", "place", "time", "mood",
                             "descr", "chars", "tags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def shrink(path, px=560, quality=72):
    """缩到长边 px 的 JPEG——视觉模型看场景够用，token 成本降一个量级。"""
    from PIL import Image
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.thumbnail((px, px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def scan_files(root, exts):
    out = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            stem, ext = os.path.splitext(fn)
            if ext.lower() in exts:
                out.setdefault(stem, os.path.join(dp, fn))
    return out


def label_images(con, prov, table, sysmsg, files, todo, batch, px, dry):
    """通用的看图打标循环。table 决定写哪张表。"""
    done, t0 = 0, time.time()
    for i in range(0, len(todo), batch):
        chunk = [k for k in todo[i:i + batch] if k in files]
        if not chunk:
            continue
        if dry:
            print(f"  [dry] 将发送 {len(chunk)} 张: {'、'.join(chunk[:4])}…")
            done += len(chunk)
            continue
        try:
            images = [(k, shrink(files[k], px)) for k in chunk]
        except Exception as e:
            print(f"  ! 读图失败，跳过这批: {e}")
            continue
        kb = sum(len(b) for _, b in images) // 1024
        sysmsg_with_filename_context = sysmsg + "\nFilename hints (auxiliary only; judge the actual pixels first):\n" + "\n".join(
            f"- key={key}; original_filename={os.path.basename(files[key])}"
            for key in chunk
        )
        try:
            res = prov.complete_json_vision(
                sysmsg_with_filename_context, images,
                f"以上 {len(images)} 张，逐一标注。key 用方括号里的文件名原样填回。",
                SCHEMA)
        except LLMError as e:
            print(f"  ! 这批失败（已保留之前的结果）: {e}")
            continue

        for it in res.get("items", []):
            k = it.get("key")
            if k not in files:
                continue
            by = f"vision:{prov.model}"
            if table == "bg":
                con.execute(
                    "UPDATE bg SET label=?,place=?,time=?,mood=?,tags=?,labeled_by=? "
                    "WHERE name=?",
                    (it.get("label"), it.get("place"), it.get("time"),
                     it.get("mood"), it.get("tags"), by, k))
            else:
                con.execute(
                    "INSERT INTO popup(name,label,descr,chars,tags,labeled_by) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                    "label=excluded.label,descr=excluded.descr,chars=excluded.chars,"
                    "tags=excluded.tags,labeled_by=excluded.labeled_by",
                    (k, it.get("label"), it.get("descr"), it.get("chars"),
                     it.get("tags"), by))
            done += 1
        con.commit()                      # 每批落盘，中断也不丢
        el = time.time() - t0
        print(f"  {done}/{len(todo)}  本批 {len(images)} 张 {kb}KB  "
              f"已用 {el:.0f}s")
    return done


def label_sounds(con, prov, todo, batch, dry):
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        if dry:
            print(f"  [dry] {len(chunk)} 个: {'、'.join(chunk[:5])}…")
            done += len(chunk)
            continue
        try:
            res = prov.complete_json("", SOUND_SYS,
                                     "音效文件名：\n" + "\n".join(chunk), SCHEMA)
        except LLMError as e:
            print(f"  ! 失败: {e}")
            continue
        for it in res.get("items", []):
            if it.get("key") in set(chunk):
                con.execute("UPDATE sound SET label=?,tags=?,labeled_by=? WHERE name=?",
                            (it.get("label"), it.get("tags"),
                             f"text:{prov.model}", it["key"]))
                done += 1
        con.commit()
        print(f"  {done}/{len(todo)}")
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "aa_assets.db"))
    ap.add_argument("--index", default=os.path.join(HERE, "aa_resources.json"))
    ap.add_argument("--overrides", help="AA overrides 目录（不给就自动探测）")
    ap.add_argument("--llm", default=os.path.join(HERE, "llm.json"))
    ap.add_argument("--provider")
    ap.add_argument("--model", help="Vision model ID used for this run only")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--bg", action="store_true")
    ap.add_argument("--popup", action="store_true")
    ap.add_argument("--sound", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--force", action="store_true", help="重标已标注过的")
    ap.add_argument("--limit", type=int, help="最多处理多少条（试水用）")
    ap.add_argument("--batch", type=int, default=8, help="每次请求几张图")
    ap.add_argument("--px", type=int, default=560, help="图片缩放后的长边")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    P = aapaths.require(a.overrides and os.path.dirname(a.overrides))
    a.overrides = a.overrides or P["overrides"]
    con = assetdb.connect(a.db)
    do_bg, do_pop, do_snd = a.bg or a.all, a.popup or a.all, a.sound or a.all

    if a.init or not con.execute("SELECT COUNT(*) FROM bg").fetchone()[0]:
        idx = json.load(open(a.index, encoding="utf-8"))
        n = assetdb.import_index(con, idx)
        n["bg磁盘"] = assetdb.import_bg_files(con, os.path.join(a.overrides, "bgs"))
        got = assetdb.label_bg_from_name(con, a.force)
        assetdb.set_meta(con, schema_version="1", source=a.overrides)
        con.commit()
        print("初始化：" + "  ".join(f"{k} {v}" for k, v in n.items()))
        print(f"按命名推断出 {got} 个背景的初步标签（看图会覆盖得更准）")

    if do_bg or do_pop or do_snd:
        prov = make_provider(a.llm, a.provider)
        if a.model:
            prov.model = str(a.model)
        if hasattr(prov, "_strict_response_format_unavailable") or prov.name == "openai":
            prov._strict_response_format_unavailable = True
        print(f"模型  {prov.name} / {prov.model}\n")

        if do_bg:
            files = scan_files(os.path.join(a.overrides, "bgs"), {".jpg", ".jpeg", ".png", ".webp"})
            q = "SELECT name FROM bg" if a.force else \
                "SELECT name FROM bg WHERE labeled_by IS NULL OR labeled_by NOT LIKE 'vision%'"
            todo = [r[0] for r in con.execute(q) if r[0] in files][:a.limit]
            print(f"背景  磁盘上 {len(files)} 张，待标注 {len(todo)} 个")
            if todo:
                label_images(con, prov, "bg", BG_SYS, files, todo, a.batch, a.px, a.dry_run)

        if do_pop:
            files = scan_files(os.path.join(a.overrides, "popups"), {".png", ".jpg", ".jpeg", ".webp"})
            have = {r[0] for r in con.execute(
                "SELECT name FROM popup WHERE labeled_by LIKE 'vision%'")}
            todo = [k for k in sorted(files) if a.force or k not in have][:a.limit]
            print(f"\nCG弹窗  磁盘上 {len(files)} 张，待标注 {len(todo)} 个")
            if todo:
                label_images(con, prov, "popup", POPUP_SYS, files, todo, a.batch, a.px, a.dry_run)

        if do_snd:
            q = "SELECT name FROM sound" if a.force else \
                "SELECT name FROM sound WHERE labeled_by IS NULL"
            todo = [r[0] for r in con.execute(q)][:a.limit]
            print(f"\n音效  待标注 {len(todo)} 个")
            if todo:
                label_sounds(con, prov, todo, 60, a.dry_run)

        print(f"\n{prov.report()}")

    print("\n=== 素材库现状 ===")
    for k, (total, done) in assetdb.stats(con).items():
        bar = f"{done}/{total}" if done is not None else str(total)
        print(f"  {k:<8} {bar}")

    if a.export:
        assetdb.export_json(con, a.index)
        print(f"\n已导出 {a.index}")
    print(f"数据库  {a.db}")
    print("把这个 .db 拷给别人，他们就不用再让 AI 看一遍图了。")


if __name__ == "__main__":
    main()
