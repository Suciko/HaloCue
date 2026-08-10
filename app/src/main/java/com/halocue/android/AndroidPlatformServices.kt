package com.halocue.android

import android.content.Context
import android.content.Intent
import java.io.File
import java.util.LinkedHashMap
import java.util.UUID

data class PublishedAapExport(
    val shareId: String,
    val displayName: String,
    val relativePath: String,
    val size: Long,
)

class AndroidPlatformServices(context: Context) {
    private val applicationContext = context.applicationContext
    private val exporter = AapPublicExporter(applicationContext)
    private val exports = LinkedHashMap<String, PublicAapExportResult>()

    @Synchronized
    fun publishAap(sourcePath: String, project: String): PublishedAapExport {
        val workspace = File(applicationContext.filesDir, "workspace").canonicalFile
        val source = File(sourcePath).canonicalFile
        require(source.path.startsWith(workspace.path + File.separator)) {
            "待导出的 .aap 不在应用工作区"
        }
        require(source.extension.equals("aap", ignoreCase = true)) {
            "只能导出 .aap 文件"
        }
        val exported = exporter.export(source, project)
        val shareId = "share-${UUID.randomUUID()}"
        exports[shareId] = exported
        while (exports.size > MAX_EXPORTS) {
            exports.remove(exports.entries.first().key)
        }
        return PublishedAapExport(
            shareId = shareId,
            displayName = exported.displayName,
            relativePath = exported.relativePath,
            size = exported.size,
        )
    }

    @Synchronized
    fun shareIntent(shareId: String): Intent? {
        val exported = exports[shareId] ?: return null
        return AapShareIntentFactory.create(exported.uri, exported.displayName)
    }

    companion object {
        private const val MAX_EXPORTS = 16
    }
}
