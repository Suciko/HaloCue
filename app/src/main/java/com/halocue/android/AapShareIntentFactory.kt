package com.halocue.android

import android.content.ClipData
import android.content.Intent
import android.net.Uri

object AapShareIntentFactory {
    fun create(uri: Uri, displayName: String): Intent = Intent(Intent.ACTION_SEND).apply {
        type = "application/octet-stream"
        putExtra(Intent.EXTRA_STREAM, uri)
        clipData = ClipData.newRawUri(displayName, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
}
