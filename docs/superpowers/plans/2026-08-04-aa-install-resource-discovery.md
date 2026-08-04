# AA Install and Resource Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户只选择 `AzureArchive.exe` 或 AA 安装目录，就能自动定位当前工作区、`.aap/.aas`、官方资源缓存，并在本机建立可供背景和角色选择界面使用的预览索引。

**Architecture:** 新建纯 Python 路径发现模块，以 Unity `app.info` 确认程序身份，以 AA 的 `user_settings.json` 作为工作区和缓存路径真源；`aapaths.py` 保留旧字典接口作为兼容适配层。资源侧分成快速 UnityFS 探测和异步本地预览索引两层，Web 层只消费结构化结果与受控预览键，不向浏览器暴露哈希缓存内部路径。

**Tech Stack:** Python 3.9+、标准库 `dataclasses/pathlib/json/hashlib/threading`、UnityPy 1.25.2+、Pillow 10.0+、SQLite、原生 JavaScript/CSS、pytest、Node 运行时 UI 契约测试、Playwright。

## Global Constraints

- EXE 是发现入口，AA 自己的 `workspacePath` 和 `cachePath` 是路径真源。
- 仍兼容用户直接选择 `data` 或工作区父目录；本次显式 `data` 选择不得被旧配置覆盖。
- 不做整盘或无界递归扫描，只检查设计文档列出的有限位置。
- 不修改 AA 的 EXE、配置、AssetBundle、工作区内容或文件时间戳。
- 不随发布包分发解包出的背景、头像、表格或 AssetBundle。
- 本地预览只写入程序的 `out/official-previews`，该目录继续被 Git 忽略。
- “资源包已安装”和“预览索引已生成”必须是两个独立状态。
- 资源索引单文件损坏时记录并跳过，不能让整次任务丢失已经完成的结果。
- 现有 `detect(explicit)`、`require(explicit)`、`save_config(data_dir)` 调用保持兼容。
- 原始 TXT/Markdown 继续由剧情工作区索引管理，不声称 AA 能定位任意源剧本。
- 路径设置接口可以返回设置页需要核对的规范化目录，但普通素材接口不得返回哈希缓存内部路径。
- 保留工作区中与本功能无关的现有改动；每次提交只暂存任务列出的文件。

---

## File Structure

- Create `aa_install_discovery.py`: 纯路径规范化、Unity 身份读取、LocalLow/工作区/缓存候选解析和结构化发现结果。
- Modify `aapaths.py`: 将旧入口适配到结构化发现器，并兼容旧配置格式。
- Modify `launcher.py`: 接受 EXE/安装目录，报告工作区与资源状态，并通过 Windows 文件选择器引导首次配置。
- Modify `aa_resource_cache.py`: 有界 UnityFS 快速探测与资源缓存状态。
- Modify `official_catalog.py`: 通用 Addressables bundle 定位，不依赖固定哈希。
- Create `official_preview_index.py`: 官方背景和角色头像的本地缩略图索引、状态、增量恢复和安全路径解析。
- Modify `assetdb.py`: 保存官方角色表中的 `avatar` 路径键。
- Modify `build_index.py`: 保留并导入官方角色 `avatar` 元数据。
- Modify `webui.py`: 设置 API、运行状态、预览索引任务和官方预览服务。
- Modify `ui.html`, `js/app.js`, `css/app.css`, `css/layout.css`: AA 安装与资源状态界面、索引进度和图片预览接入。
- Modify `prepare_release.py`, `README.md`, `使用说明-从这里开始.md`: 发布依赖、文件清单和用户说明。
- Create `tests/test_aa_install_discovery.py`: 安装、LocalLow、重定向工作区、冲突和历史文件测试。
- Modify `tests/test_aa_resource_cache.py`, `tests/test_official_catalog.py`: 快速探测与通用 catalog 解析测试。
- Create `tests/test_official_preview_index.py`: 背景/头像缩略图、断点恢复和源目录只读测试。
- Modify `tests/test_launcher.py`, `tests/test_web_setup_status.py`, `tests/test_story_file_picker_api.py`: 启动器和设置接口测试。
- Create `tests/test_web_official_previews.py`: Web 索引任务和受控预览端点测试。
- Modify `tests/test_ui_workbench.py`, `tests/test_ui_polish_contract.py`: 设置 UI 行为和布局契约测试。

---

### Task 1: Pure AA Installation Discovery

**Files:**
- Create: `aa_install_discovery.py`
- Create: `tests/test_aa_install_discovery.py`

**Interfaces:**
- Produces: `UnityIdentity(vendor: str, product: str)`
- Produces: `DiscoveryIssue(code: str, message: str, path: Path | None = None)`
- Produces: `PathCandidate(path: Path, source: str, valid: bool)`
- Produces: `AADiscoveryResult` with `executable`, `install_root`, `identity`, `local_low_root`, `data`, `projects`, `saves`, `overrides`, `settings`, `resource_cache`, `catalog`, `recent_project_files`, `data_candidates`, `requires_selection`, `source`, `issues`
- Produces: `normalize_aa_data_path(value: str | os.PathLike | None) -> Path | None`
- Produces: `resolve_aa_executable(value: str | os.PathLike | None) -> Path | None`
- Produces: `discover_aa(selection: str | os.PathLike | None = None, *, config_path: str | os.PathLike | None = None, home: str | os.PathLike | None = None, environ: Mapping[str, str] | None = None) -> AADiscoveryResult`

