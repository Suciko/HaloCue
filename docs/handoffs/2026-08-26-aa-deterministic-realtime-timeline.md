# 2026-08-26 AA deterministic realtime timeline

## Scope

This slice turns the calibrated P69 preview into the first deterministic
realtime scene path for the 1.1 video-first renderer. It follows GitHub issues
#8 and #24 and keeps user-owned AA resources behind the existing local resource
adapter.

## Changes

- `render-timeline/1.0` now has a versioned JSON Schema under
  `packages/contracts/render-timeline/1.0.schema.json`.
- The browser AA runtime builds the same end-exclusive event ranges and default
  durations as `packages/project-model/render_timeline.py`; a Node/Python parity
  test compares the complete JSON result.
- The scene preview controller exposes `seekFrame`, `seekEvent`,
  `seekReference`, `play`, `pause`, and `dispose`. Event-boundary state is
  cached so sequential frame playback does not replay the entire scene on each
  frame.
- `?reference=1` seeks and freezes descriptor reference metadata. P69 records
  frame 35 at 30fps and a 1166.667ms Spine sample. `?frame=N` and `?play=1`
  support deterministic authoring and headless capture.
- Realtime Spine players support pause and absolute seek. They stop ticking in
  hidden documents, detach with invisible actors, and retain the capped canvas
  resolution policy. The default preview remains a freely animated realtime
  view.
- `?editor=1` now exposes a transport with play/pause, a frame scrubber, frame
  position, and reference-frame jump. Wide screens use a non-overlapping
  resource/stage workbench; narrow screens keep the stage above the bottom
  controls.

## Verification

- `33 passed`:
  `tests/test_aa_runtime_contract.py`, `tests/test_render_timeline.py`,
  `tests/test_ba_scene_preview.py`, `tests/test_aa_stage_media.py`, and
  `tests/test_csp_headers.py`.
- `10 passed`: `tests/test_ba_scene_preview_ui.py`.
- `node --check` passed for `aa-runtime.js`, `preview.js`, and
  `spine-preview.js`; `git diff --check` passed.
- Local authorized-resource browser validation confirmed two realtime P69
  canvases ready with no console errors. Two reference-mode captures 420ms
  apart had identical hashes, while two default-mode captures differed.
- Visual checks passed at 1280x720 and 640x360 without overlap between the
  stage, timeline transport, and overlay-option controls.

## Follow-up

The next vertical slice should make the headless/offline renderer consume the
same `render-timeline/1.0` payload and capture one frame by explicit frame
number. After that, validate the descriptor-only path against a second official
scene with different slots, events, and background framing before adding audio
muxing.
