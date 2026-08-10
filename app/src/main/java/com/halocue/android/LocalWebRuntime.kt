package com.halocue.android

import android.content.Context
import android.util.Base64
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.security.SecureRandom

data class LocalWebSession(
    val url: String,
    val token: String,
    val port: Int,
)

class LocalWebRuntime(context: Context) {
    private val applicationContext = context.applicationContext
    private var activeSession: LocalWebSession? = null

    @Synchronized
    fun start(): LocalWebSession {
        activeSession?.let { return it }
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(applicationContext))
        }
        val tokenBytes = ByteArray(TOKEN_BYTES).also(SecureRandom()::nextBytes)
        val token = Base64.encodeToString(
            tokenBytes,
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING,
        )
        val result = Python.getInstance()
            .getModule("android_web_server")
            .callAttr("start", applicationContext.filesDir.absolutePath, token)
        check(result.callAttr("get", "ready").toBoolean()) {
            "Local WebUI service did not become ready"
        }
        return LocalWebSession(
            url = result.callAttr("get", "url").toString(),
            token = token,
            port = result.callAttr("get", "port").toInt(),
        ).also { activeSession = it }
    }

    @Synchronized
    fun stop() {
        if (!Python.isStarted() || activeSession == null) return
        try {
            Python.getInstance().getModule("android_web_server").callAttr("stop")
        } finally {
            activeSession = null
        }
    }

    companion object {
        private const val TOKEN_BYTES = 32
    }
}
