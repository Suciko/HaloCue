# Android Full WebUI Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Android MVP page with the original PC WebUI served by a protected localhost Python service inside the APK.

**Architecture:** A whitelist sync copies reusable PC Python and WebUI files into the Android project without copying generated data. `android_web_server.py` wraps the existing `webui.H` handler, adds per-process session authentication, and exposes a start/stop API to Kotlin. `MainActivity` loads the returned loopback URL and keeps the packaged asset page only as a startup-failure fallback.

**Tech Stack:** Kotlin, Android WebView, Chaquopy Python 3.13, Python `ThreadingHTTPServer`, PowerShell sync scripts, JUnit 4, pytest, AndroidX instrumentation.

## Global Constraints

- Bind the HTTP service only to `127.0.0.1` and use a system-selected free port.
- Every `/api/*` request must authenticate with the per-process session, using `X-HaloCue-Session` for JavaScript requests or the HttpOnly same-origin session cookie for media element requests.
- Keep the original PC HTML/CSS/JavaScript structure and visible UI unless Android platform behavior requires a narrow adaptation.
- Do not package PC `out/`, `output/`, caches, logs, test screenshots, API keys, or official assets. Import-only compatibility modules may be copied when `webui.py` requires them, but their Windows/Spine execution paths must be disabled on Android.
- Do not request accessibility, legacy storage, or all-files access permissions.
- Keep public `.aap` output at `Download/HaloCue/`; never claim automatic AA import.

---

### Task 1: Whitelist PC Runtime Synchronization

**Files:**
- Create: `scripts/pc-runtime-manifest.json`
- Create: `scripts/sync-pc-runtime.ps1`
- Create: `scripts/test-pc-runtime-sync.ps1`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: PC source root `../01-完整程序/aa`.
- Produces: synchronized Python modules under `app/src/main/python/` and UI files `ui.html`, `css/**`, `js/**`, `branding/halocue-favicon.png` beside `webui.py`.

- [ ] **Step 1: Write the failing sync contract**

Create `scripts/test-pc-runtime-sync.ps1` with assertions equivalent to:

```powershell
$required = @(
  'app/src/main/python/webui.py',
  'app/src/main/python/ui.html',
  'app/src/main/python/js/api.js',
  'app/src/main/python/js/app.js',
  'app/src/main/python/css/app.css',
  'app/src/main/python/annotate.py',
  'app/src/main/python/draft_store.py',
  'app/src/main/python/model_profiles.py',
  'app/src/main/python/asset_catalog.py',
  'app/src/main/python/spine_semantic_faces.py'
)
$forbidden = @('out', 'output', '__pycache__', '.env', 'llm.json', 'assets.db')
```

Require every file in `$required` to exist after sync, reject any synchronized path containing a forbidden segment, and verify every manifest entry has a SHA-256 value.

- [ ] **Step 2: Run the contract to verify RED**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-pc-runtime-sync.ps1
```

Expected: FAIL because the manifest and complete WebUI runtime are absent.

- [ ] **Step 3: Implement deterministic synchronization**

Use a JSON manifest with explicit `python`, `directories`, and `static` arrays. The sync script must resolve both source and destination roots, reject destinations outside `06-安卓端`, copy only listed files, remove stale files only when they were recorded by the previous generated manifest, and write `app/src/main/python/PC运行时来源.json`:

```json
{
  "source": "../01-完整程序/aa",
  "files": [
    {"path": "webui.py", "sha256": "<computed uppercase hash>"}
  ]
}
```

Include the import-only dependencies `install_manager.py`, `spine_face_renderer.py`, `spine_face_analysis.py`, and `spine_face_labeler.py` because `webui.py` imports them at module load; do not call their Windows AA or Spine CLI entry points on Android. Do not list `launcher.py`, Windows command files, user configuration, or generated data.

- [ ] **Step 4: Run sync and contract to verify GREEN**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-pc-runtime.ps1
powershell -ExecutionPolicy Bypass -File scripts/test-pc-runtime-sync.ps1
git diff --check
```

