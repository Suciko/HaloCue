# Story Workspace, Shared Assets, and AA BGM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-story AA workbench whose drafts share project-scoped assets, can safely copy assets from historical AA projects, and can optionally play verified custom BGM inside AA while defaulting to silence.

**Architecture:** Treat the current AA project scope as the story workspace identity. Keep the shared asset catalog separate from per-draft usage assignments, expose both through opaque story/history tokens, and make every import or copy a project/save mirrored transaction. Implement BGM only after a controlled AA import experiment produces a verified manifest and `bgmId` contract; the browser consumes the same story-scoped APIs for local import and historical reuse.

**Tech Stack:** Python 3.12+ standard library, SQLite, Pillow, existing local HTTP server, vanilla JavaScript/DOM APIs, CSS, pytest, Node.js VM-based browser-unit tests, AzureArchive project/save manifests.

## Global Constraints

- One source story normally corresponds to one AA project.
- Only one story workspace is active in the UI at a time.
- All drafts of that story share custom characters, backgrounds, short sounds, and BGM.
- Applying an asset to a line or scene modifies only the selected draft.
- Historical assets are copied and registered into the current story; never retain a runtime dependency on the history project.
- New stories default to no AA BGM; normal script rows compile with `bgmId = 999` until the user enables music.
- AI may select only BGM that is registered, physically present, and verified in the current story scope.
- All AA project/save writes require AA to be closed and must roll back as a pair on failure.
- Never infer a BGM ID from filename, array position, or an unverified hash.
- Do not initialize a Git repository. This workspace currently has no `.git`; each conditional commit step is skipped unless repository metadata is restored by the user.
- Preserve user assets and unrelated working files. Never overwrite a same-name/different-content asset.

---

## File Structure and Responsibilities

### New Python modules

- `story_workspace.py` — recent-story index, opaque story tokens, current project scope, source-path recovery.
- `history_assets.py` — read-only historical project discovery and safe conversion of history records into current-story import requests.
- `bgm_contract.py` — load and validate the verified AA BGM native contract; no guessing fallback.
- `tools/inspect_bgm_override_contract.py` — normalize before/after AA snapshots and emit evidence used by `bgm_contract.py`.

### Existing Python modules

- `asset_validation.py` — add BGM validation based on the verified contract.
- `aa_registry.py` — add mirrored `BgmOverrides` registration and rollback.
- `asset_import.py` — route `kind="bgm"` through discovery, validation, registration, and catalog metadata.
- `asset_catalog.py` — expose story-scoped BGM and unified scoped asset lists.
- `draft_store.py` — persist per-draft BGM policy and return frozen story context without merging it into shared asset state.
- `prompt.py` / `annotate.py` — add optional, allowlisted BGM proposals only when the draft enables AI music.
- `script2aap.py` — resolve verified BGM names to IDs and enforce `999` in silent mode.
- `webui.py` — story, history, scoped asset, BGM preview, and copy endpoints.

### Frontend files

- `ui.html` — markup-only single-story shell; remove the independent asset workspace.
- `js/api.js` — JSON request/error helper and polling.
- `js/app.js` — startup, navigation, current-story lifecycle, settings/help.
- `js/story.js` — `StoryContextBar`, recent stories, open/replace story flows.
- `js/assets.js` — shared asset strip, asset/task cards, local import state machine.
- `js/history.js` — historical project browser and copy flow.
- `js/bgm.js` — BGM policy, BGM cards, preview, loop settings.
- `js/cards.js` — connect story assets and BGM proposals to draft review cards.
- `css/layout.css` / `css/app.css` — one-story layout, strip, drawers, card states, responsive behavior.

### New tests

- `tests/test_bgm_contract.py`
- `tests/test_bgm_registration.py`
- `tests/test_bgm_compile.py`
- `tests/test_story_workspace.py`
- `tests/test_history_assets.py`
- `tests/test_story_asset_api.py`
- `tests/test_ui_story_workspace.py`
- `tests/test_ui_asset_tasks.py`
- `tests/test_ui_bgm.py`

---

### Task 1: Establish the Native AA BGM Contract

**Files:**
- Create: `tools/inspect_bgm_override_contract.py`
- Create: `tests/test_bgm_contract.py`
- Create after the real experiment: `docs/bgm-native-contract.json`
- Create after the real experiment: `../../04-素材机制实验/BGM原生导入差异/2026-08-01-BGM原生导入验证.md`

**Interfaces:**
- Consumes: AA `manifest.json` and `.aap` snapshots taken before import, after import, and after AA restart.
- Produces: `inspect_contract(before_manifest, after_manifest, before_aap, after_aap) -> dict` and a checked-in `docs/bgm-native-contract.json` containing `manifest_entry_fields`, `supported_extensions`, `path_folder`, `id_strategy`, `loop_units`, and `restart_verified`.

- [ ] **Step 1: Write the failing contract-inspector tests**

```python
from tools.inspect_bgm_override_contract import inspect_contract


def test_inspector_reports_one_added_bgm_and_changed_script_id():
    result = inspect_contract(
        {"BgmOverrides": []},
        {"BgmOverrides": [{
            "Path": r"bgms\demo.ogg",
            "LoopStartTime": "0",
            "LoopEndTime": "12.5",
            "LoopTransitionTime": "0",
            "LoopOffsetTime": "0",
            "Volume": "1",
        }]},
        {"rows": [{"text": "probe", "bgmId": 999}]},
        {"rows": [{"text": "probe", "bgmId": 7}]},
    )
    assert result["added_entries"][0]["Path"] == r"bgms\demo.ogg"
    assert result["bgm_id_changes"] == [{"text": "probe", "before": 999, "after": 7}]
```

