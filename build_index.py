# -*- coding: utf-8 -*-
"""
扫描 AzureArchive 存储目录，生成 aa_resources.json 资源索引。

产出内容：
  - bg          背景名 -> bgName 哈希（从历史工程中收割，AA 的哈希算法未公开）
  - sounds      可用音效名
  - characters  全局素材库角色（identifier / 中文名 / 社团 / 表情表）
  - emoticon / action / appear / shape   数字枚举 -> 语义（由 .aap↔.aas 配对反推）

用法:  python build_index.py [--data <AA存储目录>]
"""
import argparse, glob, hashlib, json, os, re, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aapaths                                              # noqa: E402
from official_catalog import (                              # noqa: E402
    locate_character_table_bundle,
    read_character_table_bundle,
    select_native_characters,
)

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))

# 由 .aap ↔ .aas 配对反推得到，见 README。数值为 AA 工程文件中的整数。
EMOTICON = {
    0: "[빠직]", 1: "[재잘]", 2: "…", 3: "[!]", 4: "[하트]", 5: "[음표]",
    6: "[?]", 7: "[반응]", 8: "[///]", 9: "[?!]", 10: "[땀]", 11: "[반짝]",
    12: "[속상함]", 13: "[딴생각]", 14: "{Bulb}", 15: "{Sad}", 16: "{Sigh}",
    17: "{Steam}", 18: "{Tear}", 19: "{Zzz}",
}
EMOTICON_CN = {
    0: "怒筋", 1: "叽喳", 2: "沉默", 3: "惊叹", 4: "爱心", 5: "音符",
    6: "疑问", 7: "反应", 8: "脸红", 9: "惊疑", 10: "冷汗", 11: "闪亮",
    12: "难过", 13: "走神", 14: "灵光一闪", 15: "悲伤", 16: "叹气",
    17: "冒烟", 18: "落泪", 19: "瞌睡",
}
ACTION = {0: "", 1: "greeting", 2: "falldownl", 3: "falldownr",
          4: "stiff", 5: "shake", 6: "jump", 7: "hophop"}
ACTION_CN = {1: "向下确认", 2: "向左倒", 3: "向右倒", 4: "小颤抖", 5: "大颤抖",
             6: "跳", 7: "蹦跳"}
APPEAR = {0: "", 1: "al", 2: "ar", 3: "a", 4: "dl", 5: "dr", 6: "d"}
APPEAR_CN = {1: "从右入场", 2: "从左入场", 3: "登场", 4: "向左退场",
             5: "向右退场", 6: "退场"}
# Only confirmed values are exposed to generators and models.  Other corpus
# observations are evidence, not selectable effects.
SHAPE = {0: "", 1: "communication", 2: "silhouette", 3: "communication+silhouette",
         4: "closeup", 5: "communication+closeup", 6: "silhouette+closeup",
         7: "communication+silhouette+closeup"}
SHAPE_CN = {1: "通讯", 2: "黑屏剪影", 3: "通讯+黑屏剪影", 4: "特写",
            5: "通讯+特写", 6: "黑屏剪影+特写", 7: "通讯+黑屏剪影+特写"}


def harvest_bg(data):
    """从所有历史 .aap 里收割 背景名 -> 哈希 的对应关系。"""
    pairs, conflict = {}, set()

    def walk(o):
        if isinstance(o, dict):
            if str(o.get("$type", "")).startswith("ScriptData,"):
                fn, bn = o.get("bgFriendlyName", ""), o.get("bgName", 0)
                if fn and bn:
                    if fn in pairs and pairs[fn] != bn:
                        conflict.add(fn)
                    pairs[fn] = bn
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in glob.glob(os.path.join(data, "projects", "**", "*.aap"), recursive=True):
        try:
            with open(f, encoding="utf-8") as fh:
                walk(json.load(fh))
        except Exception:
            continue
    for c in conflict:
        pairs.pop(c, None)
    return pairs, sorted(conflict)


