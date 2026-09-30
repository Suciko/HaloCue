# Manual manuscript / assistant save handoff — 2026-09-25

- Kind: handoff; status: local, uncommitted, not published.
- Scope: existing writing client on codex/1.0-release-readiness-20260914; no backend or contract change.
- Source: user-authorized continuation; product-direction-1.x.md, CONTEXT-MAP.md, contexts/client/CONTEXT.md, ADR-0006; preceding 2026-09-25-writing-entry-paths.md.
- Issue: no linked issue identified in previous local slice; no remote issue/PR created.

## Changes
- Assistant composer shows a quiet live-status notice as soon as the current manuscript becomes dirty. Explains that AI needs saved text and saving does not send a message.
- Native button with form=sceneManuscriptForm submits the existing manuscript handler from the assistant pane, including mobile. No automatic save/send chaining, extra endpoint, or new revision rules.
- Notice state synchronized with top save: checks writing/draft view, owning scene, actual manuscript form, dirty/saving flags. Saved state hides notice; saving disables action and labels it 保存中….
- Successful assistant-triggered save restores focus to the discussion textarea. Failure retains original focus/retry path. Existing unsaved-message capture/restore and Agent dirty guards unchanged.
- Scoped neutral styles wrap in narrow sidebar/mobile, light/dark theme tokens, 44px mobile control.
- Pending review path inspected through existing tests, not redesigned in this slice.

## Paths
- services/halocue/writing/web/app.js
- services/halocue/writing/web/authoring-ui.css
- services/halocue/writing/web/index.html (two cache-version tags)
- services/halocue/writing/tests/test_topbar_manuscript_save.py (5 additional cases)

## Verification
- python -m pytest services/halocue/writing/tests/test_topbar_manuscript_save.py services/halocue/writing/tests/test_scene_detail_polish.py services/halocue/writing/tests/test_writing_entry_polish.py services/halocue/writing/tests/test_scene_message_ui.py -q: 55 passed.
- python -m pytest services/halocue/writing/tests/test_change_review_ui.py services/halocue/writing/tests/test_writing_responsive_shell.py services/halocue/writing/tests/test_manuscript_interaction_ui.py -q: 23 passed.
- node --check services/halocue/writing/web/app.js: passed.
- git diff --check on edited web/test paths: passed.
- New tests use shipping save handler with mocked transport: success/failure, one manuscript request and zero Agent submits, retained instructions, saving state, focus, scene ownership and clean-state hiding; notice layout at 390/1280 light/dark.
- Internal browser: dedicated temporary tab on synthetic port 8765 fixture; dirty hint appears immediately, desktop/390x844 screenshots inspected, assistant text retained across responsive tab switch. No save/model call made through browser. Temporary test-only tab closed and viewport reset; original user tabs untouched.

## Limits
78 targeted tests, not full suite. Save success/failure verified with mocked transport, not a live model/end-to-end provider run. No API credits, persisted user manuscript changes, commit, push, package or deployment. Existing broad dirty working tree preserved. Follow-up should focus on a synthetic saved-revision-to-proposal review journey, not additional modes.
