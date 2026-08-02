# AA Custom Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, idempotent pipeline that discovers, validates, registers, constrains, and verifies official and custom AA backgrounds, sound effects, and Spine characters.

**Architecture:** Treat `E:\AzureArchive\资源文件` plus its Addressables catalog as the authoritative official-resource cache, and treat global/project `manifest.json` files as AA override registries. Keep user-authored character identifiers opaque and required. Store validated source assets in the tool catalog, then materialize only selected assets into project-private directories and manifests.

**Tech Stack:** Python 3, pytest, Pillow, ffprobe/ffmpeg, UnityPy, SQLite, AA `.aap` JSON and override manifests.

## Global Constraints

- Never delete, move, or overwrite original assets.
- Tests and real imports use `D:\桌面\蔚蓝档案二创\AA自动写剧本文件\04-素材机制实验`.
- Do not modify `E:\AzureArchive\存储文件\data\overrides\manifest.json` during project-private tests.
- Character `Identifier` is user-supplied, opaque, required, and persisted verbatim.
- Official IDs come from AA/game tables or existing indexes; only custom background IDs are calculated as xxHash32 of the exact UTF-8 filename stem.
- The model may select only assets whose status is `registered` or `verified`.
- Existing camera projects and official indexes must remain byte-identical unless a test explicitly targets a copied fixture.
- This directory has no Git repository; replace commit steps with passing tests plus a SHA-256 checkpoint of changed files.

---

### Task 1: Official Resource Cache Discovery

**Files:**
- Create: `aa_resource_cache.py`
- Test: `tests/test_aa_resource_cache.py`
- Modify: `aapaths.py`

**Interfaces:**
- Produces: `ResourceCacheLayout`, `detect_resource_cache()`, `iter_cached_bundles()`, `inspect_cached_bundle()`.
- Consumes: AA executable path, workspace path, optional explicit cache/catalog paths.

- [ ] **Step 1: Write failing cache-layout tests**

```python
def test_iter_cached_bundles_recognizes_unity_cache_layout(tmp_path):
    data = tmp_path / "outer" / "inner" / "__data"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"UnityFS" + b"\0" * 16)
    bundles = list(iter_cached_bundles(tmp_path))
    assert bundles[0].data_path == data
    assert bundles[0].outer_hash == "outer"
    assert bundles[0].content_hash == "inner"
```

- [ ] **Step 2: Run the focused test and confirm import failure**

Run: `python -m pytest tests/test_aa_resource_cache.py -q`

Expected: FAIL because `aa_resource_cache` does not exist.

- [ ] **Step 3: Implement read-only cache discovery**

Implement exact three-level recognition `<cache>/<outer>/<content>/__data`, reject non-`UnityFS` files, and expose the bundled and downloaded Addressables catalog paths without scanning bundle contents by default.

- [ ] **Step 4: Add a real read-only smoke test**

Assert the current cache yields at least 13,000 bundles and that the known FlatData bundle can be opened by UnityPy and contains `scenariobgeffectexceltable`.

- [ ] **Step 5: Run tests and record a checkpoint**

Run: `python -m pytest tests/test_aa_resource_cache.py -q`

Record SHA-256 for `aa_resource_cache.py`, `aapaths.py`, and the test.

### Task 2: Asset Models and Validation

**Files:**
- Create: `asset_models.py`
- Create: `asset_validation.py`
- Test: `tests/test_asset_validation.py`

**Interfaces:**
- Produces: `AssetCandidate`, `ValidationIssue`, `ValidationResult`, `validate_background()`, `validate_sound()`, `validate_spine()`.
- Spine validation consumes a required `identifier: str`; it never generates one.

- [ ] **Step 1: Write failing tests for background validation**

Test RGB/RGBA PNG, RGB JPEG, empty stem, same-scope casefold conflict, and a hand-checked custom background hash literal.

- [ ] **Step 2: Verify background tests fail for missing implementation**

Run: `python -m pytest tests/test_asset_validation.py -k background -q`

- [ ] **Step 3: Implement background validation**

Return exact stem, width, height, mode, SHA-256, and uint32 AA key. Reject unreadable images, CMYK/unsupported modes, empty names, and detected same-scope naming conflicts.

- [ ] **Step 4: Write failing sound tests**

Use generated fixture WAV headers to test PCM16 acceptance, incompatible codec reporting, empty stem, and collision detection. Assert the AA reference is the exact filename stem.

- [ ] **Step 5: Implement ffprobe-based sound validation**

Accept only verified PCM16 WAV for installation in the first release. Report codec, sample rate, channels, bit depth, duration, and a deterministic transcode recommendation for other inputs.

- [ ] **Step 6: Write failing Spine closure tests**

Cover missing `.skel`, `.atlas`, atlas page texture, `-avatar.png`, empty user identifier, and a valid four-file bundle. Assert the atlas page name is matched exactly.

- [ ] **Step 7: Implement Spine closure and version inspection**

Require the user identifier verbatim, parse every atlas page, detect the Spine version string from `.skel`, and report expression discovery as `known`, `observed`, or `unresolved` rather than inventing face IDs.

- [ ] **Step 8: Run all validation tests**

Run: `python -m pytest tests/test_asset_validation.py -q`

### Task 3: Idempotent Project-Private Registry

**Files:**
- Create: `aa_registry.py`
- Test: `tests/test_aa_registry.py`

**Interfaces:**
- Produces: `register_background()`, `register_sound()`, `register_character()`, `load_manifest()`, `write_manifest_atomic()`.
- Consumes only successful `ValidationResult` objects.

- [ ] **Step 1: Write failing background registry tests**

