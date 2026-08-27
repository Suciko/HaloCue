# Handoff: screen shake non-blocking tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: one additional Studio-evidenced non-blocking effect
- Status: implementation complete and pushed
- Code commit: `4c73c5e feat(1.1): overlap screen shakes with following events`

## Delivery

`halocue.ba:screen-shake` now opts into the existing non-blocking completion
protocol. New screen-shake events still default to sequential execution and
expose an editor checkbox labelled `等待震动完成`. Disabling it keeps the
ordered Cue event list canonical while starting the following event at the same
sequential cursor.

The shared registry remains the capability authority. `character-motion`,
`halocue.ba:background-pan`, and `halocue.ba:screen-shake` advertise
`supports_non_blocking: true`; all other registered events still reject
`wait_for_completion: false` in project validation and timeline compilation.
The contract chain remains `scene-events/1.2`, `render-timeline/1.2`,
`scene-performance/1.4`, and `scene-evaluation/1.5` because this slice changes a
manifest capability, not a wire shape.

At 30 fps, a 360 ms non-blocking shake spans `F0-11`. A following 300 ms
dialogue also starts at `F0` and spans `F0-9`; `total_frames` is the maximum end
frame, 11. The performance plan keeps the shake contribution active while the
latest-authored dialogue remains the primary timeline item. Reverse seek resets
the stage offset to baseline, and a later forward seek reproduces the same
deterministic shake sample.

## Studio evidence

Public first-party references reviewed on 2026-08-28:

- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio editor overview image](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio Stage Animation manual](https://docs.avg-engine.com/manual/writing/blocks/stage-animation)
- [Studio Stage Animation timeline image](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio Camera block](https://docs.avg-engine.com/manual/writing/blocks/camera/)

The current v1.20 editor manual describes one ordered Block source shown through
multiple editing views, with selection updating the real-time preview and the
Block property inspector. It also exposes a distinct performance-design view
without changing the underlying script data. The Stage Animation manual divides
that task surface into stage preview, multi-track timeline, property inspector,
and transport; the playhead can be dragged for frame-level inspection.

The official timeline image presents camera movement, camera shake, character,
and scene work as separate lanes. The selected shake row has its event timing
and shake parameters below the timeline, while the enclosing shot inspector
exposes `后续执行`. The manual defines `同时执行` as immediately running the next
Block and explicitly says the animation may overlap following dialogue or other
Blocks. These observations support HaloCue's derived Effect / Timing shake clip,
shared playhead, selected-event inspector, and explicit completion policy.

HaloCue does not adopt Studio's project hierarchy, arbitrary absolute event
starts, editable keyframes, track mutation, or proprietary visual assets in this
tracer. The first implementation remains an ordered event list with a derived
five-track projection. Absolute placement and richer Stage Animation editing
remain separate future decisions.

Maintainer-local recovered Studio 1.11 material was consulted read-only under
ADR-0005. Its observable runtime behavior independently confirms that camera
shake defaults to waiting: the effect starts first, and only the enabled
completion option delays the next operation. No recovered implementation body,
source map, bundle, fixture, font, image, audio, model, installed Studio/AA
resource, or other proprietary asset entered the repository or runtime closure.

## TDD and verification

- Red: timeline, registry, editor catalog, authoring UI, project validation,
  performance, browser parity, and production rendering tests first required
  screen shake to support non-blocking completion while the manifest still
  rejected it.
- Green: the canonical and browser registry mirrors opt in screen shake, and the
  editor catalog adds a boolean field defaulting to true.
- Focused frontend: **6 files, 38 tests passed**.
- Focused Python behavior: **10 tests passed**.
- Full frontend: **30 files, 169 tests passed**.
- Frontend build: passed with the known unresolved preview-font URL warning.
- Ruff lint: passed for all touched Python tests. Range-format checks pass for
  every function added or extended by this tracer; unrelated whole-file format
  drift remains untouched.
- Browser preview overlap and production frame-renderer overlap: **2 tests
  passed**. One earlier browser attempt received Chromium's forbidden port 6665
  from an ephemeral test server and failed before navigation; rerunning on a
  safe port passed without product or test-infrastructure changes.
- Browser narrow (390x844): background pan `F47-74`, dialogue `F47-143`, and
  screen shake `F47-58` share the same horizontal start. The shake inspector
  reports `与后续事件并行`; `body` and `document` both remain 390 px wide, with
  long clips confined to the timeline's horizontal scroller.
- Browser desktop (1440x1000): the same three clips share the exact start
  coordinate, the vertical playhead aligns at F47, and no page-level horizontal
  overflow appears.
- Repository-wide Python: **2205 passed, 14 skipped in 695.92s**.

## Commit and push

The code commit `4c73c5e` and this handoff are pushed normally to
`origin/feature/1.1-ba-editor-from-1.0` for PR #27. No force push was used.

## Next bounded slice

The strongest next tracer is non-blocking `halocue.ba:screen-text`. The public
[Studio Floating Text manual](https://docs.avg-engine.com/manual/writing/blocks/floating-text)
states that authors can close `阻塞` so the story continues, and that infinite
text automatically becomes non-blocking until a later Hide Floating Text Block
removes it.

HaloCue already maps screen text to Dialogue / Overlay and exposes overlapping
`activeItems`, but the browser currently renders only the primary event and
clears screen text when later dialogue becomes primary. Start with a failing
browser seek test that requires the text overlay to remain visible behind
dialogue, then implement the smallest active-overlay composition seam before
enabling the registry capability. Prove reverse-seek baseline reset and
production-frame parity. Do not add infinite lifetime, a hide event, absolute
start positions, or a scene-performance overlay contract in that first tracer
unless the failing end-to-end path demonstrates they are necessary.
