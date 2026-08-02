# Final Review Fix Wave Implementation Plan

> **For agentic workers:** Execute each checkbox with a failing test before the corresponding production change. This project is not a Git repository; use test evidence instead of commits.

**Goal:** Close every Critical, Important, and Minor finding in the final custom-assets code review without touching real AA data, camera logic, or source assets.

**Architecture:** Centralize Windows path validation and project-pair coordination in `aa_project_assets.py`. Keep registry copying transactional under a canonical cross-process lock, let generation persist the exact resource-capability index as project-scoped data, and keep the web handler's build reservation thread-safe.

**Tech Stack:** Python 3.11+, standard library, Pillow, pytest, existing AAP/manifest formats.

## Global Constraints

- Use only pytest temporary directories and synthetic assets.
- Do not start AA or write `E:\AzureArchive`, `data/overrides`, `aa_assets.db`, `llm.json`, original assets, or camera code.
- Accept legal Chinese, spaces, hyphens, and ordinary numeric identifiers.
- Every behavior below must have an observed RED run before its implementation.

---

### Task 1: Path boundary and pair locking

**Files:**
- Modify: `aa_project_assets.py`, `aa_registry.py`, `asset_validation.py`, `webui.py`, `script2aap.py`
- Test: `tests/test_final_fix_wave.py`

- [ ] Write tests rejecting traversal, separators, drives, UNC, control characters, and device names at character, web, CLI, and direct-registry boundaries while accepting Chinese legal names.
- [ ] Run the path tests and record their expected failures.
- [ ] Add one shared component validator, validate direct targets, and prove every resolved destination remains under its intended root before creating it.
- [ ] Write concurrency tests for two different registrations and simultaneous same-project build requests.
- [ ] Run them RED, add canonical pair file/thread locking plus atomic build reservation, then run them GREEN.

### Task 2: Safe installation transaction

**Files:**
- Modify: `aa_project_assets.py`, `aa_registry.py`, `script2aap.py`
- Test: `tests/test_final_fix_wave.py`

- [ ] Write tests for an injected process-probe failure, direct `--install` denial with no files written, and a non-install pure output path that remains allowed.
- [ ] Run the tests RED, distinguish unknown probe state from confirmed closed, and inject the CLI probe.
- [ ] Write a failing injected-copy test that leaves neither temporary nor target file and never overwrites a pre-existing target.
- [ ] Run it RED, use same-directory temporary `copy2` plus checked `os.replace`, rollback, and run GREEN.

### Task 3: Capability handoff and UI semantics

**Files:**
- Modify: `script2aap.py`, `verify.py`, `ui.html`
- Test: `tests/test_final_fix_wave.py`, `tests/test_web_asset_api.py`

- [ ] Write an end-to-end generated-project test where an observed/verified face 99 in the build index reaches project verification only through the persisted sidecar; assert atlas-only 99 stays rejected.
- [ ] Run it RED, atomically persist the exact build index in the project scope, and run GREEN.
- [ ] Update the executable UI test so it expects skeleton signature and separate Spine version, then run it RED.
- [ ] Render `spine_signature` and `spine_version` separately and run it GREEN.

### Task 4: Verification and report

**Files:**
- Create: `04-素材机制实验/实施验证/sdd-aa-native-custom-assets/final-fix-report.md`

- [ ] Run all final-fix focused tests, existing related focused suites, `pytest -q`, and `py_compile`.
- [ ] Re-read the final review and inspect all interfaces for unprotected paths, lock scope, rollback, sidecar precedence, and unchanged camera behavior.
- [ ] Record each RED/GREEN cycle, exact commands/results, modified files, and residual concerns in the required report.
