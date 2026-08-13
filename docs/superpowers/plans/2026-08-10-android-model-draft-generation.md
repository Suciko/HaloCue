# Android Model, Draft, and Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the full Android WebUI support PC-equivalent model configuration, story files, drafts, AI annotation, real `.aap` generation, public export, and sharing.

**Architecture:** Reuse the synchronized PC model, draft, annotation, and compiler modules. Android-specific credential, file-selection, and export behavior is exposed through narrow Kotlin services and Python adapters; PC business modules call stable adapter interfaces instead of Windows APIs.

**Tech Stack:** Kotlin, Android Keystore, Storage Access Framework, Chaquopy Python 3.13, PC HaloCue Python modules, WebView JavaScript bridge, MediaStore, pytest, AndroidX instrumentation.

## Global Constraints

- API Keys must never be stored in plaintext JSON, SQLite fields, logs, WebView storage, or page payloads.
- Existing PC model profile, routing, draft, card, and generation API contracts remain compatible.
- Android file access uses user-selected SAF documents copied into app-private storage.
- AI/network failures must not block local draft editing or `.aap` compilation from already annotated content.
- Generated `.aap` files are published only to `Download/HaloCue/` and may be shared; they are not written into AA private directories.
- Keep the original AA package `com.foxxlight.AzureArchive` unchanged.

## Progress Update (2026-08-10)

- [x] Tasks 1-6: runtime compatibility, Keystore profiles, SAF import, private drafts, annotation, and real `.aap` generation.
- [x] Task 7: full WebUI build publication and opaque `shareId` system sharing, committed as `4bb4d6d`.
- [ ] Task 8: final interactive acceptance remains open; automated host/device verification and the development APK are recorded in `安卓端接手记忆.md`.

---

### Task 1: Python Dependency Compatibility Gate

**Files:**
- Modify: `app/build.gradle.kts`
- Create: `app/src/main/python/android_capabilities.py`
- Create: `app/src/test/python/test_android_capabilities.py`
- Create: `scripts/test-python-runtime-imports.ps1`

**Interfaces:**
- Produces: `capability_report() -> dict[str, dict]` with `available`, `required`, and `reason` for `pillow`, `anthropic`, `opencc`, and `unitypy`.

- [ ] **Step 1: Write failing capability tests**

```python
def test_required_runtime_modules_are_available():
    report = capability_report()
    assert report["pillow"]["available"] is True
    assert report["anthropic"]["required"] is False


def test_optional_import_failure_has_a_readable_reason(monkeypatch):
    monkeypatch.setattr(importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))
    assert "不可用" in capability_report()["opencc"]["reason"]
```

- [ ] **Step 2: Run tests to verify RED**

```powershell
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python/test_android_capabilities.py -q
```

Expected: FAIL because the capability module is absent.

- [ ] **Step 3: Implement imports and package only verified dependencies**

Keep Pillow 11.0.0. Add the Anthropic SDK version currently used by the PC application only after `scripts/test-python-runtime-imports.ps1` proves it imports in the built arm64 APK. Treat OpenCC and UnityPy as optional: import lazily and report unavailable capabilities instead of failing `webui.py` startup.

The PowerShell test must import `webui`, `llm`, `model_profiles`, `draft_store`, `annotate`, and `script2aap` using `PYTHONPATH=app/src/main/python`.

- [ ] **Step 4: Verify host and device imports**

Run the focused pytest test, the PowerShell import test, `assembleDebug`, and a device instrumentation probe which imports the same modules through Chaquopy. Expected: required modules import; optional failures are represented in the report.

- [ ] **Step 5: Commit**

```powershell
git add app/build.gradle.kts app/src/main/python/android_capabilities.py app/src/test/python/test_android_capabilities.py scripts/test-python-runtime-imports.ps1
git commit -m "build(android): gate optional Python capabilities"
```

### Task 2: Keystore-Backed Credential Store

