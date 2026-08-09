package com.halocue.android

import android.content.Context
import com.chaquo.python.Kwarg
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

data class AndroidCompileResult(
    val project: String,
    val aapFile: String,
    val projectDir: String,
    val dialogueCount: Int,
    val warnings: List<String>,
    val imported: Boolean,
)

class AndroidCompilerBridge(context: Context) {
    private val applicationContext = context.applicationContext

    fun compileText(text: String, project: String): AndroidCompileResult {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(applicationContext))
        }
        val workspace = File(applicationContext.filesDir, "compiler")
        val result = Python.getInstance()
            .getModule("android_compiler")
            .callAttr(
                "compile_text",
                text,
                Kwarg("project", project),
                Kwarg("workspace", workspace.absolutePath),
            )

        return AndroidCompileResult(
            project = result.callAttr("get", "project").toString(),
            aapFile = result.callAttr("get", "aap_file").toString(),
            projectDir = result.callAttr("get", "project_dir").toString(),
            dialogueCount = result.callAttr("get", "dialogue_count").toInt(),
            warnings = result.callAttr("get", "warnings").asList().map { it.toString() },
            imported = result.callAttr("get", "imported").toBoolean(),
        )
    }
}
