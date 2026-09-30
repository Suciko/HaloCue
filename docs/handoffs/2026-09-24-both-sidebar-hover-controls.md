# Symmetric sidebar seams and hover controls — 2026-09-24

User requested fixing the still-detached right Agent border and hiding edge collapse/expand buttons until hover.

Changes: consolidated writing-side resizer styles for both rails. Right seam sits at right:0 of its 12px gutter; removed duplicate Inspector left border. Full-height seams remain neutral under hover/focus; only a 72px local grip signals resize interaction. Expanded right button is aligned +6px to its panel edge (left mirrors -6px). Both edge buttons use rail material without independent border chrome.

Fine-pointer desktop buttons now fade with 160ms opacity: hidden at rest, visible on gutter hover, button hover, keyboard focus-visible or activation. Collapsed buttons remain hit-testable/keyboard-reachable in their edge slots. No display:none or pointer-events:none on controls; existing topbar Directory/Agent buttons unchanged. Touch/no-hover keeps buttons visible, reduced-motion removes transitions. No change to drag handlers, widths, panel preferences, data or proposal lifecycle. Stylesheet version bumped.

Validation:
- Integrated sidebar resize tests: 4 passed (updated visibility assertion to hover first).
- New integrated seam interaction tests: 2 passed, light/dark. Covers both edges, duplicate border removal, 12px hit area, neutral hover line, short grip, rest/hover fade, collapse/reopen, keyboard Tab/Enter, touch fallback and reduced-motion.
- test_writing_sidebar_layout.py + test_writing_responsive_shell.py: 10 passed.
- git diff --check on changed tracked files: passed.
- Actual internal browser: clean preview refreshed; right Inspector border0, seam neutral and attached to panel edge, buttons opacity0 at rest and opacity1 for keyboard focus. Prior unsaved page not refreshed. Preview retained.

Initial keyboard fixture used programmatic focus immediately after pointer activation (not focus-visible); replaced with actual Tab navigation to validate the requested keyboard behavior. Full suite/package not run. Files: writing/web/authoring-ui.css, writing/web/index.html, integrated/tests/test_production_navigation.py.