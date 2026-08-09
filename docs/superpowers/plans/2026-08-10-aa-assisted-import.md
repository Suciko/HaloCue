# AA Assisted Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户点击“生成并导入原版 AA”后，由 HaloCue 生成 `.aap`、暂存到 `Download/HaloCue/`、通过用户授权的辅助功能操作 vivo 文件管理器复制到原版 AA，并在成功后打开 AA。

**Architecture:** 保留现有 Chaquopy 编译层，新增相互独立的公共暂存器、导入任务仓库、纯 Kotlin 导航决策器和 vivo 辅助功能适配器。页面只消费统一的导入状态；“已导入”只能由辅助功能观察到复制成功后写入。

**Tech Stack:** Kotlin, Android MediaStore, AccessibilityService, WebView JavaScript bridge, Chaquopy/Python 3.13, JUnit 4, AndroidX instrumentation tests.

## Global Constraints

- 原版 AA 包名固定为 `com.foxxlight.AzureArchive`，不得修改、重签或注入。
- 首版真机范围固定为 vivo X100s Pro `V2324HA`、Android 16 / API 36、OriginOS 16。
- 辅助功能必须由用户主动授权，只能由用户点击“生成并导入原版 AA”后启动。
- 不申请传统存储权限，不把 ADB 能力当成 APK 能力。
- 不允许确认覆盖 AA 中的同名项目；遇到冲突必须停止。
- 自动导入失败必须保留私有生成物和公共暂存副本。
- 页面不得把“已生成”或“已暂存”显示成“已导入”。

---

### Task 1: Public AAP staging

**Files:**
- Create: `app/src/main/java/com/halocue/android/AapPublicExporter.kt`
- Create: `app/src/androidTest/java/com/halocue/android/AapPublicExporterTest.kt`
- Modify: `app/build.gradle.kts`

**Interfaces:**
- Consumes: `File` returned by `AndroidCompilerBridge.compileText`.
- Produces: `AapPublicExporter.export(source: File, project: String): PublicAapExportResult`; result fields are `uri: Uri`, `displayName: String`, `relativePath: String`, and `size: Long`.

- [x] **Step 1: Write a failing device test**

Create a unique private source file, call `AapPublicExporter.export`, query its returned URI through `ContentResolver`, and assert the bytes match, `DISPLAY_NAME == "HaloCueExportProbe.aap"`, and `RELATIVE_PATH == "Download/HaloCue/"`. Delete only the returned URI in `finally`.

- [x] **Step 2: Run the test and verify RED**

Run the single instrumentation class and confirm compilation fails because `AapPublicExporter` does not exist.

- [x] **Step 3: Implement MediaStore staging**

Use `MediaStore.Downloads.EXTERNAL_CONTENT_URI`, `DISPLAY_NAME`, MIME `application/json`, `RELATIVE_PATH`, and `IS_PENDING=1`. Copy bytes through `openOutputStream`, then publish with `IS_PENDING=0`. On failure, delete the new URI and rethrow. Reject missing source files and blank project names.

- [x] **Step 4: Verify GREEN**

Run the single instrumentation class and confirm the exported bytes and metadata pass on the vivo device without storage permission.

- [x] **Step 5: Commit**

Commit the exporter and its passing test as `feat(android): stage generated aap in downloads`.

### Task 2: Persistent import task and capability checks

**Files:**
- Create: `app/src/main/java/com/halocue/android/AaImportTaskStore.kt`
- Create: `app/src/main/java/com/halocue/android/AaImportCoordinator.kt`
- Create: `app/src/androidTest/java/com/halocue/android/AaImportTaskStoreTest.kt`
- Create: `app/src/androidTest/java/com/halocue/android/AaImportCoordinatorTest.kt`

**Interfaces:**
- Consumes: `PublicAapExportResult` from Task 1.
- Produces: `AaImportTask(project, displayName, sourceUri, state, message, updatedAt)` and `AaImportCoordinator.prepare(result): AaImportOutcome`.
- States: `READY`, `NEEDS_ACCESSIBILITY`, `IMPORTING`, `IMPORTED`, `FAILED`.

- [x] **Step 1: Write failing persistence and capability tests**

Assert a task round-trips through `SharedPreferences`; assert `prepare` returns `NEEDS_ACCESSIBILITY` when the HaloCue service is absent from `AccessibilityManager.getEnabledAccessibilityServiceList`, while preserving the staged URI and project.

- [x] **Step 2: Verify RED**

Run the focused device tests and confirm they fail because the task store/coordinator are absent. `SharedPreferences` is verified on Android directly rather than through a simulated JVM environment.

- [x] **Step 3: Implement the task store and coordinator**

Serialize only scalar fields into a private named preference file. Determine service availability using its exact component name. Expose intents for `Settings.ACTION_ACCESSIBILITY_SETTINGS` and the vivo file manager launcher. Do not launch either from `prepare`; return the required next action.

- [x] **Step 4: Verify GREEN**

Run focused tests, then the existing compiler bridge test to ensure the compiler remains independent of import state.

- [x] **Step 5: Commit**

Commit as `feat(android): track assisted AA imports`.

### Task 3: Semantic vivo file-manager navigator

**Files:**
- Create: `app/src/main/java/com/halocue/android/VivoImportNavigator.kt`
- Create: `app/src/test/java/com/halocue/android/VivoImportNavigatorTest.kt`
- Create: `app/src/main/java/com/halocue/android/VivoAaImportAccessibilityService.kt`
- Create: `app/src/main/res/xml/aa_import_accessibility_service.xml`
- Modify: `app/src/main/AndroidManifest.xml`

