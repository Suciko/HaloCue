# 2026-09-19 — Agent workspace: script-first interaction

Scope: works/ideation only. Existing dirty work preserved; no commit or push.

## Implemented
- Discussion prompts default to AA-performable scripts, without asking the user to select prose versus script. Explicit prose requests remain supported. No accepted brief or revision is rewritten.
- Legacy generic format questions no longer occupy the decision dock when the user has not requested prose or a mode comparison. Original message remains visible, with a short explanatory note.
- New-conversation notice-only threads render the start surface and do not immediately offer Generate Plan.
- Inspector starts collapsed on works; explicit todo navigation opens it, returning to a decision closes it.
- New scoped agent-workspace CSS and JS: composer auto-height, clearer restart wording, expandable operation timeline, outside-click/Escape menus, focus return, latest-message navigation, restrained disclosure animation and reduced-motion support.
- Tool history is bounded to 12 displayed events with a notice; counts are activity events, not claimed unique calls.
- Restored decision rendering invokes enhancement hooks and preserves unsent input.

## Reference study
Read official deepseek-ai/deepseek-harness sources via GitHub API/raw: QuestionComposer.tsx and tool-call-tree.ts. Studied separation of questions, drafts, and tool activity. No upstream source copied or dependencies added. This is not a full Harness recreation.

## Verification
- Node syntax checks: app.js, shell.js, agent-workspace.js pass.
- node --test services/halocue/writing/tests/ideation_todos.test.cjs: 5 passed.
- pytest test_provider_tool_calling.py test_ba_skill_runtime.py test_agent_ui_and_prompt_contract.py: 37 passed.
- pytest test_agent_async.py test_agent_presentation.py: 21 passed.
- In-app browser, disposable fake fixture: custom option input; defer/reopen preserving custom text and composer draft; successful choice submission and acknowledgement; formal revision count remains zero; dark appearance; mobile todo dialog; menu Escape focus return; latest-message button; new thread start page.
- Real integrated workbench: no legacy mode decision dock; explanatory note shown; original history preserved; console error log empty.
- A final multi-width sweep on the real tab did NOT apply viewport changes (all observations remained 1468px); do not claim that sweep verified breakpoints. 390px was visually verified on the separate fixture.
- No real model requests made this turn; generated-response quality under the new prompt is not live-validated.
- Integrated service restarted only after checking both works for active agent runs (none). Current local PID 48432, same runtime data paths.

## Evidence and remaining scope
Maintainer-local screenshots outside repository: output/2026-09-19-agent-workspace/{01-dark-options,02-mobile-dark,03-mobile-todos,04-empty-workspace-dark,05-live-workbench}.png.
Right-side dedicated artifact preview, streaming transport/partial response layout, and exhaustive modal lifecycle redesign remain follow-up work. Source-thread proposal navigation retains prior limitations. Full repository regression not run.
