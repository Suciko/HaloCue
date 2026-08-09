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
import org.json.JSONObject
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var bootstrapPayload: JSONObject
    private val compilerExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

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

    private inner class AndroidBridge {
        @JavascriptInterface
        fun openAzureArchive() {
            runOnUiThread { this@MainActivity.openAzureArchive() }
        }

        @JavascriptInterface
        fun compileAap(project: String, text: String) {
            compilerExecutor.execute {
                val payload = try {
                    require(project.isNotBlank()) { "工程名不能为空" }
                    require(text.isNotBlank()) { "剧本文本不能为空" }
                    val result = AndroidCompilerBridge(this@MainActivity)
                        .compileText(text = text, project = project)
                    JSONObject()
                        .put("ok", true)
                        .put("project", result.project)
                        .put("aapFile", result.aapFile)
                        .put("dialogueCount", result.dialogueCount)
                        .put("imported", result.imported)
                } catch (error: Exception) {
                    JSONObject()
                        .put("ok", false)
                        .put("message", error.message ?: "生成失败")
                        .put("imported", false)
                }
                runOnUiThread {
                    webView.evaluateJavascript(
                        "window.HaloCueApp.compileFinished($payload);",
                        null,
                    )
                }
            }
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
