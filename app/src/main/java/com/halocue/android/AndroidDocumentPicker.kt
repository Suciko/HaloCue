package com.halocue.android

data class DocumentPickRequest(
    val requestId: String,
    val purpose: String,
    val allowedSuffixes: Set<String>,
)

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