- [ ] **Step 2: Run the test and verify the missing module failure**

Run: `python -m pytest tests/test_bgm_contract.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.inspect_bgm_override_contract'`.

- [ ] **Step 3: Implement the snapshot normalizer and diff**

```python
def _rows(aap):
    if "rows" in aap:
        return aap["rows"]
    rows = []
    for node in aap.get("nodes", {}).get("$values", []):
        rows.extend(node.get("Scripts", {}).get("$values", []))
    return rows


def inspect_contract(before_manifest, after_manifest, before_aap, after_aap):
    before = before_manifest.get("BgmOverrides", [])
    after = after_manifest.get("BgmOverrides", [])
    added = [entry for entry in after if entry not in before]
    old = {row.get("text", ""): row.get("bgmId") for row in _rows(before_aap)}
    changes = []
    for row in _rows(after_aap):
        text = row.get("text", "")
        if text in old and old[text] != row.get("bgmId"):
            changes.append({"text": text, "before": old[text], "after": row.get("bgmId")})
    return {"added_entries": added, "bgm_id_changes": changes}
```

- [ ] **Step 4: Run the inspector unit tests**

Run: `python -m pytest tests/test_bgm_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Perform one controlled native AA import**

Use a newly created disposable AA project named `AA_BGM_NATIVE_PROBE_20260801`, one short redistributable test tone, and one script row whose text is exactly `BGM_NATIVE_PROBE`. Record:

1. project and save manifests before import;
2. `.aap` before import;
3. the same files after importing BGM through AA and applying it to the probe row;
4. the same files after closing AA, restarting it, reopening the project, and confirming playback and looping.

Store snapshots only under `../../04-素材机制实验/BGM原生导入差异/`; do not place the test audio in Git.

- [ ] **Step 6: Generate and validate the contract file**

Run:

```powershell
python tools/inspect_bgm_override_contract.py `
  --before-manifest "../../04-素材机制实验/BGM原生导入差异/before/manifest.json" `
  --after-manifest "../../04-素材机制实验/BGM原生导入差异/after/manifest.json" `
  --before-aap "../../04-素材机制实验/BGM原生导入差异/before/AA_BGM_NATIVE_PROBE_20260801.aap" `
  --after-aap "../../04-素材机制实验/BGM原生导入差异/after/AA_BGM_NATIVE_PROBE_20260801.aap" `
  --output docs/bgm-native-contract.json
```

Expected: output contains one added `BgmOverrides` entry, one non-999 `bgmId` change, exact field names, and `restart_verified: true` after the manual replay confirmation is recorded.

- [ ] **Step 7: Apply the hard gate**

If the snapshots do not prove a deterministic project-local mapping from the registered entry to a script `bgmId`, stop implementation here and revise the design with the evidence. Do not begin Task 2 and do not expose custom BGM in the UI.

- [ ] **Step 8: Conditional commit**

If Git metadata exists:

```powershell
git add tools/inspect_bgm_override_contract.py tests/test_bgm_contract.py docs/bgm-native-contract.json "../../04-素材机制实验/BGM原生导入差异/2026-08-01-BGM原生导入验证.md"
git commit -m "test: establish verified AA BGM contract"
```

Otherwise record the passing command and snapshot paths in the implementation log.

---

### Task 2: Validate and Register Project-Private BGM

**Files:**
- Create: `bgm_contract.py`
- Modify: `asset_validation.py`
- Modify: `aa_registry.py`
- Modify: `asset_import.py`
- Test: `tests/test_asset_validation.py`
- Create: `tests/test_bgm_registration.py`

**Interfaces:**
- Consumes: `docs/bgm-native-contract.json` from Task 1 and existing `AAProjectTarget` mirror transactions.
- Produces: `validate_bgm(path, *, contract=None) -> ValidationResult`, `register_bgm(result, target, *, loop=None, volume="1", running_probe=None) -> RegistrationResult`, and web-import payload `kind="bgm"`.

- [ ] **Step 1: Write failing BGM validation tests**

```python
from asset_validation import validate_bgm

VERIFIED_TEST_CONTRACT = {
    "supported_extensions": [".ogg"],
    "path_folder": "bgms",
    "id_strategy": {"kind": "native-probe-fixture"},
    "restart_verified": True,
}


def test_bgm_validation_uses_verified_extensions(tmp_path):
    source = tmp_path / "theme.ogg"
    source.write_bytes(b"verified fixture bytes")
    result = validate_bgm(source, contract=VERIFIED_TEST_CONTRACT)
    assert result.ok
    assert result.candidate.kind == "bgm"
    assert result.candidate.aa_key == "theme"


def test_bgm_validation_rejects_unverified_extension(tmp_path):
    source = tmp_path / "theme.flac"
    source.write_bytes(b"fixture")
    result = validate_bgm(source, contract=VERIFIED_TEST_CONTRACT)
    assert not result.ok
    assert result.issues[0].code == "bgm_format_unverified"
```

- [ ] **Step 2: Run validation tests and confirm failure**

Run: `python -m pytest tests/test_asset_validation.py -k bgm -v`

Expected: FAIL because `validate_bgm` is not defined.

- [ ] **Step 3: Implement strict contract loading and validation**