FACE_ALIAS = {  # 官方美术的拼写错误 -> 归一化语义
    "embarassed": "embarrassed", "embrassed": "embarrassed", "embarrased": "embarrassed",
    "emvarassed": "embarrassed", "embarrass": "embarrassed", "nomal": "normal",
    "defualt": "default", "deuflat": "default", "depressde": "depressed",
    "deparaeesd": "depressed", "repond": "respond", "sarcatic": "sarcastic",
    "yarn": "yawn", "serioous": "serious", "inocent": "innocent",
    "eyeclosed": "eyeclose", "eye_close": "eyeclose", "thingking": "thinking",
}


def faces_of(atlas_path):
    """从 .atlas 读表情区域：'03_smile' -> {'id':'03','label':'smile'}"""
    out = []
    try:
        with open(atlas_path, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^(\d{2})_(\S+?)\s*$", line)
                if m:
                    lab = m.group(2)
                    key = re.sub(r"_\d+$|_0\d$", "", lab).lower()
                    out.append({"id": m.group(1), "raw": lab,
                                "label": FACE_ALIAS.get(key, key)})
                elif re.match(r"^(\d{2})\s*$", line):        # 无语义名的追加差分
                    out.append({"id": line.strip(), "raw": line.strip(), "label": ""})
    except Exception:
        pass
    return out


def harvest_characters(data):
    mpath = os.path.join(data, "overrides", "manifest.json")
    if not os.path.exists(mpath):
        return []
    man = json.load(open(mpath, encoding="utf-8"))
    chars = []
    for c in man.get("CharacterOverrides", []):
        spine = c.get("SpinePortraitPath") or ""
        faces = []
        if spine:
            asset = os.path.basename(spine)
            atlas = os.path.join(data, "overrides", os.path.dirname(spine), asset + ".atlas")
            faces = faces_of(atlas)
            skel = os.path.join(data, "overrides", os.path.dirname(spine), asset + ".skel")
        else:
            skel = ""
        spine_signature = ""
        if skel and os.path.isfile(skel):
            with open(skel, "rb") as fh:
                spine_signature = hashlib.sha256(fh.read()).hexdigest()
        chars.append({
            "identifier": c.get("Identifier"), "name": c.get("Name"),
            "club": c.get("Nickname"), "spine": spine, "faces": faces,
            "spine_signature": spine_signature,
            "outfit_key": os.path.basename(spine) if spine else "",
        })
    return chars


def harvest_official_characters(*, cache_root, catalog_path, observed_identifiers=()):
    """Read AA-native labels/IDs from ScenarioCharacterNameExcel.

    ``CharacterOverrides`` only describes imported assets.  Native portraits
    live in Addressables, so their Traditional-Chinese labels must come from
    AA's own FlatData table instead.
    """
    bundle = locate_character_table_bundle(catalog_path, cache_root)
    rows = read_character_table_bundle(bundle)
    return select_native_characters(rows, observed_identifiers)


# AA 内置角色（韩文名那批）的立绘在 Addressables 包里，磁盘上没有 .atlas 可读。
# 退而求其次：从历史工程里统计每个标识实际用过哪些 faceId —— 用过的必然存在。
# 0~6 是蔚蓝档案标准表情位，语义固定；7 以上是各角色自己的追加差分，无法命名。
BA_STD = {"00": "default", "01": "normal", "02": "respond", "03": "smile",
          "04": "embarrassed", "05": "serious", "06": "depressed"}


def harvest_faces_used(data):
    used = defaultdict(lambda: defaultdict(int))

    def walk(o):
        if isinstance(o, dict):
            if str(o.get("$type", "")).startswith("ScriptData+CharacterRecordData"):
                if o.get("name") and o.get("faceId"):
                    used[o["name"]][o["faceId"]] += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in glob.glob(os.path.join(data, "projects", "**", "*.aap"), recursive=True):
        try:
            walk(json.load(open(f, encoding="utf-8")))
        except Exception:
            continue

    out = {}
    for ident, faces in used.items():
        keep = sorted(faces)
        if keep:
            out[ident] = [{"id": f, "raw": f, "label": BA_STD.get(f, "")} for f in keep]
    return out
def _project_character_variants(aap_path):
    """Return the exact skeleton variant selected by one project manifest.

    AA stores a project .aap either beside its manifest or one level above a
    same-named project folder.  The manifest is the only local proof that an
    AAP character identifier belonged to a particular custom Spine bundle.
    """
    folder = os.path.dirname(aap_path)
    stem = os.path.splitext(os.path.basename(aap_path))[0]
    candidates = [os.path.join(folder, stem), folder]
    for project_dir in candidates:
        manifest_path = os.path.join(project_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            manifest = json.load(open(manifest_path, encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        variants = {}
        for row in manifest.get("CharacterOverrides", []):
            identifier = str(row.get("Identifier") or "")
            spine = str(row.get("SpinePortraitPath") or "")
            if not identifier or not spine:
                continue
            relative = spine.replace("\\", "/").split("/")
            skel = os.path.join(project_dir, *relative) + ".skel"
            signature = ""
            if os.path.isfile(skel):
                with open(skel, "rb") as fh:
                    signature = hashlib.sha256(fh.read()).hexdigest()
            variants[identifier] = (signature, os.path.basename(spine), spine)
        return variants
    return {}


def harvest_face_capabilities(data):
    """Return atlas candidates and AAP observations scoped to their skeleton."""
    capabilities = defaultdict(list)
    for character in harvest_characters(data):
        ident = character.get("identifier")
        if not ident:
            continue
        faces = {}
        for face in character["faces"]:
            faces.setdefault(face["id"], {
                "id": face["id"], "raw": face["raw"], "label": face["label"], "cn": "",
                "sources": ["atlas_candidate"], "observed_count": 0, "verified": False,
            })
        capabilities[ident].append({
            "spine_signature": character["spine_signature"],
            "outfit_key": character["outfit_key"], "spine": character["spine"],
            "faces": [faces[key] for key in sorted(faces)],
        })

    observed = defaultdict(lambda: defaultdict(int))
    def walk(value, variants):
        if isinstance(value, dict):
            if str(value.get("$type", "")).startswith("ScriptData+CharacterRecordData"):
                if value.get("name") and value.get("faceId"):
                    identifier = str(value["name"])
                    signature, outfit_key, spine = variants.get(identifier, ("", "", ""))
                    observed[(identifier, signature, outfit_key, spine)][str(value["faceId"])] += 1
            for child in value.values():
                walk(child, variants)
        elif isinstance(value, list):
            for child in value:
                walk(child, variants)
    for path in glob.glob(os.path.join(data, "projects", "**", "*.aap"), recursive=True):
        try:
            walk(json.load(open(path, encoding="utf-8")), _project_character_variants(path))
        except Exception:
            continue
    for (ident, signature, outfit_key, spine), faces in observed.items():
        capabilities[ident].append({
            "spine_signature": signature, "outfit_key": outfit_key, "spine": spine,
            "faces": [{
                "id": face, "raw": face, "label": BA_STD.get(face, ""), "cn": "",
                "sources": ["aap_observed"], "observed_count": count, "verified": False,
            } for face, count in sorted(faces.items())],
        })
    return dict(capabilities)


def harvest_sounds(data):
    mpath = os.path.join(data, "overrides", "manifest.json")
    if not os.path.exists(mpath):
        return []
    man = json.load(open(mpath, encoding="utf-8"))
    out = set()
    for s in man.get("SoundOverrides", []):
        out.add(os.path.splitext(os.path.basename(s.replace("\\\\", "/").replace("\\", "/")))[0])

    def walk(o):
        if isinstance(o, dict):
            if str(o.get("$type", "")).startswith("ScriptData,") and o.get("sound"):
                out.add(o["sound"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in glob.glob(os.path.join(data, "projects", "**", "*.aap"), recursive=True):
        try:
            walk(json.load(open(f, encoding="utf-8")))
        except Exception:
            continue
    return sorted(out)


def build_resource_index(data, *, cache=None, aa_install=None, out=None):
    """从 AA 工作区构建 ``aa_resources.json`` 索引内容。

    CLI（main）与 Web UI 共用同一实现，保证产出一致。
    返回 ``(index_dict, stats_dict)``；给出 *out* 时同时写入该路径。
    """
    P = aapaths.require(data)
    data = P["data"]

    bg, conflict = harvest_bg(data)
    chars = harvest_characters(data)
    sounds = harvest_sounds(data)
    faces_used = harvest_faces_used(data)
    face_capabilities = harvest_face_capabilities(data)

    official = []
    warnings = []
    cache_root = cache or P.get("cache")
    catalog_path = None
    if aa_install:
        candidate = os.path.join(aa_install, "AzureArchive_Data", "StreamingAssets", "aa", "catalog.json")
        if os.path.isfile(candidate):
            catalog_path = candidate
        else:
            warnings.append(f"AA 安装目录中没有 catalog.json，跳过官方角色表：{candidate}")
    if cache_root and catalog_path:
        try:
            official = harvest_official_characters(
                cache_root=cache_root, catalog_path=catalog_path,
                observed_identifiers=faces_used.keys(),
            )
            for row in official:
                row["faces"] = faces_used.get(row["identifier"], [])
                row["spine_signature"] = ""
                row["outfit_key"] = os.path.basename(row["spine"])
        except (FileNotFoundError, LookupError, ValueError, KeyError) as exc:
            warnings.append(f"官方角色表未导入：{exc}")

    # A custom override intentionally takes precedence over a native row with
    # the same opaque identifier.
    custom_ids = {str(row.get("identifier")) for row in chars}
    chars.extend(row for row in official if str(row["identifier"]) not in custom_ids)

    idx = {
        "_source": data,
        "bg": bg,
        "bg_conflict": conflict,
        "sounds": sounds,
        "characters": chars,
        "faces_used": faces_used,
        "face_capabilities": face_capabilities,
        "enums": {
            "emoticon": {str(k): {"sym": EMOTICON[k], "cn": EMOTICON_CN.get(k, "")} for k in EMOTICON},
            "action": {str(k): {"verb": ACTION[k], "cn": ACTION_CN.get(k, "")} for k in ACTION if k},
            "appear": {str(k): {"verb": APPEAR[k], "cn": APPEAR_CN.get(k, "")} for k in APPEAR if k},
            "shape": {str(k): {"verb": SHAPE[k], "cn": SHAPE_CN.get(k, "")} for k in SHAPE if k},
        },
    }
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(idx, fh, ensure_ascii=False, indent=1)

    stats = {
        "data": data,
        "source": P.get("source"),
        "backgrounds": len(bg),
        "bg_conflicts": len(conflict),
        "sounds": len(sounds),
        "characters": len(chars),
        "custom": len(chars) - len(official),
        "official": len(official),
        "withface": sum(1 for c in chars if c["faces"]),
        "faces_used": len(faces_used),
        "warnings": warnings,
    }
    return idx, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="AA 存储目录（不给就自动探测）")
    ap.add_argument("--cache", help="AA 官方资源缓存目录（默认从工作区探测）")
    ap.add_argument("--aa-install", help="AA 安装目录；用于读取 Addressables catalog.json")
    ap.add_argument("--out", default=os.path.join(HERE, "aa_resources.json"))
    a = ap.parse_args()

    idx, stats = build_resource_index(
        a.data, cache=a.cache, aa_install=a.aa_install, out=a.out)
    print(f"AA 存储目录  {stats['data']}   （来源：{stats['source']}）")
    for warning in stats["warnings"]:
        print("警告：" + warning)
    print(f"背景  {stats['backgrounds']} 个" + (f"（{stats['bg_conflicts']} 个同名冲突已剔除）" if stats["bg_conflicts"] else ""))
    print(f"音效  {stats['sounds']} 个")
    print(f"角色  {stats['characters']} 个（自定义 {stats['custom']} / 官方 {stats['official']}），其中 {stats['withface']} 个成功读出表情表")
    print(f"实测  另有 {stats['faces_used']} 个标识从历史工程反查出可用表情（覆盖内置角色）")
    print(f"枚举  emoticon {len(EMOTICON)} / action {len(ACTION)-1} / appear {len(APPEAR)-1} / shape 4")
    print(f"\n已写入 {a.out}")


if __name__ == "__main__":
    main()
