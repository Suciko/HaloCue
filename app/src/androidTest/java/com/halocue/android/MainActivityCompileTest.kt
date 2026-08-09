package com.halocue.android

import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.matcher.ViewMatchers.withId
import androidx.test.espresso.web.assertion.WebViewAssertions.webMatches
import androidx.test.espresso.web.sugar.Web.onWebView
import androidx.test.espresso.web.webdriver.DriverAtoms.findElement
import androidx.test.espresso.web.webdriver.DriverAtoms.getText
import androidx.test.espresso.web.webdriver.Locator
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.hamcrest.CoreMatchers.containsString
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityCompileTest {
    @Test
    fun page_exposes_local_compile_controls_and_unimported_status() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onWebView(withId(R.id.main_webview))
                .forceJavascriptEnabled()
                .withElement(findElement(Locator.ID, "compile-aap"))
                .check(webMatches(getText(), containsString("生成 .aap")))

            onWebView(withId(R.id.main_webview))
                .withElement(findElement(Locator.ID, "compile-status"))
                .check(webMatches(getText(), containsString("尚未生成")))
        }
    }
}
