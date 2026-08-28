# 2026-08-27 ScenePerformance shake tracer bullet

## Scope

This slice starts the Studio-informed animation execution backbone without
building the complete professional timeline UI. It takes the existing
`halocue.ba:screen-shake` author event through compilation, source mapping,
deterministic execution modes, realtime preview, headless frame capture, and
resumable sequence identity.

- Owning context: `ba-editor`, `contracts`, `backend`
- Issues: part of #11 and #24
- Branch: `feature/1.1-ba-editor-from-1.0`
- PR: https://github.com/Suciko/HaloCue/pull/27
- Research boundary: ADR-0005; no Studio implementation or private assets copied

## Contracts

- Added `scene-performance/1.0` as a renderer-independent compiled performance
  plan. The first operation is a stable stage shake with target, channel, value
  space, frame range, parameters, and source-event mapping.
- Added `scene-evaluation/1.1`, which binds descriptor, render timeline,
  performance plan, and diagnostics. `scene-evaluation/1.0` remains present as
  the previous contract.
- Added `render-sequence/1.1`. Its resumable identity now hashes the performance
  plan as well as descriptor and timeline, preventing frame reuse across
  animation-plan changes. `render-sequence/1.0` remains present for old records.
- No persisted `HaloCueProject` schema migration was required. The performance
  plan is a deterministic derived artifact.

## Implementation

- TypeScript and Python compilers normalize the same author event into the same
  canonical plan.
- TypeScript, Python, and browser samplers implement `play`, `sample`, `skip`,
  and `reduced-motion` modes. Play and sample share exact frame math; skip and
  reduced motion retain a clean final baseline for this transient effect.
- The browser preview validates an injected plan against its independently
  derived result and exposes whether the source is `supplied` or `derived`.
- Sampled offsets are applied to stable stage child geometry, not CSS keyframe
  animation. Browser capture can disable animations without deleting the
  authored shake.
- Individual-frame and sequence renderers require and validate the same plan.
  Repository CLIs compile it before invoking the render Adapter.
- Realtime editor preview sends the complete `scene-evaluation/1.1` result to
  the iframe.

## Verification

```text
scene-editor Vitest: 10 files, 47 tests passed
scene-editor TypeScript/Vite build: passed
Python focused model/runtime/browser/export suite: 58 passed
scene-frame renderer suite: 6 passed
Ruff on all changed Python files: passed
Node syntax checks for preview and performance runtimes: passed
git diff --check: passed (only existing Windows LF/CRLF notices)
```

The browser/export regression renders one synthetic shake event at start,
middle, and end. Start and end PNG hashes are identical; the middle PNG hash is
different while Playwright captures with CSS animations disabled. This proves
that deterministic performance sampling, rather than a wall-clock CSS pulse,
owns the exported intermediate state.

## Known limits

- `scene-performance/1.0` currently defines only the stage shake operation. It
  deliberately does not claim that character tracks, camera tracks, patches,
  interval cues, audio, particles, or transitions are implemented.
- The contract currently uses frame-native timing because the existing render
  schedule is frame-native. A future professional clip authoring contract may
  retain millisecond keyframes and compile them into these frame ranges.
- Manual click-to-advance still has legacy transient CSS effects for event
  presentation. Deterministic timeline play, seek, preview synchronization, and
  export use the new sampler; the remaining transient effects should migrate
  one vertical slice at a time.
- Preview baseline generations, incremental reload/rebuild policy, and async
  invalidation remain the next Preview Session Module work, not part of this
  compiler tracer.

## Next recommended slice

Deepen the same Module with deterministic character enter/exit composition:

```text
enter/exit author event
  -> normalized opacity/layout operation with source map
  -> play/sample/skip/reduced-motion parity
  -> realtime preview and headless export parity
```

This should introduce contribution ownership for `character / layout` and
`character / opacity` instead of adding another CSS-only animation. After that,
add preview baseline generations before implementing professional timeline drag.
