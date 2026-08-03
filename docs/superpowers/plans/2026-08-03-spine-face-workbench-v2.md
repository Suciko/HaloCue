# Spine Face Workbench V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fast, responsive Spine face labeling workflow whose render, AI, database, catalog, editing, and task feedback states stay consistent.

**Architecture:** Keep `FACE_JOB` as in-memory execution state, add focused database helpers as the persisted fact source, and expose browser-safe label/preview/edit endpoints. Render at bounded concurrency, send numbered 3x3 batches to vision providers, and render the workbench from per-face cards rather than a full contact sheet.

**Tech Stack:** Python 3, SQLite, Pillow, Spine 3.8 CLI, vanilla JavaScript, CSS container/media queries, pytest, Node syntax checks, Playwright.

## Global Constraints

- Default Spine render concurrency is 4 and never exceeds 4.
- Vision requests contain at most one numbered 3x3 sheet with 9 faces; the full contact sheet is never sent to the model.
- Low-confidence or invalid batch items are retried individually.
- Manual labels are stored separately from AI labels and are never overwritten by reruns.
- Attachment handling is type-driven; no face ID or skeleton-specific fix is allowed.
- Unknown counts display as pending/unknown, never as a misleading numeric zero.
- Desktop, tablet, and mobile layouts must not create a second page scrollbar.

---

### Task 1: Persisted Label Records And Manual Overrides

**Files:**
- Modify: `assetdb.py`
- Modify: `spine_face_labeler.py`
- Test: `tests/test_spine_face_labeler.py`
- Test: `tests/test_face_evidence.py`

**Interfaces:**
- Produces: `list_visual_face_labels(con, *, ident, spine_signature, outfit_key) -> list[dict]`
- Produces: `update_visual_face_label(con, *, ident, spine_signature, outfit_key, face_id, patch, expected_version) -> dict`
- Produces: `_update_visual_face_label_row(con, ident, spine_signature, outfit_key, face_id, patch, expected_version) -> dict` as the transactional optimistic-lock implementation
- Produces: `persist_visual_face_labels(con, *, ident: str, spine_signature: str, outfit_key: str, model: str, labels: Iterable[dict]) -> dict` with `saved_count`, `failed_count`, and `completed_at`

- [ ] **Step 1: Write failing migration and repository tests**

```python
def test_manual_override_survives_visual_rerun(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    # Persist AI label, manually change primary_emotion, rerun AI persistence.
    # The query helper must return ai_primary_emotion and manual_primary_emotion separately.
    assert row["effective_primary_emotion"] == "人工修正"
    assert row["version"] == 2
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `pytest tests/test_spine_face_labeler.py tests/test_face_evidence.py -q`

Expected: FAIL because override columns and repository helpers do not exist.

- [ ] **Step 3: Add additive SQLite migration and repository helpers**

Add `manual_json`, `version`, and `updated_at` columns to `face_visual_label` through idempotent migration. Parse JSON safely, validate patch keys against `primary_emotion`, `secondary_emotions`, `valence`, `arousal`, `eyes`, `brows`, `mouth`, `blush`, `tears`, and `description_cn`, and update with `WHERE version=?` optimistic locking.

```python
ALLOWED_MANUAL_FACE_FIELDS = frozenset({
    "primary_emotion", "secondary_emotions", "valence", "arousal",
    "eyes", "brows", "mouth", "blush", "tears", "description_cn",
})

def update_visual_face_label(
    con, *, ident: str, spine_signature: str, outfit_key: str,
    face_id: str, patch: dict, expected_version: int,
) -> dict:
    unknown = set(patch) - ALLOWED_MANUAL_FACE_FIELDS
    if unknown:
        raise ValueError(f"不支持的标注字段：{sorted(unknown)}")
    return _update_visual_face_label_row(
        con, ident, spine_signature, outfit_key, face_id, patch, expected_version
    )
```

- [ ] **Step 4: Return persistence evidence without overwriting manual JSON**

Change `persist_visual_face_labels` to return exact saved/failed counts and completion time while retaining `manual_json`, `version`, and `updated_at` on conflict.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_spine_face_labeler.py tests/test_face_evidence.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add assetdb.py spine_face_labeler.py tests/test_spine_face_labeler.py tests/test_face_evidence.py
git commit -m "feat: persist editable face labels"
```

