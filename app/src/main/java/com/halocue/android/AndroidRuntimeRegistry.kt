package com.halocue.android

import android.content.Context

object AndroidRuntimeRegistry {
    @Volatile
    private var credentialStore: SecureCredentialStore? = null

    @JvmStatic
    fun initialize(context: Context) {
        if (credentialStore == null) {
            synchronized(this) {
                if (credentialStore == null) {
                    credentialStore = SecureCredentialStore(context.applicationContext)
                }
            }
        }
    }

    @JvmStatic
    fun credentials(): SecureCredentialStore =
        credentialStore ?: error("Android runtime registry is not initialized")
}
