# Handoff: Shot active-context accessibility tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: accessible active-playhead context for the Professional Shot Timeline
- Status: implementation complete, code committed and ready to push

## Delivery

The Shot Timeline now derives an `activeClips` list from the same shared
playhead and end-exclusive clip ranges used by visual highlighting. A compact
`aria-live`/`aria-atomic` context reports the current frame and all active clip
labels, including simultaneous character motion and dialogue. Active clip
buttons append `播放头当前` to their accessible name while retaining the
existing selected-state and frame-range wording. This is editor-only derived
state and does not alter the project model, contracts, revision, or history.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The public Stage Animation workspace keeps the playhead, current timeline
objects, preview, and properties in one focused task surface. HaloCue extends
that visible relationship to assistive technology without copying Studio's
implementation or branding. No decompiled source body, source map, private
asset, or installed Studio/AA resource was added to the repository.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`

## Commit and verification

- Code commit: `fda7ee0 feat(1.1): announce active shot context`
- Red: the new UI test failed because the active context node and active labels
  were absent.
- Green/refactor: `npm test -- --run src/shotTimelineUi.test.tsx` -> **13 tests passed**.
- Full editor suite: `npm test` -> **25 files, 148 tests passed**.
- Build: `npm run build` -> passed. Vite retains the known runtime font URL as
  an external asset for the optional preview service.
- `git diff --check` -> passed before commit.
- Browser desktop: `output/playwright/shot-active-context-desktop.png` shows
  the live active context and highlighted clip at F17.
- Browser narrow: `output/playwright/shot-active-context-narrow.png` shows the
  context fitting above the timeline; `bodyScrollWidth=390` and
  `bodyClientWidth=390`.
- Browser DOM check at F17 returned `播放头 F17 · 角色入场 · #1` and an active
  clip accessible name ending in `播放头当前`.

The optional renderer on `127.0.0.1:8898` was not running during the browser
check, so the embedded preview retained its known proxy/font warnings. The
editor DOM, derived state, and responsive layout were verified independently.

## Next bounded slice

Push this focused code and handoff. Then select one additional Studio-informed
tracer from the long-term plan, preferably a narrow UI-foundation or simple
script-flow improvement. Keep clip resizing, absolute starts, and audio tracks
out of scope until the current projection semantics have maintainer review.
