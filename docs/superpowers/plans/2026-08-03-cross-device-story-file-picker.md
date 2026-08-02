# Cross-device Story File Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the raw directory button list with a dual-source story picker that uses the current device's native file chooser or a responsive Explorer-style host browser.

**Architecture:** A focused Python module owns uploaded story copies and opaque host-entry tokens. A focused browser component owns source choice, upload, host navigation, selection, and keyboard state; `app.js` receives one normalized `{file_token, name}` result and runs the existing story workflow.

**Tech Stack:** Python standard library HTTP server, pathlib/tempfile, vanilla JavaScript, HTML/CSS, pytest, Node VM component tests, Playwright browser QA.

## Global Constraints

- Accept only `.txt` and `.md` story files, with a 10 MiB maximum for device uploads.
- Never return upload paths or selectable host physical paths to the browser.
- Host selection must use an exact short-lived server-issued entry token.
- Preserve the existing path-based `/api/picker` compatibility route for internal callers.
- No inline event handlers; all user-provided values enter the DOM through `textContent` or safe attributes.
- Support desktop and 390 px mobile layouts without horizontal page overflow.

---

### Task 1: Safe Device Upload and Host Entry Tokens

**Files:**
- Create: `story_file_picker.py`
- Modify: `webui.py`
- Test: `tests/test_story_file_picker_api.py`

**Interfaces:**
- Produces: `StoryFilePicker.upload(name: str, content: bytes) -> dict`
- Produces: `StoryFilePicker.list_directory(entry_token: str = "", query: str = "", sort: str = "name", direction: str = "asc") -> dict`
- Produces: `StoryFilePicker.select(entry_token: str) -> dict`
- HTTP: `POST /api/story-files/upload`, `GET /api/story-files/host`, `POST /api/story-files/select`

- [ ] Write failing API tests for valid upload, invalid extension, empty/oversized/binary content, opaque responses, host metadata filtering, directory navigation, and exact-token selection.
- [ ] Run `python -m pytest tests/test_story_file_picker_api.py -q` and confirm failures are caused by missing routes/module.
- [ ] Implement an application-owned temporary upload directory, atomic writes, text validation, short-lived entry tokens, canonical allowed-root checks, sortable metadata, and route handlers.
- [ ] Run `python -m pytest tests/test_story_file_picker_api.py tests/test_web_asset_browse.py tests/test_story_workspace.py -q` and confirm all pass.
- [ ] Commit with `feat: add secure cross-device story file APIs`.

### Task 2: Dual-source Picker Component

**Files:**
- Create: `js/story_picker.js`
- Modify: `ui.html`
- Modify: `js/app.js`
- Modify: `tests/ui_runtime_harness.js`
- Create: `tests/test_ui_story_picker.py`

**Interfaces:**
- Consumes: Task 1 HTTP routes.
- Produces: `window.StoryUI.StoryFilePicker(root, {onChoose})`
- Produces: `open(trigger)`, `close()`, `openHost()`, and normalized `onChoose({file_token, name, size})`.

- [ ] Write failing Node/browser-component tests proving source choice, native input upload, host navigation history, search/sort, row selection, double-click/Enter open, cancel/focus restoration, stale token error, and no physical-path persistence.
- [ ] Run `python -m pytest tests/test_ui_story_picker.py -q` and confirm the component is missing.
- [ ] Add semantic source chooser and file-manager DOM, load `story_picker.js`, and connect its normalized result to the existing story opening/analyze transition without posting a path.
- [ ] Run `python -m pytest tests/test_ui_story_picker.py tests/test_ui_runtime_behavior.py tests/test_ui_runtime_transitions.py tests/test_ui_async_operations.py -q` and confirm all pass.
- [ ] Commit with `feat: add dual-source story file picker`.

### Task 3: Explorer-style Responsive Presentation and Browser QA

**Files:**
- Modify: `css/layout.css`
- Modify: `css/app.css`
- Modify: `tests/test_ui_story_picker.py`
- Create: `tests/test_ui_story_picker_responsive.py`

**Interfaces:**
- Consumes: Task 2 semantic DOM and component states.
- Produces: desktop details view and mobile one-column view with navigation drawer and sticky selection footer.

- [ ] Write failing responsive assertions for desktop columns, 390 px overflow, stable row dimensions, sticky footer, horizontal breadcrumb containment, and mobile navigation drawer.
- [ ] Run `python -m pytest tests/test_ui_story_picker_responsive.py -q` and capture the initial failures.
- [ ] Implement a restrained Windows utility visual system: compact command bar, icon controls, navigation rail, sortable column headers, selected rows, empty/loading/error states, and mobile adaptations.
- [ ] Run `python -m pytest tests/test_ui_story_picker.py tests/test_ui_story_picker_responsive.py tests/test_csp_headers.py -q` and `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`.
- [ ] Restart the feature server, inspect desktop and mobile screenshots with Playwright, verify both source flows, and confirm no CSP, 404, overflow, overlap, or uncaught errors.
- [ ] Run `python -m pytest tests/test_story_file_picker_api.py tests/test_ui_story_picker.py tests/test_ui_story_picker_responsive.py tests/test_ui_runtime_behavior.py tests/test_ui_runtime_transitions.py tests/test_csp_headers.py -q` and `git diff --check`.
- [ ] Commit with `feat: complete responsive story file explorer`.
