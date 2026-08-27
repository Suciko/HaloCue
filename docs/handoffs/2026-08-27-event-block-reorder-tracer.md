# Selected event-block reorder tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `824b599`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

Professional multi-selection can now move as one ordered block. The same
stable placement operation is used by:

- pointer drag and before/after row drop targets;
- ArrowUp and ArrowDown one-external-item movement;
- Home and End movement to the first or last external boundary; and
- the visible row direction buttons.

Selected events are resolved in canonical Cue order, removed together, and
inserted together. Contiguous and disjoint selections therefore keep their
internal relative order and become a contiguous block after a successful move.
A target inside the selected source set is invalid, and an equivalent external
boundary returns the original array reference so the Editor Transaction remains
a true no-op.

Starting a drag from a selected row keeps the complete selection. Every selected
row receives the dragging state, targets inside the block do not show a drop
indicator, and the completed announcement reports both the event count and its
new positional range. Starting from an unselected row retains the established
single-event behavior.

## State and transaction boundary

`reorderEventBlock` is a pure stable-ID list operation. `moveEvent` chooses the
current editor selection only when the initiating event belongs to it; otherwise
it moves that one event. The Store's existing commit boundary owns validation,
history, revision, autosave, diagnostics, and no-op detection.

The selected stable IDs, primary event, and range anchor do not change during a
successful move and are restored with the project snapshot on Undo. No editor
selection state enters `HaloCueProject`, preview intent, render descriptors, or
export contracts.

## Changed paths

- `apps/desktop-client/scene-editor/src/eventReorder.ts`
- `apps/desktop-client/scene-editor/src/eventReorder.test.ts`
- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/projectStore.test.ts`
- `apps/desktop-client/scene-editor/src/eventReorderUi.test.tsx`
- `apps/desktop-client/scene-editor/src/App.tsx`

No canonical project schema, migration, renderer, resource, or cross-context
contract changed.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
20 test files passed; 112 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1604 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Pure tests cover canonical ordering, disjoint selection, one-external-item
movement, internal-target rejection, equivalent placement, and invalid source
IDs. Store tests prove one revision, selection identity retention, internal
no-op behavior, and exact Undo restoration. Complete-App tests drive selected
block pointer drag, group dragging/drop states, Home/End, direction buttons,
announcements, and Undo.

A browser check selected events 02–03 and used the visible group-aware Up
button. The rows became positions 01–02 in their original order, both remained
selected, and the live region announced `2 个事件已移动到第 1–2 项`. One Undo
restored the original four-row order, both selected rows, and
`event/enter/noa` as the primary inspector event.

## Known boundary and delivered next action

Block movement is intentionally scoped to one Cue. It compresses a disjoint
selection into one contiguous block after movement; it does not preserve gaps,
move events across Cues, or retime animation durations. Timeline duration
handles remain single-event gestures because a proportional multi-event retime
needs a separate baseline and snapping rule.

The professional command-dispatch slice was delivered in implementation commit
`cc7e631` and is handed off in
`docs/handoffs/2026-08-27-professional-command-dispatch-tracer.md`. Duplicate,
Delete, Move, Undo, and Redo work from one list-surface dispatcher instead of
per-row handlers. Platform modifiers, IME composition, native text undo, Store
outcomes, and accessible announcements now share one tested boundary.
