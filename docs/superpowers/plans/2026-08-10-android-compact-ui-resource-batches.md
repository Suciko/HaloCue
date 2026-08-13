# Android Compact UI and AA Resource Mapping Implementation Plan

> **Status:** implementation complete; final regression/build verification is tracked in Task 5.

**Goal:** Keep Android behavior compatible with PC annotations while mapping the ordinary and extra resource packages already imported by the original AA application.

**Architecture:** Package the PC resource index as the base catalog. Generate an Android-only overlay from the supplied extra package's manifest and atlas metadata. Merge that overlay at runtime, then translate only selected serialized character identifiers at compile time. HaloCue never imports AA's ordinary or extra package.

## Global constraints

- Never access or write the original AA app's `Android/data` directory.
- Never add an AA resource-package importer to HaloCue Android.
- Never alter PC annotation identifiers, native keys, background keys, sound keys, or face IDs.
- Do not add Spine rendering to Android.
- Resolve same-name/multi-outfit aliases with `outfit_key`; do not guess.

### Task 1: Build the extra-package mapping

**Files:**
- `scripts/build-android-resource-mapping.ps1`
- `app/src/main/python/android_resource_mapping.json`
- `app/src/test/python/test_android_resource_mapping.py`

- [x] Read the extra package's `manifest.json` and portrait `.atlas` metadata without unpacking or shipping full resource assets.
- [x] Join entries to the PC index by `outfit_key` and preserve the PC identifier.
- [x] Record package identifier aliases, face IDs/labels, and characters missing from the PC index.
- [x] Verify the supplied package summary: 194 entries, 192 mapped, 52 aliases, 40 new, 1 skipped.

### Task 2: Merge and compile with outfit-aware aliases

**Files:**
- `app/src/main/python/android_resource_mapping.py`
- `app/src/main/python/android_compiler.py`
- `app/src/main/python/script2aap.py`
- `scripts/sync-compiler-core.ps1`

- [x] Merge the generated Android overlay into the PC base index at runtime.
- [x] Keep PC annotations stable and attach `android_package_identifier` to the matching outfit.
- [x] Translate only character names serialized into generated `.aap` scenes.
- [x] Require `outfit_key` when one PC identifier could refer to multiple outfits.
- [x] Make compiler synchronization line-ending independent and fail clearly if its injection point is missing.

### Task 3: Android settings and compact first screen

**Files:**
- `app/src/main/python/ui.html`
- `app/src/main/python/css/layout.css`
- `app/src/main/python/js/app.js`
- `app/src/test/python/test_android_ui_contract.py`

- [x] Hide PC AA path controls and Spine settings in the Android runtime.
- [x] Show mapping readiness plus character, background, sound, and alias counts.
- [x] Remove duplicated system-bar top spacing.
- [x] Collapse the ready-state panel and recent-story card so the script picker enters the first viewport.
- [x] Hide the action bar on downward scroll and restore it immediately on upward scroll.

### Task 4: Native file and folder selection parity

**Files:**
- `app/src/main/java/com/halocue/android/IncomingFileStore.kt`
- `app/src/main/java/com/halocue/android/MainActivity.kt`
- `app/src/main/python/android_incoming_files.py`
- `app/src/main/python/android_web_server.py`

- [x] Keep story-file selection tokenized and one-use.
- [x] Route custom asset files and directories through Android's system picker.
- [x] Keep these custom-asset flows separate from AA's own ordinary/extra-package importer.
- [x] Cover native staging and Python claim/cleanup behavior with host and instrumentation tests.

### Task 5: Full verification and device acceptance

- [x] Verify settings on vivo `V2324HA`: 983 characters, 580 backgrounds, 310 sounds, 52 aliases, and no PC AA path/Spine controls.
- [x] Verify on a loaded story that downward scrolling hides the action bar and upward scrolling restores it.
- [x] Run the complete Android Python suite: 70 passed, 1 skipped.
- [x] Build the main and instrumentation APKs.
- [x] Run the instrumentation suite on the connected vivo device: 29/29 passed.
- [x] Copy the final APK to `构建产物/`, record size/SHA-256, and update `安卓端接手记忆.md`.
