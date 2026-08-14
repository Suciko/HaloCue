# Review Workflow UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active story and draft survive refresh, make 300+ card drafts easy to navigate, and expose concise background, cache, and compile outcomes.

**Architecture:** Keep browser-only navigation state in one versioned `localStorage` record containing opaque tokens and the selected card ID. Add review filtering and jump behavior inside the existing review state/render pipeline, while reusing current card rendering and selection callbacks. Surface annotation reuse and compile metadata from existing API results without persisting paths, secrets, or full draft content.

**Tech Stack:** Vanilla JavaScript, HTML/CSS, Python HTTP endpoints, pytest, Node VM runtime harness, Playwright.

## Global Constraints

- Preserve the current dirty worktree and do not reformat unrelated files.
- Persist only opaque story/draft/card identifiers; never persist filesystem paths or API credentials.
- Keep UI copy short and label-driven; detailed explanation belongs in Help.
- Do not install a compiled project during verification.

---

### Task 1: Refresh Recovery

**Files:**
- Modify: `tests/ui_runtime_harness.js`
- Modify: `tests/test_ui_story_workspace.py`
- Modify: `js/app.js`

**Interfaces:**
- Consumes: `/api/story/current?story_token=<token>`, `/api/drafts`, `/api/draft?token=<token>`
- Produces: `aa-active-review-v1 = {story_token, draft_token, card_id}` and `restoreActiveReview()`

- [ ] **Step 1: Write failing runtime tests**

Add tests proving that startup restores the stored story and draft, restores a selected card when it still exists, and clears stale identifiers when the story cannot be reopened.

- [ ] **Step 2: Run tests and verify the expected failure**

Run: `pytest -q tests/test_ui_story_workspace.py`

Expected: the new tests fail because startup does not read `aa-active-review-v1`.

- [ ] **Step 3: Implement minimal persistence and recovery**

Persist tokens after successful story replacement, draft loading, and card selection. On load, reopen the story, refresh drafts, load the stored draft, and select the stored card. Clear the record when recovery fails.

- [ ] **Step 4: Run targeted tests**

Run: `pytest -q tests/test_ui_story_workspace.py tests/test_ui_runtime_transitions.py`

Expected: all tests pass.

### Task 2: Large Draft Navigation

**Files:**
- Modify: `ui.html`
- Modify: `css/app.css`
- Modify: `css/layout.css`
- Modify: `tests/ui_runtime_harness.js`
- Modify: `tests/test_ui_runtime_behavior.py`
- Modify: `js/app.js`

**Interfaces:**
- Consumes: `state.review.cards`, each card's review state, kind, and line number
- Produces: `state.review.filter`, filtered card rendering, and card-number jump

- [ ] **Step 1: Write failing filter and jump tests**

Add behavior tests for `全部`, `待审`, `待处理`, and `演出`, plus jumping to a numbered card while expanding the render limit as needed.

- [ ] **Step 2: Run tests and verify the expected failure**

Run: `pytest -q tests/test_ui_runtime_behavior.py`

Expected: the new controls and behavior do not exist yet.

- [ ] **Step 3: Implement toolbar, filtering, and jump**

Add a compact segmented toolbar above the cards. Filter before applying the 80-card limit, preserve selection when possible, and make jump select, reveal, scroll to, and synchronize the preview card.

- [ ] **Step 4: Run targeted tests and responsive contract tests**

Run: `pytest -q tests/test_ui_runtime_behavior.py tests/test_ui_polish_contract.py tests/test_ui_workbench.py`

Expected: all tests pass.

### Task 3: Decision and Result Feedback

**Files:**
- Modify: `tests/test_ui_runtime_behavior.py`
- Modify: `tests/test_annotation_agent.py`
- Modify: `js/app.js`
- Modify: `webui.py` only if existing job results omit reuse metadata

**Interfaces:**
- Consumes: background resolution response, `job.result.resumed_chunks`, compile `build_id`, job timestamps/results
- Produces: concise status strings for background resolution, checkpoint reuse, and compile output

- [ ] **Step 1: Write failing feedback tests**

Add tests proving default-black selection is identified as manual, redundant background merging is reported, resumed chunk count is visible, and compile success includes the build ID.

- [ ] **Step 2: Run tests and verify the expected failure**

Run: `pytest -q tests/test_ui_runtime_behavior.py tests/test_annotation_agent.py`

Expected: at least the UI feedback tests fail because current messages omit these details.

- [ ] **Step 3: Implement minimal short feedback**

Use compact phrases such as `已设为默认黑屏`, `已合并重复背景切换`, `复用 3 段`, and `编译成功 · build-...`.

- [ ] **Step 4: Run targeted tests**

Run: `pytest -q tests/test_ui_runtime_behavior.py tests/test_annotation_agent.py tests/test_web_draft_endpoints.py`

Expected: all tests pass.

### Task 4: Full Verification

**Files:**
- Verify only

- [ ] **Step 1: Run syntax checks**

Run: `node --check js/app.js` and `git diff --check`.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -q`

- [ ] **Step 3: Run browser regression**

Verify desktop and 390px layouts, refresh recovery, filters, jump, default-black feedback, and compile-result presentation. Confirm no console errors and no horizontal overflow.
