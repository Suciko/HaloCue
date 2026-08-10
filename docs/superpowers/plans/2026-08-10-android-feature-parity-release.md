# Android Feature Parity Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close remaining PC-to-Android API gaps, harden lifecycle and data migration, and produce a verified full-feature Android development release.

**Architecture:** Generate a machine-readable parity inventory from PC and Android routes, classify only documented platform exceptions, and close every remaining functional gap. Add versioned private-data migrations, bounded logs, lifecycle recovery, and a full host/device regression gate before packaging the APK.

**Tech Stack:** Python route introspection, Kotlin/Android lifecycle, SQLite migrations, WebView, Chaquopy, PowerShell verification, pytest, JUnit 4, AndroidX instrumentation.

## Global Constraints

- The Android first screen remains the original PC WebUI served from the protected local Python service.
- Windows-only AA installation, Windows executable discovery, Windows Credential Manager, and Spine rendering remain explicit platform exceptions.
- No accessibility, legacy storage, all-files access, Root, Shizuku, AA modification, or automatic AA-directory writes.
- User drafts, profiles, labels, assets, and story data must survive upgrades and process restarts.
- Logs must redact credentials, authorization headers, session tokens, complete scripts, private paths, and SAF authorization details.
- Release verification must include vivo X100s Pro / Android 16 and must preserve existing AA projects unchanged.

---

### Task 1: Machine-Readable PC/Android Parity Inventory

**Files:**
- Create: `scripts/compare-webui-parity.py`
- Create: `docs/android-platform-exceptions.json`
- Create: `app/src/test/python/test_webui_parity.py`

**Interfaces:**
- Produces: `docs/generated/android-webui-parity.json` with `pc_routes`, `android_routes`, `missing`, `extra`, and `exceptions`.

- [ ] **Step 1: Write failing parity test**

```python
def test_android_has_no_unclassified_pc_routes(parity_report):
    assert parity_report["missing"] == []
```

The exceptions file may classify only exact route/method pairs and must include a reason and Android replacement.

- [ ] **Step 2: Run test to verify RED**

Expected: the comparison script and report do not exist.

- [ ] **Step 3: Implement route extraction and classification**

Parse literal route comparisons from both PC and synchronized Android `webui.py`, recording method plus path/prefix. Generate deterministic sorted JSON. Initial allowed exceptions are limited to direct AA installation, Windows host browsing, Windows setup discovery, and Spine render/preview endpoints; each must name its Android replacement or disabled behavior.

- [ ] **Step 4: Run report and test**

```powershell
python scripts/compare-webui-parity.py
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python/test_webui_parity.py -q
```

Expected: test fails only for real unimplemented routes, not undocumented parser noise.

- [ ] **Step 5: Commit**

```powershell
git add scripts/compare-webui-parity.py docs/android-platform-exceptions.json app/src/test/python/test_webui_parity.py
git commit -m "test(android): inventory PC API parity"
```

### Task 2: Close Story, History, Audio, and Background Gaps

**Files:**
- Modify as reported: `app/src/main/python/webui.py`
- Modify as reported: `app/src/main/python/story_workspace.py`
- Modify as reported: `app/src/main/python/history_assets.py`
- Modify as reported: `app/src/main/python/background_workflow.py`
- Modify as reported: `app/src/main/python/js/history.js`
- Modify as reported: `app/src/main/python/js/story.js`
- Create: `app/src/test/python/test_android_remaining_workflows.py`

**Interfaces:**
- Produces: every non-exempt PC route identified by Task 1, with the same JSON fields and status behavior.

- [ ] **Step 1: Convert each missing route into a failing contract case**

Port the matching behavior from PC tests for story assets, history copy/replace, backgrounds, sounds, BGM, preflight, and review state. Each case must name the exact route and assert its response shape.

- [ ] **Step 2: Run the focused suite to verify RED**

Expected: each currently missing route fails separately.

- [ ] **Step 3: Implement non-platform routes using synchronized PC logic**

Copy or enable the PC handler branches and dependencies without rewriting their data contracts. Replace any host-path input with incoming file tokens and any direct AA install output with Android export metadata. Keep audio playback as WebView-served local media; missing decoders return a capability error instead of failing startup.

- [ ] **Step 4: Regenerate parity report and verify GREEN**

