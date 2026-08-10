package com.halocue.android

import android.content.Context
import android.net.Uri
import android.os.SystemClock
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
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
    fun loads_the_loopback_webui_and_restricts_internal_navigation() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            var loadedUrl: String? = null
            val deadline = SystemClock.elapsedRealtime() + WEB_UI_TIMEOUT_MS
            while (loadedUrl?.startsWith(LOOPBACK_PREFIX) != true &&
                SystemClock.elapsedRealtime() < deadline
            ) {
                scenario.onActivity { activity ->
                    loadedUrl = activity.webViewForTest().url
                }
                if (loadedUrl?.startsWith(LOOPBACK_PREFIX) != true) {
                    SystemClock.sleep(POLL_INTERVAL_MS)
                }
            }

            assertTrue("Expected loopback WebUI, got $loadedUrl", loadedUrl?.startsWith(LOOPBACK_PREFIX) == true)
            scenario.onActivity { activity ->
                val activeUri = Uri.parse(loadedUrl)
                assertFalse(activity.webViewForTest().settings.allowFileAccess)
                assertTrue(activity.isInternalUrlForTest(activeUri))
                assertFalse(activity.isInternalUrlForTest(Uri.parse("https://example.com")))
                assertFalse(activity.isInternalUrlForTest(Uri.parse("http://127.0.0.1:1/")))
                assertTrue(activity.isInternalUrlForTest(Uri.parse(FALLBACK_ASSET_URL)))
            }
        }
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
        private const val LOOPBACK_PREFIX = "http://127.0.0.1:"
        private const val FALLBACK_ASSET_URL = "file:///android_asset/index.html"
        private const val WEB_UI_TIMEOUT_MS = 20_000L
        private const val POLL_INTERVAL_MS = 100L
    }
}
