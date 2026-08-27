# Canonical Scene selection tracer handoff

Date: 2026-08-27

## Outcome

The editor now carries one canonical four-level selection:

- `selectedChapterId`;
- `selectedSceneId`;
- `selectedCueId`; and
- `selectedEventId`.

The selection is initialized when a project opens, repaired when Chapter,
Scene, or Cue changes, and captured in undo/redo history. Clicking an already
selected parent is idempotent and does not discard its more specific child
selection. Stale cross-Scene Cue and event IDs are rejected.

## Command ownership

The shared command path now resolves the selected Scene before editing. This
applies to dialogue/environment/character updates, slot swaps, event editing,
Cue insertion/duplication/movement/deletion, and selection repair after delete.
Undo and redo restore the complete Chapter/Scene/Cue/event identity alongside
the project snapshot.

Descriptor generation and Scene Evaluation accept an explicit `sceneId`.
Advanced-event diagnostics are scoped to the evaluated Scene, while project
structural diagnostics remain project-wide. Preview Intent therefore carries
the same selected Scene identity into the browser session.

## Editor navigation

The project rail renders every Chapter and Scene. Selecting either repairs Cue
and event selection to the first valid child; professional mode expands the
selected Scene's Cue list. Stage slots, Cue strip, inspectors, event list, and
timeline all read the same selected Scene.

The `firstScene` helper remains only as a compatibility default for older
callers and tests that omit `sceneId`; it is no longer used by live editor
commands or panels.

## Verification

Verification completed with 55 scene-editor tests and 63 Python/model/browser
integration tests. The TypeScript production build and whitespace check also
passed.

## Remaining work

Scene creation, deletion, and reordering are not part of this tracer. The next
architecture slice is Editor Transaction: distinguish no-op from mutation,
make save failure atomic, and coalesce edit commits, autosave, and preview
compilation without losing the canonical selection established here.
