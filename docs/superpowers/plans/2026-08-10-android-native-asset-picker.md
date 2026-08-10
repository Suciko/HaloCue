# Android Native Asset Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Android's embedded PC-style custom-asset browser with system document and directory pickers while keeping story-scoped validation and registration.

**Architecture:** Extend the existing WebView-to-Kotlin document picker contract with explicit `asset_file` and `asset_tree` purposes. Kotlin copies selected provider content into the existing app-private incoming area; Python atomically claims the opaque token and returns a normal private path/file token to the unchanged asset validation and registration flow.

**Tech Stack:** Kotlin, Android Activity Result APIs, Storage Access Framework, `DocumentsContract`, Chaquopy Python 3.13, JavaScript WebUI, JUnit/AndroidX instrumentation, pytest/Node.

## Global Constraints

- Android never reads or writes the original AA application's `Android/data` directory.
- Python never receives or persists `content://` URIs.
- A story remains required for custom asset registration.
- Background and sound use a single system document selection.
- Character and batch imports use a system directory tree selection.
- PC host-browser behavior remains unchanged.
- Failed or cancelled selections do not create import tasks or alter registered assets.
- Preserve unrelated dirty worktree changes.

---

### Task 1: Native Picker Request Contract

**Files:**
- Modify: `app/src/main/java/com/halocue/android/AndroidDocumentPicker.kt`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Test: `app/src/androidTest/java/com/halocue/android/IncomingFileStoreTest.kt`

**Interfaces:**
- Produces: `DocumentPickPurpose` enum with wire values `story`, `asset_file`, and `asset_tree`.
- Produces: `DocumentPickRequest(requestId, purpose, assetKind, allowedSuffixes)`.
- Produces: picker launch routing that maps `asset_tree` to `OpenDocumentTree` and the other purposes to `OpenDocument`.

- [ ] **Step 1: Write failing request-contract tests**

Add assertions that supported purposes parse, unsupported purposes are rejected, `asset_file` requires `background` or `sound`, and `asset_tree` accepts `character` or `batch`.

- [ ] **Step 2: Run the instrumentation test and verify RED**

Run: `./gradlew.bat :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.halocue.android.IncomingFileStoreTest`

Expected: compilation/test failure because the new purpose and asset-kind contract does not exist.

- [ ] **Step 3: Implement the request contract and launch routing**

Parse bridge requests before storing them, preserve purpose/kind through activity recreation, launch the correct Activity Result contract, and return `invalid_request`, `picker_busy`, or `picker_unavailable` without changing the active story.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 2: Bounded Private Tree Staging and Python Claiming

**Files:**
- Modify: `app/src/main/java/com/halocue/android/IncomingFileStore.kt`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/main/python/android_incoming_files.py`
- Test: `app/src/androidTest/java/com/halocue/android/IncomingFileStoreTest.kt`
- Test: `app/src/test/python/test_android_incoming_files.py`

**Interfaces:**
- Produces: `IncomingTree(token: String, name: String, fileCount: Int, size: Long)`.
- Produces: `IncomingFileStore.stageTree(displayName, entries, limits): IncomingTree`, where entries expose normalized relative path plus input stream.
- Produces: `claim_incoming_tree(token: str) -> pathlib.Path`.

- [ ] **Step 1: Write failing staging and claiming tests**

Cover a valid Spine tree, duplicate/unsafe relative paths, file-count and total-size limits, one-use claims, and cleanup after failure.

- [ ] **Step 2: Run Kotlin and Python tests and verify RED**

Run: `./gradlew.bat :app:connectedDebugAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=com.halocue.android.IncomingFileStoreTest`

Run: `python -m pytest app/src/test/python/test_android_incoming_files.py -q`

Expected: FAIL because tree staging and claiming are absent.

- [ ] **Step 3: Implement bounded tree copy and atomic claim**

Traverse the granted document tree with `DocumentsContract`, reject unsafe names, cap depth/file count/per-file bytes/total bytes, write metadata only after all files finish, and delete only the new token directory on failure. Python validates metadata and atomically moves the tree to `workspace/imports/<token>`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run both commands from Step 2. Expected: PASS.

### Task 3: Android WebUI Native Asset Selection

**Files:**
- Modify: `app/src/main/python/js/story_picker.js`
- Modify: `app/src/main/python/js/library_import.js`
- Modify: `app/src/main/python/js/assets.js`
- Modify: `app/src/main/python/ui.html`
- Test: `app/src/test/python/test_android_story_picker_js.py`
- Test: `app/src/test/python/test_android_ui_contract.py`

**Interfaces:**
- Produces: `StoryFilePicker.openNative(trigger, purpose, assetKind)` using the existing `HaloCueNative.pickDocument` bridge.
- Produces: native selection results containing `file_token`, `name`, and `size` for files or `tree_token`, `name`, `file_count`, and `size` for trees.
- Consumes: Task 1 bridge contract and Task 2 private tokens.

- [ ] **Step 1: Write failing JavaScript/UI contract tests**

Assert Android background/sound actions request `asset_file`, character requests `asset_tree`, batch scan requests `asset_tree`, and the embedded host panel is not opened. Assert the non-Android path still calls `openHost()`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest app/src/test/python/test_android_story_picker_js.py app/src/test/python/test_android_ui_contract.py -q`

