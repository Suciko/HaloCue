# Spine Face Preview Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every completed render immediately supplies the current face previews, keep preview GET requests read-only after startup migration, and simplify the optional full AI relabel action.

**Architecture:** Rendering and visual labeling remain separate stages. A small label-store operation refreshes preview paths for all existing model rows before any provider-dependent return, while versioned preview URLs invalidate browser cache. Database migration gets a serialized version gate and connections get a finite busy timeout; the UI exposes force relabel only as a secondary action after saved results exist.

**Tech Stack:** Python 3, SQLite, stdlib `http.server`, vanilla JavaScript, pytest, Node syntax checks.

## Global Constraints

- Do not special-case face IDs 37-40 or modify their attachment geometry.
- Updating a preview path must preserve AI label fields, manual overrides, reviewed state, and cross-model rows.
- Keep the latest renderer crop intact; do not add CSS `object-fit: cover` that can cut off hair or accessories.
- The primary workflow must remain usable without an API key and must report that AI vision was skipped.

---

### Task 1: Refresh Persisted Preview Paths Independently of AI

**Files:**
- Modify: `spine_face_labeler.py`
- Modify: `spine_face_analysis.py`
- Modify: `webui.py`
- Test: `tests/test_spine_face_labeler.py`
- Test: `tests/test_spine_face_analysis.py`
- Test: `tests/test_asset_library.py`

**Interfaces:**
- Produces: `refresh_visual_face_preview_paths(con, *, ident, spine_signature, outfit_key, faces) -> int`.
- Consumes: `RenderedFace.face_id` and `RenderedFace.head_path` from the renderer report.
- Produces: preview URLs containing `v=<record version>`.

- [ ] **Step 1: Write failing label-store tests**

Add tests that seed two model rows plus a manual override, call `refresh_visual_face_preview_paths`, and assert both rows move from `heads-v4` to `heads-v7`, versions increment only when paths change, and AI/manual/reviewed fields remain byte-for-byte equivalent.

- [ ] **Step 2: Run the label-store tests and verify RED**

Run: `python -m pytest tests/test_spine_face_labeler.py -k refresh_visual_face_preview_paths -q`

Expected: FAIL because the refresh function does not exist.

- [ ] **Step 3: Implement the minimal label-store update**

Implement one transaction that maps face IDs to absolute head paths and updates matching rows only when `head_path` differs:

```python
UPDATE face_visual_label
SET head_path=?, version=version+1, updated_at=CURRENT_TIMESTAMP
WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
  AND COALESCE(head_path, '')<>?
```

Return the number of changed rows without touching semantic or manual columns.

- [ ] **Step 4: Write failing analysis tests for both early returns**

Extend the provider-missing and fully-cached tests so renderer faces point at new head files while seeded labels point at old files. Assert both calls refresh stored paths before returning.

- [ ] **Step 5: Run analysis tests and verify RED**

Run: `python -m pytest tests/test_spine_face_analysis.py -k "missing_key or cached" -q`

Expected: FAIL because analysis currently returns before refreshing paths.

- [ ] **Step 6: Refresh paths immediately after rendering**

Call the label-store function after `render_face_variations` and before `if provider is None` or cached-label checks. Include `refreshed_preview_count` in the result for task evidence.

- [ ] **Step 7: Add versioned preview URL test and implementation**

Assert `_public_visual_face` emits `/api/assets/faces/preview?...&v=<version>`, then append the record version through `urlencode`.

- [ ] **Step 8: Run focused tests and commit**

Run: `python -m pytest tests/test_spine_face_labeler.py tests/test_spine_face_analysis.py tests/test_asset_library.py -q`

Commit: `fix: refresh rendered face previews`

### Task 2: Serialize Schema Migration for Concurrent Preview Reads

**Files:**
- Modify: `assetdb.py`
- Modify: `asset_catalog.py`
- Test: `tests/test_asset_library.py`

**Interfaces:**
- Produces: SQLite connections with `PRAGMA busy_timeout=5000`.
- Produces: `asset_catalog.migrate(con)` with an in-process lock and schema-version fast path.
- Consumes: `meta.asset_schema_version` as the migration commit marker.

