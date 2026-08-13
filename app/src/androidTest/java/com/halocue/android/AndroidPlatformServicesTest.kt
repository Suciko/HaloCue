package com.halocue.android

import android.content.Intent
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidPlatformServicesTest {
    @Test
    fun publishes_workspace_aap_and_resolves_only_a_known_share_id() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val source = File(context.filesDir, "workspace/test/PlatformServices.aap")
        source.parentFile?.mkdirs()
        source.writeText("{\"ProjectName\":\"PlatformServices\"}")
        val services = AndroidPlatformServices(context)

        val published = services.publishAap(source.absolutePath, "PlatformServices")
        val shareIntent = services.shareIntent(published.shareId)

        assertEquals("PlatformServices.aap", published.displayName)
        assertEquals("Download/HaloCue/", published.relativePath)
        assertTrue(published.shareId.isNotBlank())
        assertNotNull(shareIntent)
        assertNull(services.shareIntent("unknown-share-id"))
        assertEquals(Intent.ACTION_SEND, shareIntent?.action)
        assertTrue(
            shareIntent?.flags?.and(Intent.FLAG_GRANT_READ_URI_PERMISSION) != 0,
        )

        val uri = shareIntent?.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
        if (uri != null) context.contentResolver.delete(uri, null, null)
    }
}
