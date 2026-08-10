package com.halocue.android

import android.content.ComponentName
import android.content.Context
import android.net.Uri
import android.view.View
import android.view.WindowManager
import android.webkit.WebView
import androidx.activity.ComponentActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {
    @Test
    fun main_activity_supports_activity_result_document_picker() {
        assertTrue(ComponentActivity::class.java.isAssignableFrom(MainActivity::class.java))
    }

    @Test
    fun document_result_is_not_published_to_a_destroyed_webview() {
        assertTrue(canPublishDocumentResult(false, false, true, false))
        assertFalse(canPublishDocumentResult(false, true, true, false))
        assertFalse(canPublishDocumentResult(false, false, true, true))
        assertFalse(canPublishDocumentResult(false, false, false, false))
    }

    @Test
    fun secure_webview_disables_file_and_content_access() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        lateinit var webView: WebView

        InstrumentationRegistry.getInstrumentation().runOnMainSync {
            webView = createSecureWebView(context)
            assertTrue(webView.settings.javaScriptEnabled)
            assertTrue(webView.settings.domStorageEnabled)
            assertFalse(webView.settings.allowContentAccess)
            assertFalse(webView.settings.allowFileAccess)
            assertFalse(webView.settings.allowFileAccessFromFileURLs)
            assertFalse(webView.settings.allowUniversalAccessFromFileURLs)
            webView.destroy()
        }
    }

    @Test
    fun system_bar_insets_are_applied_to_the_webview_container() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val content = View(context)
        val container = createInsetWebViewContainer(context, content)
        val insets = WindowInsetsCompat.Builder()
            .setInsets(
                WindowInsetsCompat.Type.systemBars(),
                androidx.core.graphics.Insets.of(0, 96, 0, 72),
            )
            .build()

        ViewCompat.dispatchApplyWindowInsets(container, insets)

        assertTrue(container.paddingTop == 96)
        assertTrue(container.paddingBottom == 72)
        assertTrue(content.paddingTop == 0)
        assertTrue(content.paddingBottom == 0)
    }

    @Test
    fun main_activity_resizes_for_the_soft_keyboard() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val activityInfo = context.packageManager.getActivityInfo(
            ComponentName(context, MainActivity::class.java),
            0,
        )

        assertTrue(
            activityInfo.softInputMode and WindowManager.LayoutParams.SOFT_INPUT_MASK_ADJUST ==
                WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE,
        )
    }

    @Test
    fun loopback_policy_rejects_unrelated_origins() {
        val activePort = 43123
        assertTrue(isInternalWebUiUrl(Uri.parse("http://127.0.0.1:$activePort/?session=test"), activePort))
        assertTrue(isInternalWebUiUrl(Uri.parse(FALLBACK_ASSET_URL), activePort))
        assertFalse(isInternalWebUiUrl(Uri.parse("https://example.com"), activePort))
        assertFalse(isInternalWebUiUrl(Uri.parse("http://127.0.0.1:1/"), activePort))
        assertFalse(isInternalWebUiUrl(Uri.parse("http://localhost:$activePort/"), activePort))
        assertFalse(isInternalWebUiUrl(Uri.parse("http://127.0.0.1:$activePort/"), null))
    }

    @Test
    fun runtime_and_original_aa_environment_are_available() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }

        val health = Python.getInstance().getModule("runtime_probe").callAttr("health")

        assertTrue(health.callAttr("get", "ready").toBoolean())
        assertNotNull(context.packageManager.getLaunchIntentForPackage(AA_PACKAGE))
    }

    companion object {
        private const val AA_PACKAGE = "com.foxxlight.AzureArchive"
        private const val FALLBACK_ASSET_URL = "file:///android_asset/index.html"
    }
}