Expected: FAIL because asset pickers only use host endpoints and the old scan label remains.

- [ ] **Step 3: Implement Android-only native selection**

Generalize native request dispatch in `story_picker.js`, route the asset dialog by kind, feed successful selections into `StoryAssets.importLocal`, route batch directories into scan registration, change Android-facing labels, and never reveal the embedded host browser on Android.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 4: Python Token Exchange and Asset Discovery

**Files:**
- Modify: `app/src/main/python/webui.py`
- Modify: `app/src/main/python/asset_import.py`
- Test: `app/src/test/python/test_android_web_server.py`
- Create: `app/src/test/python/test_android_asset_picker.py`

**Interfaces:**
- Produces: `POST /api/assets/select-native` accepting `incoming_token`, `kind`, and `selection_type`.
- Produces: one-use file/tree token payload suitable for existing `/api/assets/validate` and `/api/assets/register` calls.
- Produces: `resolve_character_source(root: Path) -> Path`, returning the unique valid Spine bundle root or raising `AssetImportRequestError`.

- [ ] **Step 1: Write failing endpoint and discovery tests**

Cover file-token exchange, tree-token exchange, unique Spine bundle selection, zero/multiple bundle errors, token reuse rejection, and batch discovery under a selected tree.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest app/src/test/python/test_android_web_server.py app/src/test/python/test_android_asset_picker.py -q`

Expected: FAIL because the endpoint and tree source resolution are absent.

- [ ] **Step 3: Implement the exchange endpoint and source resolution**

Claim incoming content once, register opaque file tokens, normalize character tree sources before existing validation, and send stable error codes without returning private paths to JavaScript.

- [ ] **Step 4: Run tests and verify GREEN**

Run the command from Step 2. Expected: PASS.

### Task 5: Regression Verification and APK

**Files:**
- Modify only if tests expose an in-scope regression.
- Output: `app/build/outputs/apk/debug/app-debug.apk`

**Interfaces:**
- Consumes all previous tasks.
- Produces a debug APK for device verification.

- [ ] **Step 1: Run the full Python suite**

Run: `python -m pytest app/src/test/python -q`

Expected: all tests pass.

- [ ] **Step 2: Run Android unit tests and build**

Run: `./gradlew.bat :app:testDebugUnitTest :app:assembleDebug`

Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 3: Run available connected instrumentation tests**

Run: `./gradlew.bat :app:connectedDebugAndroidTest`

Expected: all connected tests pass; if no device is connected, record that limitation explicitly.

- [ ] **Step 4: Inspect the final diff and artifact**

Run: `git diff --check` and `Get-FileHash app/build/outputs/apk/debug/app-debug.apk -Algorithm SHA256`.

Expected: no whitespace errors and a fresh APK hash.
