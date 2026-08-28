# Handoff: background pan non-blocking tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: one additional officially evidenced non-blocking event
- Status: implementation complete and pushed
- Code commit: `532b398 feat(1.1): overlap background pans with following events`

## Delivery

`halocue.ba:background-pan` now opts into the existing non-blocking timing
protocol. New background-pan events default to sequential execution and expose
an editor checkbox labelled `等待镜头完成`. Disabling it preserves the ordered
Cue event list while starting the following event at the same sequential
cursor.

The registry remains the single capability authority. Only
`character-motion` and `halocue.ba:background-pan` currently advertise
`supports_non_blocking: true`; all other events still reject
`wait_for_completion: false` during project validation and timeline building.
The contract chain remains `scene-events/1.2`, `render-timeline/1.2`,
`scene-performance/1.4`, and `scene-evaluation/1.5` because this slice changes a
registry capability, not a wire shape.

For a 900 ms pan at 30 fps followed by dialogue, both events start at the same
frame. The pan ends 27 frames later, dialogue remains the latest-authored
primary item, and `total_frames` is still the maximum end frame. Browser preview
and production frame rendering retain the active pan contribution while
dialogue is primary; reverse seek restores the baseline pan before a later
forward seek reapplies the authored value.

## Studio evidence

Public first-party references reviewed:

- [Studio Camera block](https://docs.avg-engine.com/manual/writing/blocks/camera/)
- [Studio blocks overview](https://docs.avg-engine.com/manual/writing/blocks-overview)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)
- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)

The Camera manual states that `等待完成` decides whether the next block waits
for the camera animation. When disabled, the camera animation keeps playing in
the background while later blocks execute. It also documents state accumulation:
parameters not explicitly authored by a later Camera block retain their prior
value.

The Stage Animation image places `后续执行` in the shot inspector with
`等待完成` selected, while camera motion and screen shake appear as distinct
event lanes under the same multi-track shot. HaloCue adopts the explicit
completion policy and semantic track projection, but this tracer does not adopt
arbitrary absolute event start times or Studio's internal shot/track/event data
hierarchy; the ordered Cue event list remains canonical.

Maintainer-local recovered Studio 1.11 material was inspected read-only under
ADR-0005. The runtime evidence independently confirms that Camera and Stage
Animation start their animation first and await its completion only when their
completion option is enabled and the animation is not an infinite loop. A local
compatibility fixture also records camera/stage `waitForComplete` values and an
independent blocking choice for character placement transitions. These facts
support the ordered-list-plus-overlap model and identify future bounded
candidates; they do not make those additional capabilities part of this slice.

No recovered implementation body, source map, bundle, fixture, font, image,
audio, model, or other proprietary asset entered the repository or runtime
closure. HaloCue's implementation is defined by its own registry, contracts,
tests, and deterministic projections.

## TDD and verification

- Red: registry tests first required background pan support while the canonical
  manifest still returned false.
- Green: the canonical and browser registries opt in background pan; the editor
  catalog adds a boolean field defaulting to true.
- Focused frontend: **8 files, 42 tests passed**.
- Focused Python: **45 tests passed**.
- Full frontend: **30 files, 165 tests passed**.
- Frontend build: passed with the known external preview-font URL warning.
- Ruff check passed for the touched Python module and tests. Ruff format check
  passed for `render_timeline.py` and its focused timeline test after applying
  the requested condition formatting.
- Browser preview overlap and production frame-renderer overlap checks passed.
- Browser desktop: Camera pan `F47-74` and dialogue `F47-143` overlapped; the
  header reported `播放头 F47 · 背景移动、对白`, and the inspector reported the
  27-frame Camera clip as `与后续事件并行`.
- Browser narrow (390x844): the same overlap and inspector state remained
  reachable, `bodyScrollWidth=390`, and only the timeline canvas scrolled
  horizontally. The optional renderer on `127.0.0.1:8898` was not running, so
  the embedded preview surface stayed blank while editor-side timing and
  interaction checks remained available.
- Post-format focused frontend: **5 files, 27 tests passed**.
- Post-format Python timeline: **13 tests passed**; the three directly affected
  contract/registry/production checks also passed.
- Repository-wide Python: **2202 passed, 14 skipped in 827.20s**.

## Commit and push

The code commit `532b398` was pushed normally to
`origin/feature/1.1-ba-editor-from-1.0` for PR #27. No force push was used.

## Next bounded slice

Use the same evidence-and-registry process for one additional Studio-backed
timing capability, or deepen Camera state accumulation and reset semantics if
the long-term plan ranks that higher. Keep the event list canonical, write the
failing cross-runtime parity case first, and do not generalize arbitrary
absolute start times.