- [ ] **Step 1: Write failing path and identity tests**

```python
def make_install(root: Path) -> Path:
    exe = root / "App" / "AzureArchive.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    data = exe.parent / "AzureArchive_Data"
    data.mkdir()
    (data / "app.info").write_text("foxxlight\nAzureArchive\n", encoding="utf-8")
    catalog = data / "StreamingAssets" / "aa" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}", encoding="utf-8")
    return exe


def test_resolves_exe_file_app_directory_and_install_root(tmp_path):
    exe = make_install(tmp_path / "AzureArchive")
    assert resolve_aa_executable(exe) == exe.resolve()
    assert resolve_aa_executable(exe.parent) == exe.resolve()
    assert resolve_aa_executable(tmp_path / "AzureArchive") == exe.resolve()


def test_rejects_named_exe_without_unity_identity(tmp_path):
    exe = tmp_path / "AzureArchive.exe"
    exe.write_bytes(b"MZ")
    assert resolve_aa_executable(exe) is None
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `python -m pytest tests/test_aa_install_discovery.py -v`

Expected: FAIL during import because `aa_install_discovery` does not exist.

- [ ] **Step 3: Implement input normalization and Unity identity parsing**

```python
@dataclass(frozen=True)
class UnityIdentity:
    vendor: str
    product: str


def resolve_aa_executable(value):
    candidate = _resolved(value)
    if candidate is None:
        return None
    choices = [candidate] if candidate.is_file() else [
        candidate / "AzureArchive.exe",
        candidate / "App" / "AzureArchive.exe",
    ]
    for executable in choices:
        app_info = executable.parent / "AzureArchive_Data" / "app.info"
        if executable.is_file() and executable.name.casefold() == "azurearchive.exe" and app_info.is_file():
            return executable.resolve()
    return None
```

`read_unity_identity()` 必须去除 UTF-8 BOM、空白和空行；少于两行时返回 `None`，不抛出到 UI。

- [ ] **Step 4: Add failing relocated-workspace and recent-file tests**

```python
def test_discovers_relocated_workspace_cache_and_recent_files(tmp_path):
    home = tmp_path / "home"
    exe = make_install(tmp_path / "AzureArchive")
    workspace = tmp_path / "disk-e" / "存储文件"
    data = workspace / "data"
    for name in ("projects", "saves", "overrides", "settings"):
        (data / name).mkdir(parents=True, exist_ok=True)
    cache = tmp_path / "disk-e" / "资源文件"
    cache.mkdir()
    external = tmp_path / "external" / "chapter.aap"
    external.parent.mkdir()
    external.write_text("{}", encoding="utf-8")
    local_settings = home / "AppData" / "LocalLow" / "foxxlight" / "AzureArchive" / "data" / "settings"
    local_settings.mkdir(parents=True)
    (local_settings / "user_settings.json").write_text(json.dumps({
        "workspacePath": str(workspace),
        "cachePath": str(cache),
        "visitedFiles": [str(external), str(tmp_path / "gone.aas"), str(tmp_path / "note.txt")],
    }), encoding="utf-8")

    result = discover_aa(exe, home=home)

    assert result.data == data.resolve()
    assert result.resource_cache == cache.resolve()
    assert result.catalog == exe.parent / "AzureArchive_Data" / "StreamingAssets" / "aa" / "catalog.json"
    assert result.recent_project_files == (external.resolve(),)
    assert result.source == "user_settings.workspacePath"
```

Add cases for malformed JSON, non-object JSON, empty `workspacePath`, direct explicit `data`, old `aa_config.json.aa_data`, missing optional directories, and two conflicting valid candidates. The conflict case must assert both candidates are returned, `requires_selection is True`, and no fallback candidate is silently activated.

- [ ] **Step 5: Implement structured discovery and deterministic precedence**

The implementation must use this decision split:

```python
explicit_data = normalize_aa_data_path(selection)
if explicit_data is not None:
    return _result_for_data(explicit_data, source="explicit data")

