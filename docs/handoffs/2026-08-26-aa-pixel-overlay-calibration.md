# 2026-08-26 AA pixel-overlay calibration

## Scope

This slice calibrates the 1.1 scene preview against an authorized local AA
GameDevRoom recording and observable PreviewScene transform data. The
implementation remains independent: no AA implementation body or game asset is
checked into the repository.

## Visual method

- `scene-0031` was selected because it contains a completed two-line dialogue,
  not only the speaker row.
- Background features were registered with a RANSAC homography to verify that
  the same scene framing was being compared.
- UI was then compared in normalized viewport coordinates because the 864x540
  recording and the 16:9 export use different aspect ratios while AA pins its
  dialogue UI to the viewport.
- A 50% alpha overlay confirmed matching left anchors for speaker, secondary
  identity, separator, and dialogue text.

## Changes

- Character slot projection now accounts for PreviewScene's orthographic
  camera, 0.0012012012 root scale, and 1280x720 render target. The visible
  character span is 2960 authored units, producing slot centers near
  18.75/35.3/50/64.7/81.25 percent.
- Missing per-character media scale now defaults to 1.35, matching the local AA
  stage-frame fixture rather than rendering new characters undersized.
- Painted dialogue geometry is calibrated to the reference: speaker 68px,
  alias/club 48px, body 48px on the 2560 design grid; speaker and secondary
  identity use a fixed 248px grid; the panel minimum height is 336px.
- The lower shade darkens earlier through the dialogue band while preserving
  the scene above it. Custom diamond/bar decoration was removed from the
  official-compatible layer.
- `alias` is carried through the project-model descriptor and later enter
  events. Alias takes precedence over club and full-name fallback.
- The location label now has a finite entrance/hold/exit animation. Actor,
  dialogue, background, caret, and typewriter motion retain reduced-motion
  behavior.
- The AUTO/MENU editor tray is transparent on export-safe URLs and is revealed
  with `?editor=1`; descriptor values still control whether either stage button
  is rendered.

## Verification

- `24 passed`:
  `tests/test_aa_runtime_contract.py`, `tests/test_aa_stage_media.py`,
  `tests/test_ba_scene_preview.py`, `tests/test_ba_scene_preview_ui.py`, and
  `tests/test_render_timeline.py`.
- `node --check apps/desktop-client/scene-preview/aa-runtime.js`
- `node --check apps/desktop-client/scene-preview/preview.js`
- `git diff --check`
- In-app-browser checks at 640x360, 1280x720, and 1920x1080 kept the speaker,
  secondary identity, and dialogue anchors stable within 0.0014 normalized
  viewport units.
- Plain `pytest -q` remains blocked during collection by duplicate
  `test_http_api.py` module names in the existing production/writing service
  suites. `--import-mode=importlib` exposes existing absolute test-module
  imports and is not a valid substitute without a separate test-layout fix.

## Visual review

| Before | After | Why |
| --- | --- | --- |
| Extreme slots at 13.87/86.13% | Extreme slots at 18.75/81.25% | Applies the actual orthographic camera span instead of treating world units as 2560 canvas pixels. |
| Name 48, secondary 36, body 44 | Name 68, secondary 48, body 48 | Matches the observed 1.4:1 name/body hierarchy and reference glyph height. |
| Secondary identity flowed after the name | Fixed 248px secondary column | Keeps aliases and clubs at the same AA anchor regardless of name length. |
| Dialogue began too low | Name/text band raised and re-baselined | Alpha overlay aligns speaker, separator, and first dialogue line. |
| Editor switches ghosted into output | Export-safe tray opacity is zero | Straight video frames contain only authored stage UI. |

## Follow-up

Per-skeleton origin overrides may still be needed for unusual Spine crops, but
the shared camera projection, default size, and slot positions are now fixed.