**Files:**
- Create: `app/src/main/java/com/halocue/android/SecureCredentialStore.kt`
- Create: `app/src/main/java/com/halocue/android/AndroidRuntimeRegistry.kt`
- Create: `app/src/androidTest/java/com/halocue/android/SecureCredentialStoreTest.kt`
- Create: `app/src/main/python/android_credentials.py`
- Create: `app/src/test/python/test_android_credentials.py`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`

**Interfaces:**
- Kotlin: `put(name: String, value: String)`, `has(name: String): Boolean`, `masked(name: String): String?`, `delete(name: String)`.
- Python: `set_secret(name: str, value: str)`, `get_secret(name: str) -> str | None`, `secret_status(name: str) -> dict`, `delete_secret(name: str)`.

- [ ] **Step 1: Write failing Kotlin and Python tests**

Kotlin must verify round-trip storage, masked output, deletion, and that preferences do not contain the plaintext value. Python must use a fake backend and verify that `secret_status()` returns only `configured` and `masked`.

```python
assert secret_status("anthropic_api_key") == {"configured": True, "masked": "••••1234"}
assert "sk-test" not in json.dumps(secret_status("anthropic_api_key"))
```

- [ ] **Step 2: Run tests to verify RED**

Run the focused pytest and instrumentation classes. Expected: missing symbols.

- [ ] **Step 3: Implement AES/GCM Keystore storage**

Use an Android Keystore AES key alias `halocue_credentials_v1`, randomized 12-byte IVs, and AES/GCM/NoPadding. Store only Base64 IV and ciphertext in private SharedPreferences `halocue_secure_credentials`. Initialize `AndroidRuntimeRegistry` from `Application`/`MainActivity` with `applicationContext`; Python accesses it through Chaquopy Java interop.

`get_secret()` is callable only inside Python provider construction and must never be exposed by an HTTP response.

- [ ] **Step 4: Run focused tests to verify GREEN**

Expected: Kotlin round trips on device, plaintext scan is empty, and Python adapter tests pass with the fake backend.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/java/com/halocue/android/SecureCredentialStore.kt app/src/main/java/com/halocue/android/AndroidRuntimeRegistry.kt app/src/main/java/com/halocue/android/MainActivity.kt app/src/androidTest/java/com/halocue/android/SecureCredentialStoreTest.kt app/src/main/python/android_credentials.py app/src/test/python/test_android_credentials.py
git commit -m "feat(android): protect model credentials with Keystore"
```

### Task 3: Model Profiles and Provider APIs

**Files:**
- Modify: `app/src/main/python/model_profiles.py`
- Modify: `app/src/main/python/llm.py`
- Modify: `app/src/main/python/webui.py`
- Create: `app/src/test/python/test_android_model_profiles.py`

**Interfaces:**
- Consumes: `android_credentials.secret_status/get_secret/set_secret/delete_secret`.
- Produces: existing `/api/models/profiles`, save, delete, activate, capability, and model-list endpoints without returning full secrets.

- [ ] **Step 1: Port PC web-model tests and add secret assertions**

Copy the relevant cases from PC `tests/test_web_model_profiles.py`, `tests/test_model_profiles.py`, and `tests/test_model_router.py`. Add:

```python
def test_profile_response_never_returns_api_key(client):
    payload = client.get_json("/api/models/profiles")
    assert "sk-secret" not in json.dumps(payload)
    assert payload["profiles"][0]["credential"]["configured"] is True
```

- [ ] **Step 2: Run tests to verify RED**

Expected: Windows credential access or missing Android status fields causes failure.

- [ ] **Step 3: Inject the Android credential backend**

Add a credential-provider interface to `model_profiles.py`; select `android_credentials` when `HALOCUE_PLATFORM=android`. Keep provider/model/base URL/reasoning settings in the existing profile store, but move API Key writes and reads to the credential backend. Preserve PC behavior when the environment variable is absent.

`llm.py` must resolve the Key only while constructing a provider. HTTP endpoints may update, replace, or delete a credential but may return only masked status.

- [ ] **Step 4: Run model tests and WebUI import test**

