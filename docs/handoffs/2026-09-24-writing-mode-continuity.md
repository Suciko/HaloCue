# Writing mode continuity and empty manuscript entry — 2026-09-24

## Scope
Current dirty branch preserved. No commit, push, build, deployment or real provider call. This slice follows the writing-sidebar polish; it does not redesign proposal acceptance/undo.

## Changes
- Canonical handleAppRouteClick now preserves draft/structure/release when selecting a chapter. Re-selecting the active chapter is a no-op, preserving its active scene and unsaved editor. Legacy workbench handler delegates rather than maintaining another transition.
- Chapter disclosure has a separate sibling button with aria-expanded. It only changes ephemeral tree expansion keyed by work/chapter; it does not navigate or mutate manuscript state.
- Chapter switching resets scene context and context-editor state, closes the mobile scene drawer, and retains existing unsaved-navigation confirmation. Cancel leaves the editor intact. No automatic save/generation is introduced.
- selectedScene respects explicit chapter scope. An empty chapter cannot display the first scene from another chapter; draft displays an explicit link to establish scenes in structure.
- Empty scene command is a compact hint. Detailed prerequisites and their resolution remain in Agent. A ready Agent entry still only prefills a request, never sends automatically.
- Empty manuscript has one large keyboard-accessible writing entry; it creates a local paragraph and focuses text. Empty status is 尚未开始; save is disabled until editing. Dirty changes update both local badge/save button and global save status.
- Sidebar widths, resize handling, review/release actions for existing revisions and provider gates retained.

## Files
- services/halocue/writing/web/app.js
- services/halocue/writing/web/writing-workbench.js
- services/halocue/writing/web/authoring-ui.css
- services/halocue/writing/web/index.html
- services/halocue/writing/tests/chapter_navigation.test.cjs
- services/halocue/writing/tests/test_writing_entry_polish.py
- services/halocue/writing/tests/test_writing_sidebar_layout.py

## Final validation
- python -m pytest services/halocue/writing/tests/test_writing_entry_polish.py services/halocue/writing/tests/test_writing_sidebar_layout.py services/halocue/writing/tests/test_writing_handoff_ui.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/writing/tests/test_agent_ui_and_prompt_contract.py -q: 25 passed.
- node --test services/halocue/writing/tests/chapter_navigation.test.cjs services/halocue/writing/tests/writing_handoff.test.cjs services/halocue/writing/tests/agent_main_surface.test.cjs: 24 passed.
- python -m pytest services/halocue/integrated/tests/test_production_navigation.py -k sidebar_resize -q: 4 passed, 13 deselected.
- node --check for app.js and writing-workbench.js: passed.
- git diff --check on app.js, writing-workbench.js and index.html: passed.

Internal browser used synthetic local fixture, separate from original page. Verified draft-to-draft chapter selection, structure-to-structure chapter selection, independent expansion, click-to-write focus, dirty-navigation dialog and cancel retention, mobile Agent/manuscript return. Restored viewport. Final fresh preview has no test paragraph; original page with prior unsaved state was not refreshed. Preview error log was empty. Synthetic fixture writing-target saves occurred through normal navigation; no formal manuscript was saved or model request sent.

## Limits
Full repository suite and packaging not run. Unsaved work remains protected by the existing stay/discard dialog, not new automatic persistence. Proposal apply/undo lifecycle is intentionally outside this slice.