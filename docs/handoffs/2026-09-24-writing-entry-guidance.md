# 2026-09-24 — Ideation-to-writing next-step guidance

## Scope
User requested concrete, discoverable clicks for the transition from story discussion to scene writing. Client presentation only on existing branch `codex/1.0-release-readiness-20260914`; existing dirty changes preserved. No new issue, commit, push or package build. Source-of-truth: product direction, client context and earlier authoring handoffs.

## Changes
- `app.js`: pure `nextWritingScene` selects saved drafted scene, otherwise first unwritten scene. `writingHandoffMarkup` replaces generic user-status guidance when confirmed structure is actually writable. Suppressed for pending/blocked/running/unconfirmed/completed-all-scenes states; does not bypass existing gates.
- Work discussion shows a named scene, its goal, `开始写第一场` / `继续写这一场` and optional `查看章节安排`. Uses the existing `data-scene-open` command and saved writing target. No auto-navigation on acceptance or model call on entry.
- `writing-workbench.js`: a pending structure has specific copy and `回到构思，审查章节安排`, using the existing proposal-focusing route. Chapter plan uses the same scene recommendation and primary direct-entry button, rather than only asking for more discussion.
- Empty ready scene offers `让 Agent 起草本场` and `自己写`. Agent entry opens existing composer and fills a bounded request only if blank; existing draft is preserved and nothing is submitted. Missing character evidence retains the prerequisite action and offers manual writing separately.
- Manual writing uses the existing insert-first-paragraph action and focuses its text field. It creates an unsaved local draft, not a formal revision.
- Styling added to existing authoring CSS, responsive layout and named regions. Asset cache labels updated.

## Validation
- Internal browser, fake provider: started on blocked chapter page, clicked back to the exact pending structure, accepted it in the disposable work, saw `开始写第一场`, clicked directly into the correct scene. No directory detour and no drafting model call.
- Old long-running temporary fixture later returned FileNotFoundError on work retrieval (metadata list still existed). No source fix or user-data migration attempted. Started a fresh isolated fixture at its returned port and repeated structure acceptance and chapter-directory entry successfully.
- In the fresh fake work, missing character cards were truthfully shown. Clicking `自己写` created one textarea with activeElement.name=text and an unsaved indicator. No typed story or formal revision saved. Browser left on this test-only input for inspection.
- `node --test services/halocue/writing/tests/writing_handoff.test.cjs services/halocue/writing/tests/agent_main_surface.test.cjs`: 18 passed.
- `python -m pytest services/halocue/writing/tests/test_writing_handoff_ui.py services/halocue/writing/tests/test_agent_ui_and_prompt_contract.py services/halocue/writing/tests/test_manuscript_interaction_ui.py services/halocue/writing/tests/test_ui_polish_layout.py -q`: 20 passed in 28.34s.
- New UI tests execute shipping entry-handler code at 1280 and 390 widths: draft prefill, existing-draft preservation, focus, existing panel/tab selection and zero form submissions.
- The ready-scene Agent branch was tested with controlled shipping-handler fixtures, not by generating a real model answer. No real user story or credentials used.

## Files
- `services/halocue/writing/web/app.js`
- `services/halocue/writing/web/writing-workbench.js`
- `services/halocue/writing/web/authoring-ui.css`
- `services/halocue/writing/web/index.html`
- New `services/halocue/writing/tests/writing_handoff.test.cjs`
- New `services/halocue/writing/tests/test_writing_handoff_ui.py`

## Limits
This slice clarifies navigation; it does not add automatic scene generation or loosen character-card/model prerequisites. Original full suite and installed desktop package have not been rebuilt/verified. Remote work handoff needs isolation from the pre-existing mixed working tree.