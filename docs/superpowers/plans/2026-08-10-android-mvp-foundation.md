# HaloCue Android MVP Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, install, and launch a standalone HaloCue Android APK which renders a bundled WebView, starts an embedded Python runtime, reports whether original AzureArchive is installed, and can open it.

**Architecture:** A standard single-activity Android app owns the WebView and phone integrations. Chaquopy packages a small Python probe now and becomes the seam for moving reusable desktop Python modules later. The WebView loads APK assets and receives a JSON bootstrap payload from Kotlin after the page finishes loading.

**Tech Stack:** Kotlin, Android Gradle Plugin 8.9.1, Gradle 8.11.1, compile/target SDK 36, Chaquopy 17.0.0, Python 3.13, Android WebView, JUnit 4, AndroidX Test.

## Global Constraints

- All Android source, plans, tests, and evidence live under `06-安卓端/`.
- The original AA package `com.foxxlight.AzureArchive` must not be modified, resigned, injected, or overwritten.
- The first APK uses package name `com.halocue.android`, `minSdk 24`, `targetSdk 36`, and contains only `arm64-v8a` native Python binaries for the vivo X100s Pro probe.
- The UI is loaded from APK assets inside WebView; normal operation never opens a browser URL.
- The app must not claim it imported a project into AA.
- The first probe must not write to AA storage.

---

### Task 1: Reproducible Android Build Skeleton

**Files:**
- Create: `06-安卓端/settings.gradle.kts`
- Create: `06-安卓端/build.gradle.kts`
- Create: `06-安卓端/gradle.properties`
- Create: `06-安卓端/.gitignore`
- Create: `06-安卓端/app/build.gradle.kts`
- Create: `06-安卓端/app/proguard-rules.pro`
- Create: `06-安卓端/app/src/main/AndroidManifest.xml`
- Create: `06-安卓端/gradlew`
- Create: `06-安卓端/gradlew.bat`
- Create: `06-安卓端/gradle/wrapper/gradle-wrapper.jar`
- Create: `06-安卓端/gradle/wrapper/gradle-wrapper.properties`

**Interfaces:**
- Consumes: JDK 21 already installed on the workstation; Android SDK installed at a local user path.
- Produces: `./gradlew.bat` and an `app` module which Gradle can configure.

- [x] **Step 1: Install the Android command-line SDK and Gradle 8.11.1 into user-local tooling directories**

Download the official command-line tools, verify SHA-256 `90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a`, install `platforms;android-36`, `build-tools;36.0.0`, and `platform-tools`, then download Gradle 8.11.1.

- [x] **Step 2: Create the Gradle skeleton**

Use plugin versions `com.android.application:8.9.1`, `org.jetbrains.kotlin.android:2.1.20`, and `com.chaquo.python:17.0.0`. Configure namespace `com.halocue.android`, application ID `com.halocue.android`, one `arm64-v8a` ABI, and Python 3.13.

- [x] **Step 3: Generate the Gradle wrapper**

Run the downloaded Gradle distribution with `wrapper --gradle-version 8.11.1 --distribution-type bin`.

- [x] **Step 4: Verify Gradle configuration**

Run: `./gradlew.bat tasks --all`

Expected: exit code 0 and Android build tasks including `assembleDebug` and `connectedDebugAndroidTest`.

---

### Task 2: Embedded Python Runtime Contract

**Files:**
- Create: `06-安卓端/app/src/test/python/test_runtime_probe.py`
- Create: `06-安卓端/app/src/main/python/runtime_probe.py`

**Interfaces:**
- Consumes: no Android APIs.
- Produces: `runtime_probe.health() -> dict[str, object]` with `runtime`, `ready`, `schema`, and `message` fields.

- [x] **Step 1: Write the failing Python test**

```python
from runtime_probe import health


def test_health_reports_stable_android_bridge_contract():
    assert health() == {
        "runtime": "python",
        "ready": True,
        "schema": 1,
        "message": "本地 Python 已启动",
    }
```

