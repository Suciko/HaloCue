package com.halocue.android

import android.content.Context
import android.provider.MediaStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AapPublicExporterTest {
    @Test
    fun exports_a_complete_aap_to_the_halocue_download_folder() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val expectedBytes = "{\"ProjectName\":\"HaloCueExportProbe\"}".toByteArray()
        val source = File(context.cacheDir, "HaloCueExportProbe-source.aap").apply {
            writeBytes(expectedBytes)
        }

        val result = AapPublicExporter(context).export(
            source = source,
            project = "HaloCueExportProbe",
        )

        try {
            assertEquals("HaloCueExportProbe.aap", result.displayName)
            assertEquals("Download/HaloCue/", result.relativePath)
            assertEquals(expectedBytes.size.toLong(), result.size)

            context.contentResolver.query(
                result.uri,
                arrayOf(
                    MediaStore.MediaColumns.DISPLAY_NAME,
                    MediaStore.MediaColumns.RELATIVE_PATH,
                    MediaStore.MediaColumns.SIZE,
                ),
                null,
                null,
                null,
            )!!.use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals("HaloCueExportProbe.aap", cursor.getString(0))
                assertEquals("Download/HaloCue/", cursor.getString(1))
                assertEquals(expectedBytes.size.toLong(), cursor.getLong(2))
            }

            val actualBytes = context.contentResolver.openInputStream(result.uri)!!.use { it.readBytes() }
            assertArrayEquals(expectedBytes, actualBytes)
        } finally {
            context.contentResolver.delete(result.uri, null, null)
            source.delete()
        }
    }

    @Test
    fun replaces_only_the_previous_halocue_staging_entry_for_the_same_project() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val source = File(context.cacheDir, "HaloCueReplaceProbe-source.aap")
        val exporter = AapPublicExporter(context)
        source.writeText("first")
        val first = exporter.export(source, "HaloCueReplaceProbe")

        source.writeText("second")
        val second = exporter.export(source, "HaloCueReplaceProbe")

        try {
            val firstStillExists = context.contentResolver.query(
                first.uri,
                arrayOf(MediaStore.MediaColumns._ID),
                null,
                null,
                null,
            )?.use { it.moveToFirst() } ?: false
            assertEquals(false, firstStillExists)
            val actualBytes = context.contentResolver.openInputStream(second.uri)!!.use { it.readBytes() }
            assertArrayEquals("second".toByteArray(), actualBytes)
        } finally {
            context.contentResolver.delete(second.uri, null, null)
            source.delete()
        }
    }
}
