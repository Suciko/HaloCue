package com.halocue.android

import android.content.Intent
import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AapShareIntentFactoryTest {
    @Test
    fun shares_only_the_exported_aap_with_temporary_read_access() {
        val uri = Uri.parse("content://media/external/downloads/42")

        val intent = AapShareIntentFactory.create(uri, "ShareProbe.aap")

        assertEquals(Intent.ACTION_SEND, intent.action)
        assertEquals("application/octet-stream", intent.type)
        assertEquals(uri, intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java))
        assertTrue(intent.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        assertEquals(uri, intent.clipData!!.getItemAt(0).uri)
    }
}