```python
def load_bgm_contract(path=None):
    source = Path(path or Path(__file__).with_name("docs") / "bgm-native-contract.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    required = {"supported_extensions", "path_folder", "id_strategy", "restart_verified"}
    if not required <= data.keys() or data["restart_verified"] is not True:
        raise BgmContractError("AA BGM native contract is incomplete or unverified")
    return data
```

`validate_bgm` must reject any extension or metadata combination not proven by the contract; it must return duration/codec metadata when the existing ffprobe path can read it.

- [ ] **Step 4: Write failing mirrored-registration tests**

```python
def test_bgm_registration_mirrors_file_and_manifest(tmp_path):
    source = tmp_path / "theme.ogg"
    source.write_bytes(b"verified fixture bytes")
    bgm_result = validate_bgm(source, contract=VERIFIED_TEST_CONTRACT)
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")
    installed = register_bgm(bgm_result, target, volume="0.8")
    for root in (target.project_dir, target.save_dir):
        assert (root / "bgms" / "theme.ogg").is_file()
        entry = load_manifest(root)["BgmOverrides"][0]
        assert entry["Path"] == r"bgms\theme.ogg"
        assert entry["Volume"] == "0.8"
    assert installed.aa_key == "theme"
```

- [ ] **Step 5: Implement BGM manifest-object registration**

Add a BGM-specific transaction instead of `_register_simple`, because `BgmOverrides` contains objects rather than strings:

```python
def register_bgm(result, target, *, loop=None, volume="1", running_probe=None):
    candidate = _require_valid(result)
    settings = normalize_bgm_settings(loop or {}, volume)
    with _registration_transaction(target, running_probe) as directories:
        return _register_bgm_unlocked(candidate, directories, settings)
```

Use the same preflight, pair lock, atomic copy, and rollback helpers as background/sound registration. Compare normalized filename stems and SHA-256 before adding a manifest object.

- [ ] **Step 6: Route `kind="bgm"` through unified import**

Update `_validate`, discovery filters, registration dispatch, catalog metadata, and the public result payload. Discovery must not return the same audio file as both `sound` and `bgm`; local BGM selection passes an explicit kind and file token.

- [ ] **Step 7: Run BGM validation and registry tests**

Run:

```powershell
python -m pytest tests/test_asset_validation.py tests/test_bgm_registration.py tests/test_dual_registration.py -v
```

Expected: PASS, including AA-running, same-name/same-bytes idempotency, same-name/different-bytes rejection, and injected rollback failures.

- [ ] **Step 8: Conditional commit**

```powershell
git add bgm_contract.py asset_validation.py aa_registry.py asset_import.py tests/test_asset_validation.py tests/test_bgm_registration.py
git commit -m "feat: register project-private AA BGM"
```

Skip only while the workspace has no Git metadata.

---

### Task 3: Add Story-Scoped BGM Catalog, Compilation, and AI Allowlist

**Files:**
- Modify: `asset_catalog.py`
- Modify: `draft_store.py`
- Modify: `prompt.py`
- Modify: `annotate.py`
- Modify: `script2aap.py`
- Create: `tests/test_bgm_compile.py`
- Modify: `tests/test_model_asset_constraints.py`
- Modify: `tests/test_model_proposals.py`

**Interfaces:**
- Consumes: registered BGM records and verified `id_strategy` from Tasks 1–2.
- Produces: `export_model_constraints(con, scope=project_dir)["bgms"]`, per-draft `bgm_policy`, compiler helpers `resolve_bgm_id(name, registered_bgms, contract) -> int` and `compile_bgm_rows(rows, policy, registered_bgms, contract) -> list[dict]`, and BGM proposals only in AI mode.

- [ ] **Step 1: Write failing silent-mode compile test**

```python
from script2aap import compile_bgm_rows


def test_silent_policy_forces_999_on_normal_rows(tmp_path):
    rows = [{"text": "凯伊: 你好", "bgm": "custom_theme"}]
    result = compile_bgm_rows(
        rows,
        policy={"enabled": False, "arrangement": "manual"},
        registered_bgms={"custom_theme": {"bgm_id": 7, "id_strategy": "native-probe-fixture"}},
        contract={"id_strategy": {"kind": "native-probe-fixture"}},
    )
    assert {row["bgmId"] for row in result} == {999}
```

- [ ] **Step 2: Write failing allowlisted-name compile test**

```python
def test_enabled_policy_resolves_registered_bgm_name():
    rows = [{"text": "凯伊: 你好", "bgm": "custom_theme"}]
    result = compile_bgm_rows(
        rows,
        policy={"enabled": True, "arrangement": "manual"},
        registered_bgms={"custom_theme": {"bgm_id": 7, "id_strategy": "native-probe-fixture"}},
        contract={"id_strategy": {"kind": "native-probe-fixture"}},
    )
    assert result[0]["bgmId"] == 7
```

- [ ] **Step 3: Run tests and confirm current integer-only behavior fails**

Run: `python -m pytest tests/test_bgm_compile.py -v`

Expected: FAIL because the compiler cannot resolve registered BGM names and does not enforce the draft policy.

- [ ] **Step 4: Extend scoped catalog output**

Return a fourth collection:

```python
out = {"backgrounds": {}, "sounds": {}, "bgms": {}, "characters": []}
```

Each BGM record includes `aa_key`, `display_name`, `install_path`, `bgm_id`, `labels`, `duration`, `volume`, and normalized loop fields. `merge_model_constraints` adds `bgms` only from the requested project scope.

- [ ] **Step 5: Persist draft BGM policy**

