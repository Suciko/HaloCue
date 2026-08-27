# Handoff: Shot active-clip feedback tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: derived active-state feedback for clips under the shared Shot Timeline playhead
- Status: implementation complete, code committed and ready to push

## Delivery

Professional Shot Timeline clips now expose a derived `is-active` state whenever
the shared playhead is inside their end-exclusive frame range. Multiple clips
can be active at once, so a non-blocking character motion and the following
dialogue remain visibly active together during their overlap. At the exact end
frame, the earlier clip clears while the later clip remains active. The state is
represented by a visual highlight plus `data-shot-active="true"`; it does not
change selection, authored timing, project revision, undo/history, or the
canonical event list.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public Stage Animation workspace keeps a visible playhead and selected
timeline objects in the same focused task surface. HaloCue applies the observed
feedback relationship by highlighting every clip covered by the playhead while
retaining its own five-track projection and ordered event model. No decompiled
implementation body, source map, private asset, or installed Studio/AA
resource was copied into the repository.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit and verification

- Code commit: `a9994a1 feat(1.1): highlight active shot clips`
- Red: the new overlap/boundary UI test failed because clips had no active state.
- Green/refactor: `npm test -- --run src/shotTimelineUi.test.tsx` -> **12 tests passed**.
- Full editor suite: `npm test` -> **25 files, 147 tests passed**.
- Build: `npm run build` -> passed. Vite retains the known runtime font URL as
  an external asset for the optional preview service.
- `git diff --check` -> passed before commit.
- Browser desktop: `output/playwright/shot-active-desktop.png` shows the
  playhead and active Stage clip highlight.
- Browser narrow: `output/playwright/shot-active-narrow-frame17.png` at F17
  shows the end-exclusive boundary transition; `bodyScrollWidth=390`,
  `bodyClientWidth=390`, and the timeline scroll remains internal (`649px`).

The optional renderer on `127.0.0.1:8898` was not running during the browser
check, so the embedded preview retained its known proxy/font warnings. Editor
DOM, active-state projection, and responsive layout were verified independently.

## Next bounded slice

Push this focused commit and handoff. Then continue with the next high-value
Studio-informed editor slice: make the active playhead context explicit for
keyboard and assistive-technology users without turning derived timeline state
into authored data. Keep clip resizing, absolute starts, and audio tracks out
of scope until this feedback contract is stable.
