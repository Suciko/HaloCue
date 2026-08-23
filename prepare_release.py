# -*- coding: utf-8 -*-
"""
打包成可以传 GitHub 的干净目录。

  python prepare_release.py --check          只做安全检查，不拷文件
  python prepare_release.py -o ../release    拷到指定目录
  python prepare_release.py -o ../release --with-db   连素材数据库一起带上
  python prepare_release.py -o ../release --release-095  发布统一的 0.95 包

检查项见 UPLOAD.md。核心原则：传代码和知识，不传素材和作品。
"""
import argparse, json, os, re, shutil, sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))

CODE = [
    # Core compiler and web entry points.
    "script2aap.py", "stage.py", "camera.py", "annotate.py", "prompt.py",
    "llm.py", "tables.py", "aapaths.py", "assetdb.py", "build_index.py",
    "label_assets.py", "verify.py", "webui.py", "ui.html", "launcher.py",
    "runtime_layout.py", "prepare_release.py",
    # 0.95 director pipeline and its protocol/state/quality chain.
    "annotation_scene_planner.py", "annotation_safety.py",
    "annotation_telemetry.py", "annotation_chunks.py", "annotation_protocol.py",
    "annotation_memory.py", "annotation_agent.py", "direction_quality.py",
    "direction_rules.py", "director_policy.py", "director_state.py",
    "performance_rules.py", "dialogue_pacing.py",
    # Resource, background and character-labeling features used by 0.95.
    "asset_catalog.py", "asset_import.py", "asset_models.py", "asset_validation.py",
    "aa_registry.py", "aa_project_assets.py", "aa_install_discovery.py",
    "aa_resource_cache.py", "official_catalog.py", "official_preview_index.py",
    "background_requests.py", "background_workflow.py", "background_labeler.py",
    "scene_asset_labeler.py", "batch_label_scene_assets.py", "portrait_layout.py",
    "face_selection.py", "face_semantics.py", "face_label_backend.py",
    # Web workbench/runtime support imported by webui and launcher.
    "model_capabilities.py", "model_profiles.py", "model_router.py",
    "document.py", "diagnostics.py", "draft_identity.py", "draft_store.py",
    "history_assets.py", "install_manager.py", "jobs.py", "picker_token.py",
    "story_file_picker.py", "story_workspace.py", "build_bundle.py",
    "spine_face_analysis.py", "spine_face_browser.py", "spine_face_renderer.py",
    "spine_face_web_renderer.py", "desktop_app.py", "build_desktop_release.py",
    "spine_face_labeler.py", "spine_semantic_faces.py",
    "official_face_examples.py",
]
PROGRAM_FILES = ["启动程序.cmd", "检查运行环境.cmd"]
DATA_FILES = [
    "aa_resources.json",
    "portrait_layout_hints.json",
    # Name aliases are runtime data, not private user configuration.  Keep
    # the source package aligned with the desktop bundle's character lookup.
    "character_aliases.json",
]
STATIC_DIRS = ["js", "css", os.path.join("tools", "spine_web_runtime")]
DOCS = ["README.md", "UPLOAD.md", ".gitignore", "使用说明-从这里开始.md"]
EXAMPLES = {"llm.json": "llm.json.example", "cast.json": "cast.example.json"}

BANNED_EXT = {".skel", ".atlas", ".ogg", ".wav", ".mp3", ".jpg", ".jpeg",
              ".db-journal"}
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|"
    r"['\"]?api[_-]?key['\"]?\s*[:=]\s*['\"][^'\"]{20,}['\"])", re.I)
ABS_RE = re.compile(r"[A-Za-z]:\\\\?(?:Users|AzureArchive|桌面|下载)")
TEXT_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]"
    r"(?=(?:Users|AzureArchive|桌面|下载)(?=[^A-Za-z0-9]|$))"
)

_SKIP_DIR_NAMES = {
    "__pycache__", ".git", ".worktrees", ".venv-desktop-build", "build",
    "dist", "output", "release-output", ".playwright-cli", ".thumbs",
    "overrides", "assets", "out",
}


def _skip_directory(name):
    return name in _SKIP_DIR_NAMES or name.startswith(".pytest-")


def _sanitize_json_value(value):
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, str) and ABS_RE.search(value):
        return ""
    return value


def _sanitized_json_copy(source, destination):
    """Copy a JSON resource snapshot without machine-specific paths."""
    try:
        value = json.loads(open(source, encoding="utf-8").read())
    except (OSError, ValueError, TypeError):
        shutil.copy2(source, destination)
        return
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(_sanitize_json_value(value), handle, ensure_ascii=False, indent=1)


