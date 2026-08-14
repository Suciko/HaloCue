package com.halocue.android

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.GeneralSecurityException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureCredentialStore(
    context: Context,
    private val keyAlias: String = KEY_ALIAS,
) {
    private val preferences = context.applicationContext.getSharedPreferences(
        PREFERENCES_NAME,
        Context.MODE_PRIVATE,
    )

    fun put(name: String, value: String) {
        validateName(name)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        check(cipher.iv.size == IV_BYTES) { "Keystore returned an unexpected GCM IV length" }
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        persist(
            preferences.edit()
                .putString(ivKey(name), Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
                .putString(ciphertextKey(name), Base64.encodeToString(encrypted, Base64.NO_WRAP))
        )
    }

    fun get(name: String): String? {
        validateName(name)
        val iv = preferences.getString(ivKey(name), null)
        val ciphertext = preferences.getString(ciphertextKey(name), null)
        if (iv == null || ciphertext == null) {
            if (iv != null || ciphertext != null) removePersisted(name)
            return null
        }
        val key = secretKey()
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                key,
                GCMParameterSpec(GCM_TAG_BITS, Base64.decode(iv, Base64.NO_WRAP)),
            )
            cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP)).toString(Charsets.UTF_8)
        } catch (_: GeneralSecurityException) {
            removePersisted(name)
            null
        } catch (_: IllegalArgumentException) {
            removePersisted(name)
            null
        }
    }

    fun has(name: String): Boolean {
        validateName(name)
        return preferences.contains(ivKey(name)) && preferences.contains(ciphertextKey(name))
    }

    fun masked(name: String): String? {
        val value = get(name) ?: return null
        return if (value.length <= MASKED_SUFFIX_LENGTH) {
            MASK_PREFIX
        } else {
            "$MASK_PREFIX${value.takeLast(MASKED_SUFFIX_LENGTH)}"
        }
    }

    fun delete(name: String) {
        validateName(name)
        removePersisted(name)
    }

    private fun removePersisted(name: String) {
        persist(
            preferences.edit()
            .remove(ivKey(name))
            .remove(ciphertextKey(name))
        )
    }

    private fun persist(editor: android.content.SharedPreferences.Editor) {
        check(editor.commit()) { "Unable to persist secure credential" }
    }

    private fun secretKey(): SecretKey = synchronized(KEY_LOCK) {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        val existing = keyStore.getKey(keyAlias, null) as? SecretKey
        existing ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER).run {
            init(
                KeyGenParameterSpec.Builder(
                    keyAlias,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .build(),
            )
            generateKey()
        }
    }

    private fun validateName(name: String) {
        require(SECRET_NAME.matches(name)) { "Invalid credential name" }
    }

    private fun ivKey(name: String) = "$name.iv"

    private fun ciphertextKey(name: String) = "$name.ciphertext"

    companion object {
        const val PREFERENCES_NAME = "halocue_secure_credentials"
        private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
        private const val KEY_ALIAS = "halocue_credentials_v1"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val GCM_TAG_BITS = 128
        private const val IV_BYTES = 12
        private const val MASK_PREFIX = "\u2022\u2022\u2022\u2022"
        private const val MASKED_SUFFIX_LENGTH = 4
        private val KEY_LOCK = Any()
        private val SECRET_NAME = Regex("^[A-Za-z0-9_.-]{1,128}$")
    }
}