Store in the draft session or a dedicated `settings.json`:

```json
{"enabled": false, "arrangement": "manual"}
```

Add `DraftStore.update_bgm_policy(token, policy, expected_draft_version)`. This changes compilation output, so it increments both `draft_version` and `content_revision`. New drafts copy the current story default; existing drafts do not change automatically.

- [ ] **Step 6: Implement verified BGM resolution**

```python
def resolve_bgm_id(name, registered_bgms, contract):
    record = registered_bgms.get(name)
    if record is None:
        raise ValueError(f"未登记 BGM：{name}")
    strategy = contract["id_strategy"]["kind"]
    if record.get("id_strategy") != strategy:
        raise ValueError(f"BGM 映射策略不匹配：{name}")
    return int(record["bgm_id"])


def compile_bgm_rows(rows, policy, registered_bgms, contract):
    compiled = []
    for source in rows:
        row = dict(source)
        row["bgmId"] = (
            999 if not policy["enabled"]
            else resolve_bgm_id(row.get("bgm", ""), registered_bgms, contract)
        )
        compiled.append(row)
    return compiled
```

When `enabled` is false, ignore/remove draft BGM directives during compilation and emit `999` for normal rows. When enabled, unknown BGM is a blocking diagnostic.

- [ ] **Step 7: Add AI BGM schema only for AI arrangement**

When `bgm_policy == {"enabled": True, "arrangement": "ai"}`, add the current story BGM names and semantic labels to the prompt and accept a `bgm` proposal at scene boundaries. In every other policy, omit the BGM field from the model schema and discard unexpected BGM output with a structured diagnostic.

- [ ] **Step 8: Run catalog, compile, and proposal tests**

Run:

```powershell
python -m pytest tests/test_bgm_compile.py tests/test_model_asset_constraints.py tests/test_model_proposals.py tests/test_annotation_constraints.py -v
```

Expected: PASS.

- [ ] **Step 9: Conditional commit**

```powershell
git add asset_catalog.py draft_store.py prompt.py annotate.py script2aap.py tests/test_bgm_compile.py tests/test_model_asset_constraints.py tests/test_model_proposals.py
git commit -m "feat: compile allowlisted story BGM"
```

---

### Task 4: Create the Single-Story Workspace and Recent-Story Index

**Files:**
- Create: `story_workspace.py`
- Create: `tests/test_story_workspace.py`
- Modify: `webui.py`
- Modify: `tests/test_draft_import.py`

**Interfaces:**
- Consumes: file tokens, validated AA project names, `DraftStore`, and AA data root.
- Produces: `StoryWorkspaceRegistry.open_path(path, project=None) -> StoryContext`, HTTP adapter `open_story(file_token, project=None) -> StoryContext`, `list_recent() -> list[StorySummary]`, `resolve_story_token(token) -> StoryContext`, and API routes `/api/stories/open`, `/api/stories/recent`, `/api/story/current`.

- [ ] **Step 1: Write failing registry tests**

```python
def test_open_story_uses_source_stem_and_returns_opaque_token(tmp_path):
    registry = StoryWorkspaceRegistry(tmp_path / "story-index.json", aa_data=tmp_path / "data")
    context = registry.open_path(tmp_path / "第一章.txt")
    assert context.project == "第一章"
    assert context.story_token
    assert str(tmp_path) not in context.story_token


def test_reopen_moves_story_to_front_without_duplicate(tmp_path):
    registry = StoryWorkspaceRegistry(tmp_path / "story-index.json", aa_data=tmp_path / "data")
    first = registry.open_path(tmp_path / "第一章.txt")
    registry.open_path(tmp_path / "第二章.txt")
    again = registry.open_path(tmp_path / "第一章.txt", project=first.project)
    assert [row.project for row in registry.list_recent()] == [again.project, "第二章"]
```

- [ ] **Step 2: Run tests and confirm missing registry**

Run: `python -m pytest tests/test_story_workspace.py -v`

Expected: FAIL with missing `story_workspace` module.

- [ ] **Step 3: Implement atomic recent-story storage**

Persist only user-safe metadata in `out/story-index.json`: project name, source path, last-opened timestamp, and latest draft token. Generate opaque per-server story tokens mapped to canonical project directories; never accept a client-supplied project path.

Use these exact domain records:

```python
@dataclass(frozen=True)
class StoryContext:
    story_token: str
    project: str
    project_dir: Path
    save_dir: Path
    source_path: Path | None
    latest_draft_token: str | None
    bgm_default: dict


@dataclass(frozen=True)
class StorySummary:
    story_token: str
    project: str
    source_name: str
    last_opened_at: str
    latest_draft_token: str | None
```

`StoryContext.project_dir`, `save_dir`, and `source_path` are server-only. Public response serializers expose `story_token`, `project`, `source_name`, `latest_draft_token`, and `bgm_default`.

- [ ] **Step 4: Add story APIs**

Use request/response shapes:

```json
POST /api/stories/open
{"file_token":"file-token-第一章","project":"第一章"}

200
{"story_token":"story-token-第一章","project":"第一章","source_name":"第一章.txt","latest_draft_token":null}
```

`GET /api/stories/recent` returns display-only summaries. `GET /api/story/current?story_token=` returns the resolved context and never returns the canonical filesystem path.

- [ ] **Step 5: Make draft creation inherit story context**

Extend `/api/drafts/import` and `/api/annotate` to accept `story_token`; resolve the project on the server and reject a mismatched raw `project` value. Include `project`, `story_token`, `bgm_policy`, and `cast` summary in `GET /api/draft`.

