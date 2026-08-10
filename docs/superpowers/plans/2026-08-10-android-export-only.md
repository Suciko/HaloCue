# Android Export-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 把 HaloCue 安卓端从不可行的自动导入模式收口为可验证的本机编译、公共目录导出和系统分享闭环，并交付 0.3.0-dev APK。

**Architecture:** 保留 Chaquopy 编译核心和 `AapPublicExporter`，由 `MainActivity` 在后台完成“编译 -> MediaStore 导出”，原生层仅在内存中持有最近导出的 URI。页面只消费导出状态和公共相对路径；分享通过独立的 `AapShareIntentFactory` 构造安全的 `ACTION_SEND` Intent。整个 vivo 辅助导入子系统从清单、代码、资源和测试中删除。

**Tech Stack:** Kotlin, Android WebView, MediaStore Downloads, Android share intents, Chaquopy Python 3.13, JUnit 4, AndroidX instrumentation, PowerShell device contracts.

## Global Constraints

- 原版 AA 包名固定为 `com.foxxlight.AzureArchive`，不得修改、重签或注入。
- 公共文件固定发布到 `Download/HaloCue/<工程名>.aap`。
- 不申请传统存储权限、所有文件访问权限或辅助功能权限。
- 页面不得显示或声称“已导入原版 AA”。
- 分享 URI 只保留在原生内存中，页面只接收 `displayName`、`relativePath` 和 `shareAvailable`。
- 下一个交付版本固定为 `versionCode = 3`、`versionName = "0.3.0-dev"`。
- 所有真机测试只创建唯一探针文件，并按明确 URI 或文件名清理。

---

### Task 1: Export-only page contract

**Files:**
- Modify: `scripts/test-device-page-contract.ps1`
- Modify: `app/src/main/assets/index.html`
- Modify: `app/src/main/assets/app.css`

**Interfaces:**
- Consumes: bootstrap payload fields `python`, `aa`, `export`, and `appVersion`.
- Produces: JavaScript calls `HaloCueNative.generateAndExport(project, text)`, `HaloCueNative.shareLastExport()`, and `HaloCueNative.openAzureArchive()`; native calls `window.HaloCueApp.exportUpdated(payload)`.

- [x] **Step 1: Change the device contract first**

Require the rendered page to contain:

```powershell
$expectedButton = "生成工程文件"
$expectedStatus = "尚未生成"
$expectedShare = "分享工程文件"
```

Assert `compile-aap` equals the primary label, `compile-status` equals the initial status, `share-aap` exists and starts hidden or disabled, and no rendered node contains `自动导入辅助功能`、`继续导入` or `生成并导入原版 AA`.

- [x] **Step 2: Run the contract to verify RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-device-page-contract.ps1
```

Expected: FAIL because the installed 0.2 page still renders `生成并导入原版 AA` and accessibility guidance.

- [x] **Step 3: Implement the export-only page**

In `index.html`:

```javascript
function applyExportState(payload) {
  const state = payload?.state || 'IDLE';
  primaryButton.disabled = state === 'GENERATING';
  shareButton.hidden = payload?.shareAvailable !== true;
  status.textContent = payload?.message || '尚未生成';
  status.className = 'compile-status';
  if (state === 'EXPORTED') status.classList.add('success');
  if (state === 'FAILED') status.classList.add('error');
  exportLocation.hidden = state !== 'EXPORTED';
  exportLocation.textContent = state === 'EXPORTED'
    ? `${payload.relativePath}${payload.displayName}`
    : '';
}
```

Use the approved visible strings, remove accessibility and continue-import elements/listeners, add `share-aap` and `export-location`, and call `generateAndExport` from the primary button.

In `app.css`, remove `.accessibility-note` and style `.export-location` as compact selectable path text. Keep existing responsive card dimensions and button styles.

- [x] **Step 4: Build, install, and verify GREEN**

Run:

```powershell
subst R: "D:\桌面\蔚蓝档案二创\AA自动写剧本文件\06-安卓端"
R:\gradlew.bat -p R:\ assembleDebug
adb install -r R:\app\build\outputs\apk\debug\app-debug.apk
powershell -ExecutionPolicy Bypass -File scripts/test-device-page-contract.ps1
```

Expected: the page contract passes and no accessibility copy is rendered.

- [x] **Step 5: Commit**

```powershell
git add app/src/main/assets/index.html app/src/main/assets/app.css scripts/test-device-page-contract.ps1
git commit -m "feat(android): present export-only workflow"
```

### Task 2: Safe Android share intent

**Files:**
- Create: `app/src/main/java/com/halocue/android/AapShareIntentFactory.kt`
- Create: `app/src/androidTest/java/com/halocue/android/AapShareIntentFactoryTest.kt`

**Interfaces:**
- Consumes: `uri: Uri`, `displayName: String` from `PublicAapExportResult`.
- Produces: `AapShareIntentFactory.create(uri: Uri, displayName: String): Intent`.

- [x] **Step 1: Write the failing instrumentation test**

```kotlin
@Test
fun shares_only_the_exported_aap_with_temporary_read_access() {
    val uri = Uri.parse("content://media/external/downloads/42")
    val intent = AapShareIntentFactory.create(uri, "ShareProbe.aap")

    assertEquals(Intent.ACTION_SEND, intent.action)
    assertEquals("application/octet-stream", intent.type)
    assertEquals(uri, intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java))
    assertTrue(intent.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
    assertEquals(uri, intent.clipData!!.getItemAt(0).uri)
}
```

- [x] **Step 2: Run the test to verify RED**

Run:

```powershell
R:\gradlew.bat -p R:\ connectedDebugAndroidTest `
  -Pandroid.testInstrumentationRunnerArguments.class=com.halocue.android.AapShareIntentFactoryTest
```