### Task 2: Numbered 3x3 Vision Batches

**Files:**
- Modify: `spine_face_labeler.py`
- Modify: `spine_face_analysis.py`
- Test: `tests/test_spine_face_labeler.py`
- Test: `tests/test_spine_face_analysis.py`

**Interfaces:**
- Produces: `make_vision_sheet(faces, *, cell_size=384, columns=3) -> tuple[bytes, list[str]]`
- Changes: `label_face_images(provider, faces: Sequence[RenderedFace], *, batch_size=9, batch_workers=2, confidence_threshold=0.6, semantic_hints=None, max_attempts=3, progress=None) -> list[dict]`

- [ ] **Step 1: Write failing sheet and batching tests**

```python
@pytest.mark.parametrize((count, calls), [(1, 1), (9, 1), (10, 2)])
def test_visual_labeler_sends_numbered_nine_face_sheets(tmp_path, count, calls):
    labels = label_face_images(provider, faces[:count])
    assert len(provider.calls) == calls
    assert all(len(call.images) == 1 for call in provider.calls)
    assert labels == sorted(labels, key=lambda item: item["face_id"])
```

- [ ] **Step 2: Run tests and verify old multi-image behavior fails**

Run: `pytest tests/test_spine_face_labeler.py -q`

Expected: FAIL because the provider currently receives 8 individual JPEGs.

- [ ] **Step 3: Implement numbered sheet generation**

Use Pillow to place up to 9 RGBA previews in a 3x3 image, reserve a high-contrast label strip inside each cell, and encode a single JPEG. Return stable IDs separately so validation never depends on OCR.

- [ ] **Step 4: Add bounded batch concurrency and single-item review**

Use `ThreadPoolExecutor(max_workers=min(batch_workers, 2))`; preserve batch and face ordering after futures complete. Retry only incomplete/low-confidence face IDs as single-image sheets and reject duplicate or unknown IDs.

- [ ] **Step 5: Expose batch progress through analysis**

Add labeling progress callbacks carrying completed faces, total faces, batch count, and review count. Keep provider calls isolated from render workers.

- [ ] **Step 6: Run focused tests and commit**

Run: `pytest tests/test_spine_face_labeler.py tests/test_spine_face_analysis.py -q`

```bash
git add spine_face_labeler.py spine_face_analysis.py tests/test_spine_face_labeler.py tests/test_spine_face_analysis.py
git commit -m "feat: label faces in numbered nine-grid batches"
```

### Task 3: Generic Attachment Restoration And Render Validation

**Files:**
- Modify: `spine_face_renderer.py`
- Test: `tests/test_spine_face_renderer.py`

**Interfaces:**
- Produces: `restore_attachment_images(skeleton_json, images_root, atlas_metadata=None) -> list[dict]`
- Produces: `validate_rendered_face(face: RenderedFace) -> dict`
- Extends: `RenderReport` with `calibration: Sequence[dict]`, where each item contains `face_id`, `status`, `attachment`, `slot`, and `reason`

- [ ] **Step 1: Write failing region, mesh, and unsupported metadata tests**

```python
def test_attachment_restore_preserves_region_trim_and_mesh_uv(tmp_path):
    diagnostics = restore_attachment_images(skeleton, images, atlas)
    assert diagnostics[0]["status"] == "restored"
    assert diagnostics[1]["type"] == "mesh"
    assert diagnostics[1]["status"] != "silently_resized"
```

Also add a generic fixture containing animations `37` through `40` and assert no branch inspects those IDs.

- [ ] **Step 2: Run renderer tests and verify failure**

Run: `pytest tests/test_spine_face_renderer.py -q`

Expected: FAIL because mesh restoration and calibration diagnostics are absent.

- [ ] **Step 3: Parse atlas transforms and dispatch by attachment type**

Replace `restore_region_attachment_images` with a compatibility wrapper around `restore_attachment_images`. Region handling applies original size, offset, trim, and rotation. Mesh handling preserves UV/vertex geometry and only restores source texture dimensions when metadata proves the mapping; otherwise return `needs_manual_calibration`.

