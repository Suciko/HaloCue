# Android Compact UI and Incremental Resource Batches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Android workbench compact and let users import multiple AA resource batches through one entry while preserving the PC mapping keys.

**Architecture:** A small Python resource-library module validates incoming ZIP/tree snapshots and merges Addressables bundles into an app-private canonical cache, recording batch metadata without changing existing catalog/mapping functions. The Android bridge stages either a document or a tree into the existing private incoming area. The WebUI replaces the PC-only AA path controls with an Android batch importer and adds a scroll-aware compact workbench header.

**Tech Stack:** Kotlin Android ActivityResult APIs, DocumentsContract, Chaquopy Python 3.13 standard library, existing WebUI HTML/CSS/JavaScript, pytest and Android instrumentation tests.

## Global Constraints

- Never access or write the original AA app's `Android/data` directory.
- Never alter PC identifier, native-key, background-key, sound-key, or face-ID mapping algorithms.
- Do not add Spine rendering to Android.
- A failed batch must not change the active library or invalidate the previous index.
- Re-importing identical content is idempotent.

### Task 1: Resource Library Core

**Files:**
- Create: `app/src/main/python/android_resource_library.py`
- Modify: `app/src/main/python/android_web_server.py`
- Test: `app/src/test/python/test_android_resource_library.py`

**Interfaces:**
- `import_batch(source: Path, library_root: Path) -> dict` validates and merges one staged directory or archive.
- `resource_library_status(library_root: Path) -> dict` returns batch count, active catalog, cache counts and last import.
- The effective catalog remains at `<library_root>/catalog.json`; effective bundles remain under `<library_root>/cache`.

- [ ] **Step 1: Write failing tests** for a base batch followed by an extra batch, idempotent re-import, same-key replacement, traversal rejection, and failed-batch rollback. Use tiny fake UnityFS files beginning with `UnityFS` and minimal Addressables catalog fixtures.
- [ ] **Step 2: Run the focused pytest file** and confirm failures are caused by the missing module/functions.
- [ ] **Step 3: Implement staged validation and merge.** Accept a directory containing `catalog.json` plus cache directories, or a ZIP with safe relative paths. Copy only validated `__data` UnityFS bundles and catalog files into a temporary merge directory, then atomically replace active files and append a JSON batch manifest. Count `added`, `duplicate`, and `replaced` by canonical relative key.
- [ ] **Step 4: Expose status through Android runtime setup** while keeping the existing PC `setup_status()` shape compatible. The Android status must include `aa.resource_library` and must not claim an AA executable is connected.
- [ ] **Step 5: Run the focused tests** and commit `feat(android): add incremental resource library`.

### Task 2: Native Android Document and Directory Staging

