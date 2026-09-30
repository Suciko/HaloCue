# 2026-09-19 — Main Agent conversation composition

Scope: works/ideation main surface only. Preserve the user-approved dark function rail. No backend/model policy changes this turn. No commits/pushes; existing dirty changes preserved.

## Implementation
- Empty/notice-only conversation: centered heading + composer + editable starter prompts. One composer in both states. Pending proposals/decisions/runs keep the normal conversation layout.
- Existing conversation: compact thread title, task-record entry, lighter assistant identity, aligned reading column. User bubbles and assistant prose have distinct weights.
- Tool rows are tied to the original message/run and expand individually with stable disclosure IDs. Unknown status is not called completed. Existing failed-run recovery branch is retained. Full task records remain reachable via header; duplicate global process card removed from the main conversation.
- Escaped limited prose rendering for paragraphs, lists, headings, inline/fenced code; model HTML is never executed. Not a full Markdown implementation.
- Composer: model settings entry, circular send control, low-frequency organize action under more menu. Duplicate mobile conversation-list button removed from composer (header entry retained). More menu supports outside click/Escape + focus return.
- Copy reply reports success/failure; draft and expanded tool state survive in-scope rendering. Notice messages render as subdued notices rather than assistant replies.

## Validation
- node --check app.js / agent-workspace.js: passed.
- node --test services/halocue/writing/tests/{agent_main_surface,ideation_todos,neutral_palette,theme_preference}.test.cjs: 20 passed.
- python -m pytest services/halocue/writing/tests/test_agent_ui_and_prompt_contract.py services/halocue/writing/tests/test_agent_presentation.py -q: 20 passed.
- In-app browser with disposable fake service: new-thread centered layout, starter prefill without sending, explicit send -> bottom composer, tool disclosure + state retained after another response, draft retention on opening inspector, more-menu Escape/focus, copy success, model settings entry, light/dark pages.
- Responsive measurements from actual test-tab viewport: widths 390/761/1115/1440 all had no document horizontal overflow; composer stayed on screen. Mobile circular send 44x44. Short 390x560 start layout scrollable with send visible.
- Fixture formal revisions still zero after simulated conversation sends. No real model requests or real story edits.
- Live integrated workbench reloaded, actual tool/prose rendering visually checked; browser error log empty. User theme preference untouched.

## Evidence / limits
Maintainer-local screenshots outside repository under output/2026-09-19-agent-main:
01-start-dark.png, 02-start-light.png, 03-mobile-conversation.png, 04-mobile-start.png, 05-tools-decisions-dark.png, 06-live-conversation.png.
No new live-streaming transport, standalone artifact-preview redesign, or full repository regression. Full task history still uses the existing task page. Browser fixture tab closed and its service stopped after QA; integrated service not restarted.
