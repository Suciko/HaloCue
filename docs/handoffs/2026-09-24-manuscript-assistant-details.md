# Manuscript and assistant detail pass — 2026-09-24

User authorized the six screenshot-review improvements. Scope stays authoring UI: no backend, formal revision, provider call, package or deployment.

## Changes
- Empty manuscript begins directly below scene guidance. Removed inherited 360px minimum-height/vertical alignment, duplicate reassurance, empty green status and disabled bottom action chrome. Editing unhides editor metadata/save controls and hides startup guidance. Reading width is unchanged.
- Chapter header uses a short Chinese label and no instructional paragraph. Main action follows current state: 与助手讨论 / 修改本场正文 / 查看待审修改. Review action uses existing review handler; other actions open/focus the assistant without sending. Scope is explicitly current scene; review menu label fixed from 检查本章 to 检查本场.
- Removed redundant 查看 Agent and manual-start buttons from startup hint. Existing full ready/gated candidate flow remains available in assistant.
- Inspector title is 本场助手. Missing prerequisite notice is neutral, one compact summary/action plus expandable detail; duplicate blocked badge hidden. Other running/pending/ready statuses preserved.
- Only the exact server-authored initial assistant notice (kind notice, no tools/reasoning/proposal) is collapsed to a details disclosure. Full text remains inspectable; ordinary replies and unrelated notices remain normal messages.
- Composer placeholder shortened; prompt chips vary between empty manuscript, saved manuscript and pending candidate. Prompt buttons still only prefill, not send.
- Discuss action reuses existing assistant DOM to retain unsent text. On mobile it focuses the composer after tab-focus restoration.

## Files
writing/web: app.js, writing-workbench.js, authoring-ui.css, index.html.
writing/tests: test_scene_detail_polish.py (new), test_writing_entry_polish.py, test_scene_message_ui.py, test_http_api.py.
integrated/tests: test_production_navigation.py.

## Validation
- test_scene_detail_polish.py final run: 14 passed (empty/ready/existing/pending, desktop/narrow/light/dark, exact notice disclosure, real replies retained, gating and discuss-focus/draft preservation).
- Combined detail/entry/scene-message/manuscript/topbar-save run before final 2 focus tests: 53 passed.
- test_change_review_ui.py + test_chapter_scroll_orientation.py + test_writing_responsive_shell.py: 25 passed.
- Integrated scene active-run resume + mobile chat + topbar named controls: 6 passed.
- HTTP source contract for gated discussion/candidate generation: 1 passed.
- agent_main_surface.test.cjs + writing_handoff.test.cjs: 18 passed.
- node --check app.js / writing-workbench.js and git diff --check: passed (Git notes existing LF->CRLF normalization).

Updated test contracts deliberately: empty save/status now hidden; inspector label renamed; disabled candidate control was already hidden by authoring-ui.css, so running-state test now asserts it hidden and Stop visible. Isolated scene-submit fixture was missing existing sceneReviewDiscussionContext dependency; added an empty-review-context stub, no production dispatch logic change.

Internal browser used existing synthetic fixture: entry is ~36px below scene header rather than vertically centered; notice and missing-data details open correctly; opening assistant preserves unsent text. Mobile discuss focuses sceneAgentMessage without submitting. Test input cleared with real keyboard events; viewport reset and original manuscript data left untouched. Final preview has no console errors and is retained. Original unsaved tabs not reloaded. Full suite/build not run.