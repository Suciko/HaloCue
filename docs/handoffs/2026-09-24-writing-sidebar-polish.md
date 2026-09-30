# Writing sidebar polish — 2026-09-24

Scope: writing-directory visual hierarchy and its left boundary only. Existing dirty changes preserved; no commit, package, deployment or provider request.

## Cause and change
- The tree had a right border; its adjacent 12px resize gutter also drew a 2px line offset 5px from the edge. Removed the duplicate tree border, put a single 1px separator at the edge, and aligned the collapse handle with it. The 12px hit target, keyboard handlers and persisted width budget remain unchanged.
- Compact one-line workflow selector plus a single stage-specific instruction. Gate reasons and click handlers retained; current stage has aria-current=step.
- Chapter titles now own the row (up to two lines), with scene count/status below. Full titles are available on hover. Volume headings and scene indentation are simplified; redundant hierarchy lines removed.
- Explicit grid rows prevent the extra instruction from stretching the structure header. Directory scroll stays in sceneTree rather than creating two nested scrollports.
- Mobile scene drawer copies the same markup outside #app, so directory styling explicitly covers that surface too.

## Files
- services/halocue/writing/web/authoring-ui.css
- services/halocue/writing/web/writing-workbench.js
- services/halocue/writing/web/index.html (asset versions)
- services/halocue/writing/tests/test_writing_sidebar_layout.py

## Validation
- python -m pytest services/halocue/writing/tests/test_writing_sidebar_layout.py -q — 6 passed. 180/236/320px, light/dark, shipping renderer + CSS, long titles, scroll, boundary, focus, gate metadata and 390px mobile drawer.
- python -m pytest services/halocue/integrated/tests/test_production_navigation.py -k sidebar_resize -q — 4 passed, 13 deselected. Drag, keyboard Home/End, collapse/restore, persisted width and narrow layouts.
- python -m pytest services/halocue/writing/tests/test_writing_handoff_ui.py services/halocue/writing/tests/test_ui_polish_layout.py services/halocue/writing/tests/test_agent_ui_and_prompt_contract.py -q — 11 passed.
- node --test services/halocue/writing/tests/writing_handoff.test.cjs services/halocue/writing/tests/agent_main_surface.test.cjs — 18 passed.
- node --check services/halocue/writing/web/writing-workbench.js — passed.
- git diff --check -- services/halocue/writing/web/index.html services/halocue/writing/web/writing-workbench.js — passed.

Internal-browser acceptance used the existing synthetic local fixture with fake provider in a separate tab; original unsaved page was not reloaded. Verified chapter selection, scene/main-pane linkage, 180px keyboard resize, actual pointer dragging and 390px scene drawer. Reset viewport and restored sidebar width to its observed original 231px, then returned preview to original scene. Full suite/build not run.
## Follow-up: detached accent seam
The user reported that the full-height blue interaction line still looked disconnected. The previous single-edge fix retained a full-height hover/focus accent and therefore did not fully solve the visual issue.

Updated authoring-ui.css: the left resize hit area is transparent; its full-height edge stays neutral during hover/focus. A 72px grip aligned with the collapse control appears only during interaction (neutral hover, accent keyboard/active). Expanded collapse control uses the rail background without a floating outline. Width budget, 12px pointer hit area and keyboard handlers are unchanged. Incremented the stylesheet asset version.

Validation: test_writing_sidebar_layout.py: 6 passed at 180/236/320px in light/dark, now asserting neutral full edge and bounded interaction feedback. The initial hover test targeted the center covered by the collapse button; corrected it to exercise the resize hit area above that button. Internal browser verified keyboard resize, restoring 231px, collapse/reopen and no grip at rest. Fresh preview updated; original unsaved page untouched.