- [ ] **Step 6: Run story and draft API tests**

Run:

```powershell
python -m pytest tests/test_story_workspace.py tests/test_draft_import.py tests/test_drafts_api.py tests/test_draft_freeze.py -v
```

Expected: PASS.

- [ ] **Step 7: Conditional commit**

```powershell
git add story_workspace.py webui.py tests/test_story_workspace.py tests/test_draft_import.py
git commit -m "feat: add single-story workspace context"
```

---

### Task 5: Add Scoped Asset Lists and Historical Copy Transactions

**Files:**
- Create: `history_assets.py`
- Create: `tests/test_history_assets.py`
- Create: `tests/test_story_asset_api.py`
- Modify: `asset_catalog.py`
- Modify: `webui.py`

**Interfaces:**
- Consumes: opaque `story_token`, server-generated `history_token`, project/save manifests, and Task 2 import functions.
- Produces: `list_story_assets(scope) -> dict`, `HistoryAssetBrowser.list_projects()`, `list_assets(history_token)`, `copy_to_story(history_asset_token, story_context)`, plus `/api/story/assets`, `/api/history/projects`, `/api/history/assets`, and `/api/story/assets/copy`.

- [ ] **Step 1: Write failing scope-isolation tests**

```python
def test_story_asset_list_excludes_other_project_custom_assets(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    for scope, stem in (("A", "A-night"), ("B", "B-night")):
        candidate = AssetCandidate(
            kind="background",
            source_path=tmp_path / f"{stem}.png",
            stem=stem,
            aa_key=stem,
            sha256=stem,
        )
        upsert_candidate(
            con,
            candidate,
            scope=str(tmp_path / "projects" / scope),
            status="registered",
            install_path=str(tmp_path / "projects" / scope / "bgs" / f"{stem}.png"),
        )
    assets = list_story_assets(con, scope=str(tmp_path / "projects" / "A"))
    assert {row["name"] for row in assets["backgrounds"]} == {"A-night"}
    assert "B-night" not in json.dumps(assets, ensure_ascii=False)
```

- [ ] **Step 2: Write failing history-copy independence test**

```python
def test_history_copy_survives_history_project_removal(tmp_path):
    aa_data = tmp_path / "data"
    history_root = aa_data / "projects" / "History"
    current_root = aa_data / "projects" / "Current"
    (history_root / "bgs").mkdir(parents=True)
    (history_root / "bgs" / "night.png").write_bytes(b"history image bytes")
    write_manifest_atomic(history_root, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    current = StoryContext(project="Current", project_dir=current_root, story_token="story-current")
    history = browser.list_projects()[0]
    token = browser.asset_token(history, kind="background", key="night")
    result = browser.copy_to_story(token, current)
    shutil.rmtree(history_root)
    assert Path(result["install_path"]).read_bytes() == b"history image bytes"
```

- [ ] **Step 3: Run tests and confirm missing APIs**

Run: `python -m pytest tests/test_history_assets.py tests/test_story_asset_api.py -v`

Expected: FAIL because scoped/history functions do not exist.

- [ ] **Step 4: Implement read-only historical discovery**

Scan only canonical AA `projects`/`saves` layouts. Normalize and verify every manifest path with `realpath + commonpath`. A history asset record is available only when its physical file exists and matches the manifest type. Return an opaque `history_asset_token`; never return an arbitrary copy source path to the browser.

- [ ] **Step 5: Implement copy by reusing current import transactions**

Convert a history record to the same validated candidate used by local import, then call `register_background`, `register_sound`, `register_character`, or `register_bgm` against the current `AAProjectTarget`. Preserve `source_project` only as catalog metadata.

- [ ] **Step 6: Add story-scoped HTTP endpoints**

```json
GET /api/story/assets?story_token=story-token-第一章
{"characters":[],"backgrounds":[],"sounds":[],"bgms":[],"counts":{}}

POST /api/story/assets/copy
{"story_token":"story-token-第一章","history_asset_token":"history-asset-night"}
```

Return `409 same_name_different_content`, `409 aa_running`, `410 history_source_missing`, and `422 validation_failed` with stable `code` values.

- [ ] **Step 7: Run scoped/history integration tests**

Run:

```powershell
python -m pytest tests/test_history_assets.py tests/test_story_asset_api.py tests/test_web_asset_api.py tests/test_project_save_verification.py -v
```

Expected: PASS.

- [ ] **Step 8: Conditional commit**

```powershell
git add history_assets.py asset_catalog.py webui.py tests/test_history_assets.py tests/test_story_asset_api.py
git commit -m "feat: copy historical assets into current story"
```

---

### Task 6: Extract the Frontend Runtime and Establish One Story Context Store

**Files:**
- Create: `js/api.js`
- Create: `js/app.js`
- Create: `js/story.js`
- Modify: `ui.html`
- Modify: `webui.py`
- Create: `tests/test_ui_story_workspace.py`
- Modify: `tests/test_csp_headers.py`

**Interfaces:**
- Consumes: story APIs from Task 4.
- Produces: `window.Api.request`, `window.StoryStore.get/set/subscribe`, markup-only `ui.html`, and CSP-safe event listeners.

- [ ] **Step 1: Write failing static frontend tests**

