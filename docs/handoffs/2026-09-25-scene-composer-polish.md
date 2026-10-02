# Scene assistant composer polish — 2026-09-25

- Kind: handoff; status: local/uncommitted; existing branch codex/1.0-release-readiness-20260914.
- Scope: writing client screenshot request, not broader sidebar redesign. Source: current user screenshot, product-direction-1.x.md, contexts/client/CONTEXT.md, previous manual-assistant-save-handoff.md. No matching linked issue from prior local UI slice; no remote publication.

## Implementation
- One rounded themed composer surface instead of nested textarea background/border and toolbar divider.
- 96px initial textarea, input/focus/resize/render synchronization grows up to min(224px,24vh) with 96px floor, then internal scroll. Clearing returns to baseline; no native resize grip. Uses existing input events including quick-action prefills, preserves value and scroll position.
- Secondary prompt chips become low-emphasis text actions with hover/focus treatments. Permissions left and send right; explicit widths override legacy grid and full-width button styles. Mobile buttons keep touch sizing and hide desktop keyboard hint.
- Visible desktop Enter/Shift+Enter hint; existing Shift+Enter newline and IME-safe Enter semantics unchanged.
- Saves, proposal action and Stop are retained. Corrected scene submit-button selection to exclude cross-form manuscript save button introduced in preceding slice; otherwise loading state could target the wrong button.

## Files
- services/halocue/writing/web/app.js
- services/halocue/writing/web/authoring-ui.css
- services/halocue/writing/web/index.html
- services/halocue/writing/tests/test_scene_composer_polish.py (new)

## Validation
- python -m pytest services/halocue/writing/tests/test_topbar_manuscript_save.py services/halocue/writing/tests/test_scene_detail_polish.py services/halocue/writing/tests/test_scene_message_ui.py services/halocue/writing/tests/test_permission_menu_layout.py -q: 61 passed.
- python -m pytest services/halocue/writing/tests/test_scene_composer_polish.py services/halocue/writing/tests/test_permission_menu_layout.py -q: 15 passed (10 overlap prior run).
- Final scoped style adjustments followed by test_scene_composer_polish.py: 5 passed. Total distinct covered tests: 66.
- New tests exercise shipping form markup, permission markup, growth helper, keyboard handlers and CSS at desktop/narrow/short/light/dark: grows/shrinks, overflow bound, IME not sent, Shift+Enter newline, Enter submit, permission/send same row, save button excluded, no horizontal button overflow.
- Internal browser synthetic fixture: empty and multiline desktop screenshots, 390x844 layout and retained draft, permission popover open/close without changing permission. Test text cleared, viewport reset, preview tab 8 retained. User's original tabs not reloaded.
- node --check app.js and git diff --check edited files: passed.

## Limits
No real model request, persisted manuscript modification, packaging, full suite, commit/push/deployment. Existing unrelated dirty changes preserved. The user can compare the new preview without losing their original unsaved tabs.
