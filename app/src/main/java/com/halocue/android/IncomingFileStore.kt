package com.halocue.android

import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.util.Locale
import java.util.UUID
import org.json.JSONObject

data class IncomingFile(
    val token: String,
    val name: String,
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

    fun discard(token: String) {
        if (!token.matches(Regex("[a-f0-9]{32}"))) return
        incomingDir.resolve("$token.tmp").delete()
        incomingDir.resolve("$token.bin").delete()
        incomingDir.resolve("$token.json.tmp").delete()
        incomingDir.resolve("$token.json").delete()
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
