# 2026-09-24 — Author-facing AI change review

## Scope and provenance
- Release: local 1.0 writing workbench; owner: client presentation over the existing writing service.
- User request: improve manuscript interaction and make additions, modifications and deletions inspectable in the initial story discussion, informed by the locally installed DeepSeek Harness.
- Branch: `codex/1.0-release-readiness-20260914` (existing working checkout).
- Issue: no matching writing issue was returned by the scoped issue lookup. This is a local user-requested slice, not a merged/released issue claim.
- Sources of truth: `CONTEXT-MAP.md`, `docs/product-direction-1.x.md`, client/AI context invariants, ADR-0003, and the repository memory/collaboration protocols.
- Reference: maintainer-local installation of `@deepseek-ai/dsh`, especially its tool diff-card presentation. Inspected intended/applied diff behavior; no third-party implementation or user data copied into this repository.
- The checkout already contains extensive unrelated uncommitted edits. They were preserved; no commit, push or PR was made for this slice.

## Changes
- New pure `web/change-review.js` projects formal/candidate content into add/modify/remove rows with before/after values. It covers direction, chapter plans, structure placeholders/new entities, and durable knowledge field diffs.
- Direction/structure cards, chapter review and knowledge decision docks include an explicit pending change list. Baseline mismatches, missing before/after records and integrity failures do not produce misleading counts.
- Scene review uses the authoritative `block_changes` and keeps one existing selection checkbox per change. The existing `selected_change_ids` accept request and server version checks are unchanged.
- Expanded review values are complete, escaped text, not truncated previews. Desktop uses before/after columns; narrow viewports stack the two sides. Operation names accompany the colors.
- Removed the small nested scroll region for the now-expanded scene review rows. The document remains the scroll owner and the decision footer is sticky.
- Full-scene preview now traverses original block coordinates like selective acceptance. Previously, earlier deletions could make trailing deletions disappear from the preview; speaker-only changes could also hide the old speaker. Both have regressions.
- `index.html` loads the review projection before `app.js` and scoped review styles after the legacy theme.
- No API, persistence, model policy, or schema changes. AI output remains a proposal until explicitly accepted.

## Files in this slice
- `services/halocue/writing/web/change-review.js`
- `services/halocue/writing/web/change-review.css`
- Targeted integration changes in `services/halocue/writing/web/app.js` and `index.html` (both already dirty).
- `services/halocue/writing/tests/change_review.test.cjs`
- `services/halocue/writing/tests/test_change_review_ui.py`
- Updated one renderer-location/copy contract in `test_http_api.py` (already dirty).

## Validation
- `node --check services/halocue/writing/web/app.js`: passed.
- `node --check services/halocue/writing/web/change-review.js`: passed.
- `node --test services/halocue/writing/tests/change_review.test.cjs services/halocue/writing/tests/agent_main_surface.test.cjs`: 27 passed.
- `python -m pytest services/halocue/writing/tests/test_change_review_ui.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/writing/tests/test_agent_ui_and_prompt_contract.py services/halocue/writing/tests/test_ui_polish_layout.py services/halocue/writing/tests/test_http_api.py::test_scene_candidate_keeps_full_context_and_selective_change_review -q`: 25 passed.
- Final CSS refinement reran `test_change_review_ui.py`: 7 passed.
- UI tests render shipping functions and all shipping CSS with synthetic proposal state. They check keyboard disclosure, complete/escaped content, light/dark contrast, 390/1280 widths, no horizontal overflow, no nested review scrolling, selection/all/none and the exact partial-accept request. Requests are intercepted; this is not a live-model or persisted acceptance test.
- Maintainer-local visual evidence: `output/2026-09-24-change-review/` in the project workspace, outside the source repository. Desktop/narrow dark scenes and light/dark direction screenshots were captured; desktop direction and scene screenshots were visually inspected.

## Limits / next bounded action
- Not a complete redesign of the manuscript editor. Existing inline editing, selection tools, save/navigation guards, and discussion history remain.
- This adds pending review, not a new post-accept revision history or per-field acceptance for direction/structure proposals.
- No real model calls and no formal user story edits. No installed desktop package rebuild or deployment.
- Before sharing a PR, isolate this slice from the pre-existing working-tree edits. Then validate the complete discussion → generated proposal → persisted selective acceptance flow against a disposable service, and rebuild the desktop package if requested.

## Follow-up — linked single-workspace interaction (same day)
User clarified that the priority is one coherent main window, less visual duplication and fewer manual steps. Acceptance therefore used the **Codex in-app browser**, running the full workbench against a disposable `WritingService` with an explicitly fake provider and a synthetic rule pack, not only isolated render tests.

