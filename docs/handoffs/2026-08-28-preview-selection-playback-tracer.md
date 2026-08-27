# Handoff: preview selected-range playback tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: bounded playback for the selected Professional event or Simple Cue
- Status: implementation complete and pushed

## Delivery

The preview toolbar now exposes `播放所选` whenever the shared selection has a
derived render range. Professional mode plays the selected event range; Simple
mode plays the complete selected Cue range. Both calls use the existing
end-exclusive render-timeline contract (`fromFrame = start_frame`,
`toFrame = end_frame - 1`) and clamp degenerate ranges without creating a new
timeline model.

The control is disabled until the current preview controller is ready. It does
not change the project JSON, editor revision, undo/redo history, autosave, or
selection. Existing `定位` and `从头播放` actions remain available beside it.

## Public Studio evidence and clean-room boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The editor overview and timeline image place preview transport, the selected
Block/clip, the playhead, and the contextual inspector in one task surface. The
toolbar's bounded playback follows that observable relationship while keeping
HaloCue's ordered events and derived timeline as the source of truth. No
decompiled implementation body, source map, private asset, font, bundle, or
installed Studio/AA resource entered the repository. Public images were
downloaded only to a system temporary directory for visual inspection.

## TDD and verification

- Red: `previewToolbarUi.test.tsx` failed because the selected-range playback
  control did not exist.
- Green: the toolbar calls the shared preview controller with the selected
  event/Cue's derived frame range.
- Focused: `npm test -- --run src/previewToolbarUi.test.tsx` -> **2 tests passed**.
- Related: `npm test -- --run src/previewToolbarUi.test.tsx src/previewCompilation.test.ts src/shotTimelineUi.test.tsx src/cueStripUi.test.tsx` -> **24 tests passed**.
- Full editor: `npm test -- --run` -> **30 files, 159 tests passed**.
- Build: `npm run build` -> passed. Vite retains the known external runtime
  font URL warning for `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- Browser desktop (1280px): Shot Timeline shows the new `播放所选` control,
  selected range, locator, and full-play controls together; captured
  `output/playwright/preview-play-selection-desktop.png`.
- Browser narrow (390px): the control remains reachable, and
  `bodyScrollWidth=390`, `bodyClientWidth=390`; captured
  `output/playwright/preview-play-selection-narrow.png`.
- `git diff --check` passed before commit.

The optional renderer at `127.0.0.1:8898` was not running during browser
checks, so the iframe stayed in its known loading/proxy-error state. The
editor-side controller contract, DOM, range labels, and responsive layout were
verified independently.

## Commit and push

- Code commit: `8a60690 feat(1.1): play selected preview range`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Keep preview transport and selection state on the same seam. The next useful
Studio-informed tracer is a compact playhead status contract: expose whether
the preview is ready, synchronizing, or failed beside the selected range, and
make refresh/seek/play controls announce that state without entering project
history. Keep audio tracks, absolute clip starts, and theme migration out of
scope.
