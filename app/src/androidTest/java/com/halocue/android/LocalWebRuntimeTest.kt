package com.halocue.android

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.net.HttpURLConnection
import java.net.URL
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalWebRuntimeTest {
    @Test
    fun starts_a_tokenized_loopback_web_service() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val runtime = LocalWebRuntime(context)
        try {
            val session = runtime.start()
            assertTrue(session.url.startsWith("http://127.0.0.1:"))
            assertTrue(session.url.contains("?session="))
            assertTrue(session.token.length >= 32)
            assertTrue(session.port > 0)
            assertSame(session, runtime.start())

            val connection = URL("http://127.0.0.1:${session.port}/api/android/health")
                .openConnection() as HttpURLConnection
            connection.setRequestProperty("X-HaloCue-Session", session.token)
            assertEquals(200, connection.responseCode)
            connection.disconnect()
        } finally {
            runtime.stop()
            runtime.stop()
        }
    }
}