Assert the file is copied to `bgs`, the relative path appears once in `BgOverrides`, the source remains unchanged, and a second registration produces no manifest or file change.

- [ ] **Step 2: Implement atomic background registration**

Write a temporary manifest in the same directory, parse it back, then replace the target. Preserve unrelated keys and ordering semantics.

- [ ] **Step 3: Write failing sound registry tests**

Assert the file is copied to `sounds`, `SoundOverrides` contains one relative path, and `.aap` must reference only its stem.

- [ ] **Step 4: Implement sound registration**

Reject a different file with the same casefolded stem and report both source paths.

- [ ] **Step 5: Write failing character registry tests**

Assert all Spine files are copied under `characters/<user identifier>`, manifest paths omit extensions, display name may repeat, and reusing the same identifier with different content is rejected.

- [ ] **Step 6: Implement character registration**

Persist `Identifier` exactly as supplied. Never hash, normalize, randomize, or infer it.

- [ ] **Step 7: Run registry tests**

Run: `python -m pytest tests/test_aa_registry.py -q`

### Task 4: Catalog and Model Constraints

**Files:**
- Create: `asset_catalog.py`
- Test: `tests/test_asset_catalog.py`
- Modify: `assetdb.py`
- Modify: `build_index.py`
- Modify: `annotate.py`

**Interfaces:**
- Produces catalog rows with `kind`, `source_path`, `sha256`, `aa_key`, `scope`, `install_path`, `status`, `error`, and Chinese labels.
- Exports only `registered` and `verified` assets into model whitelists.

- [ ] **Step 1: Write failing migration and whitelist tests**

Create a copy of the legacy database, migrate it, and assert unregistered rows cannot appear in exported constraints.

- [ ] **Step 2: Implement additive schema migration**

Do not destroy legacy tables or labels. Add installation and validation metadata with explicit schema versioning.

- [ ] **Step 3: Correct background index behavior**

Preserve official observed/table IDs; compute missing IDs only for manifest-registered custom files. Store provenance.

- [ ] **Step 4: Correct face and sound constraints**

An empty face allowlist rejects face changes. A sound name without a registered physical source cannot be emitted as a custom sound.

- [ ] **Step 5: Run catalog tests and legacy index smoke tests**

Run: `python -m pytest tests/test_asset_catalog.py -q`

### Task 5: Generator and Project Verification Integration

**Files:**
- Modify: `script2aap.py`
- Modify: `verify.py`
- Test: `tests/test_project_asset_integration.py`

**Interfaces:**
- `script2aap` resolves catalog records and delegates all copying/manifest work to `aa_registry`.
- `verify_project_assets(aap_path, project_dir)` returns structured errors and warnings.

- [ ] **Step 1: Write a failing combined-project test**

Build a fixture `.aap` containing one custom background, one custom sound stem, and one custom character ID. Assert every reference resolves through the manifest to a real file.

- [ ] **Step 2: Implement generator delegation**

Remove custom copy loops from the generator path and call the registry interfaces. Preserve existing official-asset behavior.

- [ ] **Step 3: Implement reference-closure verification**

Check background hash/stem, sound stem/path, character identifier, atlas pages, avatar, known face IDs, and manifest duplicates.

- [ ] **Step 4: Run the full automated suite**

Run: `python -m pytest -q`

### Task 6: Web Import Status

**Files:**
- Modify: `webui.py`
- Modify: `ui.html`
- Test: `tests/test_web_asset_api.py`

**Interfaces:**
- Adds read-only discovery/validation endpoints and an explicit project-private registration action.

- [ ] **Step 1: Write failing API behavior tests**

Assert discovery never writes, validation returns structured issues, registration requires an explicit target project, and character import requires an identifier.

- [ ] **Step 2: Implement API and status UI**

Show source preview, AA key/identifier, validation state, target path, manifest state, and actionable error text.

- [ ] **Step 3: Run web API tests**

Run: `python -m pytest tests/test_web_asset_api.py -q`

### Task 7: Real AA Differential Experiments

**Files:**
- Create under experiment root: background-only, sound-only, character-only, and combined AA projects.
- Create: `docs/custom-assets-test-report.md`

**Interfaces:**
- Consumes the completed importer and existing real assets.
- Produces reproducible input paths, output paths, hashes, AA logs, screenshots/status, and restart/idempotency results.

- [ ] **Step 1: Capture immutable baseline**

Hash global manifest, official indexes, and the camera-version chapter 1/2 projects. Record AA process state and relevant paths.

- [ ] **Step 2: Test one existing custom background**

Copy `ChatGPT Image 2026年7月19日 01_00_25.png`, register it project-privately, generate a minimal `.aap`, open it in AA, preview, compile, and record `.aas` plus log evidence.

- [ ] **Step 3: Test one project-private custom sound**

Copy `SE_Gear_06.wav` under a unique experimental stem, register it in `SoundOverrides`, play it in AA, and record audio/log evidence.

- [ ] **Step 4: Test the original Kai skeleton**

Copy `CH0335_noweapon_spr`, use the user identifier `1516544`, show the character speaking, change from face `00` to `03`, and execute an already observed action.

- [ ] **Step 5: Test the combined project and restart**

Preview and compile all three custom asset types together, exit AA, restart it, and repeat preview.

- [ ] **Step 6: Test idempotency and failures**

Run import twice, then use copied fixtures to test rename, missing atlas texture, same identifier with different content, same stem with different sound content, and incompatible audio.

- [ ] **Step 7: Verify no regressions**

Recompute all baseline hashes, run `python -m pytest -q`, and document every confirmed result, failure, and remaining uncertainty.