```python
from pathlib import Path
import re

UI = Path(__file__).parents[1] / "ui.html"


def test_ui_has_no_inline_script_or_event_handlers():
    html = UI.read_text(encoding="utf-8")
    assert "<script>" not in html
    assert not re.search(r"\son[a-z]+=", html)
    assert '<script src="/js/app.js"></script>' in html


def test_ui_has_single_story_shell_and_no_asset_workspace():
    html = UI.read_text(encoding="utf-8")
    assert 'id="storyContextBar"' in html
    assert 'id="storyAssetStrip"' in html
    assert 'id="recentStories"' in html
    assert 'id="view-assets"' not in html
```

- [ ] **Step 2: Run tests and verify current inline UI fails**

Run: `python -m pytest tests/test_ui_story_workspace.py tests/test_csp_headers.py -v`

Expected: FAIL on inline `<script>` and `onclick` handlers.

- [ ] **Step 3: Create a central API helper**

```javascript
async function request(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw Object.assign(new Error(body.e || '请求失败'), body);
  return body;
}
window.Api = { request };
```

- [ ] **Step 4: Create the story context store**

```javascript
const listeners = new Set();
let current = null;
window.StoryStore = {
  get: () => current,
  set: value => { current = value; listeners.forEach(fn => fn(value)); },
  subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); }
};
```

No component may cache or edit a project name independently of this store.

- [ ] **Step 5: Move inline runtime into external modules**

Move existing setup, model settings, draft review, player, and help behavior without changing backend semantics. Replace all inline handlers with `addEventListener`. Keep each new file under one responsibility; do not copy the full 900-line script into one new monolith.

- [ ] **Step 6: Enable the already-designed strict CSP only after tests pass**

Apply `build_csp_headers()` in `_common_headers` after the markup contains no inline scripts/styles/event handlers that the policy blocks.

- [ ] **Step 7: Run UI and CSP tests**

Run:

```powershell
python -m pytest tests/test_ui_story_workspace.py tests/test_ui_workbench.py tests/test_csp_headers.py -v
```

Expected: PASS after updating obsolete tests that asserted the removed independent asset page.

- [ ] **Step 8: Conditional commit**

```powershell
git add ui.html js/api.js js/app.js js/story.js webui.py tests/test_ui_story_workspace.py tests/test_ui_workbench.py tests/test_csp_headers.py
git commit -m "refactor: establish single-story frontend shell"
```

---

### Task 7: Build the Story Header, Recent Stories, and Safe Story Replacement

**Files:**
- Modify: `js/story.js`
- Modify: `js/app.js`
- Modify: `ui.html`
- Modify: `css/layout.css`
- Test: `tests/test_ui_story_workspace.py`

**Interfaces:**
- Consumes: `StoryStore`, `/api/stories/open`, `/api/stories/recent`, `/api/story/current`.
- Produces: startup empty state, `StoryContextBar`, recent-story restore, and `replaceStory()` that clears story-scoped UI before loading another story.

- [ ] **Step 1: Add failing Node VM tests for context replacement**

```javascript
const assetStrip = {lastLoadedToken:null, clear(){}, async load(token){this.lastLoadedToken=token;}};
const reviewWorkspace = {lastLoadedToken:null, clear(){}, async loadLatest(story){this.lastLoadedToken=story.story_token;}};
window.StoryAssets = assetStrip;
window.ReviewWorkspace = reviewWorkspace;
window.StoryJobs = {detachView(){}};
window.Preview = {clear(){}};
StoryStore.set({story_token:'story-a', project:'A'});
await replaceStory({story_token:'story-b', project:'B'});
assert.equal(StoryStore.get().project, 'B');
assert.equal(assetStrip.lastLoadedToken, 'story-b');
assert.equal(reviewWorkspace.lastLoadedToken, 'story-b');
```

- [ ] **Step 2: Run and confirm missing `replaceStory`**

Run: `python -m pytest tests/test_ui_story_workspace.py -k replace -v`

Expected: FAIL.

- [ ] **Step 3: Implement startup and recent-story rendering**

The main call to action is “打开剧情文件”. Render recent stories as a secondary list with source display name, project name, last-opened time, and resume action. Do not render asset import actions before `StoryStore.get()` is non-null.

- [ ] **Step 4: Implement atomic story replacement in the browser**

```javascript
async function replaceStory(next) {
  StoryJobs.detachView();
  StoryAssets.clear();
  ReviewWorkspace.clear();
  Preview.clear();
  StoryStore.set(next);
  await Promise.all([StoryAssets.load(next.story_token), ReviewWorkspace.loadLatest(next)]);
}
```

Running backend jobs retain their immutable story token; detaching the view must not retarget or cancel them silently.

- [ ] **Step 5: Add responsive layout**

Keep the context bar fixed at the top of the content area, asset strip below it, review list in the main column, and preview drawer to the right on wide screens. Collapse preview below review on narrow screens; never hide the current story name.

- [ ] **Step 6: Run story UI tests**

Run: `python -m pytest tests/test_ui_story_workspace.py -v`

Expected: PASS.

- [ ] **Step 7: Conditional commit**

```powershell
git add js/story.js js/app.js ui.html css/layout.css tests/test_ui_story_workspace.py
git commit -m "feat: add current-story and recent-story UI"
```

---

### Task 8: Build Shared Asset Cards and Persistent Import Feedback

**Files:**
- Rewrite: `js/assets.js`
- Modify: `ui.html`
- Modify: `css/app.css`
- Create: `tests/test_ui_asset_tasks.py`
- Modify: `tests/test_web_asset_api.py`

