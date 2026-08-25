# 2026-08-26 AA finished-frame UI calibration

This handoff supersedes the same-day `aa-pixel-overlay-calibration` visual
target. The maintainer-provided finished AzureArchive GameDevRoom frame is the
primary reference; the earlier `scene-0031` recording is not the final target.

## Scope and visual method

- The reference contains the location chip, two characters, AUTO/MENU,
  speaker/club row, separator, lower shade, and completed dialogue copy.
- Its client area was normalized to 1280x720 and compared with the preview in a
  50% alpha overlay.
- Decompiled AA metadata confirms five-slot/camera math and timings. The
  finished frame decides painted UI geometry.
- Alice animations 00-19 and Momoi animations 00-08/99 were rendered as local
  contact sheets. These ids mostly change facial expression. The remaining
  character delta comes from tight transparent-frame crops losing the original
  skeleton canvas origin, not from choosing the wrong face id.
- No AA implementation body or game asset is committed.

## Changes

- Finished AA UI is now the default demo state: persistent location chip,
  optional AUTO/MENU, active yellow AUTO, AA-like trapezoid buttons, and the
  reference speaker/dialogue copy.
- The lower shade sits above character art, with the text panel above the
  shade, so lower bodies darken like the reference.
- 2560-grid anchors were calibrated to the normalized target: speaker x=10%,
  secondary identity x=19.3%, text x=10%, AUTO x=79.92%, MENU x=89.84%.
  Speaker/secondary/body sizes are 68/48/50 design pixels.
- Speaker identity is raised independently of the separator; dialogue copy has
  the larger AA gap below the rule.
- At 1280x720 the location chip is 287x57 near y=130. AUTO/MENU are each
  120x45.
- Stage media accepts clamped per-character `offset_x`/`offset_y` values and a
  scale up to 2.0. The local reference uses scale 1.6 and restores the vertical
  displacement lost by tight cropping.
- Cached actor images no longer disappear when a dialogue rerender reuses the
  same URL. The typewriter caret hides after a line completes.
- Descriptor presentation data supplies AUTO/MENU visibility and active state;
  `?editor=1` reveals the export switches.

## Verification

- `24 passed`: `tests/test_aa_runtime_contract.py`,
  `tests/test_aa_stage_media.py`, `tests/test_ba_scene_preview.py`,
  `tests/test_ba_scene_preview_ui.py`, and `tests/test_render_timeline.py`.
- `node --check apps/desktop-client/scene-preview/aa-runtime.js`
- `node --check apps/desktop-client/scene-preview/preview.js`
- `git diff --check`
- In-app-browser checks at 640x360 and 1920x1080 produced the same normalized
  geometry. Speaker x/y stayed 0.1/0.7181; AUTO stayed
  0.7992/0.0292/0.0938/0.0625; location stayed x=0, y=0.18.
- Plain `pytest -q` is still blocked during collection by duplicate
  `test_http_api.py` module names in existing production/writing suites.

## Follow-up

For character-level matching beyond this reference, preserve the original
Spine skeleton root/canvas origin in stage-frame metadata instead of
tight-cropping every rendered PNG. Per-character offsets are the safe
descriptor-level bridge until that renderer change is made.
