# 2026-08-27 CueStateProjection maintenance slice

## Scope

This slice deepens the editor's scene-state replay into one pure TypeScript
Module. Quick editing, professional authoring, descriptor generation, and
scene evaluation now consume the same Cue projection rather than each
replaying stage events independently.

The work follows the `improve-codebase-architecture` skill's deletion test:
removing the old `stageAtCue` implementation would otherwise require callers
to recreate slot, actor-state, background, and Cue lookup logic in several
places. The new seam concentrates that knowledge without changing the
canonical `HaloCueProject` shape.

## Interface

`apps/desktop-client/scene-editor/src/cueStateProjection.ts` exposes:

- `projectCueState(project, cueId)` for project-level lookup;
- `projectSceneAtCue(scene, cueId)` for pure ordered replay;
- `beforeCue` and `afterCue` five-slot snapshots;
- effective actor state events, effective background state, ordered events,
  renderable events, and current-Cue dialogue/background indices;
- `sceneById` and `firstScene` for stable scene selection semantics.

The projection ignores out-of-range stage slots rather than creating invisible
array properties. Advanced namespaced events remain in `orderedEvents` and are
omitted only from `renderableEvents`, preserving the existing warning and
round-trip behavior.

## Callers and behavior

- `descriptor.ts` derives actors and background from `afterCue` and keeps the
  existing initial-background/hidden-initial-actors contract.
- `projectStore.ts` keeps `stageAtCue` as a compatibility wrapper, while swap,
  character-state updates, and inherited background edits use the projection.
- `App.tsx` uses the projection for slots, Cue summaries, character state,
  dialogue, and environment context in quick mode.
- An environment edit in a Cue without a local background creates a new local
  override seeded from the effective previous background, keeping the
  low-operation-cost workflow without mutating an earlier Cue.

## Verification

- Scene-editor Vitest: `32 passed`.
- Scene-editor TypeScript no-emit check and Vite production build: passed.
- `git diff --check`: passed.
- Build retains the existing runtime warning for the unresolved absolute
  `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf` browser asset path;
  this is a deployment/runtime asset lookup issue, not a TypeScript failure.

## Font clarification

The current realtime BA dialogue renderer does not use
`NotoSansTC-Medium/Bold.otf`. It uses the bundled static
`NotoSansSC-Medium.ttf` for dialogue body text (`font-weight: 500`) and
`NotoSansSC-Bold.ttf` for the speaker name (`font-weight: 700`). The editor UI
uses the separate `NotoSansSC-Variable.ttf` declaration.

## Next slice

Build an `EventEditorCatalog` Adapter on top of the existing Scene Event
Registry so professional event creation, summaries, icons, and typed field
editing stop depending on unrelated `App.tsx` kind switches. Keep simple mode
contextual by selecting only the small subset of catalog fields needed for the
current task.
