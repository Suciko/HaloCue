# Spine Face Semantic Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace component-heavy face labels with compact emotion and usage semantics, feed those semantics to the story model without hard triggers, and make every workbench preview use a shared image-difference crop that does not mutate Spine geometry.

**Architecture:** Keep the existing SQLite columns and asynchronous job reliability contracts, but expose `usage_hint_cn` as the canonical API field backed by the compatible `description_cn` column. Generate previews after all portraits are rendered so one role/skeleton gets one shared crop derived from aligned pixel differences, then render a compact two-field workbench and keep contact sheets internal to vision batching.

**Tech Stack:** Python 3, SQLite, Pillow, vanilla JavaScript, CSS, pytest, Node syntax checks, Playwright.

## Global Constraints

- Face selection semantics consist of `face_id`, `primary_emotion`, optional `usage_hint_cn`, and `confidence`.
- Usage hints describe suitable dialogue, attitude, reaction, or emotional stage; they never describe eyes, brows, mouth, blush, tears, or other visual parts.
- Usage hints guide the story model but never act as keyword triggers or mandatory selection rules.
- Duplicate emotions and duplicate usage hints across different face IDs are valid.
- Existing database columns and old records remain readable; no destructive migration is allowed.
- Manual overrides remain separate from AI values, survive model changes, and continue to win in `face_evidence`.
- Complete contact sheets and numbered vision sheets remain internal and are not appended to the normal workbench.
- Preview focus is image-driven and shared across the role's expressions; no branch may inspect face IDs 37-40, skeleton names, localized slot names, or attachment names.
- Preview generation does not change Spine attachment coordinates, dimensions, scale, source bundle, or runtime output.
- Existing four-worker cap, one-worker retry, partial/failed propagation, stale GET/PATCH guards, and same-face save serialization remain intact.
- Desktop, tablet, and mobile views must have no horizontal overflow, page-level double scrollbars, or controls outside their cards.

---

### Task 1: Compact Vision Label Contract

**Files:**
- Modify: `spine_face_labeler.py`
- Test: `tests/test_spine_face_labeler.py`

**Interfaces:**
- Produces: `usage_hint_cn(item: Mapping) -> str`, accepting new `usage_hint_cn` and legacy `description_cn` input.
- Changes: `FACE_SCHEMA` items require only `face_id`, `primary_emotion`, `usage_hint_cn`, and `confidence`.
- Changes: `label_face_images(...) -> list[dict]` accepts repeated semantic values while retaining face-ID completeness, confidence review, and per-item failure behavior.

- [ ] **Step 1: Write failing compact-schema tests**

Add tests that inspect `FACE_SCHEMA` and the provider request, then assert the model is required to return the compact fields and is not asked for component fields:

```python
def test_visual_schema_requests_selection_semantics_not_face_components():
    item = FACE_SCHEMA["properties"]["items"]["items"]
    assert set(item["required"]) == {
        "face_id", "primary_emotion", "usage_hint_cn", "confidence",
    }
    assert not ({"eyes", "brows", "mouth", "blush", "tears"} & set(item["properties"]))


def test_visual_labeler_allows_duplicate_emotion_and_usage(tmp_path):
    provider = CompactProvider([
        compact_label("00", "平静", "普通交谈或安静倾听"),
        compact_label("01", "平静", "普通交谈或安静倾听"),
    ])
    labels = label_face_images(provider, make_faces(tmp_path, ["00", "01"]))
    assert [item["primary_emotion"] for item in labels] == ["平静", "平静"]
```

Also assert the system/user prompt contains a prohibition against choosing from blush or tears and asks for usage context rather than visible-part narration.

- [ ] **Step 2: Run the compact-schema tests and confirm RED**

Run: `python -m pytest tests/test_spine_face_labeler.py -q`

Expected: FAIL because the current schema still requires component fields and rejects compact results.

- [ ] **Step 3: Implement the minimal compact contract**

Reduce `FACE_SCHEMA`, `_REQUIRED_FIELDS`, `_validate_label_item`, `_SYSTEM`, and the numbered-sheet request text to the four canonical fields. Add:

```python
def usage_hint_cn(item: Mapping) -> str:
    return str(item.get("usage_hint_cn") or item.get("description_cn") or "").strip()
```

Retain unknown/duplicate face-ID rejection, exact requested-ID coverage, confidence thresholds, individual review, stable ordering, and failure records. Do not add uniqueness checks on semantic values. Extra fields from a legacy provider may be ignored but must not be required.

- [ ] **Step 4: Run labeler tests and confirm GREEN**