Expected: compilation failure because `AapShareIntentFactory` does not exist.

- [x] **Step 3: Implement the factory**

```kotlin
object AapShareIntentFactory {
    fun create(uri: Uri, displayName: String): Intent = Intent(Intent.ACTION_SEND).apply {
        type = "application/octet-stream"
        putExtra(Intent.EXTRA_STREAM, uri)
        clipData = ClipData.newRawUri(displayName, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
}
```

- [x] **Step 4: Run the focused instrumentation test to verify GREEN**

Run the Step 2 command again. Expected: one test passes with zero failures.

- [x] **Step 5: Commit**

```powershell
git add app/src/main/java/com/halocue/android/AapShareIntentFactory.kt app/src/androidTest/java/com/halocue/android/AapShareIntentFactoryTest.kt
git commit -m "feat(android): share exported aap files"
```

### Task 3: Native export orchestration and assisted-import removal

**Files:**
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/main/AndroidManifest.xml`
- Modify: `app/src/main/res/values/strings.xml`
- Delete: `app/src/main/java/com/halocue/android/AaImportCoordinator.kt`
- Delete: `app/src/main/java/com/halocue/android/AaImportTaskStore.kt`
- Delete: `app/src/main/java/com/halocue/android/VivoImportNavigator.kt`
- Delete: `app/src/main/java/com/halocue/android/VivoAaImportAccessibilityService.kt`
- Delete: `app/src/main/res/xml/aa_import_accessibility_service.xml`
- Delete: `app/src/androidTest/java/com/halocue/android/AaImportCoordinatorTest.kt`
- Delete: `app/src/androidTest/java/com/halocue/android/AaImportTaskStoreTest.kt`
- Delete: `app/src/androidTest/java/com/halocue/android/VivoAaImportAccessibilityServiceTest.kt`
- Delete: `app/src/test/java/com/halocue/android/VivoImportNavigatorTest.kt`

**Interfaces:**
- Consumes: `AndroidCompilerBridge.compileText(text, project)` and `AapPublicExporter.export(source, project)`.
- Produces: `window.HaloCueApp.exportUpdated({state, message, displayName, relativePath, shareAvailable})`; stores the latest `PublicAapExportResult` only in `MainActivity.lastExport`.

- [x] **Step 1: Make the build fail against the new page bridge**

After Task 1, run:

```powershell
R:\gradlew.bat -p R:\ assembleDebug
```

Expected behavioral gap: the page calls `generateAndExport` and `shareLastExport`, but the native bridge still exposes only assisted-import methods.

- [x] **Step 2: Replace import orchestration with export orchestration**

Use these fields and methods in `MainActivity`:

```kotlin
private var lastExport: PublicAapExportResult? = null

private fun generateAndExport(project: String, text: String) {
    compilerExecutor.execute {
        try {
            require(project.isNotBlank()) { "工程名不能为空" }
            require(text.isNotBlank()) { "剧本文本不能为空" }
            publishExportPayload(JSONObject()
                .put("state", "GENERATING")
                .put("message", "正在本机生成…")
                .put("shareAvailable", false))
            val compiled = AndroidCompilerBridge(this).compileText(text, project)
            val exported = AapPublicExporter(this).export(File(compiled.aapFile), compiled.project)
            lastExport = exported
            publishExportPayload(JSONObject()
                .put("state", "EXPORTED")
                .put("message", "已生成，尚未导入原版 AA")
                .put("displayName", exported.displayName)
                .put("relativePath", exported.relativePath)
                .put("shareAvailable", true))
        } catch (error: Exception) {
            lastExport = null
            publishExportPayload(JSONObject()
                .put("state", "FAILED")
                .put("message", error.message ?: "生成失败")
                .put("shareAvailable", false))
        }
    }
}
```

Bootstrap `export` as `IDLE / 尚未生成 / shareAvailable=false`. Remove `onResume` import publication and every coordinator/task-store method.

Add bridge methods:

```kotlin
@JavascriptInterface
fun generateAndExport(project: String, text: String) =
    this@MainActivity.generateAndExport(project, text)

