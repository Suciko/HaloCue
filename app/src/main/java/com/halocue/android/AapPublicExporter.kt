package com.halocue.android

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import java.io.File
import java.io.IOException

data class PublicAapExportResult(
    val uri: Uri,
    val displayName: String,
    val relativePath: String,
    val size: Long,
)

class AapPublicExporter(context: Context) {
    private val applicationContext = context.applicationContext
    private val resolver = applicationContext.contentResolver
    private val stagingPreferences = applicationContext.getSharedPreferences(
        STAGING_PREFERENCES,
        Context.MODE_PRIVATE,
    )

    fun export(source: File, project: String): PublicAapExportResult {
        require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            "公共暂存需要 Android 10 或更高版本"
        }
        require(source.isFile) { "待导出的 .aap 不存在" }
        val safeProject = project.trim()
        require(safeProject.isNotEmpty()) { "工程名不能为空" }
        require('/' !in safeProject && '\\' !in safeProject) { "工程名不能包含路径分隔符" }

        val displayName = "$safeProject.aap"
        removePreviousStagingEntry(displayName)

        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, displayName)
            put(MediaStore.MediaColumns.MIME_TYPE, AAP_MIME_TYPE)
            put(MediaStore.MediaColumns.RELATIVE_PATH, RELATIVE_PATH)
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: throw IOException("无法在下载目录创建暂存文件")

        try {
            resolver.openOutputStream(uri, "w")?.use { output ->
                source.inputStream().use { input -> input.copyTo(output) }
            } ?: throw IOException("无法写入下载目录中的暂存文件")

            val published = resolver.update(
                uri,
                ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                null,
                null,
            )
            if (published != 1) {
                throw IOException("暂存文件发布失败")
            }
            stagingPreferences.edit().putString(displayName, uri.toString()).apply()
            return PublicAapExportResult(
                uri = uri,
                displayName = displayName,
                relativePath = RELATIVE_PATH,
                size = source.length(),
            )
        } catch (error: Exception) {
            resolver.delete(uri, null, null)
            throw error
        }
    }

    private fun removePreviousStagingEntry(displayName: String) {
        val previousUri = stagingPreferences.getString(displayName, null)?.let(Uri::parse) ?: return
        runCatching { resolver.delete(previousUri, null, null) }
        stagingPreferences.edit().remove(displayName).apply()
    }

    companion object {
        const val RELATIVE_PATH = "Download/HaloCue/"
        private const val AAP_MIME_TYPE = "application/octet-stream"
        private const val STAGING_PREFERENCES = "halocue_public_aap_staging"
    }
}