executable = resolve_aa_executable(selection or saved_executable)
identity = read_unity_identity(executable) if executable else None
local_low = _local_low_root(identity, home)
settings = _read_json_object(local_low / "data" / "settings" / "user_settings.json")
candidates = _workspace_candidates(settings, local_low, saved_data, environ)
```

Only candidates containing `projects` are valid data roots. A valid `user_settings.workspacePath` is authoritative and does not conflict with lower-priority legacy fallbacks. If no authoritative setting exists and two distinct same-priority automatic candidates remain valid, return them through `data_candidates`, set `requires_selection=True`, and leave `data=None` until the user selects one explicitly. `recent_project_files` accepts existing `.aap` and `.aas` files only, deduplicated by resolved case-insensitive Windows path while preserving configuration order.

- [ ] **Step 6: Run discovery tests**

Run: `python -m pytest tests/test_aa_install_discovery.py -v`

Expected: PASS, including explicit-data precedence and malformed configuration cases.

- [ ] **Step 7: Commit Task 1**

```powershell
git add -- aa_install_discovery.py tests/test_aa_install_discovery.py
git commit -m "feat: discover AA paths from installation"
```

---

### Task 2: Backward-Compatible Paths and Launcher

**Files:**
- Modify: `aapaths.py`
- Modify: `launcher.py`
- Modify: `tests/test_launcher.py`
- Test: `tests/test_aa_install_discovery.py`

**Interfaces:**
- Consumes: `discover_aa()` and `normalize_aa_data_path()` from Task 1
- Produces: `aapaths.detect(explicit=None, *, aa_install=None) -> dict`
- Produces: `aapaths.save_config(data_dir=None, *, executable=None, cache_dir=None) -> str`
- Produces: `launcher.build_environment_report(..., explicit_aa_install: str | None = None) -> dict`
- Produces: CLI flag `--aa-install`

- [ ] **Step 1: Add failing compatibility and launcher tests**

```python
def test_aapaths_legacy_dict_includes_new_resolved_fields(tmp_path, monkeypatch):
    result = fake_discovery_result(tmp_path)
    monkeypatch.setattr(aapaths, "discover_aa", lambda *args, **kwargs: result)
    paths = aapaths.detect(aa_install=str(result.executable))
    assert paths["data"] == str(result.data)
    assert paths["cache"] == str(result.resource_cache)
    assert paths["executable"] == str(result.executable)
    assert paths["catalog"] == str(result.catalog)


def test_environment_report_accepts_aa_install(tmp_path, monkeypatch):
    result = fake_discovery_result(tmp_path)
    monkeypatch.setattr(launcher, "discover_aa", lambda *args, **kwargs: result)
    report = launcher.build_environment_report(
        HERE, explicit_aa_install=str(result.executable)
    )
    assert report["aa"]["connected"] is True
    assert report["aa"]["executable"] == str(result.executable)
    assert report["aa"]["resource_status"] == "installed"
```

- [ ] **Step 2: Run focused tests and verify the new assertions fail**

Run: `python -m pytest tests/test_launcher.py tests/test_aa_install_discovery.py -v`

Expected: FAIL because `detect()` lacks `aa_install` and the launcher lacks `explicit_aa_install`.

- [ ] **Step 3: Adapt `aapaths.py` without breaking old callers**

`detect()` converts the dataclass to the existing string dictionary and adds new keys. Preserve `data`, `projects`, `saves`, `overrides`, `settings`, `cache`, `source`, and `tried`. `save_config()` must merge object-shaped JSON and persist only supplied non-empty values:

```python
def save_config(data_dir=None, *, executable=None, cache_dir=None):
    updates = {
        "aa_data": str(data_dir) if data_dir else None,
        "aa_executable": str(executable) if executable else None,
        "aa_cache": str(cache_dir) if cache_dir else None,
    }
```

Invalid existing JSON is replaced with an object; unrelated keys such as `spine_cli` remain unchanged.

- [ ] **Step 4: Update launcher selection and reporting**

Add `--aa-install`. When no valid workspace is found on Windows, `_choose_aa_install()` first uses `filedialog.askopenfilename(filetypes=[("AzureArchive", "AzureArchive.exe"), ("程序", "*.exe")])`; cancellation returns `None`. The existing `data` directory chooser remains available as the second recovery action.

The JSON report adds `executable`, `install_root`, `resource_status`, `preview_status`, `projects`, and `saves` under `aa`. `_start_application()` still passes the resolved `--aa-data` so the rest of the application remains stable during this task.

- [ ] **Step 5: Run launcher and compatibility tests**

Run: `python -m pytest tests/test_launcher.py tests/test_aa_install_discovery.py tests/test_aa_resource_cache.py -v`

Expected: PASS and the old `--aa-data` subprocess test remains green.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- aapaths.py launcher.py tests/test_launcher.py tests/test_aa_install_discovery.py
git commit -m "feat: accept AA executable in launcher"
```

---

### Task 3: Bounded Resource Probe and Generic Catalog Resolution

**Files:**
- Modify: `aa_resource_cache.py`
- Modify: `official_catalog.py`
- Modify: `tests/test_aa_resource_cache.py`
- Modify: `tests/test_official_catalog.py`

**Interfaces:**
- Consumes: discovered `resource_cache`, `catalog`, and `executable` from Task 1
- Produces: `ResourceCacheProbe(status: Literal["installed", "not_installed", "invalid"], sample_bundle: Path | None, inspected_outer: int, issue: str)`
- Produces: `probe_resource_cache(cache_root: str | Path | None, *, max_outer: int = 64, max_inner: int = 4) -> ResourceCacheProbe`
- Produces: `CatalogBundleLocation(internal_id: str, bundle_name: str, content_hash: str, data_path: Path | None)`
- Produces: `catalog_bundle_locations(catalog_path, cache_root, *, internal_predicate) -> tuple[CatalogBundleLocation, ...]`

