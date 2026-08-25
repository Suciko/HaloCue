# 2026-08-26 AA dialogue presentation polish

## Scope

1.1 scene preview dialogue presentation was calibrated against the authorized
AA PreviewScene transform evidence and the local AA GameDevRoom reference
frames. The public implementation remains an independent adapter; no
decompiled implementation bodies or game bytes are copied into the repository.

## Changes

- Dialogue panel now uses a 270px design-space minimum height. With the fixed
  2560x1440 stage this places the name, separator, and body near the AA
  container/name/line/text anchors (roughly 78%/83%/86% of stage height).
- The shade is reduced to a 38% lower-stage gradient so the scene stays bright
  above the text while the lower edge remains readable.
- Name and club/alias typography now use a stronger white primary label, a
  separate cyan alias treatment, a restrained underline, and the bundled Noto
  Sans family. The typewriter caret blinks and respects reduced-motion users.
- Dialogue, actor enter/exit, and background changes use purpose-built
  transform/opacity motion with reduced-motion fallbacks.
- AUTO and MENU are optional. The editor tray is default-off and controls
  stage overlay buttons styled like the AA top-right controls; descriptor-level
  `presentation.overlay_controls.auto/menu` values are also accepted.
- Concurrent Spine stage-frame extraction is serialized to avoid the threaded
  preview server racing Playwright. Stage frame cache remains partitioned by
  animation.

## Verification

- `24 passed`:
  `tests/test_aa_runtime_contract.py`, `tests/test_aa_stage_media.py`,
  `tests/test_ba_scene_preview.py`, `tests/test_ba_scene_preview_ui.py`, and
  `tests/test_render_timeline.py`.
- `node --check apps/desktop-client/scene-preview/preview.js`
- `git diff --check`
- Four concurrent AA Spine frame requests returned HTTP 200 PNG responses.
- In-app browser visual checks passed at 1280x720 and 640x360: the stage stays
  16:9, `--stage-scale` is 0.5/0.25, and both visible AA stage images load.

## Related work

- GitHub issue #8: canonical AA-style scene playback.
- GitHub issue #24: BA editor integration and preview calibration.

## Follow-up

The next fidelity pass should calibrate per-skeleton origin offsets/idle
animation selection against a matched official frame. The current stage adapter
uses tight transparent Spine crops, so skeleton-specific local origins remain
the main remaining visual variable.
