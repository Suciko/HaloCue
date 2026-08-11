# Android 0.3.0-beta.1 Release Checklist

**Goal:** Produce the first signed, distributable Android beta without deleting the existing debug installation or its data.

- [x] Set `versionCode = 4` and `versionName = "0.3.0-beta.1"`.
- [x] Create a private 4096-bit RSA signing key outside the repository and load its credentials only from ignored `local.properties`.
- [x] Build `assembleRelease`; Android lint vital and signing validation passed.
- [x] Verify APK package `com.halocue.android`, target SDK 36, and `arm64-v8a` native ABI.
- [x] Add a side-by-side `deviceBeta` acceptance variant so the existing 152 MB debug workspace was not removed.
- [x] Install and cold-start the release-derived acceptance build on vivo `V2324HA`, Android 16 / API 36.
- [x] Run direct device instrumentation against the release-derived target: `OK (30 tests)` in 4.562 seconds.
- [x] Run the complete Android Python suite: 92 passed, 1 skipped.
- [x] Run focused release/UI contracts: 9 passed.
- [x] Capture `evidence/halocue-beta-release-device.png` and visually verify the first screen.
- [x] Package and hash `构建产物/HaloCue-Android-0.3.0-beta.1-arm64-v8a.apk`.
- [x] Publish GitHub pre-release `v0.3.0-beta.1` in `Suciko/HaloCue` and download the uploaded APK for an independent hash check.

## Result

- APK size: 57,229,553 bytes.
- APK SHA-256: `77405A3F279C34131E88FD9FA9CAECD4F7E90CB2811329018A127CCB44861891`.
- Certificate SHA-256: `BF0A5C4DD4114B0AB48FC79D0B41C56CA49A324F3FE27C019BA80B5FFC7ACB09`.
- GitHub release: `https://github.com/Suciko/HaloCue/releases/tag/v0.3.0-beta.1`.
- The downloaded GitHub asset was 57,229,553 bytes and matched the local SHA-256 exactly.
- Deferred by scope: Spine real-time rendering, automatic writes into AA private storage, and non-arm64 packages.
