package com.halocue.android

import android.content.Context

object AndroidRuntimeRegistry {
    @Volatile
    private var credentialStore: SecureCredentialStore? = null

    @Volatile
    private var platformServices: AndroidPlatformServices? = null

    @JvmStatic
    fun initialize(context: Context) {
        if (credentialStore == null) {
            synchronized(this) {
                if (credentialStore == null) {
                    credentialStore = SecureCredentialStore(context.applicationContext)
                }
            }
        }
        if (platformServices == null) {
            synchronized(this) {
                if (platformServices == null) {
                    platformServices = AndroidPlatformServices(context.applicationContext)
                }
            }
        }
    }

    @JvmStatic
    fun credentials(): SecureCredentialStore =
        credentialStore ?: error("Android runtime registry is not initialized")

    @JvmStatic
    fun platformServices(): AndroidPlatformServices =
        platformServices ?: error("Android runtime registry is not initialized")
}
