package com.halocue.android

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNotEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class VivoAaImportAccessibilityServiceTest {
    @Suppress("DEPRECATION")
    @Test
    fun service_is_private_and_can_only_be_bound_by_the_android_system() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val info = context.packageManager.getServiceInfo(
            ComponentName(context, VivoAaImportAccessibilityService::class.java),
            PackageManager.GET_META_DATA,
        )

        assertTrue(info.exported)
        assertEquals(Manifest.permission.BIND_ACCESSIBILITY_SERVICE, info.permission)
        assertNotEquals(0, info.metaData.getInt("android.accessibilityservice"))
    }
}
