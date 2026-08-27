# Scene performance nod keyframes handoff

Date: 2026-08-27

## Scope

Issue: #24, `[Phase 2] Integrate collaborator BA editor through reviewed slices`

PR: #27, `feat(1.1): add canonical dual-mode BA scene editor`

Implementation commit: `3b7c489 feat(1.1): normalize character nod performance`

This tracer replaces the preview-only CSS interpretation of `motion/nod` with
one versioned, renderer-independent performance plan. It also stops treating a
later `enter` for the same character and slot as another placement animation.

## Contract and runtime decisions

- `scene-performance/1.2` adds `numeric-keyframes` character operations.
- The first channels are additive `layout.offset-y` and
  `presentation.rotation`, both relative to the actor baseline.
- `motion/nod` preserves the existing visual poses at offsets `0`, `0.32`,
  `0.68`, and `1`, but interpolation now uses the shared strong ease-in-out
  token `cubic-bezier(0.77, 0, 0.175, 1)`.
- A true placement may compose entrance opacity/offset/scale with requested nod
  keyframes. A later same-character update compiles only the nod keyframes and
  does not replay entrance.
- Dialogue events carrying `motion/nod` resolve the character's occupied slot
  and compile the same operations.
- Play and sample are seek-safe. Skip and reduced-motion omit the transient nod
  operations, leaving offset and rotation at the clean baseline.
- `scene-evaluation/1.3` binds the new performance contract.
- TypeScript, the standalone browser runtime, and Python use matching compiler,
  cubic-bezier solver, sampling, quantization, and source-map semantics.

## Editor and preview behavior

- The preview applies sampled rotation as an individual transform alongside
  sampled translation and scale, so capture mode no longer loses the nod.
- The persistent `is-motion-nod` class is removed from sampled renders to avoid
  a second CSS animation fighting the performance plan.
- The preview controller accepts `play({fromFrame, toFrame})` and stops on the
  exact requested frame.
- Hover/focus trials for `motion/nod` locate the compiled operation and replay
  only its event range. Browser reduced-motion preference selects the
  reduced-motion execution mode for playback.

## Verification

- `npm test` in `apps/desktop-client/scene-editor`: 22 files, 124 tests passed.
- `npm run build` in `apps/desktop-client/scene-editor`: passed.
- `python -m pytest tests/test_scene_performance.py tests/test_scene_evaluation.py tests/test_scene_frame_renderer.py tests/test_ba_scene_preview_ui.py -q`: 30 passed.
- `python -m pytest -q`: 2190 passed, 14 skipped.
- Playwright verifies that deterministic capture can seek the nod peak, reads
  non-zero offset and rotation from the DOM, returns to zero at the terminal
  frame, and stops bounded playback at the exact requested frame.
- Cross-runtime tests compare Python and browser plans/samples at entrance,
  nod rise/peak/recovery, shake, and exit frames.

## Known gaps and next slice

- The canonical authoring model still overloads `enter` for placement and some
  character-state updates. Occupancy-aware compilation removes the visible
  error, but an explicit character state/motion event remains the cleaner
  long-term model.
- A nod attached to the first placement intentionally composes with entrance;
  a future explicit motion event can let Inspector trials replay motion against
  a fully settled actor without also replaying first placement.
- `motion/appear`, idle motion, hit effects, background pans, emoticon pop,
  dialogue-panel motion, and transitions still have CSS-only paths. Migrate one
  effect family at a time through `scene-performance`, with the same browser /
  Python / capture parity gate.
- The next recommended tracer is an explicit authored character-motion event
  and Inspector trial intent, followed by `motion/appear` on the same keyframe
  operation type.

## Safety and repository state

No Studio, AA, decompiled application, or real game resource bytes were copied.
Only behavior and motion semantics were implemented. Existing unrelated local
changes in `AGENTS.md`, `CONTEXT-MAP.md`, `contexts/ba-editor/CONTEXT.md`, and
the user's three untracked long-term research documents were left untouched and
were not staged.