- [ ] **Step 1: Write failing bounded-probe tests**

```python
def test_probe_distinguishes_missing_invalid_and_installed(tmp_path):
    missing = probe_resource_cache(tmp_path / "missing")
    invalid_root = tmp_path / "invalid"
    (invalid_root / "a" / "b").mkdir(parents=True)
    (invalid_root / "a" / "b" / "__data").write_bytes(b"not-unity")
    valid_root = tmp_path / "valid"
    bundle = valid_root / "outer" / "inner" / "__data"
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b"UnityFS" + b"\0" * 16)
    assert missing.status == "not_installed"
    assert probe_resource_cache(invalid_root).status == "invalid"
    assert probe_resource_cache(valid_root).status == "installed"


def test_probe_obeys_directory_bounds(tmp_path, monkeypatch):
    for index in range(100):
        (tmp_path / f"outer-{index:03}" / "inner").mkdir(parents=True)
    probe = probe_resource_cache(tmp_path, max_outer=8, max_inner=1)
    assert probe.inspected_outer == 8
```

- [ ] **Step 2: Write a synthetic Addressables catalog test**

Create test helpers that encode the existing seven-int entry records and UTF-16LE bundle option JSON. The fixture contains one internal background ID, one `avatars_assets_all.bundle`, and one unrelated audio bundle. Assert:

```python
locations = catalog_bundle_locations(
    catalog_path,
    cache_root,
    internal_predicate=lambda value: "/01_background/" in value.casefold(),
)
assert [(row.internal_id, row.bundle_name, row.content_hash) for row in locations] == [
    (background_id, "outer-bg", "content-bg")
]
assert locations[0].data_path == cache_root / "outer-bg" / "content-bg" / "__data"
```

- [ ] **Step 3: Run focused tests and verify failures**

Run: `python -m pytest tests/test_aa_resource_cache.py tests/test_official_catalog.py -v`

Expected: FAIL because the probe and generic catalog interfaces are absent.

- [ ] **Step 4: Implement bounded probing**

Sort only the first `max_outer` outer directories and first `max_inner` content directories per outer directory. Read exactly seven bytes from each `__data`. Return on the first `UnityFS` signature; an existing directory with inspected candidates but no signature is `invalid`.

- [ ] **Step 5: Implement catalog bundle locations using existing binary parsers**

Reuse `_catalog_entries()` and `_bundle_options()`. A selected asset entry obtains its bundle internal index from record slot `2`; a selected bundle internal ID uses its own record. Prefer `<bundle_name>/<m_Hash>/__data`; if absent, accept exactly one cached `*/__data` version. Never accept multiple ambiguous cached versions.

- [ ] **Step 6: Run unit and real-cache tests**

Run: `python -m pytest tests/test_aa_resource_cache.py tests/test_official_catalog.py -v`

Expected: synthetic tests PASS; existing `E:\AzureArchive` tests PASS on this machine and remain skipped elsewhere.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- aa_resource_cache.py official_catalog.py tests/test_aa_resource_cache.py tests/test_official_catalog.py
git commit -m "feat: verify AA resource cache and catalog"
```

---

### Task 4: Local Official Background and Avatar Preview Index

**Files:**
- Create: `official_preview_index.py`
- Create: `tests/test_official_preview_index.py`

**Interfaces:**
- Consumes: `catalog_bundle_locations()` from Task 3
- Produces: `PreviewIndexState(status: Literal["not_built", "building", "ready", "partial", "stale"], backgrounds: int, avatars: int, failed: int, fingerprint: str)`
- Produces: `OfficialPreviewIndex(root: str | Path)`
- Produces: `OfficialPreviewIndex.state(catalog_path, cache_root) -> PreviewIndexState`
- Produces: `OfficialPreviewIndex.build(catalog_path, cache_root, *, progress=None) -> PreviewIndexState`
- Produces: `OfficialPreviewIndex.resolve(kind: Literal["background", "avatar"], key: str) -> Path | None`

- [ ] **Step 1: Write failing manifest and path-safety tests**

```python
def test_index_state_is_not_built_before_manifest_exists(tmp_path):
    store = OfficialPreviewIndex(tmp_path / "previews")
    state = store.state(tmp_path / "catalog.json", tmp_path / "cache")
    assert state.status == "not_built"


def test_resolve_rejects_unknown_and_traversal_keys(tmp_path):
    store = ready_fixture_index(tmp_path)
    assert store.resolve("background", "BG_Classroom").is_file()
    assert store.resolve("background", "../../secret") is None
    assert store.resolve("avatar", "missing") is None