Expected: sync completes, all required files exist, forbidden paths are absent, and the source record contains hashes.

- [ ] **Step 5: Commit**

```powershell
git add .gitignore scripts app/src/main/python
git commit -m "build(android): sync reusable PC runtime"
```

### Task 2: Protected Python Localhost Server

**Files:**
- Create: `app/src/main/python/android_web_server.py`
- Create: `app/src/test/python/test_android_web_server.py`
- Modify: `app/src/main/python/js/api.js`

**Interfaces:**
- Produces: `start(workspace_dir: str, session_token: str) -> dict` with `port`, `url`, and `ready`; `stop() -> None`.
- Consumes: `webui.H`, synchronized `ui.html`, and `X-HaloCue-Session` request headers.

- [ ] **Step 1: Write failing Python tests**

Cover authenticated API access and public static files:

```python
def test_api_rejects_missing_session(running_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(running_server["url"] + "/api/android/health")
    assert exc.value.code == 403


def test_api_accepts_session_header(running_server):
    request = urllib.request.Request(
        running_server["url"] + "/api/android/health",
        headers={"X-HaloCue-Session": "test-session"},
    )
    payload = json.load(urllib.request.urlopen(request))
    assert payload == {"ok": True, "runtime": "android-webui"}
```

Also assert `/?session=test-session` sets `HaloCueSession=test-session; HttpOnly; SameSite=Strict; Path=/`, the cookie authenticates a preview/media request which cannot add custom headers, `/` returns the synchronized PC page, and `stop()` releases the port.

- [ ] **Step 2: Run focused tests to verify RED**

Run:

```powershell
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python/test_android_web_server.py -q
```

Expected: FAIL because `android_web_server` does not exist.

- [ ] **Step 3: Implement the handler and lifecycle**

Before constructing the server, configure the imported PC globals for Android:

```python
def configure_android_runtime(workspace_dir: str) -> None:
    root = Path(workspace_dir)
    webui.HERE = str(Path(__file__).parent)
    webui.STORY_ROOT = str(root / "workspace")
    webui.DB = str(root / "databases" / "aa_assets.db")
    webui.INDEX = str(root / "databases" / "aa_resources.json")
    webui.LLMCFG = str(root / "databases" / "llm.json")
    webui.THUMBS = str(root / "cache" / "thumbs")
    Path(webui.DB).parent.mkdir(parents=True, exist_ok=True)
    assetdb.connect(webui.DB).close()
    webui.MODEL_PROFILES = model_profiles.ModelProfileStore(
        str(root / "databases" / "llm_profiles.json")
    )
    webui.OFFICIAL_PREVIEW_INDEX = OfficialPreviewIndex(root / "cache" / "official-previews")
```

Set `HALOCUE_PLATFORM=android`, initialize an empty resource index when no user-selected index exists, replace `windows_host_roots()` pickers with token-backed Android pickers before serving requests, and make direct-install and Spine-render routes return their documented capability errors.

Create a handler subclass which guards all `/api/` methods before delegating:

```python
class AndroidHandler(webui.H):
    session_token = ""

    def _android_authorized(self) -> bool:
        supplied = self.headers.get("X-HaloCue-Session", "")
        if not supplied:
            morsel = SimpleCookie(self.headers.get("Cookie", "")).get("HaloCueSession")
            supplied = morsel.value if morsel else ""
        return hmac.compare_digest(supplied, self.session_token)

    def _guard_api(self) -> bool:
        if urlparse(self.path).path.startswith("/api/") and not self._android_authorized():
            self._send(403, {"ok": False, "code": "invalid_session", "e": "会话已失效"})
            return False
        return True
```

Override `do_GET`, `do_POST`, and `do_PATCH` to call `_guard_api()`. Intercept `/api/android/health`; delegate other paths to `webui.H`. Start `ThreadingHTTPServer(("127.0.0.1", 0), AndroidHandler)` on a daemon thread and store a single guarded server instance.