Run the focused suite and Task 1 report. Expected: no unclassified missing routes remain for these workflows.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python app/src/test/python/test_android_remaining_workflows.py docs/generated/android-webui-parity.json
git commit -m "feat(android): close remaining PC workflow gaps"
```

### Task 3: Official Catalog and Preview Capability Fallbacks

**Files:**
- Modify: `app/src/main/python/official_catalog.py`
- Modify: `app/src/main/python/official_preview_index.py`
- Modify: `app/src/main/python/aa_resource_cache.py`
- Modify: `app/src/main/python/js/library_preview.js`
- Create: `app/src/test/python/test_android_official_catalog.py`

**Interfaces:**
- Produces: PC-compatible official catalog metadata and explicit `preview_available`/`preview_reason` fields.

- [ ] **Step 1: Write failing selected-resource tests**

Test an indexed user-selected official resource root, a missing root, a resource with a bitmap preview, and a character with semantics but no renderable preview. Assert catalog search still works when preview is unavailable.

- [ ] **Step 2: Run tests to verify RED**

Expected: Windows AA cache discovery or preview assumptions fail.

- [ ] **Step 3: Replace discovery with selected private index roots**

Read only imported/indexed resource roots under the Android asset directory. Never probe AA `Android/data`. Serve existing bitmap previews when present; otherwise return `preview_available=false` and keep semantic/catalog data. Update the UI to display the metadata state without a broken image request.

- [ ] **Step 4: Run tests and parity report**

Expected: official catalog routes pass, no Windows cache path is accessed, and missing preview is non-fatal.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/official_catalog.py app/src/main/python/official_preview_index.py app/src/main/python/aa_resource_cache.py app/src/main/python/js/library_preview.js app/src/test/python/test_android_official_catalog.py
git commit -m "feat(android): support selected official resource indexes"
```

### Task 4: Versioned Data Migrations and Recovery

**Files:**
- Create: `app/src/main/python/android_migrations.py`
- Create: `app/src/test/python/test_android_migrations.py`
- Modify: `app/src/main/python/android_web_server.py`
- Modify: `app/src/main/java/com/halocue/android/LocalWebRuntime.kt`

**Interfaces:**
- Produces: `migrate(workspace_root: str) -> dict` with `from_version`, `to_version`, and applied migration IDs.

- [ ] **Step 1: Write failing upgrade tests**

Create fixtures representing current 0.3 data and each new schema state. Assert migration is idempotent, preserves drafts/profile metadata/assets/manual face labels, separates rebuildable caches, and recovers from an interrupted staging import.

- [ ] **Step 2: Run tests to verify RED**

Expected: no centralized Android migration runner exists.

- [ ] **Step 3: Implement ordered transactional migrations**

Store the schema version in `files/workspace/android-schema.json`. Define ordered functions such as `v1_runtime_layout`, `v2_secure_credentials`, `v3_asset_semantics`; each writes to temporary files or database transactions and records completion only after success. Run migrations before starting the HTTP server. On failure, keep user data and return a startup error with the migration ID.

- [ ] **Step 4: Run upgrade and restart tests**

Expected: repeated migration produces no changes; simulated interruption resumes safely; service starts only after a successful migration.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/android_migrations.py app/src/test/python/test_android_migrations.py app/src/main/python/android_web_server.py app/src/main/java/com/halocue/android/LocalWebRuntime.kt
git commit -m "feat(android): migrate private data safely"
```

### Task 5: Lifecycle, Task Recovery, and Redacted Diagnostics

**Files:**
- Create: `app/src/main/python/android_diagnostics.py`
- Create: `app/src/test/python/test_android_diagnostics.py`
- Modify: `app/src/main/python/jobs.py`
- Modify: `app/src/main/python/android_web_server.py`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`

**Interfaces:**
- Produces: bounded diagnostic bundle and persisted resumable job metadata without secrets or full scripts.

- [ ] **Step 1: Write failing recovery and redaction tests**

Assert saved job metadata contains job ID, stage, timestamps, progress, and result references but not story text or provider secrets. Assert redaction removes `Authorization`, `X-HaloCue-Session`, API-key-shaped values, private workspace paths, and `content://` URIs.

- [ ] **Step 2: Run tests to verify RED**

Expected: no Android diagnostic redactor or persisted recovery index exists.

- [ ] **Step 3: Implement bounded state and diagnostics**

