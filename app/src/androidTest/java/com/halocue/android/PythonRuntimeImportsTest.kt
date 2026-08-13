package com.halocue.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PythonRuntimeImportsTest {
    @Test
    fun required_pc_runtime_modules_import_in_chaquopy() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        val python = Python.getInstance()
        REQUIRED_MODULES.forEach(python::getModule)

        val report = python.getModule("android_capabilities").callAttr("capability_report")
        assertTrue(capabilityAvailable(report, "pillow"))
        assertTrue(capabilityRequired(report, "pillow"))
        assertTrue(!capabilityRequired(report, "anthropic"))
        OPTIONAL_MODULES.forEach { name ->
            assertFalse(capabilityAvailable(report, name))
            assertTrue(capabilityReason(report, name).isNotBlank())
        }
    }

    private fun capabilityAvailable(report: com.chaquo.python.PyObject, name: String): Boolean =
        report.callAttr("__getitem__", name)
            .callAttr("__getitem__", "available")
            .toBoolean()

    private fun capabilityRequired(report: com.chaquo.python.PyObject, name: String): Boolean =
        report.callAttr("__getitem__", name)
            .callAttr("__getitem__", "required")
            .toBoolean()

    private fun capabilityReason(report: com.chaquo.python.PyObject, name: String): String =
        report.callAttr("__getitem__", name)
            .callAttr("__getitem__", "reason")
            .toString()

    companion object {
        private val REQUIRED_MODULES = listOf(
            "webui",
            "llm",
            "model_profiles",
            "draft_store",
            "annotate",
            "script2aap",
        )
        private val OPTIONAL_MODULES = listOf("anthropic", "opencc", "unitypy")
    }
}
