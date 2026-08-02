# -*- coding: utf-8 -*-
"""
打包成可以传 GitHub 的干净目录。

  python prepare_release.py --check          只做安全检查，不拷文件
  python prepare_release.py -o ../release    拷到指定目录
  python prepare_release.py -o ../release --with-db   连素材数据库一起带上

检查项见 UPLOAD.md。核心原则：传代码和知识，不传素材和作品。
"""
import argparse, os, re, shutil, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

CODE = ["script2aap.py", "stage.py", "camera.py", "annotate.py", "prompt.py",
        "llm.py", "tables.py", "aapaths.py", "assetdb.py", "build_index.py",
        "label_assets.py", "verify.py", "webui.py", "ui.html",
        "model_profiles.py", "background_requests.py", "background_workflow.py",
        "asset_catalog.py", "asset_import.py", "asset_models.py",
        "asset_validation.py", "aa_registry.py", "aa_project_assets.py",
        "aa_resource_cache.py", "official_catalog.py", "performance_rules.py",
        "dialogue_pacing.py", "spine_face_analysis.py",
        "spine_face_renderer.py", "spine_face_labeler.py",
        "spine_semantic_faces.py", "launcher.py", "prepare_release.py"]
PROGRAM_FILES = ["启动程序.cmd", "检查运行环境.cmd"]
DATA_FILES = ["aa_resources.json"]
DOCS = ["README.md", "UPLOAD.md", ".gitignore", "使用说明-从这里开始.md"]
EXAMPLES = {"llm.json": "llm.json.example", "cast.json": "cast.example.json"}

BANNED_EXT = {".skel", ".atlas", ".ogg", ".wav", ".mp3", ".jpg", ".jpeg",
              ".db-journal"}
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|"
    r"['\"]?api[_-]?key['\"]?\s*[:=]\s*['\"][^'\"]{20,}['\"])", re.I)
ABS_RE = re.compile(r"[A-Za-z]:\\\\?(?:Users|AzureArchive|桌面|下载)")

REQUIREMENTS = """# 最低要求：Python 3.9+
# 核心功能（转换、校验、路径探测）零依赖，只用标准库。

pillow>=10.0        # 网页界面的缩略图 / 打标时的图片缩放
openai>=1.40        # 可选：OpenAI 兼容接口（GPT / DeepSeek / GLM / Kimi / Qwen）
anthropic>=0.40     # 可选：Claude API（带 prompt caching）
pywin32>=306        # Windows：把 API Key 安全保存到系统凭据管理器
"""