Persist only recoverable job summaries under `workspace/jobs`; atomically update them at stage transitions. On service startup, mark interrupted in-memory-only model calls as failed/retryable and restore completed draft/build references. Keep rotating logs under 5 files of 1 MiB each. Diagnostic export includes capability report, schema versions, redacted logs, and app version only.

`MainActivity` must survive configuration changes without starting a second server and must reconnect WebView to the active `LocalWebSession`.

- [ ] **Step 4: Run lifecycle and redaction tests**

Expected: activity recreation keeps one server, completed state remains available, and sensitive scans find no matches.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/android_diagnostics.py app/src/test/python/test_android_diagnostics.py app/src/main/python/jobs.py app/src/main/python/android_web_server.py app/src/main/java/com/halocue/android/MainActivity.kt
git commit -m "fix(android): recover work and redact diagnostics"
```

### Task 6: Full Regression Matrix

**Files:**
- Create: `scripts/test-android-parity.ps1`
- Modify: `scripts/test-device-page-contract.ps1`
- Modify: `docs/android-platform-exceptions.json`

**Interfaces:**
- Produces: one command which runs sync, parity, Python, Gradle, instrumentation, page, and permission contracts.

- [ ] **Step 1: Write the regression script with fail-fast stages**

The script must run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-pc-runtime.ps1
powershell -ExecutionPolicy Bypass -File scripts/test-pc-runtime-sync.ps1
python scripts/compare-webui-parity.py
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python -q
.\gradlew.bat clean testDebugUnitTest assembleDebug assembleDebugAndroidTest
```

When `-Device` is supplied, also install the APK, run `connectedDebugAndroidTest`, and run the page contract. Add manifest assertions rejecting `MANAGE_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, accessibility services, and AA-data permissions.

- [ ] **Step 2: Run host mode and fix every failure**

Expected: the script exits 0 and emits a concise summary with test counts and parity exceptions.

- [ ] **Step 3: Run device mode and fix every failure**

Expected: instrumentation/page contracts pass on vivo X100s Pro / Android 16 without hanging Espresso Web as the sole verification mechanism.

- [ ] **Step 4: Commit**

```powershell
git add scripts/test-android-parity.ps1 scripts/test-device-page-contract.ps1 docs/android-platform-exceptions.json
git commit -m "test(android): add full parity regression gate"
```

### Task 7: Device Acceptance and Development Release

**Files:**
- Modify: `app/build.gradle.kts`
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-android-feature-parity-release.md`
- Create: `构建产物/HaloCue-Android-Full-<version>-debug.apk`
- Create: `evidence/halocue-android-full-vivo-x100s-pro.png`

**Interfaces:**
- Consumes: all previous plans and Tasks 1-6.
- Produces: installable development APK, SHA-256, screenshot evidence, and final handoff record.

- [ ] **Step 1: Set the next unique development version**

Read the current `versionCode`; increment it by exactly one and set a matching development `versionName`. Do not reuse `versionCode = 3` or overwrite the existing 0.3 artifact.

- [ ] **Step 2: Run the full regression gate**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-android-parity.ps1 -Device
git diff --check
```

Expected: zero unclassified parity gaps, all required tests pass, and only documented platform exceptions remain.

- [ ] **Step 3: Complete the real-device acceptance workflow**

On vivo X100s Pro / Android 16:

1. Open the full PC UI inside HaloCue.
2. Configure a model credential and confirm only masked status is shown after restart.
3. Import a story and save/reopen a draft.
4. Import one official and one custom character resource.
5. Verify official expression count/semantics without AI.
6. Verify custom raw part names, AI suggestion when needed, and manual override persistence.
7. Generate a unique `.aap`, publish it to `Download/HaloCue/`, and open the share chooser.
8. Confirm the original AA project directory hashes and file list are unchanged.

- [ ] **Step 4: Package and hash the artifact**

Copy the built APK to a new exact filename under `构建产物`, compute SHA-256 with `Get-FileHash`, and capture a screenshot which shows the full Android WebUI without private script or credential content.

- [ ] **Step 5: Update handoff and commit**

Record version, artifact path/hash, test counts, parity exceptions, device results, expression behavior, and known deferred Spine-rendering limitation in `安卓端接手记忆.md`. Mark plan checkboxes only after evidence exists.

```powershell
git add app/build.gradle.kts 安卓端接手记忆.md docs/superpowers/plans/2026-08-10-android-feature-parity-release.md evidence 构建产物
git commit -m "release(android): verify full PC feature parity build"
```
