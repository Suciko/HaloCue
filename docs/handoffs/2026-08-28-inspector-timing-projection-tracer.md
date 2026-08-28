# Handoff: inspector timing projection tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: Professional event inspector timeline context
- Status: implementation complete, awaiting maintainer review

## Delivery

The Professional event inspector now distinguishes authored timing input from
derived timeline placement. `duration_ms` remains editable through the existing
transactional control. The former `开始帧: 自动` placeholder is replaced by the
actual selected event start frame, and a read-only `时间轴投影` section shows:

- semantic Shot Timeline track;
- start and end-exclusive frame boundaries;
- normalized duration in frames;
- sequential or non-blocking execution policy.

The inspector reuses `buildShotTimeline`; it does not duplicate event-to-track
classification or create editable absolute start times. Events absent from the
render timeline show `未映射` and do not receive a fabricated timing section.

## Evidence

Studio's public Stage Animation image presents the selected key point, track,
timing controls, preview, and inspector as one coordinated workspace. HaloCue
adopts the observable information relationship while preserving its ordered
event model and derived render timeline. No Studio source or asset is reused.

Source:
[Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)

## Verification

- Red: the new UI test failed with no timing-projection element.
- Focused UI: **5 tests passed**.
- Full editor suite: **25 files, 139 tests passed**.
- Editor build: passed.
- Playwright desktop (1280x900): non-blocking character motion displayed
  `Character`, `F47`, `F62`, `15 帧`, and `与后续事件并行`; the projection had
  zero interactive form controls.
- Playwright narrow (390x844): the projection fit a 347px inspector content
  width and body width remained equal to the viewport.
- `git diff --check`: passed.

The optional preview renderer remained stopped, so the known localhost proxy
errors persisted without affecting inspector or timeline verification.

## Next tracer bullet

Before adding clip editing, deepen selection continuity across workspace view
switches: preserve each Professional sub-workspace's last selected event and
playhead in editor state, define reset behavior when the Cue changes, and make
the tabs keyboard-complete. This remains editor state and must not change the
project schema or history.
