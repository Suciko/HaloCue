# 2026-08-26 official-p69 UI fidelity baseline

## Scope

The official-p69 scene is the first pixel-measured AA-compatible reference
frame for the 1.1 video-first preview. The target is a completed dialogue line
with Yuuka speaking, Aris visible in slot 5, the Game Development Club room
background, and AUTO/MENU visible. The public implementation still uses only
independent presentation code and user-owned or authorized local resources.

## Reference contract

`apps/desktop-client/scene-preview/official-p69.scene-descriptor.json` records
the reference id, 1280x720 viewport, 2560x1440 design canvas, final event index,
completion state, and normalized anchors. The same anchors are asserted by the
browser regression at 640x360, 1280x720, and 1920x1080.

| Element | Normalized target |
| --- | ---: |
| Dialogue panel left/top | 0.100000 / 0.711111 |
| Speaker left/top | 0.100000 / 0.700000 |
| Secondary identity left/top | 0.164063 / 0.715741 |
| Dialogue text left/top | 0.100000 / 0.790278 |
| Lower shade top | 0.610000 |
| Slot 1 / slot 5 center | 0.187500 / 0.812500 |
| AUTO x/y/w/h | 0.793750 / 0.025000 / 0.093750 / 0.062500 |
| MENU x/y/w/h | 0.894531 / 0.025000 / 0.093750 / 0.062500 |

The location chip is intentionally hidden for this reference frame. The
dialogue font is the bundled Noto Sans fallback; the official font bytes are
not redistributed, so exact glyph identity is not claimed beyond the measured
size, weight, color, shadow, and baseline.

## Character calibration

- Yuuka: animation `06`, scale `1.55`, x offset `-20`, y offset `812`.
- Aris: animation `00`, scale `1.62`, x offset `-25`, y offset `216`.

These values compensate for the current transparent tight-crop stage-frame
adapter. They are descriptor-level calibration data and do not copy the
original Spine canvas or implementation. The next renderer-level change should
only be considered if these offsets cannot meet the reference alpha-boundary
target.

## Verification

- `27 passed` baseline before this slice.
- New browser assertions cover the final dialogue frame and normalized geometry
  at all three required resolutions.
- `node --check apps/desktop-client/scene-preview/preview.js`
- `node --check apps/desktop-client/scene-preview/aa-runtime.js`
- `git diff --check`
- The first comparison accidentally used `halocue-p69-final-v9.jpg`, a prior
  calibrated intermediate, as the reference. That result must not be treated
  as official-video evidence.
- The canonical source is the 1280x720 frame extracted at 754 seconds from
  the local `halocue-bv1q-p69-720p.mp4`, saved as
  `acceptance-output/official-p69-video-frame-754s.png`. The browser capture is
  `acceptance-output/official-p69-browser-actual.png`.
- The corrected overlay is available at
  `acceptance-output/official-p69-video-vs-browser.html`, with static opacity
  frames beside it. This comparison visibly exposes the remaining character,
  control, and dialogue-layer offsets; the prior near-zero pixel result is
  invalid for acceptance.

## Known boundary

The browser test uses synthetic raster stand-ins in CI so it does not require
AA resources. Local visual acceptance should run with the authorized preview
index enabled and compare the saved final frame against the maintainer's
reference capture.
