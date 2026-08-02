# Beginner Entry and Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click Windows entry, startup diagnostics, in-app beginner guidance, and complete human/AI handoff documentation.

**Architecture:** Keep `webui.py` as the application server and add a small, independently testable `launcher.py` in front of it. Expose non-sensitive readiness through one setup endpoint and render it in the existing single-page UI. Keep documentation outside production code.

**Tech Stack:** Python 3.9+, Windows CMD, standard library, Pillow, HTML/CSS/JavaScript, pytest.

## Global Constraints

- Do not modify or delete original AA or user asset files.
- Do not write API keys to files, logs, HTTP responses, or documentation.
- The only network listener remains `127.0.0.1`.
- AI model configuration remains optional for deterministic conversion.
- Do not introduce a desktop framework or packaging system in this phase.
- This directory has no Git repository; verification outputs replace commit checkpoints.

---

### Task 1: Testable startup diagnostics

**Files:**
- Create: `launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Produces: `normalize_aa_data_path(path: str | Path) -> Path | None`
- Produces: `build_environment_report(program_dir: Path, explicit_aa_data: str | None = None) -> dict`
- Produces: `is_existing_server(url: str) -> bool`
- Produces: CLI flags `--check`, `--json`, `--aa-data`

- [ ] Write tests that reject a random folder and accept both an AA `data` folder and its workspace parent.
- [ ] Run `python -m pytest -q tests/test_launcher.py` and verify the tests fail because `launcher.py` does not exist.
- [ ] Implement path normalization and a structured environment report without starting a server.
- [ ] Add checks for Python 3.9+, `webui.py`, `ui.html`, `aa_assets.db`, Pillow, and AA workspace discovery.
- [ ] Run the launcher tests and verify they pass.

### Task 2: One-click Windows entry

**Files:**
- Create: `启动程序.cmd`
- Create: `检查运行环境.cmd`
- Create: `..\..\..\启动AA自动写剧本.cmd`
- Create: `..\..\..\检查运行环境.cmd`
- Modify: `launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `launcher.py --check`
- Produces: one stable top-level entry that works independently of the current directory

- [ ] Add a failing subprocess test for `launcher.py --check --json`.
- [ ] Implement CLI output, friendly failure logging, existing-server detection, and `webui.py` process startup.
- [ ] Add UTF-8 CMD wrappers that prefer `py -3`, fall back to `python`, and pause only on errors or diagnostics.
- [ ] Run the subprocess test from a different working directory and verify the returned JSON.

### Task 3: Setup readiness API

**Files:**
- Modify: `webui.py`
- Test: `tests/test_web_setup_status.py`

**Interfaces:**
- Produces: `setup_status() -> dict`
- Produces: `GET /api/setup/status`

- [ ] Add failing tests for connected AA, database readiness, active model display, and absence of secret fields.
- [ ] Implement `setup_status()` using current `CFG`, `DB`, `assetdb.stats()`, and `MODEL_PROFILES.active_profile()`.
- [ ] Register `GET /api/setup/status`.
- [ ] Run the targeted web setup tests and verify they pass.

### Task 4: Beginner card and help drawer

**Files:**
- Modify: `ui.html`
- Modify: `tests/test_ui_workbench.py`

**Interfaces:**
- Consumes: `GET /api/setup/status`
- Produces: first-use panel, help drawer, sidebar help entry, status rendering

- [ ] Add failing UI behavior tests for stable accessible labels, help drawer structure, and setup-status initialization.
- [ ] Add the first-use readiness card above the script workflow.
- [ ] Add a separate help drawer with task-oriented instructions and a persistent sidebar entry.
- [ ] Add responsive CSS, focus states, reduced-motion handling, and local dismissal that can always be reversed through Help.
- [ ] Run UI tests and verify they pass.

### Task 5: Human and AI handoff documentation

**Files:**
- Create: `使用说明-从这里开始.md` in the archive root
- Create: `AI接手文档-2026-07-31.md` in the archive root
- Modify: `README.md`
- Modify: `prepare_release.py`

**Interfaces:**
- Produces: a five-minute human guide and a single-source AI handoff document

- [ ] Write the human guide around double-click actions and visible UI wording.
- [ ] Write the AI handoff with project paths, current architecture, confirmed behavior, sensitive-data rules, tests, known limits, and prioritized next tasks.
- [ ] Update README so the one-click entry appears before command-line instructions.
- [ ] Include `launcher.py`, CMD entries, and user guide in release packaging.
- [ ] Search both documents for secrets, ambiguous placeholders, stale counts, and absolute paths that should not ship.

### Task 6: End-to-end verification

**Files:**
- No new production files.

**Interfaces:**
- Verifies all interfaces from Tasks 1–5.

- [ ] Run `python launcher.py --check --json`.
- [ ] Start through the top-level CMD entry and verify the local page becomes reachable.
- [ ] Inspect desktop, tablet, and mobile widths; verify no console errors or warnings.
- [ ] Exercise Help, Settings, workspace switching, and setup readiness.
- [ ] Run `python -m pytest -q`.
- [ ] Run `python prepare_release.py --check`.
- [ ] Stop the local server cleanly and record exact verification results in the AI handoff document.

