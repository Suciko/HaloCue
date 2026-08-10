# Android Assets and Expression Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the PC asset library to Android, including user resource import, official expression semantics, custom Spine metadata extraction, editable AI suggestions, and manual fallback without Spine rendering.

**Architecture:** Android SAF copies user-selected resources into a quarantined private import area. Existing Python validation and catalog modules index accepted resources into the private asset database. Official semantics are used directly; custom assets pass through deterministic text parsing, optional text-model suggestions, and a manual edit layer which has permanent precedence.

**Tech Stack:** Kotlin SAF, Chaquopy Python 3.13, SQLite, PC asset modules, Spine 3.8 read-only binary parser, WebView JavaScript, pytest, Android instrumentation.

## Global Constraints

- Do not use `Spine.com`, native Spine Runtime rendering, generated expression previews, or image-based AI recognition.
- Always expose detected expression count and raw IDs even when semantic extraction fails.
- Official semantic labels do not invoke AI.
- AI results are suggestions only and cannot overwrite `source=manual` records.
- Unsupported Spine versions and model/network failures must fall back to manual editing without blocking import.
- Official assets are indexed only from resources selected or supplied by the user; they are not bundled in the APK.
- All selected files are copied into app-private storage before Python parses them.

---

### Task 1: Generic Asset Document Picker

**Files:**
- Modify: `app/src/main/java/com/halocue/android/AndroidDocumentPicker.kt`
- Modify: `app/src/main/java/com/halocue/android/IncomingFileStore.kt`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/main/python/js/library_import.js`
- Create: `app/src/androidTest/java/com/halocue/android/AssetDocumentPickerTest.kt`

**Interfaces:**
- JavaScript: `HaloCueNative.pickDocuments(requestId, purpose, suffixesJson, multiple)`.
- Callback: `window.HaloCueAndroid.documentsPicked({requestId, ok, files:[{token,name,size}]})`.

- [ ] **Step 1: Write failing picker tests**

Require multiple selection, per-file size limits, sanitized display names, cancellation, and supported suffixes `.zip`, `.atlas`, `.skel`, `.json`, `.png`, `.jpg`, `.jpeg`, `.ogg`, `.mp3`, and `.wav`.

- [ ] **Step 2: Run focused test to verify RED**

Expected: the story-only picker cannot return multiple asset files.

- [ ] **Step 3: Generalize the picker**

Use `ActivityResultContracts.OpenMultipleDocuments` for multi-file asset requests and the existing single-document contract for story files. Copy streams sequentially on an IO executor, stop the entire request on space exhaustion, and delete only files created by that failed request.

Update `library_import.js` to select Android native files when `window.HaloCueNative.pickDocuments` exists; keep PC host browsing unchanged.

- [ ] **Step 4: Verify focused tests**

Expected: single and multi-file requests produce opaque incoming tokens and never expose private paths or persisted external URI grants to JavaScript.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/java/com/halocue/android app/src/androidTest/java/com/halocue/android/AssetDocumentPickerTest.kt app/src/main/python/js/library_import.js
git commit -m "feat(android): select asset resources through SAF"
```

### Task 2: Transactional Asset Import Staging

**Files:**
- Create: `app/src/main/python/android_asset_import.py`
- Modify: `app/src/main/python/asset_import.py`
- Modify: `app/src/main/python/asset_validation.py`
- Modify: `app/src/main/python/webui.py`
- Create: `app/src/test/python/test_android_asset_import.py`

**Interfaces:**
- Consumes: incoming file tokens.
- Produces: `import_asset_tokens(tokens: list[str], kind: str) -> dict` with `ok`, `asset_id`, `warnings`, and `capabilities`.

- [ ] **Step 1: Write failing transactional tests**

```python
def test_failed_bundle_never_enters_the_asset_library(tmp_path):
    result = import_asset_tokens([bad_atlas_token], "character")
    assert result["ok"] is False
    assert list((tmp_path / "assets").iterdir()) == []


def test_successful_bundle_moves_once_after_database_commit(tmp_path):
    result = import_asset_tokens(valid_bundle_tokens, "character")
    assert result["ok"] is True
    assert Path(result["private_root"]).parent.name == "assets"
```

Also test duplicate names, missing textures, multipage atlases, ZIP path traversal, and cancellation cleanup.

- [ ] **Step 2: Run tests to verify RED**

Expected: PC import expects arbitrary host paths and does not claim Android tokens.

- [ ] **Step 3: Implement quarantine, validation, and atomic promotion**

Claim tokens into `workspace/import-staging/<uuid>`, unpack ZIPs with normalized relative paths, reject absolute paths and `..`, validate as one bundle, write the database transaction, then atomically move to `files/assets/<asset-id>`. On any exception, roll back the database and delete only the staging UUID.

Return no private paths from HTTP; expose asset/library tokens used by existing UI APIs.

- [ ] **Step 4: Run import tests to verify GREEN**

