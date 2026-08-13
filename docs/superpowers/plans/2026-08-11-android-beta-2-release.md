# Android 0.3.0-beta.2 Release Checklist

**Goal:** Publish an emergency Android beta which fixes draft generation and blocked WebView confirmation flows.

- [x] Set `versionCode = 5` and `versionName = "0.3.0-beta.2"`.
- [x] Run the complete Android Python suite: 96 passed, 1 skipped.
- [x] Run JavaScript syntax checks.
- [x] Build and validate the signed release APK; Release lint passed.
- [x] Install the release-derived acceptance build and run device tests: `OK (30 tests)`.
- [x] Package and hash `构建产物/HaloCue-Android-0.3.0-beta.2-arm64-v8a.apk`.
- [x] Push the Android source branch and tag `v0.3.0-beta.2`.
- [x] Publish the GitHub pre-release and independently verify the uploaded APK hash.

## Result

- APK size: 57,229,557 bytes.
- APK SHA-256: `CBD141BF021E6B6C01D32045D602DECA5E382DC79B32FFFE07C4BB07AFA03265`.
- Certificate SHA-256: `BF0A5C4DD4114B0AB48FC79D0B41C56CA49A324F3FE27C019BA80B5FFC7ACB09`.
- Device acceptance: vivo `V2324HA`, Android 16 / API 36, installed as `0.3.0-beta.2` and `0.3.0-beta.2-device`.
- GitHub release: `https://github.com/Suciko/HaloCue/releases/tag/v0.3.0-beta.2`.
- The downloaded GitHub asset was 57,229,557 bytes and matched the local SHA-256 exactly.
