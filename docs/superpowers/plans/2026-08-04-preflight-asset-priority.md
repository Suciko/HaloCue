# Preflight Asset Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer verified AA background candidates before asking authors for new artwork, while treating AI-proposed sound and BGM as optional enhancements.

**Architecture:** The existing preflight model receives a compact official background catalog and may return up to three candidates for each background need. `webui.py` validates every returned key against the local database and assigns `recommended`, `approximate`, or `missing`; the frontend renders verified candidates and keeps sound/BGM in a collapsed optional section.

**Tech Stack:** Python 3, SQLite, vanilla JavaScript, CSS, pytest, Node UI runtime harness, Playwright CLI.

## Global Constraints

- Candidate keys must exist in the local `bg` table and have a usable hash.
- Confidence `>= 0.75` is `recommended`; `0.60-0.74` is `approximate`; lower scores do not suppress the missing-background workflow.
- AI-derived sound and BGM suggestions never block preflight confirmation.
- Explicit authored directives such as `@sound missing-key` retain blocking validation.
- Existing full-text evidence remains unchanged.

---

### Task 1: Verified Background Candidate Contract

**Files:**
- Modify: `webui.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: local `bg(name, hash, label, place, time, mood, tags)` rows and model `usage_chain[].needs[].candidates`.
- Produces: normalized background needs with `status`, `candidates`, and an `aa_key` only after an exact or user-confirmed selection.

- [ ] **Step 1: Write failing tests** proving a real `BG_ShoppingDistrict` candidate at `0.70` becomes `approximate`, a hallucinated key is discarded, and a sub-`0.60` candidate leaves the need `missing`.
- [ ] **Step 2: Run tests to verify RED:** `E:\Miniconda3\python.exe -m pytest -q tests/test_preflight.py -k "candidate or optional"`.
- [ ] **Step 3: Add the schema and normalization:** include `official_backgrounds` in volatile context; validate candidate keys through SQLite; sort and cap candidates at three; generate prompts only when no candidate reaches `0.60`.
- [ ] **Step 4: Run the same tests to verify GREEN.**

### Task 2: Optional AI Sound And BGM

**Files:**
- Modify: `webui.py`
- Test: `tests/test_preflight.py`

**Interfaces:**
- Consumes: `detected_by` on asset references.
- Produces: warning-only `optional_asset_suggestion` issues for AI sound/BGM; explicit directive references still produce blocking errors.

- [ ] **Step 1: Write failing tests** for non-blocking AI sound/BGM and blocking explicit missing sound directives.
- [ ] **Step 2: Run the focused tests and confirm the current severity is wrong.**
- [ ] **Step 3: Mark directive refs with `detected_by="directive"` and branch issue severity/copy by origin and kind.**
- [ ] **Step 4: Re-run focused tests.**

### Task 3: Candidate And Optional UI

**Files:**
- Modify: `js/app.js`
- Modify: `css/app.css`
- Test: `tests/test_ui_preflight_timeline.py`

**Interfaces:**
- Consumes: normalized `recommended`/`approximate` needs and verified `candidates`.
- Produces: candidate rows with preview, confidence, and `采用此背景`; collapsed `可选演出增强` for sound/BGM.

- [ ] **Step 1: Write a failing Node runtime test** that renders a shopping-district candidate, applies it, and confirms sound/BGM are inside a collapsed optional group.
- [ ] **Step 2: Run the UI test to verify RED.**
- [ ] **Step 3: Render candidate choices** from `/thumb/bg/<aa_key>?px=240`, mutate the selected need to `builtin`, and re-render the usage chain without creating a missing-asset task.
- [ ] **Step 4: Render sound/BGM under nested `<details>` with the label `可选演出增强（N）`; retain secondary add-material actions without blocking.**
- [ ] **Step 5: Run the UI test to verify GREEN.**

### Task 4: End-To-End Verification

**Files:**
- Test: existing test suite and Playwright artifacts only.

**Interfaces:**
- Consumes: `D:\桌面\本日行程全部作废.txt`.
- Produces: verified desktop/mobile preflight behavior.

- [ ] **Step 1: Run focused tests:** `E:\Miniconda3\python.exe -m pytest -q tests/test_preflight.py tests/test_ui_preflight_timeline.py`.
- [ ] **Step 2: Run the full suite:** `E:\Miniconda3\python.exe -m pytest -q`.
- [ ] **Step 3: Restart port 8765 and run real AI preflight with the exact script.**
- [ ] **Step 4: Verify `BG_ShoppingDistrict` is offered before generation, optional audio does not block confirmation, and 1440px/390px layouts have no horizontal overflow.**