**Files:**
- Create: `app/src/main/java/com/halocue/android/IncomingResourceStore.kt`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/main/python/js/resource_import.js`
- Test: `app/src/androidTest/java/com/halocue/android/IncomingResourceStoreTest.kt`
- Test: `app/src/test/python/test_android_resource_picker_js.py`

**Interfaces:**
- JavaScript calls `HaloCueNative.pickResource(requestId, mode)` where `mode` is `document` or `tree`.
- JavaScript receives `HaloCueAndroid.resourcePicked({requestId, ok, token, name, size})` and claims it with `POST /api/resources/import`.
- `IncomingResourceStore` stages a ZIP document or recursively copies a selected tree into `files/incoming-resources/<token>/` with a manifest and byte limit.

- [ ] **Step 1: Write failing tests** for safe staging, cancellation, one-use result claiming, and directory traversal/name normalization.
- [ ] **Step 2: Run the focused JVM/instrumentation tests** and confirm the new contracts fail before implementation.
- [ ] **Step 3: Implement the store** using temporary files/directories followed by atomic rename; reject symlink-like or invalid relative paths and enforce a bounded total size.
- [ ] **Step 4: Add `OpenDocument` and `OpenDocumentTree` launchers** to `MainActivity`, preserve pending request/result across rotation, and deliver the same one-use acknowledgement behavior as story imports.
- [ ] **Step 5: Add `resource_import.js`** to start the picker, claim the token, render progress/status, and refresh setup status after a successful import.
- [ ] **Step 6: Run Android tests** and commit `feat(android): stage resource directories through SAF`.

### Task 3: Android WebUI Resource Settings

**Files:**
- Modify: `app/src/main/python/ui.html`
- Modify: `app/src/main/python/js/app.js`
- Modify: `app/src/main/python/css/layout.css`
- Modify: `app/src/main/python/webui.py`
- Modify: `app/src/main/python/android_web_server.py`
- Test: `app/src/test/python/test_android_web_server.py`

**Interfaces:**
- Android `POST /api/resources/import` claims a staged token, calls `android_resource_library.import_batch`, and returns counts plus `aa.resource_library` status.
- Android `GET /api/setup/status` returns an Android-specific resource section; PC keeps its existing AA install controls.

- [ ] **Step 1: Write failing contract tests** proving Android no longer renders or calls the PC-only AA executable endpoint, that `/api/settings/aa-install` remains explicitly unavailable, and that `/api/resources/import` merges successive batches.
- [ ] **Step 2: Run the focused tests** and verify the expected failures.
- [ ] **Step 3: Replace the Android settings block** with one “导入 AA 资源” control, “导入文件/导入目录” actions, current library summary, last batch, and “重建图片预览”. Keep the PC HTML unchanged via a platform class or server-injected data attribute.
- [ ] **Step 4: Wire the import action and error states** so previous catalog status remains visible after a rejected batch.
- [ ] **Step 5: Run Python tests** and commit `feat(android): expose cumulative resource imports`.

### Task 4: Compact First Screen and Scroll Toolbar

**Files:**
- Modify: `app/src/main/python/ui.html`
- Modify: `app/src/main/python/css/layout.css`
- Modify: `app/src/main/python/js/app.js`
- Test: `app/src/test/python/test_android_ui_contract.py`

**Interfaces:**
- `window.HaloCueUI.updateScrollChrome(scrollTop, direction)` toggles `is-compact` / `is-hidden` classes on the mobile topbar.
- `window.HaloCueUI.readinessSummary(statuses)` produces the compact readiness label from real status data.

- [ ] **Step 1: Write failing contract tests** for the compact summary markup, readiness details hidden by default when all required checks pass, and scroll-down/up class behavior.
- [ ] **Step 2: Run focused tests** and confirm failure.
- [ ] **Step 3: Reduce mobile topbar/content padding**, make the welcome panel collapse to a summary after readiness succeeds, and add a 48-56dp sticky compact toolbar that reappears on upward scroll.
- [ ] **Step 4: Keep full settings/model workbench in the drawer** and ensure no model editor is pinned to the page viewport.
- [ ] **Step 5: Run Python contract tests** and commit `feat(android): compact mobile workbench chrome`.

### Task 5: Full Verification and Device Acceptance

**Files:**
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-android-model-draft-generation.md`
- Create: `构建产物/HaloCue-Android-Compact-Resources-0.3.0-dev-debug.apk`

- [ ] **Step 1: Run Android Python tests:** `python -m pytest app/src/test/python -q`.
- [ ] **Step 2: Build APK and instrumentation tests:** `./gradlew.bat assembleDebug assembleDebugAndroidTest`.
- [ ] **Step 3: Install to the connected vivo device**, import a base fixture directory, then import an extra fixture directory through the same entry. Verify the status shows two batches and both catalog keys remain selectable.
- [ ] **Step 4: Capture phone screenshots** at the top, after scrolling down, and after scrolling up; verify the script picker appears earlier and the compact toolbar does not overlap content.
- [ ] **Step 5: Update the handoff/test counts and commit `test(android): verify compact UI and cumulative resources`.
