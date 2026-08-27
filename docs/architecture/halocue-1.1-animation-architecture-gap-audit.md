# HaloCue 1.1 animation architecture gap audit

- Kind: architecture audit
- Scope: release 1.1, `contexts/ba-editor`, preview and export adapters
- Status: candidate findings; no interface or contract accepted yet
- Observed at: 2026-08-27
- Owning work: Issue #11, Issue #24, PR #27
- Research basis:
  - `../../../../03-research/studio-code-architecture-study.md`
  - `../../../../03-research/studio-official-docs-module-log.md`
  - `../../../../03-research/halocue-animation-ir-draft-from-studio-study.md`
  - `docs/architecture/halocue-1.1-editor-long-term-plan.md`

This record compares the current HaloCue 1.1 implementation with the animation,
preview, and editing seams observed in Studio. It uses the Matt engineering
skills' deletion test: if removing a module merely moves its complexity into
callers, the module has useful Depth; if callers can trivially inline it, the
module is shallow.

## Verified baseline

The current branch is `feature/1.1-ba-editor-from-1.0`. On 2026-08-27 the
following narrow checks passed before any implementation change:

```text
scene-editor Vitest: 9 files, 44 tests passed
Python render/editor checks: 18 tests passed
```

The existing baseline is real and useful: one canonical project, stable Cue
and event IDs, deterministic sequential frame ranges, shared scene evaluation,
five-position stage projection, simple/professional editing, realtime preview,
headless frame capture, undo/redo, registries, and diagnostics all have tests.
The gap is not an absence of a prototype. The gap is that the prototype's
animation and preview responsibilities have not yet been deepened into one
deterministic performance system.

## Finding 1: Scene Performance Compiler Module

### Files

- `apps/desktop-client/scene-editor/src/sceneEvaluation.ts`
- `apps/desktop-client/scene-editor/src/descriptor.ts`
- `apps/desktop-client/scene-editor/src/renderTimeline.ts`
- `apps/desktop-client/scene-editor/src/cueStateProjection.ts`
- `packages/project-model/project_model.py`
- `packages/project-model/scene_evaluation.py`
- `packages/project-model/render_timeline.py`
- `packages/contracts/scene-evaluation/1.0.schema.json`
- `packages/contracts/render-timeline/1.0.schema.json`
- `apps/desktop-client/scene-preview/aa-runtime.js`

### Problem

`SceneEvaluation` is currently a shallow wrapper over descriptor and sequential
timeline construction. Removing the wrapper would let callers invoke those two
functions directly without removing much complexity. More importantly, the
same named concept has already drifted across Adapters:

- TypeScript evaluates through a selected Cue and starts from the first Scene;
- Python evaluates a complete Scene selected by `scene_id`;
- descriptor fields, capability resolution, and diagnostics differ;
- timeline construction is implemented independently in TypeScript, Python,
  and the browser runtime.

The existing `RenderTimeline` only assigns end-exclusive frame ranges to a
serial event list. It does not own normalized animation tracks, interval cues,
execution modes, source mapping, or sampled final state.

### Candidate solution

Deepen scene evaluation into a Scene Performance Compiler Module that owns
author-event normalization, explicit preview scope, stable ordering, animation
IR, source mapping, diagnostics, and the deterministic render schedule. Simple
and professional editors retain distinct authoring projections, while preview
and export consume one compiled result through explicit Adapters.

No concrete Interface is accepted by this audit.

### Benefits

- One high-Leverage Seam for simple mode, professional mode, preview, and export.
- Cross-language semantic drift becomes a parity failure instead of a visual bug.
- Compilation, source attribution, and invalid-event diagnostics gain Locality.
- New animation features stop requiring coordinated special cases in every UI
  and renderer.

### Required tests

- TypeScript and Python produce the same canonical hash for the same scope.
- current-Cue preview and complete-Scene export use explicit compile modes.
- a simple action and its equivalent professional clip sample identically.
- one source event expanded into several operations remains bidirectionally
  traceable.
