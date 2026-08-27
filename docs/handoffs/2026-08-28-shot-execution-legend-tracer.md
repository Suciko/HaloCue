# Handoff: Shot execution legend tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: derived execution-semantics legend for the Professional Shot Timeline
- Status: implementation complete, code committed and ready to push

## Delivery

The Professional Shot Timeline now exposes a compact, read-only legend for the
two execution semantics already present in the render projection: `顺序执行`
for blocking events and `与后续事件并行` for non-blocking events. The legend
uses the same green/amber visual treatment as the clips and remains outside the
canonical project model. It is available at narrow widths through a wrapping
layout and does not alter selection, preview position, undo/history, or project
revision state.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public Stage Animation workspace makes execution timing legible through a
dedicated multi-track timeline and keeps the active task's preview and property
context nearby. HaloCue adopts the information hierarchy and explicit timing
feedback, while keeping its own ordered event model and localized terminology.
No local decompiled implementation, recovered source body, source map, private
asset, or installed Studio/AA resource was read or copied into the repository.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit and verification

- Code commit: `ee0bf7a feat(1.1): add shot execution legend`
- Focused: `npm test -- --run src/shotTimelineUi.test.tsx` -> **11 tests passed**
- Build: `npm run build` -> passed. Vite retains the known runtime font URL as
  an external asset for the optional preview service.
- `git diff --check` -> passed before commit.
- Browser captures: `output/playwright/shot-execution-legend.png` and
  `output/playwright/shot-execution-legend-narrow.png`; desktop and narrow
  layouts show both legend entries, and the narrow layout keeps the timeline's
  horizontal scroll internal to the panel.

The optional renderer on `127.0.0.1:8898` was not running during the browser
check, so the embedded preview retained its known proxy/font warnings. Editor
DOM, timeline projection, and state interactions remained available.

## Next bounded slice

Push this focused commit and handoff. Then continue with a small selected-object
linkage tracer: verify that switching between Script and Shot Timeline preserves
one selected event, keeps the selected frame range visible in the preview
toolbar, and leaves preview seek/refresh state editor-only. Do not begin clip
resizing or audio tracks until that linkage is validated.
