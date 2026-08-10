package com.halocue.android

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.Executors
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var bootstrapPayload: JSONObject
    private val compilerExecutor = Executors.newSingleThreadExecutor()
    private var pageReady = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        bootstrapPayload = buildBootstrapPayload()
        webView = createWebView()
        setContentView(webView)
        webView.loadUrl(APP_ASSET_URL)
    }

    override fun onResume() {
        super.onResume()
        if (::webView.isInitialized && pageReady) {
            publishPersistedImportState()
        }
    }

    @Suppress("SetJavaScriptEnabled")
    private fun createWebView(): WebView = WebView(this).apply {
        id = R.id.main_webview
        setBackgroundColor(Color.rgb(244, 247, 251))
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowContentAccess = false
        settings.allowFileAccessFromFileURLs = false
        settings.allowUniversalAccessFromFileURLs = false
        addJavascriptInterface(AndroidBridge(), NATIVE_BRIDGE_NAME)

        webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean = openExternalUrlIfNeeded(request.url)

            override fun onPageFinished(view: WebView, url: String) {
                if (url == APP_ASSET_URL) {
                    pageReady = true
                    view.evaluateJavascript(
                        "window.HaloCueApp.bootstrap(${bootstrapPayload});",
                        null,
                    )
                }
            }
        }

        ViewCompat.setOnApplyWindowInsetsListener(this) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }
    }

    private fun buildBootstrapPayload(): JSONObject {
        val pythonStatus = try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(this))
            }
            val health = Python.getInstance().getModule("runtime_probe").callAttr("health")
            JSONObject()
                .put("runtime", health.callAttr("get", "runtime").toString())
                .put("ready", health.callAttr("get", "ready").toBoolean())
                .put("schema", health.callAttr("get", "schema").toInt())
                .put("message", health.callAttr("get", "message").toString())
        } catch (error: Exception) {
            JSONObject()
                .put("runtime", "python")
                .put("ready", false)
                .put("schema", 1)
                .put("message", "本地 Python 启动失败")
                .put("detail", error.javaClass.simpleName)
        }

        val aaInstalled = packageManager.getLaunchIntentForPackage(AA_PACKAGE) != null
        val aaStatus = JSONObject()
            .put("installed", aaInstalled)
            .put("packageName", AA_PACKAGE)
            .put("message", if (aaInstalled) "已检测到原版 AA" else "尚未检测到原版 AA")

        return JSONObject()
            .put("python", pythonStatus)
            .put("aa", aaStatus)
            .put("import", AaImportTaskStore(this).load()?.let(::importPayload) ?: JSONObject.NULL)
            .put("appVersion", BuildConfig.VERSION_NAME)
    }

    private fun openExternalUrlIfNeeded(uri: Uri): Boolean {
        if (uri.scheme == "file" && uri.path?.startsWith("/android_asset/") == true) {
            return false
        }
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, uri))
            true
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, "没有可打开此链接的应用", Toast.LENGTH_SHORT).show()
            true
        }
    }

    private fun openAzureArchive() {
        val launchIntent = packageManager.getLaunchIntentForPackage(AA_PACKAGE)
        if (launchIntent == null) {
            Toast.makeText(this, "尚未安装原版 AA", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(launchIntent)
    }

    private fun generateAndImport(project: String, text: String) {
        compilerExecutor.execute {
            try {
                require(project.isNotBlank()) { "工程名不能为空" }
                require(text.isNotBlank()) { "剧本文本不能为空" }
                val compiled = AndroidCompilerBridge(this).compileText(text = text, project = project)
                val exported = AapPublicExporter(this).export(
                    source = File(compiled.aapFile),
                    project = compiled.project,
                )
                val outcome = AaImportCoordinator(this).prepare(exported, compiled.project)
                dispatchImportOutcome(outcome)
            } catch (error: Exception) {
                publishImportPayload(
                    JSONObject()
                        .put("state", AaImportState.FAILED.name)
                        .put("message", error.message ?: "生成失败")
                        .put("action", "retry_import"),
                )
            }
        }
    }

    private fun continueImport() {
        compilerExecutor.execute {
            val task = AaImportTaskStore(this).load()
            if (task == null) {
                publishImportPayload(
                    JSONObject()
                        .put("state", AaImportState.FAILED.name)
                        .put("message", "没有可继续导入的工程")
                        .put("action", "none"),
                )
                return@execute
            }
            try {
                val exported = PublicAapExportResult(
                    uri = Uri.parse(task.sourceUri),
                    displayName = task.displayName,
                    relativePath = AapPublicExporter.RELATIVE_PATH,
                    size = 0L,
                )
                dispatchImportOutcome(AaImportCoordinator(this).prepare(exported, task.project))
            } catch (error: Exception) {
                publishImportPayload(
                    importPayload(
                        task.copy(
                            state = AaImportState.FAILED,
                            message = error.message ?: "继续导入失败",
                            updatedAt = System.currentTimeMillis(),
                        ),
                    ),
                )
            }
        }
    }

    private fun dispatchImportOutcome(outcome: AaImportOutcome) {
        val payload = importPayload(outcome.task).put(
            "action",
            when (outcome.nextAction) {
                AaImportNextAction.OPEN_ACCESSIBILITY_SETTINGS -> "open_accessibility_settings"
                AaImportNextAction.START_VIVO_FILE_MANAGER -> "none"
                AaImportNextAction.NONE -> "none"
            },
        )
        runOnUiThread {
            webView.evaluateJavascript("window.HaloCueApp.importUpdated($payload);", null)
            if (outcome.nextAction == AaImportNextAction.START_VIVO_FILE_MANAGER) {
                try {
                    startActivity(AaImportCoordinator(this).vivoFileManagerLaunchIntent())
                } catch (error: ActivityNotFoundException) {
                    val failed = outcome.task.copy(
                        state = AaImportState.FAILED,
                        message = error.message ?: "未找到 vivo 文件管理器",
                        updatedAt = System.currentTimeMillis(),
                    )
                    AaImportTaskStore(this).save(failed)
                    webView.evaluateJavascript(
                        "window.HaloCueApp.importUpdated(${importPayload(failed)});",
                        null,
                    )
                }
            }
        }
    }

    private fun publishPersistedImportState() {
        AaImportTaskStore(this).load()?.let { publishImportPayload(importPayload(it)) }
    }

    private fun publishImportPayload(payload: JSONObject) {
        runOnUiThread {
            if (!isFinishing && ::webView.isInitialized) {
                webView.evaluateJavascript("window.HaloCueApp.importUpdated($payload);", null)
            }
        }
    }

    private fun importPayload(task: AaImportTask): JSONObject = JSONObject()
        .put("state", task.state.name)
        .put("message", task.message)
        .put(
            "action",
            when (task.state) {
                AaImportState.NEEDS_ACCESSIBILITY -> "open_accessibility_settings"
                AaImportState.FAILED -> "retry_import"
                else -> "none"
            },
        )

    private inner class AndroidBridge {
        @JavascriptInterface
        fun openAzureArchive() {
            runOnUiThread { this@MainActivity.openAzureArchive() }
        }

        @JavascriptInterface
        fun generateAndImport(project: String, text: String) {
            this@MainActivity.generateAndImport(project, text)
        }

        @JavascriptInterface
        fun openImportAccessibilitySettings() {
            runOnUiThread {
                startActivity(AaImportCoordinator(this@MainActivity).accessibilitySettingsIntent())
            }
        }

        @JavascriptInterface
        fun continueImport() {
            this@MainActivity.continueImport()
        }
    }

    @Deprecated("Android system back compatibility")
    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }

    override fun onDestroy() {
        compilerExecutor.shutdownNow()
        webView.removeJavascriptInterface(NATIVE_BRIDGE_NAME)
        webView.destroy()
        super.onDestroy()
    }

    companion object {
        private const val AA_PACKAGE = "com.foxxlight.AzureArchive"
        private const val APP_ASSET_URL = "file:///android_asset/index.html"
        private const val NATIVE_BRIDGE_NAME = "HaloCueNative"
    }
}
