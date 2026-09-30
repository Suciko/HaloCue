# Writing entry paths — 2026-09-25

- Kind: handoff; status: local implementation, not published.
- Scope: existing 1.0 writing web client; no release-positioning or contract change.
- Source: user-authorized continuation; docs/product-direction-1.x.md, CONTEXT-MAP.md, contexts/client/CONTEXT.md, ADR-0006; preceding 2026-09-24-manuscript-assistant-details.md.
- Branch: codex/1.0-release-readiness-20260914. Preserve pre-existing dirty changes.
- GitHub issue: no match returned for repository writing UI search; no new remote issue or PR created in this local slice.
- Smallest slice: discoverable empty-scene import/discussion/manual entry, saved-manuscript continuation prompt, retain unsent composer text. No model calls, backend change or automatic adoption.

## Changes
- Empty manuscript retains the direct writing area, with a paste/save hint and two secondary actions: 按大纲讨论 and 导入已有文稿. No new mode model or panel. The options disappear when the first manuscript block is inserted.
- Outline entry uses the existing linked assistant opener; fills only an empty composer, dispatches input, preserves existing unsent instructions, and focuses correctly after mobile pane switching. It requests discussion of confirmed outline/current-scene goals, not automatic generation.
- Import entry uses existing data-aap-import dispatch and preview dialog, with no importer/backend changes.
- Saved-manuscript quick actions now include 接着往下写: discuss continuation from saved text and confirmed outline, preserve existing writing and scene boundary, then propose for review.
- Scene quick-action chips append rather than overwrite unsent composer text; repeated clicks do not duplicate the same suggestion. No submit is triggered.
- Centered manuscript width, permission controls, generation gates, manual-save prerequisite, and Proposal adoption remain unchanged.

## Changed paths in this slice
- services/halocue/writing/web/app.js
- services/halocue/writing/web/writing-workbench.js
- services/halocue/writing/web/authoring-ui.css
- services/halocue/writing/web/index.html (three cache-version tags)
- services/halocue/writing/tests/test_scene_detail_polish.py
- services/halocue/writing/tests/test_writing_entry_polish.py

## Validation
- `python -m pytest services/halocue/writing/tests/test_writing_entry_polish.py services/halocue/writing/tests/test_scene_detail_polish.py services/halocue/writing/tests/test_topbar_manuscript_save.py services/halocue/writing/tests/test_writing_responsive_shell.py services/halocue/writing/tests/test_scene_message_ui.py -q`: 54 passed.
- `python -m pytest services/halocue/writing/tests/test_aap_import.py services/halocue/writing/tests/test_story_import.py services/halocue/writing/tests/test_import_adoption.py -q`: 8 passed.
- `node --check` for app.js and writing-workbench.js: passed.
- `git diff --check` on six edited source/test paths: passed.
- Internal browser, existing synthetic fixture on port 8765: desktop and 390x844 entry layout inspected; outline action opens/focuses assistant and prefills without sending; quick-action append preserves original prompt; import dialog opens and cancel returns with text intact. Test composer text cleared, viewport reset. Original unsaved tabs untouched. Preview tab 6 retained.

## Limits / next bounded action
62 targeted tests, not the full suite. No real model requests, file upload through browser, user manuscript saves, deployment, commit or push. Import end-to-end model conversion was not re-run; existing offline importer tests only. Real cache hit rates were not measured. Changes remain local on the dirty branch and must be separated from pre-existing changes before any future commit. Next useful slice is a synthetic full mixed-writing/review flow, rather than adding more mode buttons.
