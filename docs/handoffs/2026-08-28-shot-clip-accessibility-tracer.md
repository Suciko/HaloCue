# Handoff: Shot clip accessibility context tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: semantic track and frame announcements for selected Shot Timeline clips
- Status: implementation complete, pushed with the commit listed below

## Delivery

Shot Timeline clip labels now include the semantic track (`Stage`, `Character`,
`Dialogue / Overlay`, or `Effect / Timing`) as well as the derived inclusive
display range. The selected-clip header context is a polite, atomic live region
so pointer and keyboard selection announce the same coordination state.

This is presentation-only. The canonical ordered events, `shot-timeline/1.0`
projection, selection IDs, playhead, revision, and history are unchanged.

## Studio evidence

First-party sources reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public Stage Animation workspace groups selected timeline objects by
semantic track and keeps their timing visible next to the preview and
inspector. HaloCue carries that relationship into keyboard and assistive
technology feedback without copying private code, branding, layout assets, or
absolute-time authoring.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit

- `2c3f0cc feat(1.1): announce shot clip context`

## Verification

- Red: the new UI test failed because clip labels omitted their semantic track.
- Focused: `npm test -- --run src/shotTimelineUi.test.tsx` -> **9 tests passed**.
- Full editor suite: `npm test` -> **25 files, 144 tests passed**.
- Build: `npm run build` passed. Vite retains the known runtime font URL as an
  external asset for the optional preview service.
- Browser: Playwright CLI at 1280x900 showed
  `Stage，背景，第 0 至 17 帧` and the live header `已选 背景 · F0-17`;
  the tab/clip screenshots remain in `output/playwright/`.
- `git diff --check` passed before commit.

The optional renderer at `127.0.0.1:8898` was stopped, so the embedded preview
still reports the known proxy errors while editor behavior remains testable.

## Next bounded slice

Add an explicit empty-state treatment for an unmapped advanced event in the Shot
Timeline inspector/header: keep its stable selection, show a diagnostic instead
of fabricated timing, and verify switching back to a renderable clip restores
the normal context. Do not add an absolute start-time editor or new contract
version for this projection-only state.