```

- [ ] **Step 2: Write failing extraction tests with a UnityPy seam**

Inject `bundle_loader: Callable[[Path], Iterable[BundleImage]]` into `build()` for tests. Each `BundleImage` has `name` and a Pillow image. Assert:

```python
state = store.build(catalog, cache, bundle_loader=fake_loader)
assert state.status == "ready"
assert state.backgrounds == 2
assert state.avatars == 1
assert Image.open(store.resolve("background", "BG_Classroom")).size == (320, 180)
assert Image.open(store.resolve("avatar", "Student_Portrait_Hifumi")).size == (160, 160)
```

Add tests proving that a failing bundle increments `failed`, preserves successful records, produces `partial`, and a second build skips records whose source bundle fingerprint is unchanged.

- [ ] **Step 3: Run preview index tests and verify failure**

Run: `python -m pytest tests/test_official_preview_index.py -v`

Expected: FAIL during import because `official_preview_index` does not exist.

- [ ] **Step 4: Implement fingerprinted, resumable manifest storage**

Use SHA-256 of catalog bytes plus resolved cache root and catalog size/mtime as the index fingerprint. Store `manifest.json` with schema version `1`, status, counts, failures, and records. Write updates to `manifest.json.tmp`, flush and `os.replace()` so interruption never corrupts the last valid manifest.

Record keys are normalized case-insensitively but retain display keys. Resolved files must remain children of the index root after `Path.resolve()`.

- [ ] **Step 5: Implement background extraction**

Select catalog IDs containing exactly:

```text
/defaultlocalgroup_assets_uis/03_scenario/01_background/
```

and ending in `.jpg.bundle`, `.jpeg.bundle`, or `.png.bundle`. Derive the lookup stem from the filename (`bg_classroom.jpg.bundle` -> `bg_classroom`). Load the cached bundle with UnityPy, choose the matching `Texture2D`/`Sprite` or the only image object, apply `ImageOps.exif_transpose`, fit inside `320x180` without cropping, and save WebP quality `78`.

- [ ] **Step 6: Implement avatar extraction**

Resolve the exact catalog bundle ending `/avatars_assets_all.bundle`. Extract `Texture2D` objects whose names start with `Student_Portrait_` or `NPC_Portrait_`; fit inside `160x160` on a transparent canvas and save PNG. This key matches the basename of official character table `avatar` values.

- [ ] **Step 7: Run preview index tests**

Run: `python -m pytest tests/test_official_preview_index.py -v`

Expected: PASS for ready, partial, stale, resume, and traversal rejection cases.

- [ ] **Step 8: Run an isolated real-resource smoke build**

Run:

```powershell
python -c "from official_preview_index import OfficialPreviewIndex; from pathlib import Path; s=OfficialPreviewIndex(Path('out')/'official-previews-smoke'); print(s.build(Path(r'E:\AzureArchive\App\AzureArchive_Data\StreamingAssets\aa\catalog.json'), Path(r'E:\AzureArchive\资源文件')))"
```

Expected: status is `ready` or `partial`, background count is greater than `1000`, avatar count is greater than `500`, and failures are reported numerically. Verify separately that no file under `E:\AzureArchive` changed by comparing pre/post file count, newest write time, and sampled SHA-256 values.

- [ ] **Step 9: Commit Task 4**

```powershell
git add -- official_preview_index.py tests/test_official_preview_index.py
git commit -m "feat: build local AA preview index"
```

---

### Task 5: Preserve Avatar Metadata and Resolve Official Previews

**Files:**
- Modify: `assetdb.py`
- Modify: `build_index.py`
- Modify: `webui.py`
- Modify: `tests/test_asset_catalog.py`
- Modify: `tests/test_preflight.py`
- Create: `tests/test_web_official_previews.py`

**Interfaces:**
- Consumes: `OfficialPreviewIndex.resolve()` from Task 4
- Produces: SQLite `character.avatar TEXT NOT NULL DEFAULT ''`
- Produces: `background_preview_path(name: str) -> Path | None`
- Produces: `character_avatar_path(avatar: str, spine: str) -> Path | None`
- Produces: `/thumb/bg/<name>` and `/thumb/av/<avatar-key>` backed by custom overrides first, official local previews second

- [ ] **Step 1: Add failing avatar migration/import tests**

```python
def test_import_index_preserves_official_avatar_key(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    index = {"characters": [{
        "identifier": "hifumi",
        "name": "日步美",
        "club": "补课部",
        "spine": "UIs/03_Scenario/02_Character/CharacterSpine_hihumi",
        "avatar": "UIs/01_Common/01_Character/Student_Portrait_Hifumi",
        "faces": [],
    }]}
    assetdb.import_index(con, index)
    row = con.execute("SELECT avatar FROM character WHERE ident='hifumi'").fetchone()
    assert row["avatar"].endswith("Student_Portrait_Hifumi")
```

Also open an old database without the column and assert `connect()` migrates it without losing existing character rows.

- [ ] **Step 2: Add failing preview precedence tests**

```python
def test_custom_background_preview_precedes_official(tmp_path, monkeypatch):
    official = tmp_path / "official.webp"
    custom = tmp_path / "overrides" / "bgs" / "BG_Classroom.png"
    make_image(official, "blue")
    make_image(custom, "red")
    configure_preview_store(monkeypatch, {"bg_classroom": official})
    monkeypatch.setitem(webui.CFG, "overrides", str(custom.parents[1]))
    assert webui.background_preview_path("BG_Classroom") == custom


def test_preflight_candidate_reports_official_preview(tmp_path, monkeypatch):
    configure_preview_store(monkeypatch, {"bg_shoppingdistrict": tmp_path / "shopping.webp"})
    result = normalize_candidate_fixture("BG_ShoppingDistrict")
    assert result["preview_available"] is True
```

- [ ] **Step 3: Run focused tests and verify failure**

Run: `python -m pytest tests/test_asset_catalog.py tests/test_preflight.py tests/test_web_official_previews.py -v`

Expected: FAIL because the avatar column and official preview resolver are absent.

- [ ] **Step 4: Add the idempotent avatar migration and import path**

Add the column through a schema inspection migration, not by assuming a fresh database. Update character inserts/updates and `assetdb.export()` to include `avatar`. Ensure `build_index.py` retains the `avatar` returned by `select_native_characters()`.

- [ ] **Step 5: Centralize preview resolution in `webui.py`**

Replace direct `_BGF` checks with `background_preview_path()`. Normalize official keys by casefolding and by comparing `BG_` database names to `bg_` catalog stems. Custom override files keep precedence. `list_backgrounds()`, `_preflight_background_library()`, `_normalize_usage_chain()`, and `/thumb/bg/` must all call the same resolver.

Update `list_characters()` to select `c.avatar` and set `avatar` to a browser route only when `character_avatar_path()` resolves. The official lookup uses `Path(avatar).name`; custom `spine + '-avatar.png'` remains first.

- [ ] **Step 6: Run focused preview and preflight tests**

Run: `python -m pytest tests/test_asset_catalog.py tests/test_preflight.py tests/test_web_official_previews.py -v`

Expected: PASS; the existing approximate `BG_ShoppingDistrict` test changes only `preview_available` in the fixture that configures an official preview.

- [ ] **Step 7: Commit Task 5**

```powershell
git add -- assetdb.py build_index.py webui.py tests/test_asset_catalog.py tests/test_preflight.py tests/test_web_official_previews.py
git commit -m "feat: use installed AA previews in asset choices"
```

---

### Task 6: Settings API, Runtime Status, and Index Job

**Files:**
- Modify: `webui.py`
- Modify: `tests/test_web_setup_status.py`
- Modify: `tests/test_story_file_picker_api.py`
- Modify: `tests/test_web_official_previews.py`

**Interfaces:**
- Consumes: `discover_aa()` from Task 1 and `OfficialPreviewIndex` from Task 4
- Produces: `POST /api/settings/aa-install`
- Produces: `GET /api/setup/status` fields `aa.program`, `aa.projects`, `aa.saves`, `aa.resource`, `aa.preview_index`
- Produces: `POST /api/resources/index`
- Produces: `GET /api/resources/index`
- Produces: `GET /api/resources/preview?kind=background|avatar&key=<opaque-name>`

- [ ] **Step 1: Add failing settings endpoint tests**

Use a temporary `StoryFilePicker` root containing both `AzureArchive.exe` and an install directory. Issue server entry tokens and POST each token to `/api/settings/aa-install`. Assert the response contains:

```python
assert payload == {
    "ok": True,
    "restart_required": True,
    "aa": {
        "connected": True,
        "program": {"status": "recognized", "path": str(exe)},
        "projects": {"status": "ready", "path": str(data / "projects")},
        "saves": {"status": "ready", "path": str(data / "saves")},
        "resource": {"status": "installed", "path": str(cache)},
        "preview_index": {"status": "not_built", "backgrounds": 0, "avatars": 0, "failed": 0},
    },
}
```

The stored configuration must contain `aa_executable`, `aa_data`, and `aa_cache`, while preserving `spine_cli`.

Add a conflict fixture where `discover_aa()` returns two `data_candidates` and `requires_selection=True`. The first POST must return `409` with `code="aa_workspace_selection_required"` and browser-safe candidate rows containing `path` and `source`; a second POST with the explicitly selected candidate succeeds and persists it.

- [ ] **Step 2: Add failing index job state tests**

Inject a blocking fake `OfficialPreviewIndex.build()`. Assert first POST returns `202` with `building`, second POST returns `409` with `index_already_running`, GET reports progress, and completion reports `ready` or `partial`. A raised exception reports `failed` with a Chinese action message and remains retryable.

- [ ] **Step 3: Add failing preview endpoint containment tests**

Assert a known key streams the expected image MIME, an unknown key returns `404`, `../` returns `404`, and the JSON response never includes the local source path.

- [ ] **Step 4: Run Web tests and verify failures**

Run: `python -m pytest tests/test_web_setup_status.py tests/test_story_file_picker_api.py tests/test_web_official_previews.py -v`

Expected: FAIL because the routes and expanded state are absent.

- [ ] **Step 5: Implement one public AA status serializer**

Create `_public_aa_status(discovery, preview_state)` and use it for `setup_status()` and the save response. Status vocabulary is fixed:

```python
program: recognized | missing | invalid
projects/saves: ready | missing
resource: installed | not_installed | invalid
preview_index: not_built | building | ready | partial | stale | failed
```

Do not collapse `not_built` or `partial` into an error. `partial` means usable thumbnails were built while individual damaged bundles were skipped and counted. Keep existing `aa.connected` and `aa.path` during migration so older JavaScript tests and launcher server detection keep working.

- [ ] **Step 6: Implement save, job, and preview routes**

`/api/settings/aa-install` accepts either an entry token resolving to file/directory or a typed `aa_install` string. It calls `discover_aa()`, rejects results without valid `projects`, persists all resolved paths, and returns `restart_required=True` rather than mutating active story registries.

The index job uses a module-level lock, daemon thread, immutable public snapshot, and progress callback. It may write only beneath `out/official-previews`. The preview endpoint calls `OfficialPreviewIndex.resolve()` and `_send_preview_file()`. When path discovery requires an explicit workspace selection, the save route validates the submitted candidate against the server-produced `data_candidates` before persisting it.

- [ ] **Step 7: Run Web tests**

Run: `python -m pytest tests/test_web_setup_status.py tests/test_story_file_picker_api.py tests/test_web_official_previews.py -v`

Expected: PASS for EXE and directory tokens, separate resource/index states, duplicate-job rejection, retry, and preview containment.

- [ ] **Step 8: Commit Task 6**

```powershell
git add -- webui.py tests/test_web_setup_status.py tests/test_story_file_picker_api.py tests/test_web_official_previews.py
git commit -m "feat: expose AA install and preview status"
```

---

### Task 7: AA Installation and Resource Settings UI

**Files:**
- Modify: `ui.html`
- Modify: `js/app.js`
- Modify: `css/app.css`
- Modify: `css/layout.css`
- Modify: `tests/test_ui_workbench.py`
- Modify: `tests/test_ui_polish_contract.py`

**Interfaces:**
- Consumes: expanded `/api/setup/status`, `/api/settings/aa-install`, and resource index endpoints from Task 6
- Produces: settings controls `aaInstallInput`, `aaProgramState`, `aaProjectsState`, `aaSavesState`, `aaResourceState`, `aaPreviewState`, `aaIndexProgress`, `buildAAIndex`

- [ ] **Step 1: Add failing structural UI tests**

```python
def test_settings_explain_install_workspace_resource_and_preview_separately():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    for element_id in (
        "aaInstallInput", "aaProgramState", "aaProjectsState", "aaSavesState",
        "aaResourceState", "aaPreviewState", "aaIndexProgress", "buildAAIndex",
    ):
        assert f'id="{element_id}"' in html
    assert "AA 数据目录（内含 projects / overrides）" not in html
    assert "选择 AA 程序或安装目录" in html
```

- [ ] **Step 2: Add failing JavaScript behavior tests**

Use the existing Node DOM harness. Mock these states and assert rendered Chinese copy and controls:

```javascript
{resource:{status:'installed'},preview_index:{status:'not_built'}}
// “资源包已安装” + “尚未建立图片预览” + index button enabled

{resource:{status:'not_installed'},preview_index:{status:'not_built'}}
// “尚未安装 AA 资源包” + index button disabled

{resource:{status:'installed'},preview_index:{status:'building',current:31,total:1554}}
// progress value 31/max 1554 + duplicate start disabled
```

Also assert selecting either a file token or directory token posts to `/api/settings/aa-install`, and the response displays “路径已保存，重启后使用新的 AA 工作区”.

Add a conflict response test that renders every returned workspace candidate as a radio choice with its source, submits the chosen path, and never auto-selects or saves the first candidate before the user clicks confirm.

- [ ] **Step 3: Run UI tests and verify failures**

Run: `python -m pytest tests/test_ui_workbench.py tests/test_ui_polish_contract.py -v`

Expected: FAIL because the new elements and state renderer are absent.

- [ ] **Step 4: Replace the old AA data row with a status group**

Use one unframed settings section, not nested cards. The input accepts pasted EXE, install directory, workspace, or data path. The picker button opens the existing settings host browser and permits both files and directories. Show five compact rows with stable label/value columns:

```text
AA 程序      已识别
项目位置     …\data\projects
存档位置     …\data\saves
官方资源包   已安装
图片预览     尚未建立
```

Use the existing status colors; no new gradients, decorative panels, or English state words.

- [ ] **Step 5: Implement state rendering and index progress**

Add `renderAAStatus(aa)` and `pollAAIndex()` to `js/app.js`. Poll only while `preview_index.status === 'building'`, at 1000 ms, and stop after ready/partial/failed or when the drawer closes. “建立图片预览” POSTs once and immediately renders the returned snapshot.

Do not label `not_built`, `partial`, or a missing optional `saves` directory as “AI 错误”. Messages must state what is complete and the next available action. Multiple workspace candidates use the heading “发现多个 AA 工作区，请确认当前使用的位置” and no candidate starts checked.

- [ ] **Step 6: Add responsive styles**

Desktop uses `grid-template-columns: 88px minmax(0,1fr)`. Below `640px`, rows stack and every picker/index button has `min-height:44px`; paths use `overflow-wrap:anywhere`. Progress has a stable height and does not resize the drawer.

- [ ] **Step 7: Run UI contract tests**

Run: `python -m pytest tests/test_ui_workbench.py tests/test_ui_polish_contract.py -v`

Expected: PASS for file/directory selection, all resource states, polling lifecycle, and narrow-layout contracts.

- [ ] **Step 8: Run Playwright visual verification**

Start the local server on an unused port and capture settings drawer screenshots at `1440x900`, `1024x768`, and `390x844`. Verify program, project, save, resource, and preview rows do not overlap; long paths wrap; progress and actions stay visible. Check browser console for errors.

- [ ] **Step 9: Commit Task 7**

```powershell
git add -- ui.html js/app.js css/app.css css/layout.css tests/test_ui_workbench.py tests/test_ui_polish_contract.py
git commit -m "feat: show AA resource discovery in settings"
```

---

### Task 8: Release Packaging, Documentation, and End-to-End Verification

**Files:**
- Modify: `prepare_release.py`
- Modify: `README.md`
- Modify: `使用说明-从这里开始.md`
- Modify: `tests/test_prepare_release_entry.py`
- Test: full `tests/`

**Interfaces:**
- Consumes: all previous tasks
- Produces: release package containing discovery/index code and `UnityPy>=1.25.2`

- [ ] **Step 1: Add failing release contract tests**

Add these assertions to `tests/test_prepare_release_entry.py`:

```python
assert "aa_install_discovery.py" in prepare_release.CODE
assert "official_preview_index.py" in prepare_release.CODE
assert "UnityPy>=1.25.2" in prepare_release.REQUIREMENTS
assert "out/official-previews" not in release_file_list
```

Also assert the generated release does not contain `.bundle`, `__data`, extracted `.jpg/.png/.webp`, or an absolute `E:\AzureArchive` configuration.

- [ ] **Step 2: Run release tests and verify failure**

Run: `python -m pytest tests/test_prepare_release_entry.py -v`

Expected: FAIL until new modules and dependency are included.

- [ ] **Step 3: Update packaging and user documentation**

Add both new modules to `CODE` and `UnityPy>=1.25.2` to generated requirements. Document this first-use sequence:

```text
设置 -> AA 安装与资源 -> 选择 AzureArchive.exe 或安装目录
程序自动显示 projects / saves / 官方资源包
资源包已安装但图片预览尚未建立时，点“建立图片预览”
预览文件只保存在本机，不会修改或上传 AA 资源
```

Document the three recovery states: invalid program selection, valid workspace without resource pack, and installed resource pack with stale/partial index.

- [ ] **Step 4: Run the focused feature suite**

Run:

```powershell
python -m pytest tests/test_aa_install_discovery.py tests/test_launcher.py tests/test_aa_resource_cache.py tests/test_official_catalog.py tests/test_official_preview_index.py tests/test_web_setup_status.py tests/test_story_file_picker_api.py tests/test_web_official_previews.py tests/test_ui_workbench.py tests/test_ui_polish_contract.py -v
```

Expected: all focused tests PASS; machine-specific real AA tests either PASS or explicitly SKIP when AA is absent.

- [ ] **Step 5: Run the full automated suite**

Run: `python -m pytest -q`

Expected: all tests PASS with only the repository's documented environment-dependent skips.

- [ ] **Step 6: Run JavaScript syntax and release safety checks**

Run:

```powershell
node --check js/app.js
python prepare_release.py --check
```

Expected: JavaScript syntax exits `0`; release safety check reports no secrets, hardcoded runtime AA paths, or packaged copyrighted assets.

- [ ] **Step 7: Run actual-install read-only acceptance**

Using `E:\AzureArchive\App\AzureArchive.exe`, record before/after counts and newest write times for:

```text
E:\AzureArchive\存储文件\data
E:\AzureArchive\资源文件
C:\Users\Sakura\AppData\LocalLow\foxxlight\AzureArchive
```

Then verify:

- discovered EXE is `E:\AzureArchive\App\AzureArchive.exe`;
- data is `E:\AzureArchive\存储文件\data`;
- projects, saves, and overrides exist;
- resource state is `installed`;
- preview state becomes `ready` or `partial` with more than `1000` backgrounds and more than `500` avatars;
- background `BG_ShoppingDistrict` resolves to a local preview;
- the three AA source locations retain their pre-test newest write times and sampled hashes.

- [ ] **Step 8: Commit Task 8**

```powershell
git add -- prepare_release.py README.md 使用说明-从这里开始.md tests/test_prepare_release_entry.py
git commit -m "docs: package AA resource discovery"
```

- [ ] **Step 9: Record final verification evidence**

Run: `git status --short` and `git log -8 --oneline`

Expected: only pre-existing unrelated worktree changes remain; the eight feature commits are visible and no generated preview or AA asset is tracked.