When `/` or `/index.html` receives the correct `session` query parameter, send the HttpOnly `HaloCueSession` cookie before serving the page. Reject an incorrect session query. This cookie exists only for the active random loopback origin and is required because `<img>`, `<audio>`, and download element requests cannot attach `X-HaloCue-Session` themselves.

Update `js/api.js` so `request()` reads `session` from the page query once and adds `X-HaloCue-Session` without replacing caller headers:

```javascript
const session = new URLSearchParams(window.location.search).get('session') || '';
options = options || {};
options.headers = Object.assign({}, options.headers || {}, {'X-HaloCue-Session': session});
```

- [ ] **Step 4: Run tests to verify GREEN**

Run the focused pytest command again. Expected: all server tests pass and repeated `start()` calls return the same running service until `stop()`.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/android_web_server.py app/src/main/python/js/api.js app/src/test/python/test_android_web_server.py
git commit -m "feat(android): host protected PC WebUI locally"
```

### Task 3: Kotlin Runtime Controller and Loopback Policy

**Files:**
- Create: `app/src/main/java/com/halocue/android/LocalWebRuntime.kt`
- Create: `app/src/androidTest/java/com/halocue/android/LocalWebRuntimeTest.kt`
- Modify: `app/src/main/res/xml/network_security_config.xml`

**Interfaces:**
- Produces: `LocalWebRuntime.start(): LocalWebSession`, `LocalWebRuntime.stop()`, and `LocalWebSession(url: String, token: String)`.
- Consumes: Python `android_web_server.start(workspace_dir, session_token)` and `.stop()`.

- [ ] **Step 1: Write failing instrumentation test**

```kotlin
@Test
fun starts_a_tokenized_loopback_web_service() {
    val runtime = LocalWebRuntime(context)
    val session = runtime.start()
    assertTrue(session.url.startsWith("http://127.0.0.1:"))
    assertTrue(session.url.contains("?session="))
    assertTrue(session.token.length >= 32)
    runtime.stop()
}
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
.\gradlew.bat connectedDebugAndroidTest `
  -Pandroid.testInstrumentationRunnerArguments.class=com.halocue.android.LocalWebRuntimeTest
```

Expected: compilation failure because `LocalWebRuntime` is absent.

- [ ] **Step 3: Implement controller and cleartext restriction**

Generate a 32-byte token with `SecureRandom`, encode it URL-safe without padding, call the Python module on a background thread, and append the URL-encoded token as the `session` query parameter. `stop()` must call Python exactly once and tolerate shutdown after partial startup.

Change the network policy to permit cleartext only for loopback:

```xml
<network-security-config>
    <base-config cleartextTrafficPermitted="false" />
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">127.0.0.1</domain>
    </domain-config>
</network-security-config>
```

- [ ] **Step 4: Run focused test to verify GREEN**

Run the Step 2 command again. Expected: the service starts, the URL is loopback-only, and shutdown completes without a leaked test process.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/java/com/halocue/android/LocalWebRuntime.kt app/src/androidTest/java/com/halocue/android/LocalWebRuntimeTest.kt app/src/main/res/xml/network_security_config.xml
git commit -m "feat(android): manage localhost WebUI runtime"
```

### Task 4: MainActivity Loads the PC WebUI

**Files:**
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/androidTest/java/com/halocue/android/MainActivityTest.kt`
- Modify: `app/src/main/assets/index.html`

**Interfaces:**
- Consumes: `LocalWebRuntime.start()`.
- Produces: a WebView restricted to the active loopback origin; packaged `index.html` is used only for startup failure.

- [ ] **Step 1: Write failing activity contract**

Require the active WebView URL to start with loopback and reject navigation to unrelated HTTP origins. Keep external `https:` links delegated to the system:

```kotlin
assertTrue(activity.webViewForTest().url!!.startsWith("http://127.0.0.1:"))
assertFalse(activity.isInternalUrlForTest(Uri.parse("https://example.com")))
```