def _sanitized_text_copy(source, destination):
    """Copy public text while removing machine-specific drive prefixes."""
    try:
        text = open(source, encoding="utf-8", errors="replace").read()
    except OSError:
        shutil.copy2(source, destination)
        return
    text = TEXT_PATH_RE.sub("<local-path>/", text)
    with open(destination, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _configured_overlay_databases():
    config_path = os.path.join(HERE, "aa_config.json")
    try:
        values = json.loads(open(config_path, encoding="utf-8").read())
    except (OSError, ValueError, TypeError):
        return []
    raw = values.get("asset_databases") if isinstance(values, dict) else []
    if isinstance(raw, (str, os.PathLike)):
        raw = [raw]
    return [str(path) for path in raw or [] if os.path.isfile(os.path.expanduser(str(path)))]


def _copy_database_seed(source, destination, source_index):
    """Create a path-free 0.95 database seed while retaining semantic labels."""
    from build_desktop_release import prepare_release_seed

    source = os.fspath(source)
    destination = os.fspath(destination)
    source_index = os.fspath(source_index)
    staging = destination + ".staging"
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    prepare_release_seed(source, source_index, staging)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.move(os.path.join(staging, "aa_assets.db"), destination)
    shutil.rmtree(staging, ignore_errors=True)


REQUIREMENTS = """# 最低要求：Python 3.9+
# 核心功能（转换、校验、路径探测）零依赖，只用标准库。

pillow>=10.0        # 网页界面的缩略图 / 打标时的图片缩放
UnityPy>=1.25.2     # 从用户自己的 AA 资源包生成本地官方图片预览
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
        dns[:] = [d for d in dns if not _skip_directory(d)]
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
        dns[:] = [d for d in dns if not _skip_directory(d)]
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
    ap.add_argument(
        "--release-095", action="store_true",
        help="生成统一可公开分发的 0.95 包：带路径清理后的主库和只读叠加库",
    )
    # Kept as a compatibility alias for the first two local 0.95 builds.
    ap.add_argument("--private-095", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument(
        "--overlay-db", action="append", default=[],
        help="0.95 发布包的第二标注数据库；可重复传入",
    )
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
    release_095 = a.release_095 or a.private_095
    if release_095 and os.path.exists(out):
        print(f"\n拒绝覆盖已有目录：{out}")
        print("请使用新的独立输出目录，以保留旧发布和盲测封存。")
        sys.exit(1)
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
            destination = os.path.join(aa, fn)
            if os.path.splitext(fn)[1].lower() == ".json":
                _sanitized_json_copy(p, destination)
            else:
                shutil.copy2(p, destination)
            n += 1
    for src, dst in EXAMPLES.items():
        p = os.path.join(HERE, src)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(aa, dst))
            n += 1
    for fn in DOCS:
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            _sanitized_text_copy(p, os.path.join(out, fn))
            n += 1
    for relative_dir in STATIC_DIRS:
        source_dir = os.path.join(HERE, relative_dir)
        if not os.path.isdir(source_dir):
            continue
        for dp, _, files in os.walk(source_dir):
            relative = os.path.relpath(dp, HERE)
            destination = os.path.join(aa, relative)
            os.makedirs(destination, exist_ok=True)
            for fn in files:
                # Runtime bundles are intentionally included: they are the
                # local WebGL code used by the face browser, not game assets.
                shutil.copy2(os.path.join(dp, fn), os.path.join(destination, fn))
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
                source = os.path.join(dp, fn)
                _sanitized_text_copy(source, os.path.join(destination, fn))
                n += 1
    if release_095:
        primary = os.path.join(HERE, "aa_assets.db")
        if not os.path.isfile(primary):
            print("\n0.95 包缺少主数据库 aa_assets.db")
            sys.exit(1)
        primary_index = os.path.join(HERE, "aa_resources.json")
        _copy_database_seed(primary, os.path.join(aa, "aa_assets.db"), primary_index)
        n += 1

        overlays = a.overlay_db or _configured_overlay_databases()
        overlays = [os.path.abspath(os.path.expanduser(path)) for path in overlays]
        overlays = list(dict.fromkeys(overlays))
        if not overlays:
            print("\n0.95 包没有找到第二标注数据库；请传 --overlay-db")
            sys.exit(1)
        config_databases = []
        database_dir = os.path.join(aa, "databases")
        for index, source in enumerate(overlays, 1):
            if not os.path.isfile(source):
                print(f"\n第二标注数据库不存在：{source}")
                sys.exit(1)
            source_index = os.path.join(os.path.dirname(source), "aa_resources.json")
            if not os.path.isfile(source_index):
                source_index = primary_index
            filename = f"overlay-{index}-aa-assets.db"
            _copy_database_seed(
                source,
                os.path.join(database_dir, filename),
                source_index,
            )
            config_databases.append(f"databases/{filename}")
            n += 1
        with open(os.path.join(aa, "aa_config.json"), "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "pipeline": "0.95",
                    "prompt_revision": "v10-canonical-emo-protocol",
                    "asset_databases": config_databases,
                    "database_policy": "read_only_overlay",
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        with open(os.path.join(out, "0.95-发布说明.md"), "w", encoding="utf-8") as fh:
            fh.write(
                "# HaloCue 0.95 发布包\n\n"
                "本包包含 0.95 G1/G2 导演链路、背景分类检索、全量表情语义和只读数据库叠加。\n"
                "数据库只含资源名称与标注元数据，不含 AA 图片、音频或 Spine 素材。\n"
                "首次运行请双击 `检查运行环境.cmd`，再配置本机 AzureArchive 和模型接口。\n"
            )
            n += 1
        print("  已生成 0.95 发布包数据库：主库 + " + str(len(config_databases)) + " 个只读叠加库")
    elif a.with_db:
        p = os.path.join(HERE, "aa_assets.db")
        if os.path.exists(p):
            _copy_database_seed(
                p,
                os.path.join(aa, "aa_assets.db"),
                os.path.join(HERE, "aa_resources.json"),
            )
            n += 1
            print("  已带上路径清理后的 aa_assets.db")

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