@JavascriptInterface
fun shareLastExport() = runOnUiThread {
    this@MainActivity.shareLastExport()
}
```

`shareLastExport` must create a chooser from `AapShareIntentFactory`, catch `ActivityNotFoundException`, and retain the exported file on failure.

- [x] **Step 3: Remove the assisted-import surface**

Delete the listed classes/tests/resource. Remove the file-manager package query and accessibility service from the manifest. Reduce `strings.xml` to the app name. Clear legacy task preferences once from `onCreate` using the exact preference name `halocue_aa_import_task`; this does not delete public files.

- [x] **Step 4: Verify compilation and regression tests**

Run:

```powershell
R:\gradlew.bat -p R:\ testDebugUnitTest assembleDebug assembleDebugAndroidTest
$env:PYTHONPATH = "app/src/main/python"
python -m pytest app/src/test/python -q
git diff --check
```

Expected: Gradle succeeds, Python reports all tests passing, and no assisted-import symbols remain:

```powershell
rg -n "AaImport|VivoAaImport|VivoImportNavigator|自动导入辅助功能|continueImport|generateAndImport" app/src scripts
```

Expected: no matches.

- [x] **Step 5: Commit**

```powershell
git add app/src/main app/src/test app/src/androidTest
git commit -m "refactor(android): remove unsupported assisted import"
```

### Task 4: Version 0.3 artifact and vivo acceptance

**Files:**
- Modify: `app/build.gradle.kts`
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-android-export-only.md`
- Create: `构建产物/HaloCue-Android-MVP-0.3.0-dev-debug.apk`
- Create: `evidence/halocue-v030-export-only-vivo-x100s-pro.png`

**Interfaces:**
- Consumes: the export-only APK from Tasks 1-3.
- Produces: installed and verified 0.3 development artifact plus handoff evidence.

- [x] **Step 1: Bump the version**

Set:

```kotlin
versionCode = 3
versionName = "0.3.0-dev"
```

- [x] **Step 2: Run the full fresh verification suite**

Run:

```powershell
R:\gradlew.bat -p R:\ clean testDebugUnitTest assembleDebug assembleDebugAndroidTest
$env:PYTHONPATH = "app/src/main/python"
python -m pytest app/src/test/python -q
adb install -r R:\app\build\outputs\apk\debug\app-debug.apk
R:\gradlew.bat -p R:\ connectedDebugAndroidTest
powershell -ExecutionPolicy Bypass -File scripts/test-device-page-contract.ps1
```

Expected: all host/device tests pass and the page contract reports success.

- [x] **Step 3: Perform the unique real-device export**

Use project name `HCV030-Export-<HHmmss>`, generate one `.aap`, and verify through `MediaStore` and `/sdcard/Download/HaloCue/` that its size is non-zero. Tap “分享工程文件” and verify an Android chooser is the resumed activity. Confirm the original AA project directory file list and hashes were not changed by HaloCue.

- [x] **Step 4: Capture evidence and package the artifact**

Capture the export-success screen without private user content to `evidence/halocue-v030-export-only-vivo-x100s-pro.png`. Copy the built APK to `构建产物/HaloCue-Android-MVP-0.3.0-dev-debug.apk` and compute SHA-256 with `Get-FileHash`.

- [x] **Step 5: Clean exact device probes and update memory**

Delete only the unique export probe, the earlier `HaloCuePathProbe_20260810.aap`, and diagnostic `halocue-*.xml` files created by this verification. Record the Android 16 permission conclusion, removed accessibility flow, artifact path/hash, test counts, share behavior, and remaining limitation in `安卓端接手记忆.md`.

- [x] **Step 6: Commit**

```powershell
git add app/build.gradle.kts 安卓端接手记忆.md docs/superpowers/plans/2026-08-10-android-export-only.md evidence/halocue-v030-export-only-vivo-x100s-pro.png 构建产物/HaloCue-Android-MVP-0.3.0-dev-debug.apk
git commit -m "release(android): verify export-only 0.3 development build"
```
