# Permission popover layout — 2026-09-24

User describes three writing workflows: import an existing script and revise with AI; discuss with AI and draft from the established outline; alternate manual writing and AI supplementation. These should share the authoring workspace rather than become disconnected modes. User also requests careful cache-hit work; no provider/cache change or claim of measured improvement in this UI slice. Future cache audit should validate real usage telemetry, stable context reuse, fresh authored revisions and scene/work scope isolation.

Immediate requested fix: permission options appeared as a vertical strip. Actual browser measurement showed a 28px text column and ~608px popover height. shell.css still used an obsolete icon/text/check three-column grid although renderPermissionMenu now emits text/check only.

Fix: two-column flexible text/check layout in shared base; selected check keeps a reserved column. Scoped theme-token styles for works/writing; choice title/description spacing, natural wrapping, selection and keyboard outline. Scene popover anchors to the whole composer rather than its narrow permission summary. Bounded viewport-relative max height with internal overflow; no permission handler, permissions, authorization rules or models changed. Cache-bust shell.css and authoring-ui.css in index.html.

Files: writing/web/shell.css, writing/web/authoring-ui.css, writing/web/index.html; writing/tests/test_permission_menu_layout.py.

Validation: permission layout + scene detail tests: 24 passed. Includes light/dark, writing rail240/340, phone390, works composer, height520, full safety copy, checked states and keyboard reachability. Actual browser right rail: text232px, popover~298px high; phone390x667: text319px, popover~240px high, no overflow. Open/close only, actual permission remains review. No source text changes or permission requests sent. Reset viewport, retained preview, original unsaved tabs untouched; console error log empty. git diff --check passed.

Additional composer_finish.test.cjs run: 1 passed, 1 failed. Its whole-file tail scope assertion flags the pre-existing agent-rail-title selector after the Composer finish section in agent-workspace.css (line383); that CSS and test are unchanged by this slice. Not fixed opportunistically. Full suite/build not run.