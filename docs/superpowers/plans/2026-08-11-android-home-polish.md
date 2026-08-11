# Android Home Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a denser, calmer Android home screen while preserving every PC and Android workflow action.

**Architecture:** Add semantic state to the existing story and asset components, then style those states only inside the Android narrow-screen CSS block. The shared WebUI structure and APIs remain unchanged.

**Tech Stack:** HTML, CSS, browser JavaScript, Python pytest contracts, Android WebView, Gradle, ADB.

## Global Constraints

- Do not change PC layout or behavior.
- Do not remove any top-bar, story, asset, or workflow action.
- Keep command touch targets at least 44 px high.
- Keep the existing Android top-bar scroll behavior.

---

### Task 1: Define the compact Android home contract

**Files:**
- Modify: `app/src/test/python/test_android_ui_contract.py`

**Interfaces:**
- Consumes: Android runtime CSS markers and WebUI component source.
- Produces: A regression contract for the compact header, story summary, empty asset state, and workflow strip.

- [x] Add assertions for `.android-home-header`, `.android-story-summary`, `.story-asset-strip.is-empty-state`, and compact workflow selectors.
- [x] Run the focused contract while implementing the markers and confirm the final contract passes.

### Task 2: Add semantic rendering hooks

**Files:**
- Modify: `app/src/main/python/ui.html`
- Modify: `app/src/main/python/js/story.js`
- Modify: `app/src/main/python/js/assets.js`

**Interfaces:**
- Consumes: Existing `StoryContextBar.render(story)` and `StoryAssetStrip.renderContent(loading, error)` state.
- Produces: Stable classes and title text for Android-only CSS without changing API data.

- [x] Add header and story-summary class hooks to existing elements.
- [x] Make the story title prefer `source_name` so internal workspace paths do not become the primary label.
- [x] Toggle `is-empty-state` only when no asset cards, active tasks, loading state, or error exists.
- [x] Re-run the focused UI contract after the semantic hooks.

### Task 3: Implement the Android narrow-screen layout

**Files:**
- Modify: `app/src/main/python/css/layout.css`

**Interfaces:**
- Consumes: The semantic classes from Task 2.
- Produces: Android-only compact top bar, story summary, empty asset section, and workflow strip.

- [x] Add styles under `body.android-native` and `@media (max-width: 600px)` only.
- [x] Preserve 44 px command targets and the existing scroll-hide transforms.
- [x] Center command controls on both axes while preserving left-aligned catalog rows and metadata.
- [x] Run the focused UI contract and confirm it passes.
- [x] Run `node --check` on each modified JavaScript file.

### Task 4: Build and verify on device

**Files:**
- Modify: `docs/superpowers/plans/2026-08-11-android-home-polish.md`

**Interfaces:**
- Consumes: Final WebUI source and Android project.
- Produces: Verified APK and first-screen screenshot.

- [x] Run the complete Android Python suite: 90 collected, 89 passed, 1 skipped.
- [x] Build `assembleDebug` and `assembleDebugAndroidTest` with stable single-process Kotlin settings: `BUILD SUCCESSFUL`, 75 tasks.
- [x] Install the APK and run direct ADB instrumentation on vivo `V2324HA`: 30/30 tests passed on Android 16 / API 36.
- [x] Inspect the first screen, material workbench, settings, import dialog, and review UI in the in-app browser at 360 x 800 and 412 x 915.
- [x] Update this checklist with exact verification counts and APK hash.

## Final Verification Results

- `deepseek-v4-flash` is the DeepSeek preset in both Python and JavaScript. A temporary unsaved text connection test returned `ok=true`, `mode=text`, and `model=deepseek-v4-flash`.
- Browser measurements covered 22 main-workflow command controls at each phone width and 15 material/import controls. All measured content centers were within 1 px of the control center.
- The complete saved-story flow passed: reopen story, open draft, approve all 7 cards, validate with 0 blocking errors, compile, and export a valid JSON `.aap`.
- Preview AAP: `.preview-workspace-ui-fix/exports/HaloCue/完整流程测试.aap`, 11,756 bytes, SHA-256 `DCD43D5D41FDE7A196A9E44E12A2B26C4189C2329BFF5C1BD7E8E4FD8212BA23`.
- Delivery APK: `构建产物/HaloCue-Android-PC-Parity-0.3.0-dev-debug.apk`, 58,628,973 bytes, SHA-256 `41E9E8416B6AF99614892694E49524261AB0EDC746614107FF88A4338E57F19F`.
- The 30 Android instrumentation tests were installed and run on vivo `V2324HA`; all 30 passed in 5.29 seconds.
- Device screenshots confirm the home screen, active-story screen, settings, material workbench, and import dialog have no overlap or horizontal overflow. Evidence is stored under `evidence/halocue-final-device-*.png`.
- Device settings show `DeepSeek · deepseek-v4-flash` with `文字已通过`, and PC annotation mapping reports `可用`.
- The import dialog remained open across portrait -> landscape -> portrait. The original automatic-rotation settings (`accelerometer_rotation=1`, `user_rotation=0`) were restored afterward.
- No computer shutdown or restart was scheduled.

## 2026-08-11 continuation: native inset and launcher verification

- Android fullscreen surfaces now override duplicated WebView safe-area compensation for settings, material workbench, import dialog, history, asset library, and face workspace. The import dialog starts at the native content edge instead of adding a second gray status-bar band.
- The recent-story Continue action is a centered full-width command on the Android narrow layout; the filename and metadata remain centered only in that recent-story card, while catalog rows remain left aligned.
- The launcher now uses the original PC source `branding/halocue-icon.png` (1024x1024 RGBA), downsampled once into the Android density PNGs and the 432px adaptive foreground. No newly drawn replacement mark is used.
- Focused Android UI contracts: 15 passed. Gradle `assembleDebug assembleDebugAndroidTest`: successful. Direct vivo instrumentation: `OK (30 tests)` in 3.679 seconds.
- Final delivery APK: `构建产物/HaloCue-Android-PC-Parity-0.3.0-dev-debug.apk`, 58,628,638 bytes, SHA-256 `6B16E729F6F519F9727C50F533813560808307D8F5E5209BD4E14D4908494A8B`.
- Real-device screenshots confirm the original launcher mark, centered Continue action, settings spacing, material empty-state spacing, and import dialog without the former top gray band. After reconnecting ADB, an explicit window-manager rotation completed portrait (1260x2800) -> landscape (2800x1260) -> portrait while `com.halocue.android/.MainActivity` remained top-resumed and the import dialog stayed open. Automatic rotation was restored to `accelerometer_rotation=1`, `user_rotation=0`.
- Final launcher QA uses a pure white adaptive/legacy background and the original 1024px PC artwork. The adaptive foreground stays at `ContentScale 0.60`; the vivo desktop screenshot `evidence/halocue-icon-white.png` confirms centered artwork, intact arcs, and no clipping.