- [ ] **Step 4: Validate every rendered preview**

Calculate alpha bounds, visible coverage, head bounds, and stability metadata. Mark invalid or unsupported outputs in `RenderReport.calibration` while returning valid faces.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_spine_face_renderer.py -q`

```bash
git add spine_face_renderer.py tests/test_spine_face_renderer.py
git commit -m "fix: restore spine attachments by geometry"
```

### Task 4: Adaptive Four-Worker Rendering And Job Persistence State

**Files:**
- Modify: `spine_face_renderer.py`
- Modify: `spine_face_analysis.py`
- Modify: `webui.py`
- Test: `tests/test_spine_face_renderer.py`
- Test: `tests/test_spine_face_analysis.py`
- Test: `tests/test_asset_library.py`

**Interfaces:**
- Changes: default render workers to 4 with a hard maximum of 4
- Produces: job phases `queued`, `rendering`, `labeling`, `persisting`, `complete`, `partial`, `failed`
- Produces: job result fields `saved_count`, `failed_count`, `completed_at`, `actual_workers`, and `calibration`

- [ ] **Step 1: Write failing worker-cap and job-transition tests**

```python
def test_renderer_caps_workers_at_four_and_preserves_result_order(tmp_path, render_source, tracking_runner):
    report = render_face_variations(
        render_source,
        spine_cli=tmp_path / "Spine.com",
        cache_root=tmp_path / "cache",
        face_ids=["04", "01", "03", "02", "00"],
        workers=12,
        runner=tracking_runner,
    )
    assert tracking_runner.peak <= 4
    assert [face.face_id for face in report.faces] == ["00", "01", "02", "03", "04"]
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py tests/test_asset_library.py -q`

- [ ] **Step 3: Implement hard cap, cache-aware scheduling, and one-step fallback**

Start at `min(max(1, workers), 4)`. Cached faces bypass the executor. If a concurrent Spine export fails with a process/resource error, retry failed faces once with one worker and include retry evidence in the report.

- [ ] **Step 4: Publish exact persistence and calibration state**

Make `spine_face_analysis` enter `persisting` before database writes and return exact saved/failed counts. Sanitize the expanded result in `face_job_snapshot` without exposing local paths.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py tests/test_asset_library.py -q`

```bash
git add spine_face_renderer.py spine_face_analysis.py webui.py tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py tests/test_asset_library.py
git commit -m "feat: publish adaptive face job progress"
```

### Task 5: Label Read, Preview, Edit, And Catalog Synchronization APIs

**Files:**
- Modify: `asset_catalog.py`
- Modify: `webui.py`
- Test: `tests/test_asset_library.py`

**Interfaces:**
- Adds: `GET /api/assets/faces/labels?aa_key=&sha256=`
- Adds: `GET /api/assets/faces/preview?aa_key=&sha256=&face_id=`
- Adds: `PATCH /api/assets/faces/labels/{face_id}`
- Produces: `face_labels_payload(con, *, aa_key: str, sha256: str) -> dict`
- Changes: character `details` to include nullable `file_count`, `face_count`, `labeled_count`, `expression_status`, and `labels_updated_at`

- [ ] **Step 1: Write failing API security and synchronization tests**

```python
def test_face_labels_payload_returns_tokens_and_effective_values(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    seed_registered_character_and_label(con, tmp_path)
    payload = webui.face_labels_payload(con, aa_key="626652156", sha256="abc123")
    assert payload["faces"][0]["preview_url"].startswith("/api/assets/faces/preview?")
    assert "head_path" not in json.dumps(payload)
```

Add stale-version PATCH, invalid face ID, traversal, missing preview, unknown count, and post-job catalog refresh cases.

- [ ] **Step 2: Run API tests and verify routes are missing**

Run: `pytest tests/test_asset_library.py -q`

- [ ] **Step 3: Implement scoped target resolution and safe preview streaming**

Reuse `library_character_analysis_target`; resolve paths server-side and require the requested face to belong to the exact signature/outfit. Return only a URL token to the browser and use an image MIME type allowlist.

- [ ] **Step 4: Implement PATCH and catalog counts**

