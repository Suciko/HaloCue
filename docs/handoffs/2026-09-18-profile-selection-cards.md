# 1.0 explicit strategy selection cards

- Kind: handoff; status: implemented locally, uncommitted/unpushed.
- Date: 2026-09-18; branch: `codex/1.0-release-readiness-20260914`; parent Issue: #15.
- Owner: embedded production UI / production read model.
- Authority: maintainer approved replacing profile dropdowns with explicit cards and restrained feedback. Product direction / client-backend invariants and ADR-0006 retained.
- Existing dirty work preserved; no remote publication.

## Implementation
Both source/new-task and generation-stage profile controls use native radios styled as two visible cards. Existing hidden select fields remain compatibility state/event adapters; business flow and API submissions are unchanged. Selected card shows an overlay and checkmark, explanations live with each option. Execution mode stays separate.

A compact status panel distinguishes last committed draft generation from next selection. New optional `draft_direction_profile` in run-detail reads the successful record named by `last_direction_generation_id`; never infer committed provenance from the most recent attempted strategy. Missing/corrupt records are unknown. No persisted schema or canonical model change.

Generation/busy/compiling states disable radios and show reason. Capability-limited strategies remain disabled. Existing confirmation and resume/new-generation logic retained. Selecting alone sends no generation write. Last user selection wins for rapid switching; native Tab/Arrow controls stay accessible.

Motion gate: occasional state indication/feedback. CSS transitions only: opacity overlay and opacity/scale(.92→1) checkmark, 180ms, existing production ease-out token. No text/layout motion or new motion library. Keyboard selection and prefers-reduced-motion have no transition. Min-height reserves help text space so action panel does not jump.

## Validation
```text
python -X utf8 -m pytest -q services/halocue/production/tests/test_direction_profile_ui.py services/halocue/production/tests/test_embedded_workbench_ui.py services/halocue/production/tests/test_direction_profiles.py services/halocue/production/tests/test_service.py services/halocue/production/tests/test_http_api.py services/halocue/production/tests/test_ui_information_architecture.py
# 221 passed
node --check services/halocue/production/ui/app.js
node --check services/halocue/writing/web/production-embed.js
```
Integrated navigation + gateway tests: 25 passed. Scoped Ruff/diff checks pass. New service test proves failed standard attempt does not relabel a prior conservative draft; unknown/path-invalid provenance stays unknown. UI tests cover unsupported capabilities, locked running state, current/next distinction, keyboard, reduced motion, rapid reversal and no writes. First-step and lock screenshots use explicit synthetic responses, not paid model calls.

Real 8928 read-only acceptance: desktop1440/mobile390 x dark/light; identical panel heights before/after selection, no horizontal overflow or JS errors. Draft and run strategy unchanged. Existing shell feedback sync POST is separately recorded. Computed animation frames contain intermediate opacity values; reduce duration is zero.

Maintainer-local evidence `<LOCAL_PROFILE_CARDS_QA>` contains RESULT/ISSUE_LOG, screenshots, tests and motion frame JSON. No keys, assets or private machine paths in shared docs. No models invoked, no new tasks, no approval/compile/install.

## Remaining boundaries
Standalone-run header/refresh observations from prior handoff remain. Old scene-confirmation panel has a dark-theme white surface outside this card scope; recorded, not claimed fixed. The test shell lacked global border-box and caused a 1px host overflow; fixture now matches real host sizing, with separate actual UI verification. Whole-repo suite not run.