- namespaced unknown events round-trip with stable diagnostic locations.
- preview and export consume matching compiled hashes at the same frame.

## Finding 2: Preview Session Module

### Files

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-preview/preview.js`
- `apps/desktop-client/scene-preview/spine-preview.js`
- `services/halocue/production/src/halocue_production/scene_frame_renderer.py`
- `services/halocue/production/src/halocue_production/scene_video_renderer.py`

### Problem

The React preview waits 140 ms after an evaluation change, remounts the browser
controller, and seeks to the last frame. The browser controller owns an
event-index snapshot cache, but there is no baseline token tied to project
revision, engine instance, source event, or generation. Background and Spine
loads can complete asynchronously without a shared stale-generation rule.
There is also no explicit incremental-seek, reload, and rebuild escalation
policy or separate target/actual cursor state.

The deletion test shows the missing Depth: lifecycle, cancellation, ready
state, and seek decisions would otherwise be reimplemented by React, browser,
capture, and future timeline callers.

### Candidate solution

Introduce a Preview Session Module independent of React. It owns baseline and
generation identity, target and actual cursors, update classification,
cancellation, failure, and the incremental-seek/reload/rebuild decision. The
iframe renderer and deterministic capture become Adapters behind this Seam.

### Benefits

- Async races and stale callbacks gain Locality.
- Compatible edits can preserve the engine and playback position.
- Timeline scrubbing, normal preview, and capture reuse one lifecycle model.
- Starting playback from a sampled middle frame need not flash through frame 0.

### Required tests

- stale background, Spine, or reload completion cannot mutate a new generation.
- compatible edits do not rebuild the engine.
- reverse seek, signature changes, and resolution changes choose the correct
  escalation path.
- drag preview changes a candidate cursor; commit performs one seek.
- aborted seek leaves no partial stage, character, filter, or playback state.
- middle-frame playback starts from the prepared sampled revision.

## Finding 3: Animation Execution and Stage Composition Module

### Files

- `packages/contracts/scene-events/1.0.json`
- `apps/desktop-client/scene-editor/src/sceneEventRegistry.ts`
- `apps/desktop-client/scene-editor/src/eventEditorCatalog.ts`
- `apps/desktop-client/scene-editor/src/capabilities.ts`
- `apps/desktop-client/scene-preview/aa-runtime.js`
- `apps/desktop-client/scene-preview/preview.js`
- `apps/desktop-client/scene-preview/preview.css`

### Problem

Animation behavior is split among `applyEvent`, `applySampledEvent`, DOM
rendering, Spine state, and CSS pulse classes. There is no normalized target,
channel, value space, continuous track, timed patch, interval cue, channel
ownership, or common `play | sample | skip | reducedMotion` behavior.

The event registry provides useful Leverage for labels, duration, and basic
renderability, but its Interface does not own execution semantics. Keeping the
registry still leaves animation conflicts, cleanup, and final-state rules spread
across runtime branches.

### Candidate solution

Deepen the registry/runtime boundary into normalized Animation IR plus an
executor Module. Stable target/channel composition owns character, camera,
scene, and overlay state; effect Adapters declare lifecycle, seek, and reduced
motion behavior through a registry Seam.

### Benefits

- Conflict, final-state, cancellation, and seek rules gain Locality.
- Each preset gains play, sample, skip, reduced-motion, and export behavior at
  once.
- Simple and professional editing share one executor instead of matching by
  convention.

### Required tests

- sampling at time T matches stable state after playing from zero to T.
- skip, zero-duration, and reduced-motion reach the same semantic final state.
- one character/channel can be superseded without stopping other channels.
- separate characters can animate concurrently.
- style, motion, focus, and camera contributions clean up independently.
- scene, audio, and particle intervals preserve their distinct seek behavior.
- deterministic capture renders animation intermediate states with CSS
  animation disabled.

## Finding 4: Editor Transaction Module

### Files

- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/projectRepository.ts`
- `apps/desktop-client/scene-editor/src/App.tsx`

