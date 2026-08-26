# 2026-08-27 SceneEvaluation / Render IR seam

## Scope

This slice makes the shared render intermediate result explicit for the 1.1
dual-mode editor. Studio remains the primary editing-semantics reference;
simple mode remains a low-operation-cost contextual workspace, and AA remains
secondary evidence for five visible slots and Cue-sized beats.

## Changes

- Added the `scene-evaluation/1.0` contract binding one scene descriptor,
  deterministic render timeline, and non-fatal diagnostics.
- Added the TypeScript `evaluateScene` and `buildRenderTimeline` seam used by
  the editor. The realtime iframe now receives the evaluated timeline and the
  existing preview validator rejects mismatches.
- Added the Python `scene_evaluation.evaluate_scene` wrapper for offline
  adapters. Namespaced professional events are reported as warnings and stay
  intact in the canonical project; the AA descriptor continues to omit only
  unsupported presentation events.
- Kept `scene-descriptor/1.0` and `render-timeline/1.0` unchanged, so current
  P69 descriptors, realtime/static preview, and video frame capture remain
  compatible.

## Verification

- `12 passed`: scene-editor Vitest suite.
- `15 passed`: scene evaluation, render timeline, and editor contract tests.
- `2164 passed, 14 skipped`: full Python suite.
- `npm run build`: TypeScript check and Vite production build passed.
- `python -m compileall -q packages/project-model tests/test_scene_evaluation.py`:
  passed.
- `python -m ruff check packages/project-model/scene_evaluation.py tests/test_scene_evaluation.py`:
  passed.
- Browser smoke with Vite plus the local preview fixture: passed at 1440x900;
  iframe reported `data-timeline-source="supplied"` and no page errors.

## Follow-up

1. Replace the demo capability map with generated local
   `character-capabilities/1.0` records and add non-destructive preview trials.
2. Route quick-effect events through the same descriptor/timeline seam.
3. Add the Tauri repository adapter and resumable export job state.

## Publication

- Branch: `feature/1.1-ba-editor-from-1.0`
- PR: https://github.com/Suciko/HaloCue/pull/27
- This handoff must be updated with the final commit hash after publication.
