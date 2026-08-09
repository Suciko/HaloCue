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
class MainActivityTest {
    @Test
    fun bundled_page_reports_python_and_detects_original_aa() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onWebView(withId(R.id.main_webview))
                .forceJavascriptEnabled()
                .withElement(findElement(Locator.ID, "python-status"))
                .check(webMatches(getText(), containsString("本地 Python 已启动")))

            onWebView(withId(R.id.main_webview))
                .withElement(findElement(Locator.ID, "aa-status"))
                .check(webMatches(getText(), containsString("已检测到原版 AA")))
        }
    }
}
