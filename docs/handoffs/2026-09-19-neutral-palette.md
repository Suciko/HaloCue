# 2026-09-19 — Neutral ideation palette

Scope: color-only changes to the works/Agent surface, using route-scoped tokens in agent-workspace.css. index.html asset query updated. No backend, layout, or story mutations.

- Light foundation: white canvas, shared #f7f7f8 rails, neutral selected conversations.
- Dark foundation: #202022 canvas, #19191b rails, #323238 selection; no blue-tinted structural surfaces.
- Azure action: #4263d4/light with white text; #a4b8ff/dark with #17171a text. Other chosen accent palettes still inherit appearance settings.
- Foreground/secondary text aliases unified; high-contrast overrides retained. Success/warning/error semantic colors untouched.
- Scoped selectors deliberately outrank existing dark legacy rules. Other workspaces/dialogs not restyled in this slice.

Validation: 7 Node tests pass (theme preferences + neutral token contrast/scope). Live integrated browser light/dark screenshots inspected; actual computed contrast for send, helper, body, active navigation: light 5.29/5.68/15.28/12.62; dark 9.27/7.39/13.92/10.90. These are sampled controls, not a complete accessibility audit. User theme preference restored to system after QA. No model calls or story edits.

Maintainer-local evidence outside repository: output/2026-09-19-neutral-palette/01-light.png and 02-dark.png. Custom accent and mobile states not visually rechecked this turn. Changes uncommitted; unrelated working-tree changes preserved.
