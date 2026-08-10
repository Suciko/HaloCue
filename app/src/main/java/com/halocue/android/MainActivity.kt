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
import androidx.annotation.VisibleForTesting
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File
import java.util.concurrent.Executors
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var webRuntime: LocalWebRuntime
    private val runtimeExecutor = Executors.newSingleThreadExecutor()
    private val compilerExecutor = Executors.newSingleThreadExecutor()
    private var pageReady = false

    @Volatile
    private var activeSession: LocalWebSession? = null

    @Volatile
    private var lastExport: PublicAapExportResult? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        LegacyImportStateCleaner.clear(this)

        webRuntime = LocalWebRuntime(this)
        webView = createWebView()
        setContentView(webView)
        startLocalWebUi()
    }

    private fun startLocalWebUi() {
        runtimeExecutor.execute {
            try {
                val session = webRuntime.start()
                activeSession = session
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) webView.loadUrl(session.url)
                }
            } catch (error: Exception) {
                val fallbackHtml = runCatching {
                    assets.open(FALLBACK_ASSET_NAME).bufferedReader().use { it.readText() }
                }.getOrElse {
                    "<h1>HaloCue failed to start</h1>"
                }
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        webView.loadDataWithBaseURL(
                            FALLBACK_ASSET_URL,
                            fallbackHtml,
                            "text/html",
                            Charsets.UTF_8.name(),
                            null,
                        )
                        Toast.makeText(
                            this,
                            "本地服务启动失败：${error.javaClass.simpleName}",
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }
            }
        }
    }

    @Suppress("SetJavaScriptEnabled")
    private fun createWebView(): WebView = WebView(this).apply {
        id = R.id.main_webview
        setBackgroundColor(Color.rgb(244, 247, 251))
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowContentAccess = false
        settings.allowFileAccess = false
        settings.allowFileAccessFromFileURLs = false
        settings.allowUniversalAccessFromFileURLs = false
        addJavascriptInterface(AndroidBridge(), NATIVE_BRIDGE_NAME)

        webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean {
                if (isInternalUrl(request.url)) return false
                if (request.url.scheme == "https") return openExternalUrl(request.url)
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                pageReady = true
            }
        }

        ViewCompat.setOnApplyWindowInsetsListener(this) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }
    }

    private fun isInternalUrl(uri: Uri): Boolean {
        if (uri.toString() == FALLBACK_ASSET_URL) return true
        val session = activeSession ?: return false
        return uri.scheme == "http" &&
            uri.host == LOOPBACK_HOST &&
            uri.port == session.port
    }

    private fun openExternalUrl(uri: Uri): Boolean = try {
        startActivity(Intent(Intent.ACTION_VIEW, uri))
        true
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(this, "没有可打开此链接的应用", Toast.LENGTH_SHORT).show()
        true
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
                    .put("message", "正在本机生成...")
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
                webView.evaluateJavascript(
                    "window.HaloCueApp && window.HaloCueApp.exportUpdated($payload);",
                    null,
                )
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

    @VisibleForTesting
    fun webViewForTest(): WebView = webView

    @VisibleForTesting
    fun isInternalUrlForTest(uri: Uri): Boolean = isInternalUrl(uri)

    @Deprecated("Android system back compatibility")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        runtimeExecutor.shutdownNow()
        compilerExecutor.shutdownNow()
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface(NATIVE_BRIDGE_NAME)
            webView.destroy()
        }
        if (::webRuntime.isInitialized) webRuntime.stop()
        super.onDestroy()
    }

    companion object {
        private const val AA_PACKAGE = "com.foxxlight.AzureArchive"
        private const val LOOPBACK_HOST = "127.0.0.1"
        private const val FALLBACK_ASSET_NAME = "index.html"
        private const val FALLBACK_ASSET_URL = "file:///android_asset/index.html"
        private const val NATIVE_BRIDGE_NAME = "HaloCueNative"
    }
}