Expected: valid assets enter the catalog; invalid imports leave no database row or permanent asset directory.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/android_asset_import.py app/src/main/python/asset_import.py app/src/main/python/asset_validation.py app/src/main/python/webui.py app/src/test/python/test_android_asset_import.py
git commit -m "feat(android): import assets transactionally"
```

### Task 3: Asset Database and Library APIs

**Files:**
- Modify: `app/src/main/python/assetdb.py`
- Modify: `app/src/main/python/asset_catalog.py`
- Modify: `app/src/main/python/history_assets.py`
- Modify: `app/src/main/python/webui.py`
- Create: `app/src/test/python/test_android_asset_library.py`

**Interfaces:**
- Produces: PC-compatible asset list, filter, sort, copy-to-story, remove-copy, delete, preview-token, and history endpoints.

- [ ] **Step 1: Port focused PC asset tests**

Port behavior from `test_asset_catalog.py`, `test_asset_library.py`, `test_asset_copy_removal.py`, `test_web_asset_api.py`, and `test_history_assets.py`. Exclude renderer-specific assertions and assert `preview_available=false` when no bitmap preview exists.

- [ ] **Step 2: Run tests to verify RED**

Expected: database locations or Windows file references fail.

- [ ] **Step 3: Route catalog paths through the Android asset root**

Store relative asset paths in SQLite, resolve them only against `HALOCUE_ASSET_DIR`, and reject escaped paths. Preserve catalog tokens and sorting fields used by the PC UI. Missing preview files return a stable placeholder response and `preview_available=false`; they are not treated as corrupt assets.

- [ ] **Step 4: Run library tests to verify GREEN**

Expected: import, list, sort, copy, history, and delete workflows pass while renderer-specific preview remains optional.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/assetdb.py app/src/main/python/asset_catalog.py app/src/main/python/history_assets.py app/src/main/python/webui.py app/src/test/python/test_android_asset_library.py
git commit -m "feat(android): enable the PC asset library"
```

### Task 4: Official Expression ID and Semantic Extraction

**Files:**
- Modify: `app/src/main/python/build_index.py`
- Modify: `app/src/main/python/asset_validation.py`
- Modify: `app/src/main/python/asset_catalog.py`
- Create: `app/src/test/python/test_android_official_expressions.py`

**Interfaces:**
- Produces for each expression: `face_id`, `display_name`, `labels`, `raw_parts`, `source="official"`, and `confidence=1.0`; catalog exposes `face_count` and `face_capabilities`.

- [ ] **Step 1: Write failing official-expression tests**

Use fixtures containing atlas entries `03_smile`, `04_angry`, and plain `05`. Assert IDs are `03`, `04`, `05`, count is 3, semantic names are preserved where present, and no model provider is called.

- [ ] **Step 2: Run tests to verify RED**

Expected: existing parsing lacks the complete persisted source/confidence record required by Android.

- [ ] **Step 3: Normalize official semantic records**

Extend the existing `faces_of()` and `extract_expression_capabilities()` flow without changing accepted PC IDs. Official names become labels directly; plain numeric IDs remain valid records with empty labels. Persist source and raw evidence in the asset database migration.

- [ ] **Step 4: Run tests to verify GREEN**

Expected: all IDs and count are present, named entries have official semantics, and the provider mock records zero calls.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/build_index.py app/src/main/python/asset_validation.py app/src/main/python/asset_catalog.py app/src/test/python/test_android_official_expressions.py
git commit -m "feat(android): read official expression semantics"
```

### Task 5: Custom Spine Text Metadata Extraction

**Files:**
- Modify: `app/src/main/python/spine_semantic_faces.py`
- Create: `app/src/test/python/test_android_spine_metadata.py`

**Interfaces:**
- Produces: `extract_spine_metadata(source: str | Path) -> dict` containing `version`, `bones`, `slots`, `skins`, `animations`, `atlas_regions`, and `faces`.

- [ ] **Step 1: Write failing Spine 3.8 metadata tests**

Use a minimal binary fixture and assert stable output:

```python
assert result["version"].startswith("3.8")
assert result["bones"] == ["root", "face", "eye_L"]
assert result["slots"][0]["name"] == "mouth"
assert result["faces"]["03"]["raw_parts"]
```

Add an unsupported-version test which returns a structured issue while atlas-only expression IDs remain available.

- [ ] **Step 2: Run tests to verify RED**

Expected: the current parser skips bone and slot names and exposes only semantic combinations.

- [ ] **Step 3: Preserve names while retaining read-only parsing**

Replace `_skip_header_to_skins` with a reader that records bone names, slot names/default attachments, skin names, attachment names/paths, and animation names/zero-time attachments while consuming the same Spine 3.8 binary bytes. Do not add rendering dependencies or modify source files.

Merge `.atlas` region names into `atlas_regions`. On unsupported binary versions, return `{supported:false, issue:{code:"unsupported_spine_version", version}}` instead of crashing the entire asset import.

- [ ] **Step 4: Run metadata and existing semantic tests**

Run the new test plus the synchronized PC `test_spine_semantic_faces.py`. Expected: both pass and previous semantic combinations remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/spine_semantic_faces.py app/src/test/python/test_android_spine_metadata.py
git commit -m "feat(android): extract custom Spine naming metadata"
```

### Task 6: Deterministic and AI Semantic Suggestions

