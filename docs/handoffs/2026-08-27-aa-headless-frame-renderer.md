# 2026-08-27 AA headless frame renderer

## Scope

This slice closes the first browser-to-offline frame loop for the 1.1
video-first renderer. It follows issues #8 and #24 and consumes the existing
`scene-descriptor/1.0` plus `render-timeline/1.0` contracts. It does not add
audio muxing, FFmpeg encoding, or proprietary resource bytes.

## Changes

- The scene preview accepts a caller-supplied `render-timeline/1.0` payload.
  Canonical JSON comparison rejects a timeline whose event data, durations, or
  frame boundaries differ from the descriptor-derived projection while
  allowing harmless object-key reordering.
- `?capture=1&frame=N` disables CSS animations, transitions, initial actor
  pulses, and wall-clock location dismissal before capture. Fonts,
  backgrounds, raster fallbacks, and visible realtime Spine canvases must all
  reach a ready state before a frame is returned.
- `halocue_production.scene_frame_renderer` validates localhost-only URLs,
  exact 16:9 dimensions, contiguous end-exclusive frame ranges, scene/event
  identity, and explicit frame bounds. It captures only `#preview-stage`,
  validates the PNG dimensions, writes atomically, and reports the event ID,
  frame rate, renderer, contract version, and SHA-256.
- `tools/render_scene_frame.py` is the current repository entry point. It
  builds the Python timeline from a descriptor and supports either an explicit
  frame or `presentation.reference_frame.resolved_frame`.
- The production package exposes Playwright as an optional `render` dependency;
  the existing service remains usable without installing a browser.

## Verification

- `36 passed`: `tests/test_aa_runtime_contract.py`,
  `tests/test_render_timeline.py`, `tests/test_ba_scene_preview.py`,
  `tests/test_aa_stage_media.py`, `tests/test_csp_headers.py`, and
  `tests/test_scene_frame_renderer.py`.
- `10 passed`: `tests/test_ba_scene_preview_ui.py`.
- `84 passed`: `services/halocue/production/tests`.
- Node syntax checks and Ruff passed for the changed JavaScript/Python files.
- The synthetic multi-event descriptor produced identical hashes for repeated
  captures of one dialogue frame and a different hash for a later speaker's
  frame, covering different slots and event history without public AA bytes.
- Local authorized-resource validation captured realtime P69 frame 35 at
  1280x720. The supplied Python timeline path and the independently derived
  browser timeline path both produced the same 1,188,632-byte PNG with SHA-256
  `3a69bf835e4a2bb16dcb9fd93eb560a56dd890311716132a83f20e32ce350ec5` in the
  validation run.

## Determinism boundary

Repeated captures inside one export path are byte-stable. Chromium processes
or reused GPU compositor contexts can round a small number of translucent edge
pixels differently. The browser-path regression therefore also checks decoded
pixels: fewer than 0.2% may differ, per-channel mean difference must stay below
0.003/255, and RMS below 0.2/255. This catches visible layout, typography,
resource, or timing drift without treating subpixel compositor rounding as a
scene-contract failure.

## Follow-up

1. Reuse one loaded page and browser context to render a complete numbered PNG
   sequence without paying startup and resource-loading cost per frame.
2. Add resumable export-job state, then feed that sequence to detected FFmpeg
   with explicit frame rate and later audio muxing.
3. Calibrate a second authorized official reference with a different
   background crop, slot arrangement, and event sequence. The current second
   descriptor proves contract generality but is synthetic, not a second
   official pixel baseline.
