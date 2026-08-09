package com.halocue.android

import android.content.Context
import android.net.Uri
import android.provider.Settings
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AaImportCoordinatorTest {
    @Test
    fun prepares_a_persistent_task_and_requests_accessibility_when_service_is_disabled() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val store = AaImportTaskStore(context)
        val exported = PublicAapExportResult(
            uri = Uri.parse("content://media/external/downloads/9876"),
            displayName = "CoordinatorProbe.aap",
            relativePath = "Download/HaloCue/",
            size = 42L,
        )

        try {
            val outcome = AaImportCoordinator(context, store).prepare(exported, "CoordinatorProbe")

            assertEquals(AaImportState.NEEDS_ACCESSIBILITY, outcome.task.state)
            assertEquals(AaImportNextAction.OPEN_ACCESSIBILITY_SETTINGS, outcome.nextAction)
            assertEquals(exported.uri.toString(), outcome.task.sourceUri)
            assertEquals("CoordinatorProbe", outcome.task.project)
            assertNotNull(store.load())
            assertEquals(outcome.task, store.load())
        } finally {
            store.clear()
        }
    }

    @Test
    fun creates_user_driven_settings_and_vivo_file_manager_intents() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val coordinator = AaImportCoordinator(context)

        assertEquals(Settings.ACTION_ACCESSIBILITY_SETTINGS, coordinator.accessibilitySettingsIntent().action)
        assertEquals(
            "com.android.filemanager",
            coordinator.vivoFileManagerLaunchIntent().component?.packageName,
        )
    }
}
