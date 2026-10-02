# Writing narrow-window grid regression — 2026-09-24

User symptom: shrinking the app placed all writing content in a thin left strip, leaving the rest blank.

Reproduction: actual in-app browser at 700px, writing surface with tree-collapsed. Computed grid areas were single-column mobile, but columns remained `126px 0px 14px 210px 10px 340px`; workspace width was only 126px. Desktop collapsed selectors overrode the less-specific mobile columns rule. Width variables were not the cause.

Fix: scoped max-width:760px writing-shell rule in redesign.css resets columns, rows and areas together with sufficient specificity to override every persisted desktop collapse combination. No change to panel state, desktop widths or editor state. Updated stylesheet version in index.html.

Regression: new test_writing_responsive_shell.py uses actual index.html and shipped CSS in runtime order, checks all four collapse combinations at 375/390/700/760px and back to 1440px. Asserts main and bottom navigation span viewport, not only absence of document overflow. Initial run reproduced failure (760px viewport, 64px main); fixed run: 4 passed.

Other checks: `python -m pytest services/halocue/integrated/tests/test_production_navigation.py -k sidebar_resize -q`: 4 passed, 13 deselected. Internal browser checked 390,700,760,761,1000,1280px and back; mobile main width equals viewport and no horizontal overflow. Temporary viewport override reset. Original unsaved page not reloaded; safe preview refreshed. No model calls, data edits, packaging or full-suite run.