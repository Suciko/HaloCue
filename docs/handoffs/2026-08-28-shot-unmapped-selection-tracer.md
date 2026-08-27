# Handoff: Unmapped Shot Timeline selection tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: explicit selected-state feedback for advanced events absent from the render timeline
- Status: implementation complete, pushed with the commit listed below

## Delivery

When Professional Shot Timeline selection points at a stable event that the
current render timeline cannot map, the header now distinguishes it from an
empty selection: it shows the event kind, stable event ID, and `未映射`.
The existing unmapped-event diagnostic remains visible. The inspector keeps
the authored event selected, shows `开始帧: 未映射`, and does not render a
fabricated timing projection. Selecting a renderable clip immediately restores
track and frame context.

This is a projection/UI-only change. It does not add a contract version,
absolute start time, project field, revision, history entry, or alternate event
model.

## Studio evidence

First-party sources reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public Studio workspace keeps selected Block identity, preview position,
and inspector context visible even when the selected content is not a normal
timeline item. HaloCue applies that identity-first feedback while preserving
the explicit distinction between authored events and renderable timeline
clips. No private implementation or application asset was used.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit

- `40f5123 feat(1.1): clarify unmapped shot selection`

## Verification

- Red: the new UI test failed because an unmapped selected event was announced
  only as `未选择可渲染事件`.
- Focused: `npm test -- --run src/shotTimelineUi.test.tsx` -> **10 tests passed**.
- Full editor suite: `npm test` -> **25 files, 145 tests passed**.
- Build: `npm run build` passed. Vite retains the known runtime font URL as an
  external asset for the optional preview service.
- Browser: Playwright CLI selected the existing `halocue.ba:reaction-beat` in
  `沉默`, switched to Shot Timeline, and captured
  `output/playwright/shot-unmapped-selection.png`. The page showed the stable
  ID and `未映射`, one unmapped-event notice, and no timing projection; the
  inspector showed `未映射` for start frame.
- `git diff --check` passed before commit.

The optional renderer at `127.0.0.1:8898` was stopped, so the embedded preview
reported the known proxy errors while editor selection and projection behavior
remained healthy.

## Next bounded slice

Review the remaining shot projection gap before editing clips: add a compact
read-only legend for sequential versus non-blocking clips, using the existing
`wait_for_completion` field and parallel visual treatment. Keep the legend
derived, localized, and outside the canonical project model.
