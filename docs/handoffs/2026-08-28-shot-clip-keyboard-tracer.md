# Handoff: Shot clip keyboard navigation tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: keyboard selection and navigation inside the Professional Shot Timeline
- Status: implementation complete, pushed with the commit listed below

## Delivery

Shot Timeline clips are now keyboard-operable selection targets. Arrow Left/
Right and Up/Down move through the deterministic flattened order of the
projection's semantic tracks; Home and End move to the first and last clip.
Navigation selects the source event, seeks the shared preview playhead to the
clip's derived start frame, and moves DOM focus to the destination clip.

Clips expose `aria-pressed` selection state and retain the existing pointer
selection path. These actions modify editor selection/playhead only: project
JSON, revision, history, and autosave state remain unchanged.

## Studio evidence

First-party sources reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public Stage Animation workspace presents a selected object/key point,
semantic track rows, a ruler/playhead, realtime preview, and an inspector as a
single task surface. HaloCue's keyboard behavior keeps that selection loop
usable without requiring a pointer, while preserving a derived timeline rather
than introducing arbitrary absolute clip starts. Studio's implementation and
assets remain outside the repository under ADR-0005.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit

- `baaade6 feat(1.1): navigate shot clips by keyboard`

## Verification

- Red: the keyboard-navigation UI test failed because ArrowRight left focus on
  the first clip.
- Focused: `npm test -- --run src/shotTimelineUi.test.tsx` -> **8 tests passed**.
- Related: `npm test -- --run src/shotTimelineUi.test.tsx src/projectStore.test.ts src/previewIntent.test.ts`
  -> **36 tests passed**.
- Full editor suite: `npm test` -> **25 files, 143 tests passed**.
- Build: `npm run build` passed. Vite retains the known runtime font URL as an
  external asset for the optional preview service.
- Browser: Playwright CLI at 1280x900 clicked a Character clip, pressed
  ArrowRight to select Dialogue and seek to its start frame, then pressed Home
  to return to the first clip; snapshots showed focus and `pressed` state.
  Screenshot: `output/playwright/shot-clip-keyboard.png`.
- `git diff --check` passed before commit.

The optional renderer at `127.0.0.1:8898` was stopped during browser checks,
so the embedded preview continued to show the known proxy errors; timeline
DOM, focus, selection, and playhead behavior were independent of that service.

## Next bounded slice

Add explicit keyboard affordance to the Shot Timeline ruler/lane relationship:
when a selected clip is focused, expose its track and frame range in the live
region and verify that keyboard navigation remains stable after projection
changes. Keep clip resizing and audio tracks out of this slice.