Validate JSON field types and optimistic version, call `update_visual_face_label`, and return save evidence. Join persisted labels into catalog details; use `None` plus `expression_status="pending"` for unknown values.

- [ ] **Step 5: Run focused tests and commit**

Run: `pytest tests/test_asset_library.py -q`

```bash
git add asset_catalog.py webui.py tests/test_asset_library.py
git commit -m "feat: expose editable face label records"
```

### Task 6: Responsive Face Cards, Task Drawer, And Navigation

**Files:**
- Modify: `index.html`
- Modify: `js/library.js`
- Modify: `js/library_preview.js`
- Modify: `js/library_faces.js`
- Modify: `css/layout.css`
- Test: `tests/test_ui_asset_library.py`
- Test: `tests/test_ui_asset_workbench_responsive.py`

**Interfaces:**
- Consumes: Task 4 job fields and Task 5 label/preview/edit APIs
- Produces: card actions `edit`, `save`, `restore-ai`, and task drawer action `toggle-tasks`

- [ ] **Step 1: Write failing DOM behavior tests**

Test that completed jobs display rendered/labeled/saved counts and saved time; cards contain the preview, ID, emotion, confidence, facial details, and edit action; PATCH updates saved status; catalog refreshes after completion; unknown counts render text rather than `0`.

- [ ] **Step 2: Run UI unit tests and verify failure**

Run: `pytest tests/test_ui_asset_library.py -q`

- [ ] **Step 3: Replace contact-sheet/label split with cards and editor**

Render one accessible article per face with stable dimensions. Keep the contact sheet only as an optional debug download. Open an inline desktop detail panel or mobile bottom sheet; save only changed fields and surface stale-version errors without discarding edits.

- [ ] **Step 4: Rework navigation and task drawer**

Move “返回目录” to the detail header's right side. Make “当前任务” open a right drawer on desktop and a bottom sheet on mobile, including queue, phase, progress, save counts, failures, and “查看标注”.

- [ ] **Step 5: Add responsive CSS and scrollbar ownership**

Use 4/3/2/1 card columns at desktop/tablet/mobile/narrow widths. Set the page shell to `overflow:hidden`; assign scrolling only to catalog, details/cards, and task drawer. Ensure controls have fixed minimum sizes and text wraps without overlap.

- [ ] **Step 6: Run UI tests, syntax checks, and commit**

Run: `pytest tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py -q`

Run: `node --check js/library.js && node --check js/library_faces.js && node --check js/library_preview.js`

```bash
git add index.html js/library.js js/library_preview.js js/library_faces.js css/layout.css tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py
git commit -m "feat: rebuild face labeling workbench"
```

### Task 7: End-To-End Verification And Performance Evidence

**Files:**
- Modify only when a verified defect is found in Tasks 1-6
- Test: existing full test suite and Playwright flows

**Interfaces:**
- Consumes all prior tasks; produces verification evidence only.

- [ ] **Step 1: Run the full automated suite**

Run: `pytest -q`

Expected: all existing and new tests pass; existing skips remain documented.

- [ ] **Step 2: Run static checks**

Run: `node --check js/app.js`

Run: `node --check js/library.js`

Run: `node --check js/library_faces.js`

Run: `git diff --check`

- [ ] **Step 3: Start the current branch server and verify desktop/mobile flows**

Open the material workbench at 1440x900, 900x900, 390x844, and 360x800. Confirm one page scrollbar owner, readable cards, the right-side desktop return button, mobile top return action, task drawer/bottom sheet, save feedback, and no text overlap.

- [ ] **Step 4: Measure representative render and labeling batches**

Record actual worker count, render duration, number of nine-grid requests, individual reviews, saved records, and calibration failures for the user's skeleton. Verify animations 37-40 through the same generic path as all other IDs.

- [ ] **Step 5: Commit verification fixes if any**

If verification required code changes, run:

```bash
git add assetdb.py asset_catalog.py spine_face_labeler.py spine_face_analysis.py spine_face_renderer.py webui.py index.html js/library.js js/library_preview.js js/library_faces.js css/layout.css tests
git commit -m "fix: close face workbench verification gaps"
```

If verification required no code changes, do not create an empty commit.
