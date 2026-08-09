package com.halocue.android

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AaImportTaskStoreTest {
    @Test
    fun persists_the_complete_import_task_across_store_instances() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val expected = AaImportTask(
            project = "PersistenceProbe",
            displayName = "PersistenceProbe.aap",
            sourceUri = "content://media/external/downloads/4321",
            state = AaImportState.READY,
            message = "已准备导入",
            updatedAt = 123456789L,
        )
        val store = AaImportTaskStore(context)

        try {
            store.save(expected)

            assertEquals(expected, AaImportTaskStore(context).load())
        } finally {
            store.clear()
        }
    }
}
