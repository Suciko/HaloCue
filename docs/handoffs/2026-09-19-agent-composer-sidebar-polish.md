# 2026-09-19 — Agent composer and sidebar polish

Works surface only; dark function rail preserved. No backend/story changes or model calls.
- Outline SVG icons replace the large character glyphs while retaining labels; hidden outside works.
- Composer auto-height floor reduced to 42px; empty send is visually subdued, input highlights it. Native required validation unchanged.
- Starter prefills emit input so height and visual state update.
- Thread spacing, title/date hierarchy, new-thread controls, footer refined. Row action buttons reveal on hover/focus (always available to touch); menu dismissal includes thread actions.
- Desktop conversation-rail toggle moved to header with collapse/restore labels and aria-controls; old midpoint toggle hidden, resizer retained. No width animation added (avoid moving reading text).

Verification: JS syntax passed; 21 Node tests passed. Live browser: collapse produces display:none and width 0, header reopens rail; nine icons; empty composer ~125px; entering test text highlights send, Ctrl+A/Backspace returns empty state. 390px no document horizontal overflow. Light/dark screenshots viewed. Theme restored to system, test draft removed, no messages sent. Browser automation fill('') was a no-op; keyboard clearing worked, no app cache change needed.

Evidence outside repository: output/2026-09-19-agent-polish/01-desktop.png, 02-collapsed.png, 03-mobile.png, 04-dark.png (dark screenshot includes unsent QA text, subsequently removed). Only targeted tests; full suite not run. Uncommitted work preserved.
