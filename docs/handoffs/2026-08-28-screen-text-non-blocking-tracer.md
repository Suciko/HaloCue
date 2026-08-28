# Handoff: screen text non-blocking tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: one fixed-duration overlay through authoring, timeline, preview, and export
- Status: implementation complete
- Code commit: `be4ca09 feat(1.1): overlap screen text with following events`

## Delivery

`halocue.ba:screen-text` now opts into the existing registry-governed
non-blocking completion protocol. New screen-text events still default to
`wait_for_completion: true`; the Professional inspector exposes a boolean
`阻塞后续事件` field and project validation accepts false only because the
canonical registry declares the capability.

At 30 fps, a 1800 ms non-blocking screen-text event spans `F0-54`. A following
500 ms dialogue starts at the same sequential cursor and spans `F0-15`, while
`total_frames` remains the maximum end frame, 54. The dialogue is the
latest-authored active event and remains primary. Browser preview additionally
composes the latest active screen-text entry from `activeItems`, so the overlay
stays visible behind the dialogue. Seeking before the overlay clears it to the
baseline; seeking forward restores the same deterministic frame state.

Screen text and dialogue share the derived `Dialogue / Overlay` track. The
Shot Timeline projection now assigns same-track overlaps to stable sub-lanes.
Lane allocation remains a projection concern in `buildShotTimeline`; it does
not add absolute starts or a second saved timeline model. Empty and
non-overlapping tracks retain the original single-lane height.

The contract chain remains `scene-events/1.2`, `render-timeline/1.2`,
`scene-performance/1.4`, and `scene-evaluation/1.5`. This tracer changes one
manifest capability and adapter behavior, not a wire shape.

## Studio evidence

Public first-party references reviewed on 2026-08-28:

- [Studio Floating Text](https://docs.avg-engine.com/manual/writing/blocks/floating-text)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio editor overview image](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)
- [Studio Stage Animation timeline image](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)

The Floating Text manual distinguishes dialogue-box text from independently
positioned overlay text. A finite overlay can close `阻塞` so the story
continues during its stay. Infinite stay automatically disables blocking and
uses a later `隐藏浮字` block, optionally addressed by a stable floating-text
ID. The official editor and Stage Animation images continue to support one
ordered Block source, a separate multi-track performance workspace, and stable
clip/timeline/selection-detail ownership.

Maintainer-local recovered Studio 1.11 material was inspected read-only under
ADR-0005. Its observable runtime behavior independently confirms that finite
floating text defaults to blocking, non-blocking text opens as topmost UI
without awaiting completion, infinite text is forced non-blocking, and a later
ID-addressed hide operation requests its exit animation. It also confirms a
meaningful product difference: Studio's immediate seek/skip path does not
recreate transient floating UI, while HaloCue's existing fixed-duration
screen-text event is deliberately sampled and exported as deterministic frame
state. That distinction is explicit rather than claimed as exact emulation.

No recovered implementation body, source map, bundle, fixture, font, image,
audio, model, installed application resource, or other proprietary asset was
copied into the repository or runtime closure.

## Deliberate limits

This tracer does not add infinite lifetime, floating-text IDs, Hide Floating
Text, rich text, variables, positioning, style controls, enter/exit animation
families, history recording, or arbitrary absolute event starts. Those require
an explicit transient-versus-persistent overlay decision and a separate TDD
slice. It also does not migrate the editor's dark theme; the work is limited to
timing semantics and readable overlap geometry.

## TDD and verification

- Red: timeline and registry tests first rejected non-blocking screen text;
  browser seek tests then exposed that primary dialogue cleared the overlay;
  catalog/factory tests required default blocking; projection and UI tests
  exposed same-track clip collision.
- Green: canonical and browser registry mirrors opt in screen text; preview
  composes compatible active overlays; the editor adds the boolean field; the
  Shot Timeline projection assigns stable lanes and the UI sizes each track.
- Refactor: lane assignment stays in the projection module and the React layer
  only consumes `lane_index`/`lane_count`. No unrelated theme or event-model
  refactor was included.
- Focused frontend: **8 files, 53 tests passed**.
- Focused Python contract/timeline/preview/export checks: **37 tests passed**.
- Full frontend: **30 files, 174 tests passed**.
- Frontend build: passed with the known unresolved preview-font URL warning.
- Browser preview overlap plus production frame rendering: **2 tests passed**;
  the formatted browser test was rerun separately and passed.
- Ruff lint: passed for every touched Python test. Range-format checks pass for
  each added/extended function; three touched files retain unrelated historical
  whole-file format drift and were intentionally not reformatted wholesale.
- Browser desktop (1440x1000): screen text `F47-101` and dialogue `F47-143`
  share the same start. `Dialogue / Overlay` reports two lanes, is 78 px high,
  and renders two 32 px clips with a 4 px gap.
- Browser narrow (390x844): `body` and `document` are both exactly 390 px wide
  with no page-level horizontal overflow. Screen text and dialogue share the
  same horizontal start and occupy separate 32 px lanes; long content remains
  inside the timeline scroller.
- Repository-wide Python: **2208 passed, 14 skipped in 695.77s**.
- `git diff --check`, JavaScript syntax checks, and the frontend production
  build passed.

## Next bounded slice

Return to the long-term plan instead of extending Floating Text opportunistically.
The next high-value tracer should either establish versioned shared editor
tokens without changing the theme wholesale, or deepen one Studio-evidenced
selection/timeline detail through the existing editor-state and preview seams.
Any infinite/Hide overlay work must first specify its seek/export policy and
remain separate from this fixed-duration contract.
