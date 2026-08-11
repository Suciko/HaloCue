package com.halocue.android

import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.util.Locale
import java.util.UUID
import org.json.JSONObject

internal fun hasAllowedDocumentSuffix(name: String, allowedSuffixes: Set<String>): Boolean {
    val normalized = name.replace('\\', '/').substringAfterLast('/').lowercase(Locale.ROOT)
    return allowedSuffixes.any { suffix ->
        val value = suffix.trim().lowercase(Locale.ROOT)
        val normalizedSuffix = if (value.startsWith('.')) value else ".$value"
        normalized.endsWith(normalizedSuffix)
    }
}

data class IncomingFile(
    val token: String,
    val name: String,
    val size: Long,
)

data class IncomingTreeEntry(
    val relativePath: String,
    val openInput: () -> InputStream,
)

data class IncomingTree(
    val token: String,
    val name: String,
    val fileCount: Int,
    val size: Long,
)

class IncomingFileStoreException(
    val code: String,
    message: String,
) : IllegalArgumentException(message)

class IncomingFileStore(private val filesRoot: File) {
    private val incomingDir: File
        get() = filesRoot.resolve("incoming")

    fun stage(
        displayName: String,
        input: InputStream,
        allowedSuffixes: Set<String>,
        maxBytes: Long,
    ): IncomingFile {
        val safeName = sanitizeName(displayName)
        val suffix = safeName.substringAfterLast('.', "")
            .let { if (it.isEmpty()) "" else ".${it.lowercase(Locale.ROOT)}" }
        val normalizedSuffixes = allowedSuffixes.mapTo(mutableSetOf()) {
            val value = it.trim().lowercase(Locale.ROOT)
            if (value.startsWith('.')) value else ".$value"
        }
        if (suffix !in normalizedSuffixes) {
            throw IncomingFileStoreException("unsupported_type", "Unsupported document type")
        }
        require(maxBytes > 0) { "maxBytes must be positive" }

        incomingDir.mkdirs()
        check(incomingDir.isDirectory) { "Unable to create incoming directory" }
        val token = UUID.randomUUID().toString().replace("-", "")
        val temporary = incomingDir.resolve("$token.tmp")
        val payload = incomingDir.resolve("$token.bin")
        val metadata = incomingDir.resolve("$token.json")
        var size = 0L
        try {
            FileOutputStream(temporary).use { output ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    size += count
                    if (size > maxBytes) {
                        throw IncomingFileStoreException(
                            "file_too_large",
                            "Document exceeds the allowed size",
                        )
                    }
                    output.write(buffer, 0, count)
                }
                output.fd.sync()
            }
            if (!temporary.renameTo(payload)) {
                throw IllegalStateException("Unable to finalize incoming document")
            }
            val metadataTemporary = incomingDir.resolve("$token.json.tmp")
            metadataTemporary.writeText(
                JSONObject().put("name", safeName).put("size", size).toString(),
                Charsets.UTF_8,
            )
            if (!metadataTemporary.renameTo(metadata)) {
                metadataTemporary.delete()
                throw IllegalStateException("Unable to finalize incoming metadata")
            }
            return IncomingFile(token = token, name = safeName, size = size)
        } catch (error: Exception) {
            temporary.delete()
            payload.delete()
            metadata.delete()
            throw error
        }
    }

    fun stageTree(
        displayName: String,
        entries: List<IncomingTreeEntry>,
        allowedSuffixes: Set<String>,
        maxFiles: Int,
        maxFileBytes: Long,
        maxTotalBytes: Long,
    ): IncomingTree {
        require(maxFiles > 0) { "maxFiles must be positive" }
        require(maxFileBytes > 0) { "maxFileBytes must be positive" }
        require(maxTotalBytes > 0) { "maxTotalBytes must be positive" }
        if (entries.size > maxFiles) {
            throw IncomingFileStoreException("too_many_files", "Directory contains too many files")
        }

        val safeName = sanitizeName(displayName)
        val normalizedSuffixes = normalizeSuffixes(allowedSuffixes)
        val seenPaths = mutableSetOf<String>()
        val normalizedEntries = entries.map { entry ->
            val relativePath = normalizeRelativePath(entry.relativePath)
            if (!seenPaths.add(relativePath.lowercase(Locale.ROOT))) {
                throw IncomingFileStoreException(
                    "duplicate_tree_path",
                    "Directory contains duplicate file paths",
                )
            }
            val suffix = File(relativePath).extension
                .let { if (it.isEmpty()) "" else ".${it.lowercase(Locale.ROOT)}" }
            if (suffix !in normalizedSuffixes) {
                throw IncomingFileStoreException("unsupported_type", "Unsupported document type")
            }
            entry.copy(relativePath = relativePath)
        }

        incomingDir.mkdirs()
        check(incomingDir.isDirectory) { "Unable to create incoming directory" }
        val token = UUID.randomUUID().toString().replace("-", "")
        val temporary = incomingDir.resolve("$token.tree.tmp")
        val payload = incomingDir.resolve("$token.tree")
        val metadataTemporary = incomingDir.resolve("$token.tree.json.tmp")
        val metadata = incomingDir.resolve("$token.tree.json")
        var totalSize = 0L
        try {
            check(temporary.mkdir()) { "Unable to create temporary incoming directory" }
            normalizedEntries.forEach { entry ->
                val target = temporary.resolve(entry.relativePath)
                val parent = checkNotNull(target.parentFile)
                check(parent.isDirectory || parent.mkdirs()) {
                    "Unable to create incoming subdirectory"
                }
                var fileSize = 0L
                entry.openInput().use { input ->
                    FileOutputStream(target).use { output ->
                        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            fileSize += count
                            totalSize += count
                            if (fileSize > maxFileBytes) {
                                throw IncomingFileStoreException(
                                    "file_too_large",
                                    "A directory file exceeds the allowed size",
                                )
                            }
                            if (totalSize > maxTotalBytes) {
                                throw IncomingFileStoreException(
                                    "tree_too_large",
                                    "Directory exceeds the allowed total size",
                                )
                            }
                            output.write(buffer, 0, count)
                        }
                        output.fd.sync()
                    }
                }
            }
            if (!temporary.renameTo(payload)) {
                throw IllegalStateException("Unable to finalize incoming directory")
            }
            metadataTemporary.writeText(
                JSONObject()
                    .put("name", safeName)
                    .put("size", totalSize)
                    .put("fileCount", normalizedEntries.size)
                    .toString(),
                Charsets.UTF_8,
            )
            if (!metadataTemporary.renameTo(metadata)) {
                throw IllegalStateException("Unable to finalize incoming directory metadata")
            }
            return IncomingTree(
                token = token,
                name = safeName,
                fileCount = normalizedEntries.size,
                size = totalSize,
            )
        } catch (error: Exception) {
            temporary.deleteRecursively()
            payload.deleteRecursively()
            metadataTemporary.delete()
            metadata.delete()
            throw error
        }
    }

    fun discard(token: String) {
        if (!token.matches(Regex("[a-f0-9]{32}"))) return
        incomingDir.resolve("$token.tmp").delete()
        incomingDir.resolve("$token.bin").delete()
        incomingDir.resolve("$token.json.tmp").delete()
        incomingDir.resolve("$token.json").delete()
        incomingDir.resolve("$token.tree.tmp").deleteRecursively()
        incomingDir.resolve("$token.tree").deleteRecursively()
        incomingDir.resolve("$token.tree.json.tmp").delete()
        incomingDir.resolve("$token.tree.json").delete()
    }

    private fun normalizeSuffixes(allowedSuffixes: Set<String>): Set<String> =
        allowedSuffixes.mapTo(mutableSetOf()) {
            val value = it.trim().lowercase(Locale.ROOT)
            if (value.startsWith('.')) value else ".$value"
        }

    private fun normalizeRelativePath(value: String): String {
        val normalized = value.replace('\\', '/')
        if (normalized.startsWith('/') || normalized.indexOf('\u0000') >= 0) {
            throw IncomingFileStoreException("unsafe_tree_path", "Directory path is unsafe")
        }
        val parts = normalized.split('/')
        if (parts.isEmpty() || parts.any { it.isEmpty() || it == "." || it == ".." }) {
            throw IncomingFileStoreException("unsafe_tree_path", "Directory path is unsafe")
        }
        return parts.joinToString("/")
    }

    private fun sanitizeName(displayName: String): String {
        val name = displayName.replace('\\', '/').substringAfterLast('/').trim()
        if (name.isEmpty() || name == "." || name == "..") {
            throw IncomingFileStoreException("invalid_name", "Document name is invalid")
        }
        return name.take(MAX_NAME_LENGTH)
    }

    companion object {
        private const val MAX_NAME_LENGTH = 180
    }
}