**Files:**
- Create: `app/src/main/python/face_semantic_suggester.py`
- Modify: `app/src/main/python/asset_catalog.py`
- Modify: `app/src/main/python/webui.py`
- Create: `app/src/test/python/test_face_semantic_suggester.py`

**Interfaces:**
- Produces: `suggest_face_semantics(face: dict, provider=None) -> dict` with `display_name`, `labels`, `source`, `confidence`, and `reason`.

- [ ] **Step 1: Write failing precedence and fallback tests**

```python
def test_clear_names_use_rules_without_ai(mock_provider):
    result = suggest_face_semantics({"face_id":"03", "raw_parts":["eye_smile", "mouth_smile"]}, mock_provider)
    assert result["source"] == "rule"
    assert "开心" in result["labels"]
    assert mock_provider.calls == 0


def test_ambiguous_names_use_structured_text_ai(mock_provider):
    result = suggest_face_semantics({"face_id":"07", "raw_parts":["eye_a2", "mouth_c4"]}, mock_provider)
    assert result["source"] == "ai_suggestion"
    assert 0 <= result["confidence"] <= 1
```

Also test missing provider, network error, invalid JSON, and `source=manual` non-overwrite.

- [ ] **Step 2: Run tests to verify RED**

Expected: the suggestion module does not exist.

- [ ] **Step 3: Implement rule-first text-only suggestion**

Reuse `extract_expression_capabilities()` for deterministic terms. Call the active text provider only when labels remain empty or conflicting. Require JSON schema:

```json
{
  "type": "object",
  "required": ["display_name", "labels", "confidence", "reason"],
  "properties": {
    "display_name": {"type": "string"},
    "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "reason": {"type": "string"}
  }
}
```

The prompt contains only raw text metadata and existing rule labels. Never send textures, screenshots, binary skeleton data, API Keys, or private paths.

- [ ] **Step 4: Run tests to verify GREEN**

Expected: rule cases do not call AI; ambiguous cases return editable suggestions; every failure returns raw/manual fallback.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/face_semantic_suggester.py app/src/main/python/asset_catalog.py app/src/main/python/webui.py app/src/test/python/test_face_semantic_suggester.py
git commit -m "feat(android): suggest custom expression semantics"
```

### Task 7: Editable Face Workbench and Manual Precedence

**Files:**
- Modify: `app/src/main/python/js/library_faces.js`
- Modify: `app/src/main/python/css/app.css`
- Modify: `app/src/main/python/webui.py`
- Modify: `app/src/main/python/assetdb.py`
- Create: `app/src/test/python/test_android_face_labels.py`

**Interfaces:**
- Consumes: face records with `source` and `confidence`.
- Produces: existing PATCH face-label endpoint plus suggestion request endpoint; manual save persists `source="manual"`.

- [ ] **Step 1: Write failing API precedence tests**

Assert manual PATCH changes the source to `manual`, a later rescan preserves it, and an AI suggestion is returned separately until explicitly accepted. Assert unlabeled faces still appear and are usable by raw ID.

- [ ] **Step 2: Run tests to verify RED**

Expected: existing PATCH data lacks the full source precedence behavior.

- [ ] **Step 3: Implement source-aware UI and persistence**

In `library_faces.js`, render expression count, raw ID, raw part names, editable display name/labels, source badge, confidence for AI suggestions, and commands to request/accept/ignore a suggestion. Do not create a preview placeholder that implies rendering; use the existing compact metadata layout.

Database update precedence is `manual > official > rule > ai_suggestion > empty`. A rescan may update `raw_parts` and timestamps but cannot replace manual display names or labels.

- [ ] **Step 4: Run API and UI contract tests**

Port relevant cases from `test_expression_inspector_semantic_export.py`, `test_semantic_face_catalog.py`, and `test_ui_asset_workbench_responsive.py`. Expected: face count and manual editing work at mobile width without Spine preview.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/js/library_faces.js app/src/main/python/css/app.css app/src/main/python/webui.py app/src/main/python/assetdb.py app/src/test/python/test_android_face_labels.py
git commit -m "feat(android): edit expression semantics without rendering"
```

### Task 8: Phase 3 Verification

**Files:**
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-android-assets-expression-semantics.md`

- [ ] **Step 1: Run clean asset verification**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-pc-runtime.ps1
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python -q
.\gradlew.bat clean testDebugUnitTest assembleDebug assembleDebugAndroidTest
git diff --check
```

- [ ] **Step 2: Verify official and custom resources on device**

Import one user-supplied official bundle and one custom bundle. Confirm official face count/IDs/names appear without AI calls. Confirm custom raw parts appear, rule/AI suggestions are editable, manual labels survive app restart and rescan, and unsupported semantics do not block `.aap` generation by raw ID.

- [ ] **Step 3: Record and commit results**

Record resource filenames only when non-sensitive, parser versions, expression counts, AI call/no-call evidence, tests, and remaining no-preview limitation.

```powershell
git add 安卓端接手记忆.md docs/superpowers/plans/2026-08-10-android-assets-expression-semantics.md
git commit -m "test(android): verify asset and expression workflow"
```