**Interfaces:**
- Consumes: `StoryStore`, `/api/story/assets`, existing picker, validate/register endpoints, and stable backend error codes.
- Produces: `StoryAssets.load`, filters for all/character/background/sound/bgm, `AssetTaskCard`, and `importLocal(kind, triggerContext)`.

- [ ] **Step 1: Write failing task-state tests**

```javascript
const card = StoryAssets.beginTask({kind:'background', name:'night.png'});
assert.equal(card.state, 'validating');
StoryAssets.updateTask(card.id, {state:'waiting_for_aa'});
assert.match(container.textContent, /关闭 AA/);
StoryAssets.updateTask(card.id, {state:'failed', code:'validation_failed', message:'图片格式不支持'});
assert.match(container.textContent, /重新选择/);
```

- [ ] **Step 2: Run tests and confirm the current strip lacks task states**

Run: `python -m pytest tests/test_ui_asset_tasks.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the task state machine**

Use explicit states:

```javascript
const TASK_STATES = new Set([
  'validating', 'validated', 'waiting_for_aa', 'registering', 'available', 'failed', 'interrupted'
]);
```

Create the task card immediately after file selection. Update the same card through validation and registration; use toast only to announce start.

- [ ] **Step 4: Render story-scoped asset cards**

Render only `/api/story/assets?story_token=story-token-from-StoryStore`. Card content follows the design spec per type. Include `source_project` as a small audit label, not as a runtime link.

- [ ] **Step 5: Add refresh/recovery behavior**

Persist active job IDs and story tokens in session storage. On reload, resume polling when the backend still knows the job; otherwise mark the card `interrupted` and show retry. A resumed job may update only the story token it was created with.

- [ ] **Step 6: Run asset UI and existing API tests**

Run:

```powershell
python -m pytest tests/test_ui_asset_tasks.py tests/test_web_asset_api.py tests/test_m3_assets_strip.py -v
```

Expected: PASS after replacing obsolete tests for `assetProject` with assertions that the story token supplies scope.

- [ ] **Step 7: Conditional commit**

```powershell
git add js/assets.js ui.html css/app.css tests/test_ui_asset_tasks.py tests/test_web_asset_api.py
git commit -m "feat: add story-scoped asset task cards"
```

---

### Task 9: Add the Historical Asset Reuse Drawer

**Files:**
- Create: `js/history.js`
- Modify: `js/assets.js`
- Modify: `js/cards.js` (background_request fill action)
- Modify: `js/app.js` (`fillBackgroundFromHistory` wiring)
- Modify: `ui.html`
- Modify: `css/layout.css`
- Modify: `css/app.css` (card action row)
- Modify: `tests/test_ui_asset_tasks.py`

**Interfaces:**
- Consumes: `/api/history/projects`, `/api/history/assets`, `/api/story/assets/copy`, `/api/drafts/<token>/backgrounds/<request_id>/resolve`.
- Produces: history project list, type filters, selectable history cards, copy progress, return-to-trigger behavior, and optional draft backfill via the `onApplied` callback.

- [x] **Step 1: Write failing history drawer tests**

```javascript
let applied = 0;
await HistoryDrawer.open({kind:'background', triggerCardId:'card-18', draftToken:'draft-tok', requestId:'card-18', draftVersion: 1, onApplied: () => { applied += 1; }});
assert.match(drawer.textContent, /历史项目/);
await HistoryDrawer.copy('history-asset-token');
assert.equal(applied, 1);
assert.match(drawer.textContent, /已复制到当前剧情/);
```

- [x] **Step 2: Run tests and verify missing module**

Run: `python -m pytest tests/test_ui_asset_tasks.py -k history -v`

Expected: FAIL.

- [x] **Step 3: Implement read-only browsing and explicit copying**

The action label must say “复制到当前剧情”, never “引用” or “链接”. Disable cards whose backend status is `source_missing` and offer a local replacement picker.

- [x] **Step 4: Reuse the same task card pipeline**

History copy creates an `AssetTaskCard` in `registering`; it transitions to `available` or a stable conflict/error state. On success, refresh the shared strip and, when launched from a missing review card (`background_request`), apply the copied asset to that card using the current draft version. Wiring: `cards.js` renders a “补背景：从历史项目复制” button; `app.js#fillBackgroundFromHistory` opens the drawer with `draftToken`/`requestId`/`draftVersion`; `history.js#applyDraftContext` resolves the card and `onApplied` reloads the review workspace. Draft resolve is conditional on the full draft context — never guessed.

- [x] **Step 5: Run history UI and backend tests**

Run:

