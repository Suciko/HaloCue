# Handoff: Professional workspace state and tab navigation tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: Professional Script/Shot Timeline workspace continuity and keyboard-complete tabs
- Status: implementation complete, pushed with the commits listed below

## Delivery

Professional Script and Shot Timeline views now expose a complete tab
interface. Each tab has a stable ID and `aria-controls` relationship, the
active tab is the only tab in the sequential keyboard order, and Left/Right,
Up/Down, Home, and End move the active view and focus the destination tab.
Each visible view is a labelled `tabpanel`.

Selection and preview position remain shared editor state across both views.
Switching views therefore keeps the same selected event and playhead without
creating a project revision or history entry. Changing the Cue has an explicit
reset rule: select the new Cue's first event (or no event when empty), clear
the old preview playhead, and leave project history untouched.

## Studio evidence

First-party sources reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)

The editor overview keeps the chapter/Fragment structure, ordered Blocks,
realtime preview, playback position, and selected-block inspector in one
authoring path. The Stage Animation image switches into a focused shot
workspace with a timeline ruler, semantic tracks, selected clip, preview, and
properties visible together. The selected object is the coordination point;
the view switch does not imply a second copy of authored data.

HaloCue adopts the observable relationship through one canonical Cue/event
selection and one render-timeline-derived playhead. It does not copy Studio's
branding, private implementation, exact layout, or assets. Absolute start-time
editing and per-workspace duplicate project selections remain out of scope;
Shot Timeline is still a projection of the ordered event list.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/shotTimelineUi.test.tsx`
- `apps/desktop-client/scene-editor/src/projectStore.test.ts`

## Commits

- `c98536c feat(1.1): complete professional workspace tab navigation`

## Verification

- Red: the new UI test failed because inactive tabs had `tabIndex=0` and no
  panel relationships.
- Focused: `npm test -- --run src/projectStore.test.ts src/shotTimelineUi.test.tsx`
  -> **28 tests passed**.
- Full editor suite: `npm test` -> **25 files, 141 tests passed**.
- Build: `npm run build` passed. Vite retains the known runtime font URL as an
  external asset for the optional preview service.
- Browser: Playwright CLI at 1280px verified ArrowRight and Home focus/selection
  changes, shared event/playhead continuity, labelled panels, and captured
  `output/playwright/professional-tabs.png`.
- Browser narrow: Playwright CLI at 390x844 reported
  `bodyScrollWidth=390`, `bodyClientWidth=390`; captured
  `output/playwright/professional-tabs-narrow.png`.
- Python regression: `python -m pytest -q` -> **2200 passed, 14 skipped**.
- `git diff --check` passed before commit.

The optional renderer at `127.0.0.1:8898` was not running during browser
checks, so the embedded preview reported its known proxy errors/blank frame;
editor DOM, timeline, selection, and keyboard behavior were verified
independently.

## Next bounded slice

Keep the same selection/playhead contract while tightening the Professional
workspace around Cue navigation: expose a compact selected-Cue context in the
Shot Timeline header, and verify that scene/Cue changes cannot leave a stale
clip highlighted. Do not add editable absolute clip starts or new project
schema fields until that projection behavior has a focused test seam.
