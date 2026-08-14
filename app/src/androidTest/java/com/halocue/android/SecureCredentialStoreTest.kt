package com.halocue.android

import android.content.Context
import android.util.Base64
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.security.KeyStore
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureCredentialStoreTest {
    @Test
    fun stores_and_deletes_synchronously_without_persisting_plaintext() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val store = SecureCredentialStore(context)
        val name = testName()
        val plaintext = "sk-device-${UUID.randomUUID()}"

        try {
            store.put(name, plaintext)

            assertTrue(store.has(name))
            assertEquals(plaintext, store.get(name))
            assertEquals("\u2022\u2022\u2022\u2022${plaintext.takeLast(4)}", store.masked(name))
            assertEquals(plaintext, SecureCredentialStore(context).get(name))
            val persisted = context.getSharedPreferences(
                SecureCredentialStore.PREFERENCES_NAME,
                Context.MODE_PRIVATE,
            ).all.values.joinToString("|")
            assertFalse(persisted.contains(plaintext))
            assertEquals(
                12,
                Base64.decode(
                    context.getSharedPreferences(
                        SecureCredentialStore.PREFERENCES_NAME,
                        Context.MODE_PRIVATE,
                    ).getString("$name.iv", null),
                    Base64.NO_WRAP,
                ).size,
            )
        } finally {
            store.delete(name)
        }

        assertFalse(store.has(name))
        assertNull(store.get(name))
        assertFalse(SecureCredentialStore(context).has(name))
    }

    @Test
    fun masking_short_secrets_never_returns_the_plaintext() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val store = SecureCredentialStore(context)
        val name = testName()
        val plaintext = "abc"

        try {
            store.put(name, plaintext)

            assertEquals("\u2022\u2022\u2022\u2022", store.masked(name))
            assertFalse(store.masked(name)!!.contains(plaintext))
        } finally {
            store.delete(name)
        }
    }

    @Test
    fun corrupt_ciphertext_is_removed_before_returning_missing() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val store = SecureCredentialStore(context)
        val name = testName()
        val plaintext = "sk-device-${UUID.randomUUID()}"
        val preferences = context.getSharedPreferences(
            SecureCredentialStore.PREFERENCES_NAME,
            Context.MODE_PRIVATE,
        )

        try {
            store.put(name, plaintext)
            preferences.edit().putString("$name.ciphertext", "AQID").commit()

            assertNull(store.get(name))
            assertFalse(store.has(name))
            assertFalse(preferences.contains("$name.iv"))
            assertFalse(preferences.contains("$name.ciphertext"))
        } finally {
            store.delete(name)
        }
    }

    @Test
    fun concurrent_first_use_uses_an_isolated_key_and_preserves_production_credentials() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val productionStore = SecureCredentialStore(context)
        val productionName = testName()
        val productionSecret = "sk-production-${UUID.randomUUID()}"
        val testKeyAlias = "halocue_credentials_test_${UUID.randomUUID()}"
        val names = List(16) { testName() }
        deleteCredentialKey(testKeyAlias)
        val start = CountDownLatch(1)
        val complete = CountDownLatch(names.size)
        val executor = Executors.newFixedThreadPool(names.size)
        val failures = ConcurrentLinkedQueue<Throwable>()

        try {
            productionStore.put(productionName, productionSecret)
            names.forEachIndexed { index, name ->
                executor.execute {
                    try {
                        start.await()
                        SecureCredentialStore(context, testKeyAlias).put(name, "concurrent-$index")
                    } catch (error: Throwable) {
                        failures.add(error)
                    } finally {
                        complete.countDown()
                    }
                }
            }
            start.countDown()

            assertTrue("Concurrent first use timed out", complete.await(10, TimeUnit.SECONDS))
            assertTrue("Concurrent first use failed: $failures", failures.isEmpty())
            names.forEachIndexed { index, name ->
                assertEquals(
                    "concurrent-$index",
                    SecureCredentialStore(context, testKeyAlias).get(name),
                )
            }
            assertEquals(productionSecret, SecureCredentialStore(context).get(productionName))
        } finally {
            executor.shutdownNow()
            names.forEach { SecureCredentialStore(context, testKeyAlias).delete(it) }
            deleteCredentialKey(testKeyAlias)
            productionStore.delete(productionName)
        }
    }

    @Test
    fun chaquopy_adapter_uses_registry_and_real_keystore_credentials() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val name = testName()
        val plaintext = "sk-integration-${UUID.randomUUID()}"
        AndroidRuntimeRegistry.initialize(context)
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        val credentials = Python.getInstance().getModule("android_credentials")

        try {
            credentials.callAttr("set_secret", name, plaintext)

            assertEquals(plaintext, credentials.callAttr("get_secret", name).toString())
            val status = credentials.callAttr("secret_status", name)
            assertTrue(status.callAttr("__getitem__", "configured").toBoolean())
            assertEquals(
                "\u2022\u2022\u2022\u2022${plaintext.takeLast(4)}",
                status.callAttr("__getitem__", "masked").toString(),
            )
            assertFalse(status.toString().contains(plaintext))

            credentials.callAttr("delete_secret", name)
            val deletedStatus = credentials.callAttr("secret_status", name)
            assertFalse(deletedStatus.callAttr("__getitem__", "configured").toBoolean())
        } finally {
            SecureCredentialStore(context).delete(name)
        }
    }

    private fun deleteCredentialKey(alias: String) {
        KeyStore.getInstance("AndroidKeyStore").apply {
            load(null)
            if (containsAlias(alias)) {
                deleteEntry(alias)
            }
        }
    }

    private fun testName(): String =
        "test_${UUID.randomUUID().toString().replace("-", "")}"
}
