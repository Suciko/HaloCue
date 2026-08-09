package com.halocue.android

import android.content.Context

enum class AaImportState {
    READY,
    NEEDS_ACCESSIBILITY,
    IMPORTING,
    IMPORTED,
    FAILED,
}

data class AaImportTask(
    val project: String,
    val displayName: String,
    val sourceUri: String,
    val state: AaImportState,
    val message: String,
    val updatedAt: Long,
)

class AaImportTaskStore(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )

    fun save(task: AaImportTask) {
        preferences.edit()
            .putString(KEY_PROJECT, task.project)
            .putString(KEY_DISPLAY_NAME, task.displayName)
            .putString(KEY_SOURCE_URI, task.sourceUri)
            .putString(KEY_STATE, task.state.name)
            .putString(KEY_MESSAGE, task.message)
            .putLong(KEY_UPDATED_AT, task.updatedAt)
            .apply()
    }

    fun load(): AaImportTask? {
        val project = preferences.getString(KEY_PROJECT, null) ?: return null
        val displayName = preferences.getString(KEY_DISPLAY_NAME, null) ?: return null
        val sourceUri = preferences.getString(KEY_SOURCE_URI, null) ?: return null
        val stateName = preferences.getString(KEY_STATE, null) ?: return null
        val state = runCatching { AaImportState.valueOf(stateName) }.getOrNull() ?: return null
        return AaImportTask(
            project = project,
            displayName = displayName,
            sourceUri = sourceUri,
            state = state,
            message = preferences.getString(KEY_MESSAGE, "").orEmpty(),
            updatedAt = preferences.getLong(KEY_UPDATED_AT, 0L),
        )
    }

    fun clear() {
        preferences.edit().clear().apply()
    }

    companion object {
        private const val PREFERENCES_NAME = "halocue_aa_import_task"
        private const val KEY_PROJECT = "project"
        private const val KEY_DISPLAY_NAME = "display_name"
        private const val KEY_SOURCE_URI = "source_uri"
        private const val KEY_STATE = "state"
        private const val KEY_MESSAGE = "message"
        private const val KEY_UPDATED_AT = "updated_at"
    }
}
