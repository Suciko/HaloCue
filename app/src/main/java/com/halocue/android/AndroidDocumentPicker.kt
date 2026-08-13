package com.halocue.android

enum class DocumentPickPurpose(val wireValue: String) {
    STORY("story"),
    ASSET_FILE("asset_file"),
    ASSET_TREE("asset_tree");

    companion object {
        fun fromWireValue(value: String): DocumentPickPurpose = entries.firstOrNull {
            it.wireValue == value.trim()
        } ?: throw IllegalArgumentException("Unsupported document picker purpose")
    }
}

data class DocumentPickRequest(
    val requestId: String,
    val purpose: DocumentPickPurpose,
    val assetKind: String,
    val allowedSuffixes: Set<String>,
) {
    val usesDirectoryTree: Boolean
        get() = purpose == DocumentPickPurpose.ASSET_TREE

    companion object {
        fun fromBridge(
            requestId: String,
            purpose: String,
            assetKind: String,
            allowedSuffixes: Set<String>,
        ): DocumentPickRequest {
            val normalizedId = requestId.trim()
            require(normalizedId.isNotEmpty()) { "Document picker request ID is required" }
            val normalizedPurpose = DocumentPickPurpose.fromWireValue(purpose)
            val normalizedKind = assetKind.trim().lowercase()
            val normalizedSuffixes = allowedSuffixes.mapTo(linkedSetOf()) {
                it.trim().lowercase()
            }.filterTo(linkedSetOf()) { it.matches(Regex("\\.[a-z0-9]{1,12}")) }
            require(normalizedSuffixes.isNotEmpty()) { "Allowed suffixes are required" }
            when (normalizedPurpose) {
                DocumentPickPurpose.STORY -> require(normalizedKind.isEmpty()) {
                    "Story picker does not accept an asset kind"
                }
                DocumentPickPurpose.ASSET_FILE -> require(normalizedKind in setOf("background", "sound")) {
                    "Single-file asset picker requires a background or sound kind"
                }
                DocumentPickPurpose.ASSET_TREE -> require(normalizedKind in setOf("character", "batch")) {
                    "Directory asset picker requires a character or batch kind"
                }
            }
            return DocumentPickRequest(
                requestId = normalizedId,
                purpose = normalizedPurpose,
                assetKind = normalizedKind,
                allowedSuffixes = normalizedSuffixes,
            )
        }
    }
}

class AndroidDocumentPicker {
    private var active: DocumentPickRequest? = null

    @Synchronized
    fun begin(request: DocumentPickRequest): Boolean {
        if (active != null) return false
        active = request
        return true
    }

    @Synchronized
    fun current(): DocumentPickRequest? = active

    @Synchronized
    fun restore(request: DocumentPickRequest): Boolean = begin(request)

    @Synchronized
    fun consume(): DocumentPickRequest? = active.also { active = null }
}
