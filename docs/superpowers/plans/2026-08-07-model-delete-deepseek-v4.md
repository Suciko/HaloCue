# Model Deletion And DeepSeek V4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add safe model deletion to the model workbench and update new DeepSeek connections to the official `deepseek-v4-flash` model ID.

**Architecture:** `ModelProfileStore` owns an atomic delete operation that optionally removes an empty connection and its Windows credential. `webui.py` exposes that operation through one model-workbench endpoint. The model list renders a destructive action with explicit browser confirmation and refreshes workbench state after success.

**Tech Stack:** Python 3, `ThreadingHTTPServer`, vanilla JavaScript, HTML/CSS, pytest.

## Global Constraints

- Assigned base or vision models cannot be deleted.
- Removing the last model may remove its connection and Windows credential only after explicit confirmation.
- API keys never enter JSON, logs, DOM state, or error responses.
- Existing saved `deepseek-chat` records are not rewritten automatically.

---

### Task 1: Atomic Storage And API Deletion

**Files:**
- Modify: `model_profiles.py`
- Modify: `webui.py`
- Test: `tests/test_model_profiles.py`
- Test: `tests/test_web_model_profiles.py`

**Interfaces:**
- Produces: `ModelProfileStore.delete_model(model_id, *, delete_empty_connection=False) -> dict`
- Produces: `POST /api/llm/models/delete` with `{id, delete_empty_connection}`

- [ ] Write failing tests for assigned-model rejection, model-only deletion, and last-model connection/key cleanup.
- [ ] Run those tests and confirm failures are caused by the missing return contract and route.
- [ ] Implement the atomic store operation and Web API route.
- [ ] Run the focused storage and Web API tests.

### Task 2: Model List Delete Action

**Files:**
- Modify: `js/app.js`
- Modify: `css/layout.css`
- Test: `tests/test_ui_model_workbench.py`

**Interfaces:**
- Consumes: `POST /api/llm/models/delete`
- Produces: model-row `delete-workbench-model` action with confirmation and refreshed state.

- [ ] Write a failing UI contract test for the delete action.
- [ ] Add a danger-styled delete button and confirmation flow.
- [ ] Show backend assignment errors in the visible workbench notice.
- [ ] Run UI tests and JavaScript syntax checks.

### Task 3: DeepSeek Current Default And Verification

**Files:**
- Modify: `model_profiles.py`
- Modify: `js/app.js`
- Test: `tests/test_model_profiles.py`

**Interfaces:**
- Produces: DeepSeek preset model `deepseek-v4-flash`.

- [ ] Write a failing assertion for the official DeepSeek preset ID.
- [ ] Update backend and offline fallback presets without migrating saved records.
- [ ] Run focused model tests.
- [ ] Restart the QA server and verify delete behavior and DeepSeek default in the browser.
- [ ] Run the model regression suite and report unrelated full-suite failures separately.