- [ ] **Step 1: Write a failing concurrent target-resolution test**

Create one migrated database and registered character, then use a thread pool with separate connections to resolve the same character target repeatedly. Instrument `assetdb.migrate_face_evidence` and assert it is not invoked after the schema version is current; assert no `sqlite3.OperationalError` is raised.

- [ ] **Step 2: Run the concurrency test and verify RED**

Run: `python -m pytest tests/test_asset_library.py -k concurrent_face_preview_resolution -q`

Expected: FAIL because every target lookup currently performs migration writes.

- [ ] **Step 3: Add connection busy timeout and migration gate**

Set `PRAGMA busy_timeout=5000` immediately after `sqlite3.connect`. In `asset_catalog.migrate`, check `meta.asset_schema_version`; if current, return. Otherwise acquire a module `threading.RLock`, check again, run schema/evidence migration, write the version, and commit.

- [ ] **Step 4: Run focused database and HTTP preview tests**

Run: `python -m pytest tests/test_asset_library.py tests/test_web_asset_api.py -q`

- [ ] **Step 5: Commit**

Commit: `fix: serialize asset database migrations`

### Task 3: Simplify Full AI Relabel and Correct Provider Messaging

**Files:**
- Modify: `ui.html`
- Modify: `js/library_faces.js`
- Modify: `css/layout.css`
- Modify: `webui.py`
- Test: `tests/test_ui_asset_library.py`
- Test: `tests/test_ui_asset_workbench_responsive.py`
- Test: `tests/test_spine_face_analysis.py`

**Interfaces:**
- Primary action sends `force_vision: false`.
- Secondary `data-face-action="force-vision"` action sends `force_vision: true` and is hidden until saved labels exist.

- [ ] **Step 1: Write failing UI structure and request tests**

Assert the old checkbox text is absent, the primary request sends `force_vision=false`, and a saved result reveals a secondary “强制重新请求 AI” action whose request sends `force_vision=true`.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `python -m pytest tests/test_ui_asset_library.py -k "force_vision or workspace_markup" -q`

Expected: FAIL while the checkbox remains the only force control.

- [ ] **Step 3: Implement the two explicit actions**

Remove `faceWorkspaceForceVision`. Add a hidden secondary button, bind it to `start(true)`, make the primary call `start(false)`, and reveal the secondary action only when persisted labels or a completed saved result exist. Keep it visually secondary and mobile-safe.

- [ ] **Step 4: Correct missing-provider status copy**

Change the task message to “当前任务未读取到模型密钥；保存配置后请重新开始任务。本次仍会完成渲染和语义命名解析”. Preserve `vision_status=skipped_missing_key`.

- [ ] **Step 5: Run UI and analysis tests**

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py tests/test_spine_face_analysis.py -q`

- [ ] **Step 6: Commit**

Commit: `fix: clarify face relabel controls`

### Task 4: Full and Real-Asset Verification

**Files:**
- Verify only; no production changes expected.

**Interfaces:**
- Consumes all prior task outputs.

- [ ] **Step 1: Run focused backend and UI suites**

Run: `python -m pytest tests/test_spine_face_labeler.py tests/test_spine_face_renderer.py tests/test_spine_face_analysis.py tests/test_asset_library.py tests/test_ui_asset_library.py tests/test_ui_asset_workbench_responsive.py -q`

- [ ] **Step 2: Run full verification**

Run: `python -m pytest -q`

Run: `python -m compileall -q assetdb.py asset_catalog.py spine_face_labeler.py spine_face_renderer.py spine_face_analysis.py webui.py prompt.py`

Run: `node --check js/app.js`

Run: `node --check js/library.js`

Run: `node --check js/library_faces.js`

Run: `node --check js/library_preview.js`

Run: `git diff --check`

- [ ] **Step 3: Verify the real character cache and database**

Run the face job for `626652156`, confirm database rows 32-40 point to `heads-v7`, and inspect 36-41 without editing attachment coordinates.

- [ ] **Step 4: Verify the UI with the in-app Browser**

Check 1440x900, 900x900, 390x844, and 360x800. Confirm current images fill their square without clipping, force relabel is secondary, no horizontal overflow or double page scrollbar appears, and restore the default viewport.