Run: `python -m pytest tests/test_spine_face_labeler.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the compact label contract**

```bash
git add spine_face_labeler.py tests/test_spine_face_labeler.py
git commit -m "refactor: focus face labels on selection semantics"
```

### Task 2: Persist And Prompt With Usage Semantics

**Files:**
- Modify: `spine_face_labeler.py`
- Modify: `asset_catalog.py`
- Modify: `prompt.py`
- Test: `tests/test_spine_face_labeler.py`
- Test: `tests/test_face_evidence.py`
- Test: `tests/test_direction_feedback_rules.py`

**Interfaces:**
- Produces: `selection_semantics(primary_emotion: str, usage_hint: str) -> str` returning `emotion｜usage` or just `emotion`.
- Changes: visual label API records expose `usage_hint_cn` in `ai`, `manual`, and `effective`, while retaining `description_cn` as a read compatibility alias.
- Changes: PATCH accepts `usage_hint_cn`; the persisted compatible manual key remains `description_cn` so old and new clients share one override.
- Changes: `face_evidence.label_cn` stores effective selection semantics, not component details.

- [ ] **Step 1: Write failing compatibility and evidence tests**

Add tests showing new and legacy inputs persist to the same database column, manual usage survives reruns/model changes, and evidence includes the effective usage hint:

```python
def test_usage_hint_is_persisted_and_exposed_with_legacy_alias(tmp_path):
    persist_visual_face_labels(con, labels=[compact_label(
        "00", "平静", "普通交谈或安静倾听"
    )], **scope)
    record = list_visual_face_labels(con, **scope)[0]
    assert record["effective"]["usage_hint_cn"] == "普通交谈或安静倾听"
    assert record["effective"]["description_cn"] == "普通交谈或安静倾听"


def test_manual_usage_hint_updates_face_selection_evidence(tmp_path):
    saved = update_visual_face_label(
        con, face_id="00", patch={"usage_hint_cn": "压低情绪回应"},
        expected_version=1, **scope,
    )
    evidence = con.execute(
        "SELECT label_cn FROM face_evidence WHERE face_id='00' AND source LIKE 'vision:%'"
    ).fetchone()[0]
    assert evidence == "平静｜压低情绪回应"
```

Add a resource-prompt assertion that `build_resources` includes the combined semantics and the expression rules say visual phenomena such as blush/tears are not selection triggers.

- [ ] **Step 2: Run focused persistence and prompt tests and confirm RED**

Run: `python -m pytest tests/test_spine_face_labeler.py tests/test_face_evidence.py tests/test_direction_feedback_rules.py -q`

Expected: FAIL because `usage_hint_cn` is not an editable/effective field and `face_evidence` currently stores only the primary emotion.

- [ ] **Step 3: Implement compatible semantic persistence**

Map external `usage_hint_cn` to the existing `description_cn` column/manual JSON key. Reject a patch containing conflicting `usage_hint_cn` and `description_cn`. Return both names with equal values during the compatibility period. Build `face_evidence.label` and `label_cn` with:

```python
def selection_semantics(primary_emotion: str, usage_hint: str) -> str:
    emotion = str(primary_emotion or "").strip()
    hint = str(usage_hint or "").strip()
    return f"{emotion}｜{hint}" if emotion and hint else emotion or hint
```

Apply manual primary emotion and manual description before rebuilding evidence. Keep `raw` as the complete AI JSON for diagnostics.

- [ ] **Step 4: Add freedom-preserving story guidance**

Update the expression section in `prompt.py` to state that usage hints are recommendations, not keyword triggers; the model may reuse a fitting expression, may choose among duplicate semantics based on continuity, and must select the closest overall emotion when no perfect visual difference exists. Do not add component fields to the resource table.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_spine_face_labeler.py tests/test_face_evidence.py tests/test_direction_feedback_rules.py -q`

Expected: PASS.

- [ ] **Step 6: Commit semantic persistence and prompting**

```bash
git add spine_face_labeler.py asset_catalog.py prompt.py tests/test_spine_face_labeler.py tests/test_face_evidence.py tests/test_direction_feedback_rules.py
git commit -m "feat: guide expression choice with usage context"
```

### Task 3: Shared Image-Difference Preview Focus

**Files:**
- Modify: `spine_face_renderer.py`
- Test: `tests/test_spine_face_renderer.py`

**Interfaces:**
- Produces: `derive_shared_face_crop(paths: Sequence[Path]) -> tuple[int, int, int, int]` in source-image coordinates.
- Produces: `crop_face_previews(faces: Sequence[RenderedFace], *, size: int = 768) -> tuple[RenderedFace, ...]` that writes each existing `head_path` with one shared crop.
- Retains: `crop_head_preview(...)` as a single-image compatibility wrapper using the fallback path.
- Changes: render cache profile/version so old loose crops cannot be reused as new focused previews.

