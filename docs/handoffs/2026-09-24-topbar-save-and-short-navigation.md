# Topbar save and short-window navigation — 2026-09-24

Scope: continued authoring chrome polish. Existing dirty changes preserved. No commit, package, deployment, provider call or real manuscript save during browser acceptance.

## Changes
- A topbar Save button appears only for a dirty manuscript on the draft surface. It is associated with the existing sceneManuscriptForm using native HTML form submission; no second persistence or proposal-acceptance path.
- Ctrl/Cmd+S submits that same form. Settings dialogs, Agent inputs, other surfaces, candidate-only surfaces without a manuscript form, repeats and clean manuscripts do not trigger a manuscript API request. Native field validity still applies.
- Shared submit handler prevents duplicate saves, makes the editor inert while saving, defers background renders, and prevents dirty navigation during the request. Failure retains edits and returns focus; success hides the toolbar action and restores focus from the disappearing toolbar button into the manuscript.
- Dirty/status updates and completed renders synchronize the contextual button. Full work title is available in the work-switch tooltip.
- At desktop heights <=700px, left rail uses 44px primary controls and 40px utility controls with tighter gaps. Width remains 64px. At 820x520 the Settings control ends at 512px rather than below the viewport.

## Files
- services/halocue/writing/web/app.js
- services/halocue/writing/web/index.html
- services/halocue/writing/web/authoring-ui.css
- services/halocue/writing/tests/test_topbar_manuscript_save.py
- services/halocue/writing/tests/test_writing_entry_polish.py (fixture helper inclusion)
- services/halocue/integrated/tests/test_production_navigation.py

## Validation
- python -m pytest services/halocue/writing/tests/test_topbar_manuscript_save.py services/halocue/writing/tests/test_writing_entry_polish.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/writing/tests/test_writing_responsive_shell.py -q: 28 passed.
- python -m pytest services/halocue/integrated/tests/test_production_navigation.py -k 'topbar_named or short_window_navigation' -q: 4 passed, 17 deselected.
- node --test services/halocue/writing/tests/chapter_navigation.test.cjs services/halocue/writing/tests/agent_main_surface.test.cjs: 18 passed.
- node --check services/halocue/writing/web/app.js: passed.
- git diff --check on changed tracked source/test files: passed.
- Browser acceptance: clean scene hides top Save; clicking start-writing preserves textarea focus and reveals enabled top Save with dirty status. Separate fresh preview checks Settings actually opens/closes, short-window nav utility bounds, no horizontal overflow and empty console error log. Viewport reset; prior unsaved tabs not refreshed. Automated save tests use fake controlled HTTP responses for success, failure, duplicate submission, native validation and navigation during save; no live work revision created.

Full suite and packaged desktop validation not performed.