```powershell
python -m pytest tests/test_ui_asset_tasks.py tests/test_history_assets.py tests/test_story_asset_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Conditional commit (skipped: project has no Git metadata)**

```powershell
git add js/history.js js/assets.js js/cards.js js/app.js ui.html css/layout.css css/app.css tests/test_ui_asset_tasks.py
git commit -m "feat: reuse historical assets in current story"
```

---

### Task 10: Add BGM Policy, BGM Cards, and Draft Review Integration

**Files:**
- Create: `js/bgm.js`
- Modify: `js/assets.js`
- Modify: `js/cards.js`
- Modify: `ui.html`
- Modify: `css/app.css`
- Create: `tests/test_ui_bgm.py`
- Modify: `webui.py`

**Interfaces:**
- Consumes: story-scoped BGM list/preview, `DraftStore.update_bgm_policy`, proposal APIs, and verified compiler behavior.
- Produces: `BgmPolicyPanel`, `BgmCard`, per-scene BGM chips, manual selection, AI proposal review, and `/api/draft/bgm-policy/update`.

- [ ] **Step 1: Write failing default-silence UI test**

```javascript
const nodes = {
  enabled: {checked:true},
  arrangement: {hidden:false},
  summary: {textContent:''}
};
BgmPolicyPanel.render({enabled:false, arrangement:'manual'});
assert.equal(nodes.enabled.checked, false);
assert.equal(nodes.arrangement.hidden, true);
assert.match(nodes.summary.textContent, /AA 中不使用 BGM/);
```

- [ ] **Step 2: Write failing scene-selection test**

```javascript
const api = {lastBody:null, async request(path, options){this.lastBody=JSON.parse(options.body); return {ok:true};}};
window.Api = api;
await BgmPicker.applyToScene({card_id:'scene-4', bgm:'custom_theme'});
assert.deepEqual(api.lastBody, {
  token:'draft-1', card_id:'scene-4', patch:{bgm:'custom_theme'}, expected_draft_version:9
});
```

- [ ] **Step 3: Run tests and confirm missing BGM UI**

Run: `python -m pytest tests/test_ui_bgm.py -v`

Expected: FAIL.

- [ ] **Step 4: Add policy update endpoint**

```json
POST /api/draft/bgm-policy/update
{"token":"draft-1","story_token":"story-token-第一章","policy":{"enabled":true,"arrangement":"ai"},"expected_draft_version":9}
```

Return both updated versions and refreshed derived review state.

- [ ] **Step 5: Implement BGM policy and cards**

Keep BGM as the fourth asset type. In disabled mode, hide arrangement controls and never show missing-BGM warnings. In enabled mode, display manual/AI choice, current-story BGM cards, preview, source, volume, and loop summary. Put detailed loop values behind an advanced expander.

- [ ] **Step 6: Integrate review cards**

Scene cards show the effective BGM and actions `[试听] [更换] [设为静音]`. AI proposals display scene/card target, track, source, rationale, and existing approve/reject actions. Manual BGM changes update only the current draft and honor CAS conflicts.

- [ ] **Step 7: Run BGM frontend and backend tests**

Run:

```powershell
python -m pytest tests/test_ui_bgm.py tests/test_bgm_compile.py tests/test_model_proposals.py tests/test_web_draft_endpoints.py -v
```

Expected: PASS.

- [ ] **Step 8: Conditional commit**

```powershell
git add js/bgm.js js/assets.js js/cards.js ui.html css/app.css webui.py tests/test_ui_bgm.py
git commit -m "feat: add AA BGM policy and review UI"
```

---

### Task 11: End-to-End Verification and Release Safety

**Files:**
- Modify: `tests/test_ui_workbench.py`
- Modify: `tests/test_prepare_release_entry.py`
- Modify: `README.md`
- Modify: `使用说明-从这里开始.md`
- Create: `docs/story-workspace-acceptance.md`

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: automated regression coverage, one real AA acceptance record, updated user instructions, and release exclusions for story/task state.

- [ ] **Step 1: Add the complete automated acceptance test matrix**

Cover:

1. no import without story context;
2. two drafts share the same scoped asset list;
3. applying an asset to draft A leaves draft B unchanged;
4. historical copy remains valid after the history directory is removed;
5. default-silent compile emits `999` on normal rows and no AI BGM proposal;
6. custom BGM project/save manifests and bytes match;
7. same-name/different-bytes, AA-running, missing-history-source, injected manifest failure, and draft CAS conflicts leave no partial state;
8. switching stories cannot redirect a running job.

- [ ] **Step 2: Run focused feature tests**

Run:

```powershell
python -m pytest tests/test_bgm_contract.py tests/test_bgm_registration.py tests/test_bgm_compile.py tests/test_story_workspace.py tests/test_history_assets.py tests/test_story_asset_api.py tests/test_ui_story_workspace.py tests/test_ui_asset_tasks.py tests/test_ui_bgm.py -v
```

Expected: PASS.

- [ ] **Step 3: Run the full regression suite**

Run: `python -m pytest -q`

Expected: all tests pass with no newly skipped BGM or story-scope tests.

- [ ] **Step 4: Perform real single-story browser acceptance**

Start the program through `启动AA自动写剧本.cmd`, then verify:

1. open one sample story;
2. import one background and observe every task-card transition;
3. create two drafts and confirm the asset is shared but assignments differ;
4. copy one historical skeleton or background;
5. keep BGM disabled and compile/install;
6. enable BGM, import the verified probe track, apply it to one scene, compile/install;
7. open AA, play the scene, confirm audio and looping;
8. close/restart AA and confirm the track still plays.

Record evidence and exact project names in `docs/story-workspace-acceptance.md`; do not store copyrighted audio or character files in the repository.

- [ ] **Step 5: Verify release safety**

Run the existing release-preparation and environment checks. Confirm release output excludes `out/drafts/`, `out/story-index.json`, active task state, BGM files, historical asset copies, model secrets, and the `.superpowers/` visual-companion directory.

- [ ] **Step 6: Update user documentation**

Document the intended simple flow: open one story, manage its shared assets, optionally reuse history, default to silent, enable AA BGM only when wanted, review, compile, install. Remove instructions that direct users to a separate custom-asset page or ask them to type an asset project name.

- [ ] **Step 7: Conditional final commit**

```powershell
git add tests README.md "使用说明-从这里开始.md" docs/story-workspace-acceptance.md
git commit -m "docs: verify single-story AA workbench"
```

Skip while no Git metadata exists, and report the complete changed-file list instead.
