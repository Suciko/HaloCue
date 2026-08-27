# Event multi-selection and batch-delete tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `43d5725`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

Professional event selection now supports a real multi-selection model:

- plain click replaces the selection;
- Ctrl/Cmd-click toggles a stable event ID without creating project history;
- Shift-click selects a contiguous canonical range from a stable anchor;
- Ctrl/Cmd+Shift-click adds that range to the existing selection;
- the last focused event remains the primary event consumed by the inspector,
  preview intent, timeline playhead fallback, and insertion anchor; and
- auxiliary selected rows use a quieter visual state than the primary row.

When more than one event is selected, the header reports the count and exposes
one visible batch-delete command. Delete on a selected event also targets the
current selection. One command removes the complete stable-ID set, selects the
nearest survivor, and creates one revision/history entry. Undo restores the
events, ordering, primary event, selected stable IDs, and range anchor together.

## Editor-state boundary

`EditorSelection` now contains:

- `selectedEventId`: the single primary event used by existing consumers;
- `selectedEventIds`: unique IDs stored in canonical Cue order; and
- `eventSelectionAnchorId`: the stable range origin.

These fields are editor interaction state and history metadata. They do not
enter `HaloCueProject`, its JSON schema, render descriptors, preview intent, or
export contracts.

`eventSelection.ts` owns replace/toggle/range/add-range transitions, stale-ID
repair, canonical ordering, and nearest-survivor selection after deletion.
Scene/Cue changes reset the event set to the new Cue's first event. Project
commands repair selection against the validated resulting Cue. History and
future snapshots retain the complete editor selection.

## Changed paths

- `apps/desktop-client/scene-editor/src/eventSelection.ts`
- `apps/desktop-client/scene-editor/src/eventSelection.test.ts`
- `apps/desktop-client/scene-editor/src/types.ts`
- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/projectStore.test.ts`
- `apps/desktop-client/scene-editor/src/eventReorderUi.test.tsx`
- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`

No canonical project schema, migration, renderer, resource, or cross-context
contract changed.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
19 test files passed; 101 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1603 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Pure tests cover replacement, toggle, canonical ordering, contiguous and
additive ranges, stale-ID repair, and survivor choice. Store tests prove that
selection changes are history-free, batch delete is one revision, and Undo
restores the multi-selection. The complete-App DOM test drives Shift range
selection, visible batch command, deletion, announcement, and Undo.

A 1280 x 720 browser check selected events 02 through 04 with Shift. All three
rows exposed `aria-pressed`, the header reported three selected items, and the
inspector remained bound to event/dialogue/001 as the primary event. Batch
delete left the background event and announced three deletions. One Undo
restored the original four events, the three selected rows, and the dialogue
primary event.

## Known boundary and next action

Multi-selection is scoped to one selected Cue. Drag reorder and duration resize
intentionally collapse back to one primary event; moving a selected block and
batch-changing heterogeneous fields require separate semantics. Simple mode
continues to expose only its task-focused single selection.

The next bounded batch slice should duplicate the selected events as one
ordered block. It must deep-copy every known and namespaced payload field,
generate fresh stable event IDs, insert through the existing stable insertion
rule, select the duplicate block with a clear primary event, commit once, and
restore the original selection/order on one Undo.
