# Inline writing model picker — 2026-09-19

## Request and fix
The composer model label incorrectly opened Settings Center. It now opens a searchable, anchored model picker using the configured provider's model endpoint. Settings is a separate secondary action. Switching uses the existing tested activation transaction, changes writing only, preserves endpoint/key/budget and does not rerender the composer. Config digest rejects stale connection selections. Anthropic model discovery now uses its endpoint instead of hardcoded names.

## Changed slice
- services/halocue/writing/web/agent-model-picker.js (new)
- services/halocue/writing/web/agent-model-picker.css (new)
- services/halocue/writing/web/app.js
- services/halocue/writing/web/index.html
- services/halocue/writing/src/halocue_writing/model_settings.py
- services/halocue/writing/tests/test_provider_activation_contract.py
- services/halocue/writing/tests/agent_main_surface.test.cjs
- services/halocue/writing/tests/in_app_browser_model_picker_fixture_server.py (local synthetic provider harness)

## Verification
- node --check on app.js and agent-model-picker.js: passed.
- python -m pytest services/halocue/writing/tests/test_provider_activation_contract.py services/halocue/writing/tests/test_provider_pinning.py -q: 14 passed.
- python -m pytest services/halocue/writing/tests/test_http_api.py -k activate_writing_model -q: 1 passed, 93 deselected.
- node --test services/halocue/writing/tests/agent_main_surface.test.cjs: 9 passed.
- In-app browser, isolated synthetic provider: searched and switched test-writer-a to test-writer-b; unsent draft preserved; reload retained selection. Unavailable model returned HTTP 404, retained test-writer-b. Search focused after async loading. Secondary settings action opened Settings Center.
- Live workbench: fetched the real configured provider list successfully; dark popup inspected and captured. Esc restored focus to model trigger. Actual selected gemini-3.8-flash unchanged; no live generation/activation test performed.
- Screenshots in workspace output/2026-09-19-model-picker: live-model-picker-dark.png, fixture-model-switch-error.png.

## Runtime and limits
Live integrated service restarted on port 8928, PID 35224, using unchanged output/2026-09-17-live-chain/runtime data directories. No active queued/running AgentRuns found before restart. Temporary fixture port 8932 stopped after QA. No real theme changes. No commit/push; preexisting worktree edits preserved.
Responsive CSS exists but mobile viewport was not reverified in this slice. Anthropic pagination is not implemented; do not promise exhaustive paginated results. Model selection applies globally to subsequent writing requests across works, expressly stated in picker. Full suite not run.

## Follow-up: registered configurations only
User corrected the intended source: quick switching must use configurations saved in Settings, not provider discovery. Added a backward-compatible registered_models collection inside the existing atomic writing-model.json. Current legacy config is listed without a write. Saving retains previous models; same protocol/endpoint/model updates its saved entry. Switching submits registered_model_id and resolves that entry's own endpoint, encrypted credential reference, and budget on the server. Unknown IDs and overrides are rejected. Public registry exposes only id/model/provider/base_url/current. Settings now displays a collapsed saved-model list. Discovery remains only in Settings.

Replaced the composer caret glyph with a 14px inline SVG; DOM measurements confirm exact text/caret vertical center alignment. Expanded state rotates arrow; reduced-motion disables transition.

Verification: provider activation + pinning + candidate binding suites 34 passed; node main surface 10 passed; HTTP activation 1 passed (93 deselected); JS syntax passed. Browser fixture provider advertises 4 models but picker lists only 2 saved models; switching b to a preserves draft. Settings shows saved count 2. Live picker lists only saved gemini-3.8-flash; live model unchanged. Screenshot output/2026-09-19-model-picker/registered-model-picker.png.

Runtime restarted after verifying no queued/running writing AgentRuns: live port8928 PID3340, unchanged data directories. Fixture stopped. Prior overwritten configurations cannot be recovered retroactively; only currently saved config migrates, subsequent saves retain entries. Saved configurations do not yet have removal/rename controls. No commit/push.