### Observed and fixed
- Removed the duplicate current-manuscript rendering and the repeated next-action banner while a scene proposal is being reviewed. The pending review is the main document surface.
- Moved full context, impact and runtime provenance under one secondary disclosure. Small change sets (up to three) show before/after without an additional click.
- Work-level proposals now show the change review first, with the complete structure/direction overview collapsed, and no duplicate next-step status card above the same proposal.
- Every scene change has `讨论这项`. It opens the existing Agent composer, attaches the exact proposal/change identity without sending automatically, and preserves an existing draft. Sending includes both sides as quoted story context. `返回这项` brings focus back to the same change. Selection counts are shared with the Agent strip.
- Fixed the real mobile round-trip bug discovered in the in-app browser: `focusSceneDiff` previously forced `inspector='decision'` and rerendered. A second return to Agent then showed a decision placeholder instead of the composer. It now uses the same manuscript tab transition as user navigation and preserves the mounted composer.
- Fixed the sticky decision bar's containing block: the outer review's `overflow:hidden` prevented it from following the actual workspace scroll. There is no new popup, detached editor or review-specific window.
- Additional touched file: `web/writing-workbench.js`; regression added to `tests/test_manuscript_interaction_ui.py`.

### In-app browser acceptance
- Desktop: opened the complete scene workspace; discussed the second change; returned to that exact change with the input draft intact and the decision bar within the viewport.
- Sent one discussion message to the fake provider; the actual saved conversation visibly contained the correct old/new blocks. No real model requests.
- 390 × 844: unchecked the second item, entered Agent, typed an unsent draft, returned to the second change and entered Agent again. Verified **one composer**, same draft, same reference and retained selection. Document horizontal overflow was zero. Temporary viewport override was reset.
- Accepted only the first change in the disposable scene: work version advanced from 10 to 11; the first dialogue changed; the unselected second narration retained its original text. Reload confirmed persisted content and no pending review. Browser error log was empty.
- Work discussion: verified one main change-review list, optional full structure overview, original composer and one set of decision controls.

### Latest tests
- `node --test services/halocue/writing/tests/change_review.test.cjs services/halocue/writing/tests/agent_main_surface.test.cjs`: **30 passed**.
- Previous five-file Python/UI command: **26 passed**, including the added two-round-trip/draft/selection regression.
- JS syntax checks, narrow diff whitespace checks and Ruff on the new UI test passed.

### Remaining boundary
This is still local source work, not a rebuilt installed desktop release or a complete redesign of every authoring screen. User works and model credentials were not used. The disposable browser service is for inspection only; its test data can be discarded when no longer needed. Earlier limitations about not performing live end-to-end persisted acceptance are superseded by the fake-service in-app acceptance above; real-provider acceptance remains untested.

## Follow-up — workspace-edge scrolling and editorial layout
- User screenshot exposed the conversation scrollbar inside the centered content column. In-app measurements: workspace width ~1155 px vs. thread width 820 px, leaving ~175 px between thread right and workspace right.
- Root cause: later `agent-workspace.css` capped the entire canvas at 940 px and padded it; thread inherited additional margins. A parent `scrollbar-gutter:stable` also reserved an unused 15 px gutter.
- Fixed ownership: canvas and thread span the main workspace; only thread content/composer use the shared 900 px reading-width token. Header spans the work surface, composer stays centered, parent workspace has no second scroll gutter. Preserve the existing thread element/scroll handlers so follow-latest behavior and Agent links are not replaced.
- Visual direction: restrained editorial workspace. Flattened nested review-card borders, clearer field-name hierarchy, gentler composer shadow, shared content alignment. Existing palette and dark/high-contrast preferences are preserved; this is not a wholesale app-wide theme replacement.
- New test: `tests/test_conversation_scroll_layout.py`, 8 cases spanning 1756/1280/390 widths, light/dark, initial and long conversations, short mobile height. Initially failed the edge-gap assertion; after changes all 8 passed.
- Combined command: `python -m pytest services/halocue/writing/tests/test_conversation_scroll_layout.py services/halocue/writing/tests/test_change_review_ui.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/writing/tests/test_ui_polish_layout.py -q`: **29 passed**. Ruff on the new test passed.
- In-app browser at 1756 x 1000: workspace right and scrollport right both 1744 px (the final 12 px is the existing collapsed panel handle), gap 0, outer vertical overflow 0, horizontal overflow 0, composer width 900 px and bottom 959.5 px. Closing the conversation sidebar retained edge gap 0.
- In-app at 390 x 844: gap 0, horizontal overflow 0, composer bounds x=16..374 and bottom 755.5; no overlap with the mobile navigation. Temporary viewport reset after acceptance. No model calls or story edits in this visual follow-up.
- Files changed this follow-up: `web/agent-workspace.css`, `web/change-review.css`, stylesheet cache labels in `web/index.html`, the new layout test and this handoff. No commit/push/package build.
