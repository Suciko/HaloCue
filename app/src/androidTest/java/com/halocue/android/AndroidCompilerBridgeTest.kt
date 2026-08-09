package com.halocue.android

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidCompilerBridgeTest {
    @Test
    fun compiles_text_into_the_apps_private_directory() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val result = AndroidCompilerBridge(context).compileText(
            text = "桃井: 真机编译成功\n",
            project = "AndroidInstrumentedCompiler",
        )

        val aap = File(result.aapFile)
        val payload = JSONObject(aap.readText(Charsets.UTF_8))

        assertEquals("AndroidInstrumentedCompiler", result.project)
        assertEquals(1, result.dialogueCount)
        assertFalse(result.imported)
        assertTrue(aap.isFile)
        assertTrue(aap.canonicalPath.startsWith(context.filesDir.canonicalPath + File.separator))
        assertEquals("AndroidInstrumentedCompiler", payload.getString("ProjectName"))
    }
}
