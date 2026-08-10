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

    @Volatile
    private var lastExport: PublicAapExportResult? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        LegacyImportStateCleaner.clear(this)

        bootstrapPayload = buildBootstrapPayload()
        webView = createWebView()
        setContentView(webView)
        webView.loadUrl(APP_ASSET_URL)
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
        val exportStatus = JSONObject()
            .put("state", "IDLE")
            .put("message", "尚未生成")
            .put("shareAvailable", false)

        return JSONObject()
            .put("python", pythonStatus)
            .put("aa", aaStatus)
            .put("export", exportStatus)
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

    private fun generateAndExport(project: String, text: String) {
        compilerExecutor.execute {
            lastExport = null
            publishExportPayload(
                JSONObject()
                    .put("state", "GENERATING")
                    .put("message", "正在本机生成…")
                    .put("shareAvailable", false),
            )
            try {
                require(project.isNotBlank()) { "工程名不能为空" }
                require(text.isNotBlank()) { "剧本文本不能为空" }
                val compiled = AndroidCompilerBridge(this).compileText(text = text, project = project)
                val exported = AapPublicExporter(this).export(
                    source = File(compiled.aapFile),
                    project = compiled.project,
                )
                lastExport = exported
                publishExportPayload(
                    JSONObject()
                        .put("state", "EXPORTED")
                        .put("message", "已生成，尚未导入原版 AA")
                        .put("displayName", exported.displayName)
                        .put("relativePath", exported.relativePath)
                        .put("shareAvailable", true),
                )
            } catch (error: Exception) {
                lastExport = null
                publishExportPayload(
                    JSONObject()
                        .put("state", "FAILED")
                        .put("message", error.message ?: "生成失败")
                        .put("shareAvailable", false),
                )
            }
        }
    }

    private fun shareLastExport() {
        val exported = lastExport
        if (exported == null) {
            Toast.makeText(this, "尚未生成工程文件", Toast.LENGTH_SHORT).show()
            return
        }
        try {
            startActivity(
                Intent.createChooser(
                    AapShareIntentFactory.create(exported.uri, exported.displayName),
                    "分享工程文件",
                ),
            )
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, "没有可分享此文件的应用", Toast.LENGTH_SHORT).show()
        }
    }

    private fun publishExportPayload(payload: JSONObject) {
        runOnUiThread {
            if (!isFinishing && ::webView.isInitialized && pageReady) {
                webView.evaluateJavascript("window.HaloCueApp.exportUpdated($payload);", null)
            }
        }
    }

    private inner class AndroidBridge {
        @JavascriptInterface
        fun openAzureArchive() {
            runOnUiThread { this@MainActivity.openAzureArchive() }
        }

        @JavascriptInterface
        fun generateAndExport(project: String, text: String) {
            this@MainActivity.generateAndExport(project, text)
        }

        @JavascriptInterface
        fun shareLastExport() {
            runOnUiThread { this@MainActivity.shareLastExport() }
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