- [ ] **Step 2: Run test to verify RED**

Run the focused `MainActivityTest`. Expected: FAIL because the activity still loads `file:///android_asset/index.html`.

- [ ] **Step 3: Replace asset bootstrap with local-service bootstrap**

Start `LocalWebRuntime` on the existing executor, load its URL on the UI thread, and show the packaged page only when startup raises an exception. Remove the MVP compiler bootstrap and `window.HaloCueApp.bootstrap` path; retain native methods still required for opening AA and sharing exports.

Allow WebView internal navigation only when scheme is `http`, host is `127.0.0.1`, and port equals the active session port. Disable file access and universal file URL access as before. Call `LocalWebRuntime.stop()` from `onDestroy()` after destroying the WebView.

- [ ] **Step 4: Run focused and host tests**

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug assembleDebugAndroidTest
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python/test_android_web_server.py -q
```

Expected: Gradle and Python tests pass; the fallback page remains packaged but is not the normal first screen.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/java/com/halocue/android/MainActivity.kt app/src/androidTest/java/com/halocue/android/MainActivityTest.kt app/src/main/assets/index.html
git commit -m "feat(android): load the full PC interface"
```

### Task 5: Mobile WebUI and Device Contract

**Files:**
- Modify: `app/src/main/python/css/layout.css`
- Modify: `app/src/main/python/css/app.css`
- Modify: `scripts/test-device-page-contract.ps1`

**Interfaces:**
- Consumes: unchanged PC DOM IDs and modules.
- Produces: usable 390 px and tablet layouts without changing desktop information architecture.

- [ ] **Step 1: Extend the device contract before CSS changes**

Require `ui.html` to load `js/api.js`, `js/app.js`, `js/model.js`, `js/story.js`, and `js/library.js`; require the rendered document to expose the existing model, story, draft, and asset-library roots. Assert no MVP-only heading `HALOCUE FOR ANDROID` is present.

- [ ] **Step 2: Run contract to verify RED**

Build and install the APK, then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test-device-page-contract.ps1
```

Expected: at least one mobile layout or full-UI assertion fails.

- [ ] **Step 3: Add Android-only responsive overrides**

At the end of `layout.css`, add a media query for `max-width: 600px` which keeps existing navigation and workbench structure but ensures one-column panels, scrollable tab strips, `min-width: 0` for grid children, 44 px minimum command targets, and safe-area padding using `env(safe-area-inset-*)`. Do not rename DOM IDs or replace desktop modules.

- [ ] **Step 4: Verify installed page contract**

Re-sync, rebuild, install, and rerun the contract. Expected: the full PC UI is present, the local service is ready, and the contract passes on the target device.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/css app/src/main/python/PC运行时来源.json scripts/test-device-page-contract.ps1
git commit -m "fix(android): make the PC WebUI usable on mobile"
```

### Task 6: Phase 1 Verification

**Files:**
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-android-full-webui-runtime.md`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: a testable APK whose first screen is the original PC interface served locally.

- [ ] **Step 1: Run a clean host build and Python suite**

```powershell
.\gradlew.bat clean testDebugUnitTest assembleDebug assembleDebugAndroidTest
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python -q
powershell -ExecutionPolicy Bypass -File scripts/test-pc-runtime-sync.ps1
git diff --check
```

Expected: every command succeeds.

- [ ] **Step 2: Run target-device verification**

Install the APK, run `connectedDebugAndroidTest`, run the page contract, and manually confirm model/story/library pages open without a blank WebView. Confirm a request without `X-HaloCue-Session` returns HTTP 403.

- [ ] **Step 3: Record results and commit**

Record test counts, device, local URL behavior, sync manifest status, and remaining disabled platform actions in `安卓端接手记忆.md`; mark completed checkboxes in this plan.

```powershell
git add 安卓端接手记忆.md docs/superpowers/plans/2026-08-10-android-full-webui-runtime.md
git commit -m "test(android): verify full WebUI runtime foundation"
```