Run the new tests plus synchronized PC tests for model capabilities/router/profiles. Expected: all pass and `webui` imports without `win32cred`.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/model_profiles.py app/src/main/python/llm.py app/src/main/python/webui.py app/src/test/python/test_android_model_profiles.py
git commit -m "feat(android): enable PC model workbench"
```

### Task 4: Android Story Document Picker

**Files:**
- Add dependency in: `app/build.gradle.kts`
- Create: `app/src/main/java/com/halocue/android/AndroidDocumentPicker.kt`
- Create: `app/src/main/java/com/halocue/android/IncomingFileStore.kt`
- Create: `app/src/androidTest/java/com/halocue/android/IncomingFileStoreTest.kt`
- Create: `app/src/main/python/android_incoming_files.py`
- Modify: `app/src/main/java/com/halocue/android/MainActivity.kt`
- Modify: `app/src/main/python/js/story_picker.js`

**Interfaces:**
- JavaScript: `HaloCueNative.pickDocument(requestId, purpose, suffixesJson)` and callback `window.HaloCueAndroid.documentPicked(payload)`.
- Python: `claim_incoming(token: str, allowed_suffixes: list[str]) -> Path`.

- [ ] **Step 1: Write failing staging-store tests**

Verify that copied names are sanitized, files are capped at 10 MiB for story text, tokens cannot traverse directories, and claiming a token moves it once from `files/incoming` to `files/workspace/imports`.

- [ ] **Step 2: Run tests to verify RED**

Run focused instrumentation and Python tests. Expected: missing picker and incoming-file store.

- [ ] **Step 3: Implement one reusable document picker**

Change `MainActivity` to `ComponentActivity`, register `ActivityResultContracts.OpenDocument`, and queue one active request. Copy the selected `content://` stream to a UUID-named private file while retaining the display name as metadata. Return only `{requestId, ok, token, name, size}` to JavaScript; never return the original URI or private path.

Update `story_picker.js` on Android to call the native picker and then POST the token to the existing story upload/select API. Browser/PC behavior remains unchanged.

- [ ] **Step 4: Verify picker cancellation and import**

Tests must cover success, user cancellation, unsupported suffix, file too large, and duplicate callbacks. Expected: cancellation is a normal `{ok:false, code:"cancelled"}` result.

- [ ] **Step 5: Commit**

```powershell
git add app/build.gradle.kts app/src/main/java/com/halocue/android app/src/androidTest/java/com/halocue/android app/src/main/python/android_incoming_files.py app/src/main/python/js/story_picker.js
git commit -m "feat(android): import story files through SAF"
```

### Task 5: Story Workspace, Drafts, and Card APIs

**Files:**
- Modify: `app/src/main/python/aapaths.py`
- Modify: `app/src/main/python/story_workspace.py`
- Modify: `app/src/main/python/draft_store.py`
- Modify: `app/src/main/python/webui.py`
- Create: `app/src/test/python/test_android_story_drafts.py`

**Interfaces:**
- Consumes: private workspace root from `HALOCUE_WORKSPACE_DIR` and incoming story tokens.
- Produces: PC-compatible recent-story, draft, version, card CRUD, freeze, and review endpoints.

- [ ] **Step 1: Port the focused PC tests**

Port the behavioral cases from `test_story_workspace.py`, `test_draft_store.py`, `test_draft_versions.py`, `test_cards_crud.py`, and `test_web_draft_endpoints.py`. Use a temporary Android workspace root and assert no path escapes it.

- [ ] **Step 2: Run tests to verify RED**

Expected: PC home/AppData assumptions or missing synchronized modules fail.

- [ ] **Step 3: Route all writable paths through Android workspace settings**

Make `aapaths.py` resolve Android database, draft, history, cache, and export directories exclusively under the provided workspace root. Keep PC path resolution unchanged outside Android. Initialize directories idempotently and run existing database migrations before serving API traffic.

- [ ] **Step 4: Run draft and story tests to verify GREEN**