- [ ] **Step 1: Write failing shared-crop tests with synthetic portraits**

Build aligned RGBA images containing the same tall body and different small face marks. Assert that the crop is square, includes all changed marks with padding, is substantially narrower than the full portrait, and is identical for every output:

```python
def test_shared_face_crop_focuses_aligned_expression_differences(tmp_path):
    paths = make_aligned_portraits(tmp_path, changes=[(44, 38), (70, 42), (58, 55)])
    box = derive_shared_face_crop(paths)
    assert box[2] - box[0] == box[3] - box[1]
    assert box[2] - box[0] < 0.8 * 240
    assert all(point_is_inside(box, point) for point in [(44, 38), (70, 42), (58, 55)])


def test_shared_face_crop_falls_back_for_identical_or_mismatched_images(tmp_path):
    identical = make_identical_portraits(tmp_path, count=2)
    assert valid_square(derive_shared_face_crop(identical))
    mismatched = make_mismatched_portraits(tmp_path)
    assert valid_square(derive_shared_face_crop(mismatched))
```

Add a source inspection assertion that the crop implementation contains no specific face ID or skeleton-name branch.

- [ ] **Step 2: Run renderer tests and confirm RED**

Run: `python -m pytest tests/test_spine_face_renderer.py -q`

Expected: FAIL because the shared-crop APIs do not exist and each head is currently cropped independently from the full portrait width.

- [ ] **Step 3: Implement aligned image-difference focus**

Use Pillow only. Downsample aligned portraits for analysis, composite RGBA against a fixed neutral background, combine `ImageChops.difference` masks between the first valid portrait and the rest, threshold low compression/antialias noise, and map the resulting bounding box back to source coordinates. Expand around the difference region enough to include the head context, clamp or transparently pad a square crop, and use the same square for all faces.

If fewer than two usable aligned images exist, the difference mask is empty, or sizes differ, derive a square from upper-body alpha distribution. The fallback must not depend on slot or attachment names. Do not modify source portraits.

- [ ] **Step 4: Integrate shared cropping after rendering**

Make render workers produce/copy portraits. After cached and newly rendered portraits are ordered, call `crop_face_previews` once before validation and manifest write. Ensure retry order, progress, `actual_workers`, calibration, and cache checks remain unchanged. Bump the render profile/cache version so stale head crops are regenerated.

- [ ] **Step 5: Run renderer tests and confirm GREEN**

Run: `python -m pytest tests/test_spine_face_renderer.py -q`

Expected: PASS.

- [ ] **Step 6: Commit shared preview focus**

```bash
git add spine_face_renderer.py tests/test_spine_face_renderer.py
git commit -m "fix: focus face previews on shared expression changes"
```

### Task 4: Remove Contact Sheet From Normal Results

**Files:**
- Modify: `spine_face_analysis.py`
- Modify: `webui.py`
- Modify: `js/library_faces.js`
- Test: `tests/test_spine_face_analysis.py`
- Test: `tests/test_asset_library.py`
- Test: `tests/test_ui_asset_library.py`

**Interfaces:**
- Changes: `analyze_character_faces(...)` does not create or return `contact_sheet`.
- Changes: public face-job snapshots do not expose `contact_sheet_available` for successful normal workbench jobs.
- Changes: `FaceWorkspace.renderJob(...)` never reveals or loads a completed contact sheet.

- [ ] **Step 1: Write failing absence tests**

Assert analysis succeeds without creating `contact-sheet.jpg`, sanitized snapshots omit availability, and the frontend source has no completed-job branch that assigns the sheet URL:

```python
def test_analysis_keeps_contact_sheets_out_of_normal_results(tmp_path, fake_report):
    result = analyze_character_faces(...)
    assert "contact_sheet" not in result
    assert not (fake_report.cache_dir / "contact-sheet.jpg").exists()
```

Update the existing UI structure test to require the internal sheet element to remain absent or permanently hidden from the face workspace.

- [ ] **Step 2: Run analysis/API/UI tests and confirm RED**

Run: `python -m pytest tests/test_spine_face_analysis.py tests/test_asset_library.py tests/test_ui_asset_library.py -q`

Expected: FAIL because analysis currently always builds the sheet and the frontend reveals it after completion.

- [ ] **Step 3: Remove normal contact-sheet generation and display**

