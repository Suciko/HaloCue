# Handoff: Shot Timeline selection detail tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: one Studio-evidenced timeline selection layer
- Status: implementation complete
- Code commit: `a1e0f15 feat(1.1): show shot timeline selection details`

## Delivery

The Professional Shot Timeline now keeps a stable read-only selection-detail
band directly below its tracks. It identifies the selected clip by its existing
stable event ID and shows the author-facing label, event kind, semantic track,
exact end-exclusive frame range, frame/millisecond duration, and sequential or
non-blocking execution state.

The band consumes the existing `ShotTimelineClip` and track projection. It does
not recompute timing in React, write project data, add a second selection model,
or move timing ownership out of `buildShotTimeline`. Selecting another clip
continues to update the shared event selection and preview playhead; the detail
follows that state without changing project revision, history, or autosave.

The right Inspector remains the event/Block-level editor. The new bottom band
owns only the selected timeline object's derived context. It contains no form
controls, so authors do not confuse read-only frame projection with canonical
event fields.

## Studio evidence

Public first-party references reviewed on 2026-08-28:

- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio editor overview image](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)
- [Studio Stage Animation timeline image](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)

The official Stage Animation image separates three responsibilities: clip and
Block controls at the top level, tracks/events in the timeline, and a full-width
selection detail below the tracks. A separate right column keeps realtime
preview and the broader Block inspector. The selected short shake interval is
therefore not edited in an inspector that changes ownership whenever selection
depth changes.

Maintainer-local recovered Studio 1.11 material was consulted read-only under
ADR-0005. The observable preview compiler keeps stable Block-to-runtime mapping
instead of assuming source and runtime indexes are identical. HaloCue retains
its own simpler stable event-ID projection in this tracer. No recovered
implementation body, source map, bundle, font, image, audio, model, or other
proprietary asset entered the repository or runtime closure.

HaloCue adopts the responsibility split, not Studio branding, colors, component
structure, keyframe schema, or proprietary visuals. The editor remains on its
current dark theme until the separate 1.0 semantic-token migration establishes
a shared foundation.

## TDD and verification

- Red: a Shot Timeline UI test required a bottom selection region with label,
  kind, track, frame range, duration, and execution policy. It also required a
  dialogue selection to replace stale motion details without project history.
  The test failed because no detail region existed; the other 15 tests passed.
- Green: `ShotTimelineWorkspace` projects the selected clip into one semantic
  `section`/`dl` band. Existing `ScanLine` iconography and timeline data are
  reused; no new store or project API was introduced.
- Refactor: `.shot-timeline-scroll` now owns the remaining flex space while the
  detail band has stable dimensions. Desktop uses a four-field row; widths at
  520 px and below use a two-column field grid. Text uses constrained tracks
  and ellipsis rather than expanding the shell.
- Focused Shot Timeline UI: **1 file, 16 tests passed**.
- Full frontend: **30 files, 175 tests passed**.
- Frontend build: passed with the known unresolved preview-font URL warning.
- Browser desktop (1440x1000): the band is 888x76 px, the timeline retains a
  340 px internal viewport, and the page remains exactly 1440 px wide. Selecting
  screen text updates the band to `F47-101`, 54 frames / 1800 ms, and
  `与后续事件并行` while the playhead locates to F47.
- Browser narrow (390x844): the band is 390x142 px, with four 195 px fields in
  two rows. The actual `#root` work-area scroller reaches the complete detail at
  `y=199..341`; body/document width remains 390 px with no horizontal overflow.
- Repository-wide Python: **2208 passed, 14 skipped in 699.34s**.
- `git diff --check` passed.

## Next bounded slice

The long-term plan's next safe UI foundation tracer is to extract a versioned
semantic token layer from HaloCue 1.0's existing `css/layout.css` and
`css/app.css`. Start without a wholesale theme switch: define reusable
background, surface, border, text, accent, status, shadow, radius, control, and
focus tokens, prove current visual parity, then migrate one responsibility at a
time before making the light workbench the default.
