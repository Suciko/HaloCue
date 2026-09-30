# Left navigation and functional topbar — 2026-09-24

Scope: authoring surfaces only. Existing dirty work preserved. No packaging, commit, deployment or model call.

- Left rail stays 64px: 52px primary controls, 46px utility controls, consistent 20px outline icons, quieter selected background without duplicate edge marker, and separation before resource navigation. Existing routes and utility actions retained.
- Writing topbar exposes named Directory / Agent controls using existing panel handlers. Focus toggle is visible again; focus exit restores the previous panel preference and compact-desktop active rail rather than blindly opening both.
- Redundant desktop workflow arrows and topbar help are visually removed on writing/ideation as scoped; workflow stages remain in the directory, help remains in global navigation. Work switch, breadcrumb, save status and model configuration are retained. Compact desktop hides the model badge, with settings still available; mobile prioritizes work switch and save status and hides desktop panel controls.
- Fixed workbench decoration to target the splitter toggle specifically, avoiding rewriting the new toolbar Directory icon/label.

Files: services/halocue/writing/web/{index.html,shell.js,writing-workbench.js,agent-workspace.js,authoring-ui.css}; services/halocue/integrated/tests/test_production_navigation.py.

Validation:
- Integrated sidebar resize tests: 4 passed. Named toolbar/focus restore tests: 2 passed (820/1440px, long work title, mobile 390px, exact preference restoration and label preservation).
- test_writing_responsive_shell.py + test_writing_sidebar_layout.py: 10 passed.
- node --test agent_main_surface.test.cjs chapter_navigation.test.cjs: 18 passed.
- node --check shell.js, agent-workspace.js, writing-workbench.js: passed.
- git diff --check on modified tracked files: passed.
- Actual internal-browser checks: Directory/Agent and Focus restore; viewport 390/700/761/820/1115/1440 without horizontal overflow; mobile save status visible. Viewport and original rail preference restored. Separate clean preview used; prior unsaved tabs not reloaded. Initial tests caught mobile save status hidden by a legacy rule and a generic decorator overwriting Directory label; both corrected before final passing runs.

No whole-repository suite or packaged desktop validation performed.