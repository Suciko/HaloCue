# Handoff: Shot Timeline Cue selector tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: in-workspace Cue navigation for Professional Shot Timeline
- Status: implementation complete and pushed

## Delivery

The Shot Timeline header now includes a `当前镜头 Cue` selector listing every
Cue in the selected Scene. Changing it uses the existing `selectCue` Store
command, which repairs selection to the new Cue's first event, clears the old
playhead, and recomputes preview range, tracks, active context, and Inspector
projection.

This closes a real responsive-workflow gap: the ProjectRail is intentionally
hidden below 860px, but users can now change shots without leaving the Shot
Timeline. Selection remains editor state and does not change project JSON,
revision, history, autosave, event order, or timing contracts.

## Public Studio evidence and clean-room boundary

First-party references reviewed:

- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)
- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)

The public Stage Animation image places an `演出段` selector in the timeline
task header, next to preview transport and the active multi-track surface.
HaloCue independently applies that task-local navigation relationship to its
canonical Scene/Cue model. It does not copy Studio implementation, branding,
layout assets, source maps, bundles, fonts, or local application resources.

## TDD and verification

- Red: Shot Timeline had no task-local Cue selector.
- Green: the selector dispatches the existing editor-state `selectCue` command.
- Focused: `npm test -- --run src/shotTimelineUi.test.tsx` -> **14 tests passed**.
- Related: Shot Timeline UI, Store, and preview intent -> **42 tests passed**.
- Full editor: `npm test -- --run` -> **30 files, 162 tests passed**.
- Build: `npm run build` -> passed with the known external preview-font URL
  warning.
- Browser narrow (390x844): selecting `02 · 意外来客` updated the selected
  event to `event/enter/koyuki`, preview range to `F143-158`, and the timeline
  and Inspector together. `bodyScrollWidth=390`, `bodyClientWidth=390`.
  Screenshot: `output/playwright/shot-cue-selector-narrow.png`.
- Repository-wide Python gate immediately before this UI-only slice:
  `python -m pytest -q` -> **2200 passed, 14 skipped in 709.16s**.
- `git diff --check` passed before commit.

The optional renderer remained stopped during browser checks; the timeline,
selection, range, Inspector, and responsive behavior were verified on the
editor side.

## Commit and push

- Code commit: `6e5c449 feat(1.1): navigate Shot Timeline Cues`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Return to the unified animation protocol and evaluate one additional
officially evidenced non-blocking capability. Prefer the existing camera-like
`halocue.ba:background-pan` event because Studio's public Camera Block documents
`等待完成`; prove registry, timeline, performance, browser runtime, validation,
and preview/export parity before exposing the switch in the editor. Keep all
other event kinds sequential in that slice.
