# Chapter reading orientation — 2026-09-24

User authorized a self-defined goal: keep chapter title/tools visible on first-scene entry, accurate later-scene navigation, and preserve reading position across Agent/manuscript views. No added permanent panel.

## Findings and fixes
- In-app reproduction: first scene auto-scroll moved workspace by ~73px, placing chapter header above viewport (top ~3px vs workspace top56px).
- scrollToChapterScene now targets workspace top for the first chapter scene; later scenes retain desktop/mobile header offsets.
- Replaced 0/120/360ms repeated scene-position timers with one layout-frame request. Ticket, work/chapter/scene identity, current view and user-scroll intent reject stale requests.
- Existing mobile restoration now guards delayed work with a view ticket, work/chapter identity and scroll intent. It cannot overwrite a deliberate scroll, a new chapter or subsequent view change.
- Updated writing-workbench asset version in index.html.

## Files
- services/halocue/writing/web/writing-workbench.js
- services/halocue/writing/web/index.html
- services/halocue/writing/tests/test_chapter_scroll_orientation.py

## Validation
- New focused regression first failed on first-scene header visibility, then passed. Includes later-scene offsets at desktop/mobile widths, coalesced/stale scheduled positions, and mobile restoration under user scroll/chapter/view changes.
- python -m pytest services/halocue/writing/tests/test_chapter_scroll_orientation.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/writing/tests/test_writing_responsive_shell.py services/halocue/writing/tests/test_writing_handoff_ui.py -q: 26 passed.
- node --test services/halocue/writing/tests/chapter_navigation.test.cjs: 6 passed.
- node --check writing-workbench.js and git diff --check on tracked changed files: passed.
- Actual internal browser: safe clean preview reload and chapter switch keep scrollTop0, chapter heading top76px inside workspace starting56px. On mobile, direct pointer clicks Agent -> manuscript preserved scrollTop125.333px exactly. Locator auto-scroll before clicking initially interfered with that check; direct clicks on visible tab coordinates isolated the real behavior. Synthetic long-manuscript regression covers later-scene offsets and restoration with 2500px content. Restored original chapter, desktop viewport, directory-collapsed preference. Existing unsaved tabs untouched; no formal manuscript save or model call.

No whole-repository suite or packaging run. Existing mobile settling retries are retained for focus/layout stability, now cancellable by newer user intent.