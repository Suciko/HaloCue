package com.halocue.android

import android.content.Context

object LegacyImportStateCleaner {
    fun clear(context: Context) {
        context.applicationContext
            .getSharedPreferences(LEGACY_PREFERENCES, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .apply()
    }

    private const val LEGACY_PREFERENCES = "halocue_aa_import_task"
}