- [x] **Step 2: Run the test and verify RED**

Run from `06-安卓端`: `python -m pytest app/src/test/python/test_runtime_probe.py -q`

Expected: collection fails because `runtime_probe` does not exist.

- [x] **Step 3: Implement the minimal runtime probe**

```python
def health():
    return {
        "runtime": "python",
        "ready": True,
        "schema": 1,
        "message": "本地 Python 已启动",
    }
```

- [x] **Step 4: Run the test and verify GREEN**

Run with `PYTHONPATH=app/src/main/python`: `python -m pytest app/src/test/python/test_runtime_probe.py -q`

Expected: one test passes.

---

### Task 3: WebView Bootstrap and AA Detection

**Files:**
- Create: `06-安卓端/app/src/androidTest/java/com/halocue/android/MainActivityTest.kt`
- Create: `06-安卓端/app/src/main/java/com/halocue/android/MainActivity.kt`
- Create: `06-安卓端/app/src/main/assets/index.html`
- Create: `06-安卓端/app/src/main/assets/app.css`
- Create: `06-安卓端/app/src/main/res/values/strings.xml`
- Create: `06-安卓端/app/src/main/res/values/themes.xml`
- Create: `06-安卓端/app/src/main/res/xml/network_security_config.xml`

**Interfaces:**
- Consumes: `runtime_probe.health()` and Android `PackageManager`.
- Produces: a visible `WebView` with resource ID `R.id.main_webview`, page title `HaloCue Android`, JavaScript function `window.HaloCueApp.bootstrap(payload)`, and native JS bridge method `openAzureArchive()`.

- [x] **Step 1: Write the failing Android instrumentation test**

```kotlin
@RunWith(AndroidJUnit4::class)
class MainActivityTest {
    @Test
    fun bundled_page_reports_python_and_detects_original_aa() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withId(R.id.main_webview)).check(matches(isDisplayed()))
            onView(withText("本地 Python 已启动")).check(matches(isDisplayed()))
            onView(withText("已检测到原版 AA")).check(matches(isDisplayed()))
        }
    }
}
```

- [x] **Step 2: Build the instrumentation test and verify RED**

Run: `./gradlew.bat assembleDebugAndroidTest`

Expected: compilation fails because `MainActivity` and `R.id.main_webview` do not exist.

- [x] **Step 3: Implement the minimal activity, assets, Python bootstrap, and AA launcher**

The activity must start Chaquopy once, call `runtime_probe.health()`, detect `com.foxxlight.AzureArchive`, load `file:///android_asset/index.html`, inject the JSON payload in `onPageFinished`, and expose an `@JavascriptInterface` which launches AA only after the user taps the page button.

- [x] **Step 4: Build the debug APK and Android test APK**

Run: `./gradlew.bat assembleDebug assembleDebugAndroidTest`

Expected: both APKs build with exit code 0.

- [x] **Step 5: Install and run the instrumentation test on the connected vivo**

Run: `./gradlew.bat connectedDebugAndroidTest`

Expected: one device, one test, zero failures.

- [x] **Step 6: Launch the APK and capture runtime evidence**

Install `app-debug.apk`, launch `com.halocue.android/.MainActivity`, verify the foreground package, dump the UI hierarchy, and capture a screenshot under `06-安卓端/evidence/`.

- [x] **Step 7: Record the first probe result**

Update `06-安卓端/安卓端接手记忆.md` with the exact build, install, test, and device results. Do not mark later `.aap` generation or automatic AA import milestones complete.

## Plan Self-Review

- Spec coverage: this plan covers the first technical probe only—standalone APK, bundled WebView, embedded Python, original-AA detection, and launch. Project generation and file transfer are deliberately separate follow-up milestones.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step remains.
- Type consistency: Python `health()` produces the bootstrap data consumed by `MainActivity`; the page consumes one JSON payload and exposes one AA-open action.