Expected: imported story text appears in recent stories; card edits and draft versions survive a new store instance; all paths remain inside the temporary root.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/aapaths.py app/src/main/python/story_workspace.py app/src/main/python/draft_store.py app/src/main/python/webui.py app/src/test/python/test_android_story_drafts.py
git commit -m "feat(android): persist stories and draft reviews"
```

### Task 6: AI Annotation and Real Generation

**Files:**
- Modify: `app/src/main/python/annotate.py`
- Modify: `app/src/main/python/prompt.py`
- Modify: `app/src/main/python/jobs.py`
- Modify: `app/src/main/python/webui.py`
- Create: `app/src/test/python/test_android_generation.py`

**Interfaces:**
- Consumes: active model profile, story/draft tokens, and existing `script2aap` compiler.
- Produces: existing annotation job progress, review output, and private generated `.aap` path.

- [ ] **Step 1: Port focused annotation and build tests**

Use PC cases from `test_annotate_main.py`, `test_annotation_protocol.py`, `test_retry_conditions.py`, `test_review_gate.py`, and `test_generator_asset_integration.py`. Add a no-network mock provider case which generates a one-line project and validates the resulting ZIP structure.

- [ ] **Step 2: Run tests to verify RED**

Expected: Windows install/finalization behavior or missing Android path configuration fails.

- [ ] **Step 3: Separate compilation from AA installation**

In Android mode, `run_build` must stop after validation and private `.aap` creation. Return `{ok, project, aap_file, warnings}` to the job result and never import `install_manager`. Preserve PC installation behavior outside Android mode.

Keep streaming/polling endpoints and retry semantics unchanged. Model failure returns a failed annotation job without deleting saved drafts.

- [ ] **Step 4: Run generation tests to verify GREEN**

Expected: mock annotation and local compilation pass; no Android test imports or writes through `install_manager`.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/python/annotate.py app/src/main/python/prompt.py app/src/main/python/jobs.py app/src/main/python/webui.py app/src/test/python/test_android_generation.py
git commit -m "feat(android): run PC annotation and generation pipeline"
```

### Task 7: Publish and Share WebUI Builds

**Files:**
- Create: `app/src/main/java/com/halocue/android/AndroidPlatformServices.kt`
- Create: `app/src/androidTest/java/com/halocue/android/AndroidPlatformServicesTest.kt`
- Create: `app/src/main/python/android_exports.py`
- Modify: `app/src/main/python/webui.py`
- Modify: `app/src/main/python/js/app.js`

**Interfaces:**
- Python: `publish_aap(source: str, project: str) -> dict` returning `displayName`, `relativePath`, and opaque `shareId`.
- JavaScript/native: `HaloCueNative.shareExport(shareId)`.

- [ ] **Step 1: Write failing export contract tests**

Assert a completed WebUI build publishes through `AapPublicExporter`, exposes no `content://` URI or private path to JavaScript, and shares only a known in-memory `shareId`.

- [ ] **Step 2: Run tests to verify RED**

Expected: the old MVP bridge only knows `lastExport` and is disconnected from WebUI build jobs.

- [ ] **Step 3: Implement platform export registry**

`AndroidPlatformServices` must publish via the existing `AapPublicExporter`, retain a bounded in-memory map of `shareId -> PublicAapExportResult`, and create chooser intents through `AapShareIntentFactory`. Python calls it through `android_exports.py`; the build API returns only public display metadata and `shareId`.

Update `app.js` so the completed build view shows the existing export wording and invokes `shareExport(shareId)`. Remove or disable PC “install into AA” commands only in Android mode.

- [ ] **Step 4: Verify host and device flow**

Run generation pytest tests, Android export/share instrumentation tests, and one real device build. Expected: `.aap` appears under `Download/HaloCue/`, share chooser opens, and AA project files remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add app/src/main/java/com/halocue/android/AndroidPlatformServices.kt app/src/androidTest/java/com/halocue/android/AndroidPlatformServicesTest.kt app/src/main/python/android_exports.py app/src/main/python/webui.py app/src/main/python/js/app.js
git commit -m "feat(android): publish and share WebUI projects"
```

### Task 8: Phase 2 Verification

**Files:**
- Modify: `安卓端接手记忆.md`
- Modify: `docs/superpowers/plans/2026-08-10-android-model-draft-generation.md`

- [ ] **Step 1: Run clean verification**

```powershell
.\gradlew.bat clean testDebugUnitTest assembleDebug assembleDebugAndroidTest
$env:PYTHONPATH = 'app/src/main/python'
python -m pytest app/src/test/python -q
powershell -ExecutionPolicy Bypass -File scripts/test-python-runtime-imports.ps1
git diff --check
```

- [ ] **Step 2: Complete a real-device workflow**

On vivo X100s Pro / Android 16: create or edit a model profile, import a story text file, save a draft, edit one card, run annotation with a configured model or the mock test profile, compile, export, and open the share chooser. Restart the app and confirm the draft/profile metadata remains.

- [ ] **Step 3: Record and commit results**

Record dependency capability results, tests, device flow, exported filename/hash, and any optional disabled provider in `安卓端接手记忆.md`.

```powershell
git add 安卓端接手记忆.md docs/superpowers/plans/2026-08-10-android-model-draft-generation.md
git commit -m "test(android): verify model draft and generation parity"
```