### Problem

The Zustand Store already centralizes some useful behavior, but its public
Interface exposes roughly one method per UI action and each Implementation
still knows cloning, ID generation, first-Scene assumptions, selection repair,
persistence, history, and revision changes. Durable edits save synchronously.
The shape cannot support high-frequency timeline drag without producing many
history entries or mixing trial state with project state.

Deleting the Store would scatter mutation and undo/redo across the UI, so it
has real Leverage. It should be deepened rather than replaced.

### Candidate solution

Create an Editor Transaction Module that owns stable IDs, command validation,
selection repair, no-op detection, begin/preview/commit, undo/redo, and project
revision. Zustand becomes a UI Adapter and `ProjectRepository` remains the
persistence Seam.

### Benefits

- Atomic mutation and history semantics gain Locality.
- simple controls, professional inspectors, shortcuts, and timeline gestures
  reuse the same commands.
- editor trials can remain non-durable until commit.

### Required tests

- one drag creates one undo entry.
- a no-op neither saves nor increments history/revision.
- a failed save does not publish partial project or selection state.
- simple and professional entry points create identical canonical changes.
- Cue/event deletion repairs selection deterministically.
- commands address the selected Chapter and Scene instead of the first Scene.
- edit commit, autosave, and preview compilation can coalesce independently.

## Recommended first tracer bullet

Start with Finding 1 and prove it using the existing
`halocue.ba:screen-shake` author event:

```text
HaloCueProject event
  -> normalized ShakeCue plus source map
  -> deterministic play/sample/skip/reducedMotion states
  -> realtime preview
  -> headless frame export
  -> cross-adapter parity tests
```

This is intentionally a narrow vertical slice, not a complete timeline editor.
Today screen shake is a CSS pulse. Deterministic capture disables CSS animation,
so the effect can appear in realtime while lacking a matching exported
intermediate state. Solving this one path forces the new Module to carry real
animation semantics through authoring, compilation, execution, preview, and
export before more effects are added.

After this tracer bullet, the same Seam can take character enter/exit, movement,
camera motion, transitions, audio, and particles in small reviewed slices.

### Implementation record

Implemented on 2026-08-27 in the current PR worktree. The result is recorded in
`docs/handoffs/2026-08-27-scene-performance-shake-tracer.md` and includes the
versioned `scene-performance/1.0`, `scene-evaluation/1.1`, and
`render-sequence/1.1` contracts plus TypeScript, Python, browser, and headless
export parity tests. This completes only the shake tracer bullet; Findings 1-4
remain broader long-term Modules rather than completed architecture.

The next slice extends that Seam to character enter/exit and is recorded in
`docs/handoffs/2026-08-27-scene-performance-character-tween-tracer.md`. It
introduces `scene-performance/1.1` and `scene-evaluation/1.2`, with one authored
event mapped to separate opacity, layout-offset, and scale operations. This is
still a performance-compiler slice, not completion of the Preview Session or
Editor Transaction Modules.

The first Preview Session slice is recorded in
`docs/handoffs/2026-08-27-preview-session-generation-tracer.md`. It adds an
explicit generation boundary, validates a candidate before replacing the live
session, and prevents stale controllers or delayed media callbacks from
mutating the shared stage. Broader scene ownership and editor-to-preview
selection synchronization remain later slices.

## Small shallow seam found

`apps/desktop-client/scene-editor/src/sceneEventFactory.ts` is currently a pure
forwarder to `createEditorEvent`. Its deletion test changes only one caller, so
it should not be treated as an architectural Seam. Removing it is optional and
should be done only inside an affected implementation slice, not as standalone
cleanup.

## Decision needed before implementation

The maintainer should choose which candidate Module to deepen first. The audit
recommends the Scene Performance Compiler tracer bullet above. After that
choice, use `to-issues` to draft small AFK/HITL tracer-bullet Issues and obtain
approval before publishing them.