**Interfaces:**
- Consumes: normalized `VivoUiSnapshot(packageName, visibleTexts, clickableTexts, currentTask)`.
- Produces: one `VivoImportAction`: `ClickText`, `LongClickText`, `Back`, `Wait`, `Complete`, or `Fail`.
- The service executes only the action returned by the navigator and persists every state transition through `AaImportTaskStore`.

- [ ] **Step 1: Write failing navigator tests**

Cover these cases: wrong foreground package returns `Wait`; visible source filename returns `LongClickText`; a copy action returns `ClickText("复制")`; directory labels are visited in exact order `Android`, `data`, `com.foxxlight.AzureArchive`, `files`, `data`, `projects`; a same-name/replace dialog returns `Fail`; a visible copy-success state returns `Complete`.

- [ ] **Step 2: Verify RED**

Run the navigator unit test and confirm the missing navigator causes failure.

- [ ] **Step 3: Implement the pure decision engine**

Use text/resource semantics only. Keep navigation phase in the persisted task, reject unexpected packages, cap each phase at 20 seconds, and never return an action which confirms replacement/overwrite.

- [ ] **Step 4: Implement the thin accessibility adapter**

Register a non-exported `AccessibilityService` limited to the verified OriginOS package `com.android.filemanager`, with window-content retrieval enabled. Convert the active window into `VivoUiSnapshot`, locate exact text nodes, execute click/long-click/back, and stop itself logically when there is no active `IMPORTING` task. On `Complete`, persist `IMPORTED` and launch the original AA; on timeout or incompatible UI, persist `FAILED` without deleting files.

- [ ] **Step 5: Verify automated tests**

Run navigator tests and Android manifest/build validation. Confirm the service never treats `READY` or `NEEDS_ACCESSIBILITY` as permission to act.

- [ ] **Step 6: Commit**

Commit as `feat(android): add vivo assisted import service`.

### Task 4: One-button user flow

**Files:**
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/main/assets/index.html`
- Modify: `app/src/main/assets/app.css`
- Modify: `app/src/androidTest/java/com/halocue/android/MainActivityCompileTest.kt`

**Interfaces:**
- JavaScript calls `HaloCueNative.generateAndImport(project, text)`.
- Native calls `window.HaloCueApp.importUpdated(payload)` with `state`, `message`, `action`, and no private path in normal success output.
- Actions are `none`, `open_accessibility_settings`, and `retry_import`.

- [ ] **Step 1: Change the page contract test first**

Require the primary button text “生成并导入原版 AA”, initial status “尚未处理”, a hidden authorization explanation, and absence of a visible private path.

- [ ] **Step 2: Verify RED**

Run the page contract test and confirm it fails on the old “生成 .aap” UI.

- [ ] **Step 3: Implement native orchestration**

In the existing executor: compile, stage through `AapPublicExporter`, persist/prepare the import task, then return either authorization-required or start the file manager and mark `IMPORTING`. Add a separate bridge method which opens accessibility settings only after an explicit page button click. Refresh persisted import state in `onResume`.

- [ ] **Step 4: Implement user-facing states**

Replace technical copy with the approved phrases. Keep the public/private file path out of normal UI. Show the authorization card only for `NEEDS_ACCESSIBILITY`; show “继续导入” only for `FAILED`; disable repeated submission while generation/import launch is in progress.

- [ ] **Step 5: Verify GREEN**

Run page contract, compiler bridge, exporter, coordinator, and unit tests. Manually verify the screen on the vivo device before enabling the service.

- [ ] **Step 6: Commit**

Commit as `feat(android): add one-button generate and import flow`.

### Task 5: Vivo profiling, safe acceptance, and 0.3 artifact

**Files:**
- Modify: `app/src/main/java/com/halocue/android/VivoImportNavigator.kt`
- Modify: `app/src/test/java/com/halocue/android/VivoImportNavigatorTest.kt`
- Modify: `app/build.gradle.kts`
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-aa-assisted-import.md`
- Create: `evidence/halocue-v030-assisted-import-vivo-x100s-pro.png`
- Create: `构建产物/HaloCue-Android-MVP-0.3.0-dev-debug.apk`

**Interfaces:**
- Consumes: real vivo UI hierarchy captured while the user performs the one-time accessibility authorization.
- Produces: verified navigator rules for the exact OriginOS file-manager UI and a reproducible 0.3 APK.

- [ ] **Step 1: Install the development APK and request manual authorization clearly**

When vivo shows install/security or accessibility settings, tell the user the exact visible control to tap and why. Do not wait silently and do not automate system authorization.

- [ ] **Step 2: Run one unique import task**

Use a project name containing a timestamp, keep all pre-existing AA projects untouched, and collect UI hierarchy only for the active task. If real labels differ from tests, first add a failing navigator fixture test, then update the navigator.

- [ ] **Step 3: Verify the user-visible result**

Confirm the task store reaches `IMPORTED`, the source remains recoverable, original AA launches, and the unique project is visible in AA. Capture the HaloCue success screen or AA project list without exposing user-private content.

- [ ] **Step 4: Build and verify version 0.3**

Set `versionCode = 3` and `versionName = "0.3.0-dev"`; run all host tests, assemble app/test APKs, run focused device tests, and compute the final APK SHA-256.

- [ ] **Step 5: Update handoff memory and commit**

Record exact device labels/resource IDs, authorization behavior, verified limitations, artifact path/hash, and fallback behavior. Commit as `docs(android): record assisted import verification`.