def check():
    bad = []
    print("=== 安全检查 ===\n")

    print("1. 源码里的绝对路径")
    n = 0
    for fn in CODE:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        for i, ln in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            if ABS_RE.search(ln):
                stripped = ln.strip()
                # 注释和文档字符串里的示例路径可以接受
                ok = stripped.startswith("#") or stripped.startswith('"') or \
                    "例" in ln or "示例" in ln or "比如" in ln or "长这样" in ln
                mark = "  （注释/示例，可接受）" if ok else "   ← 要改成自动探测"
                if not ok:
                    bad.append(f"{fn}:{i} 硬编码路径")
                    n += 1
                print(f"   {fn}:{i}{mark}")
    print(f"   -> {'干净' if n == 0 else f'{n} 处需要改'}\n")

    print("2. 疑似泄露的密钥")
    n = 0
    for dp, dns, fns in os.walk(HERE):
        dns[:] = [d for d in dns if d not in ("__pycache__", ".thumbs", "out", ".git")]
        for fn in fns:
            if os.path.splitext(fn)[1] not in (".py", ".json", ".md", ".html", ".txt"):
                continue
            p = os.path.join(dp, fn)
            try:
                t = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for m in SECRET_RE.finditer(t):
                bad.append(f"{os.path.relpath(p, HERE)} 疑似密钥")
                print(f"   {os.path.relpath(p, HERE)}: {m.group(0)[:28]}…")
                n += 1
    print(f"   -> {'干净' if n == 0 else f'{n} 处'}\n")

    print("3. 目录里的版权素材")
    big, cnt = 0, 0
    for dp, dns, fns in os.walk(HERE):
        dns[:] = [d for d in dns if d not in ("__pycache__", ".git")]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext in BANNED_EXT or fn.endswith("-avatar.png"):
                p = os.path.join(dp, fn)
                big += os.path.getsize(p)
                cnt += 1
    if cnt:
        print(f"   目录里有 {cnt} 个素材文件（{big/1024/1024:.1f} MB）—— "
              f".gitignore 会挡住，但别手动 git add -f")
    else:
        print("   干净")
    print()

    print("4. 跨机器适配")
    sys.path.insert(0, HERE)
    import aapaths
    p = aapaths.detect()
    if p["data"]:
        print(f"   本机探测到：{p['data']}（来源：{p['source']}）")
        print("   换台电脑时会按同样顺序找：aa_config.json -> 环境变量 AA_DATA")
        print("   -> AA 设置里的 workspacePath -> AppData 默认位置")
    else:
        print("   本机没探测到 AA，但这不影响发布")
    print()

    if bad:
        print(f"✗ {len(bad)} 个问题要处理：")
        for b in bad:
            print("   " + b)
        return False
    print("✓ 可以发布")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", help="输出目录")
    ap.add_argument("--check", action="store_true", help="只检查不拷贝")
    ap.add_argument("--with-db", action="store_true",
                    help="连 aa_assets.db 一起带上（打标成果，纯元数据不含素材）")
    a = ap.parse_args()

    ok = check()
    if a.check or not a.out:
        if not a.out and not a.check:
            print("\n加 -o <目录> 才会真正拷贝")
        sys.exit(0 if ok else 1)
    if not ok:
        print("\n检查没过，先修再打包。硬要打包加 --force（没做，故意的）")
        sys.exit(1)

    out = os.path.abspath(a.out)
    aa = os.path.join(out, "aa")
    docs = os.path.join(out, "docs")
    for d in (out, aa, docs, os.path.join(out, "examples")):
        os.makedirs(d, exist_ok=True)

    n = 0
    for fn in CODE:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(aa, fn))
            n += 1
    for fn in PROGRAM_FILES + DATA_FILES:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(aa, fn))
            n += 1
    for src, dst in EXAMPLES.items():
        p = os.path.join(HERE, src)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(aa, dst))
            n += 1
    for fn in DOCS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(out, fn))
            n += 1
    docs_source = os.path.join(HERE, "docs")
    if os.path.isdir(docs_source):
        for dp, _, files in os.walk(docs_source):
            relative = os.path.relpath(dp, docs_source)
            destination = (
                docs
                if relative == "."
                else os.path.join(docs, relative)
            )
            os.makedirs(destination, exist_ok=True)
            for fn in files:
                shutil.copy2(
                    os.path.join(dp, fn),
                    os.path.join(destination, fn),
                )
                n += 1
    if a.with_db:
        p = os.path.join(HERE, "aa_assets.db")
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(aa, "aa_assets.db"))
            n += 1
            print("  已带上 aa_assets.db（记得把 .gitignore 里那行注释掉）")

    with open(os.path.join(out, "requirements.txt"), "w", encoding="utf-8") as fh:
        fh.write(REQUIREMENTS)
    n += 1

    root_launch = os.path.join(out, "启动AA自动写剧本.cmd")
    with open(root_launch, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(
            '@echo off\nchcp 65001 >nul\n'
            'call "%~dp0aa\\启动程序.cmd"\n'
            'exit /b %errorlevel%\n'
        )
    root_check = os.path.join(out, "检查运行环境.cmd")
    with open(root_check, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write(
            '@echo off\nchcp 65001 >nul\n'
            'call "%~dp0aa\\检查运行环境.cmd"\n'
            'exit /b %errorlevel%\n'
        )
    n += 2

    demo = os.path.join(out, "examples", "demo.txt")
    with open(demo, "w", encoding="utf-8") as fh:
        fh.write(DEMO)
    n += 1

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(out) for f in fs)
    print(f"\n拷了 {n} 个文件到 {out}")
    print(f"总体积 {total/1024:.0f} KB" +
          ("   ← 超过 5MB，检查是不是混进素材了" if total > 5 * 1024 * 1024 else ""))
    print("\n接下来：")
    print(f"  cd {out}")
    print("  git init && git add . && git commit -m 'initial'")


DEMO = """# 示例剧本

## 千年科技学园·活动室

@bg BG_GameDevRoom
@place 千年科技学园·游戏开发部
@se SE_Typing_01
旁白: 键盘声一直没停过。

桃井(03): 这个演出再加一段就完美了！

绿(05): 今天上传的只是内部原型。

桃井(03)[怒筋]: 正因为是原型，第一印象才更重要嘛！

绿(01): 我们本来就在赶工。

@bgfx 集中线
凯伊(05)<特写>: 都停一下。

@wait 2000
旁白: 活动室安静了两秒。

## 当晚

@bg BG_MainOffice_Night
@trans 淡入淡出 1500
旁白: 晚上九点零七分。

凯伊(02): 明天下午有空吗？
"""


if __name__ == "__main__":
    main()
