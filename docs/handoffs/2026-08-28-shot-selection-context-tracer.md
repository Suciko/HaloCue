# Handoff: Shot selection context tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: selected Clip context and stale-selection handling on Cue changes
- Status: implementation complete, pushed with the commit listed below

## Delivery

The Professional Shot Timeline header now shows the currently selected
renderable clip and its derived frame range. When the selected event cannot be
mapped into the current Cue's render timeline it instead shows
`未选择可渲染事件` rather than inventing timing.

Changing Cue continues to be editor-state-only: the new Cue selects its first
event, clears the old preview playhead, and leaves project revision/history
unchanged. The Shot Timeline projection is recomputed from the new Cue, so old
clips cannot remain highlighted. This keeps the selected event as the shared
coordination point for the Script view, preview toolbar, inspector projection,
and Shot Timeline.

## Studio evidence

First-party sources reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public editor overview keeps an ordered Block list, realtime preview,
playback position, and the selected Block's inspector visibly connected. The
Stage Animation image puts the selected clip/key point, semantic tracks,
playhead ruler, preview, and property editor in one focused shot workspace.
HaloCue adopts the information relationship and selection feedback, while
retaining its own ordered event model and derived `shot-timeline/1.0`
projection. It does not copy Studio implementation, branding, layout assets,
or absolute-time editing semantics.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit

- `8c42892 feat(1.1): surface selected shot context`

## Verification

- Red: the new UI test failed because no selected-clip context element existed.
- Focused: `npm test -- --run src/shotTimelineUi.test.tsx src/projectStore.test.ts`
  -> **29 tests passed**.
- Build: `npm run build` passed. The known runtime font URL remains external
  for the optional preview service.
- Browser: Playwright CLI at 1280x900 switched from the first Cue to
  `意外来客`; the header changed to the new Cue and first event, the previous
  clip disappeared, and the preview playhead reset. The editor still reported
  only the known stopped-renderer proxy errors.
- `git diff --check` passed before commit.

## Next bounded slice

Use the same selected-event seam to make Shot Timeline clips keyboard-operable
as a focused list: expose a deterministic clip order, arrow/Home/End movement,
and focus-visible selection without creating project history. Keep ruler
scrubbing and absolute start-time editing separate until clip selection is
stable under both pointer and keyboard input.
