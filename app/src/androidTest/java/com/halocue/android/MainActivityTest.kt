package com.halocue.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {
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
    }
}
