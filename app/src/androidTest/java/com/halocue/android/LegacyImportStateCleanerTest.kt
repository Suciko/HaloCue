package com.halocue.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LegacyImportStateCleanerTest {
    @Test
    fun clears_only_the_legacy_assisted_import_preferences() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val legacy = context.getSharedPreferences(
            "halocue_aa_import_task",
            Context.MODE_PRIVATE,
        )
        val publicExports = context.getSharedPreferences(
            "halocue_public_aap_staging",
            Context.MODE_PRIVATE,
        )
        legacy.edit().putString("display_name", "LegacyProbe.aap").commit()
        publicExports.edit().putString("KeepProbe.aap", "content://downloads/42").commit()

        try {
            LegacyImportStateCleaner.clear(context)

            assertFalse(legacy.contains("display_name"))
            assertFalse(publicExports.all.isEmpty())
        } finally {
            legacy.edit().clear().commit()
            publicExports.edit().clear().commit()
        }
    }
}
