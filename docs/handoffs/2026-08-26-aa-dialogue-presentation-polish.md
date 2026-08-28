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

## Latest raster-fidelity pass

- The local AA font inventory confirms `NotoSansSC-Medium` for dialogue copy and
  `NotoSansSC-Bold` for the primary speaker label. Those static files are bundled
  under `apps/desktop-client/scene-preview/assets/fonts` so Chromium does not
  interpolate the variable font differently at the 720p reference scale.
- The speaker and club labels use small scale corrections to match the official
  glyph box without moving their normalized layout anchors. Body text is
  narrowed slightly and rendered with a symmetric soft outline, removing the
  visible right/down duplicate shadow.
- The dialogue shade now eases in continuously at its upper edge. The separator
  is a lower, dim 2px soft line with the cyan accent aligned to it, matching the
  official frame without a bright one-pixel rule.

Validation: `32 passed` across the AA runtime, stage-media, BA preview, and
render-timeline suites; JavaScript syntax checks and `git diff --check` pass.

## Realtime Spine follow-up

- `apps/desktop-client/scene-preview/spine-preview.js` now loads Spine 3.8 or
  4.2 lazily in the browser, plays the descriptor animation, and renders a
  transparent Canvas per visible `stage_media.kind = "spine"` actor.
- `webui.py` exposes `/api/resources/stage/spine/data` using the existing
  authorized bundle resolver. It returns data URIs only; physical AA paths stay
  server-side. The CSP permits only same-origin, `data:`, and `blob:` asset
  reads needed by the local Spine AssetManager.
- The existing `/api/resources/stage/spine/frame` PNG route remains the visual
  fallback when WebGL, runtime loading, or bundle data is unavailable. Canvas
  and PNG share the existing anchor, scale, and offset CSS variables.
- Canvas backing resolution follows the actual stage size at a capped 1.75x
  sample (maximum 2048px), so small previews do not pay the full-size render
  cost while the reference viewport remains sharp.
- `?descriptor=official-p69&renderer=static` disables the Canvas layer while
  retaining the exact P69 descriptor transforms. It is the valid static/runtime
  comparison pair. `local-aa` remains an uncalibrated Alice/Momoi resource
  availability fixture and must not be presented as an official visual target.
- Browser smoke check at 1280x720 confirmed two P69 Canvas actors reach
  `realtime-ready`, no console errors occur, and two captures 280ms apart differ
  in actor pixels (animation loop active). Related tests: 11 stage-media,
  4 CSP, and 17 BA preview UI tests passed; one transient Playwright run hit
  an OS unsafe-port allocation and was rerun successfully.