Delete the `make_contact_sheet` import/call from analysis, remove the public availability field and endpoint dependency used only by the workbench, and remove the frontend completion branch. Keep `make_vision_sheet` and numbered 3x3 batching intact because they remain internal model inputs.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_spine_face_analysis.py tests/test_asset_library.py tests/test_ui_asset_library.py -q`

Expected: PASS.

- [ ] **Step 5: Commit normal-result cleanup**

```bash
git add spine_face_analysis.py webui.py js/library_faces.js tests/test_spine_face_analysis.py tests/test_asset_library.py tests/test_ui_asset_library.py
git commit -m "fix: keep face contact sheets internal"
```

### Task 5: Compact Two-Field Face Workbench

**Files:**
- Modify: `js/library_faces.js`
- Modify: `css/layout.css`
- Test: `tests/test_ui_asset_library.py`
- Test: `tests/test_ui_asset_workbench_responsive.py`

**Interfaces:**
- Consumes: `face.effective.primary_emotion`, `face.effective.usage_hint_cn`, confidence, version, and preview URL.
- Produces: PATCH payload containing only changed `primary_emotion` and/or `usage_hint_cn`.
- Retains: page generation/role/signature guards and per-face save queue behavior.

- [ ] **Step 1: Write failing compact-card and editor tests**

Update DOM/runtime fixtures to assert cards display emotion and usage, omit component labels, and save only the two canonical fields:

```python
def test_face_workspace_renders_selection_semantics_only():
    source = read("js/library_faces.js")
    assert "usage_hint_cn" in source
    for removed in ("['眼睛'", "['眉毛'", "['嘴部'", "['脸红'", "['泪水'"):
        assert removed not in source
```

The JavaScript save-serialization test must retain its existing stale-role and same-face queue assertions while changing its mock inputs to `primary_emotion` and `usage_hint_cn`.

- [ ] **Step 2: Run UI tests and confirm RED**

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py -q`

Expected: FAIL because cards and editors still render all component details and use `description_cn`.

- [ ] **Step 3: Implement compact cards and editor**

Render preview, ID, emotion, one wrapping usage line, and only a low-confidence/manual marker. The inline editor contains one text input and one short textarea. Preserve edit, save, restore-AI, optimistic version, stale response guards, and queued save behavior. Do not show a percentage on every card unless it is below the existing review threshold.

- [ ] **Step 4: Tighten stable preview and responsive CSS**

Keep the existing 4/3/2/1 responsive grid, give the image area a stable square aspect ratio, and make the newly focused PNG use available space without creating layout shifts. Remove obsolete detail-list/check-field styles. Verify long Chinese emotion/usage text wraps within the card and editor controls retain usable touch height.

- [ ] **Step 5: Run UI tests and syntax check**

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py -q`

Run: `node --check js/library_faces.js`

Expected: all PASS.

- [ ] **Step 6: Commit compact workbench UI**

```bash
git add js/library_faces.js css/layout.css tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py
git commit -m "refactor: streamline face labeling cards"
```

### Task 6: End-To-End Verification

**Files:**
- Modify only when a verified defect is reproduced by a failing test.
- Test: existing Python, JavaScript syntax, and Playwright suites.

**Interfaces:**
- Consumes all prior tasks and produces verification evidence only.

- [ ] **Step 1: Run the focused backend suite**

Run:

```bash
python -m pytest tests/test_spine_face_labeler.py tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py tests/test_face_evidence.py tests/test_asset_library.py tests/test_direction_feedback_rules.py -q
```

Expected: PASS with no warnings caused by the change.

- [ ] **Step 2: Run the UI and responsive suite**

Run:

```bash
python -m pytest tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the complete automated suite**

Run: `python -m pytest -q`

Expected: all tests pass; existing documented skips may remain.

- [ ] **Step 4: Run Python and JavaScript static checks**

Run:

```bash
python -m compileall assetdb.py asset_catalog.py spine_face_labeler.py spine_face_renderer.py spine_face_analysis.py webui.py prompt.py
node --check js/app.js
node --check js/library.js
node --check js/library_faces.js
node --check js/library_preview.js
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Verify the real workbench at required viewports**

Start the current `main` server on an unused port after confirming process ownership. With Playwright, inspect 1440x900, 900x900, 390x844, and 360x800. Assert no horizontal overflow or page-level double scrollbars; return action remains on the right; task UI remains a desktop right drawer/mobile bottom panel; cards show only the compact semantics; previews fill their frames; editor controls stay inside the card. Restore the previous browser viewport after verification.

- [ ] **Step 6: Inspect representative focused previews**

Regenerate the current sample through the generic render path, compare shared crop boxes for expressions 36-41, and visually confirm the face area is larger without changing relative attachment geometry. Record that 37-40 use the same generic crop and contain no ID-specific correction.

- [ ] **Step 7: Commit only verified follow-up fixes**

If verification exposes a defect, add a failing regression test, implement the minimal fix, rerun the affected focused suite and full checks, then commit only those files. If no defect is found, do not create an empty commit.
