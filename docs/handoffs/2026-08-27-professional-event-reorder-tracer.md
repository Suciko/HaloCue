# Professional event reorder tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `8befda3`
- Full-App test boundary follow-up: `2e5cd9a`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

The grip shown on every professional event row is now a real reorder control:

- dragging a grip marks the source row and shows a two-pixel insertion line
  above or below the hovered stable target;
- dropping moves the original event object and stable ID, keeps it selected,
  clears all transient drag classes, and creates one revision;
- Arrow Up/Down move one item, Home/End move to the Cue boundaries, and the
  explicit up/down buttons use the same command; and
- an `aria-live` status announces the event label and new one-based position.

The event-selection button, reorder grip, duration handle, and destructive row
actions remain separate focus targets. This avoids making the full row both a
selection button and a drag source.

## One ordering model

`eventReorder.ts` defines `EventMove` as either a one-step direction or a stable
target ID plus `before`/`after` placement. Both forms resolve through the same
pure `reorderEvents` function. `projectStore.moveEvent` remains the only durable
event-order command; React drag state stores only the current source and visual
drop target.

The final drop derives placement directly from the pointer and target row
geometry. It does not trust an asynchronously rendered hover state, so a fast
drag-over/drop sequence cannot commit the previous insertion target. Invalid,
self, boundary, and already-equivalent placements preserve the original order
and remain no-op transactions.

## Changed paths

- `apps/desktop-client/scene-editor/src/eventReorder.ts`
- `apps/desktop-client/scene-editor/src/eventReorder.test.ts`
- `apps/desktop-client/scene-editor/src/eventReorderUi.test.tsx`
- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/projectStore.test.ts`
- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`

No contract, migration, renderer, resource, or proprietary research input
changed in this editor-only slice.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
17 test files passed; 91 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1601 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Pure tests cover midpoint placement, directional/relative equivalence,
non-adjacent targets, invalid targets, boundaries, and equivalent no-ops. Store
tests prove stable-ID order, selection preservation, one history entry, one-step
undo, and no history for an equivalent placement.

The jsdom interaction test renders the complete App in professional mode, then
dispatches `dragstart`, `dragover`, and `drop` through the event list. It checks
source dimming, the target insertion class, data-transfer move semantics, final
order, selection, revision/history, announcement text, and transient-state
cleanup. Rendering through the default App export preserves Vite's existing
Fast Refresh boundary.

A 1280 x 720 browser check confirmed the dedicated visible/focusable grip and
focus ring. Arrow Up moved the second event to position 1, retained the moved
event in the inspector, enabled one Undo, announced its new position, and one
Undo restored the full original order.

## Known boundary and next action

This slice reorders events inside one selected Cue. It does not move events
between Cues, auto-scroll long lists during drag, or add multi-selection. Those
belong to larger professional timeline and batch-edit slices.

The stable insertion follow-up is delivered in implementation commit `38392ef`
and documented by
`docs/handoffs/2026-08-27-stable-event-insertion-tracer.md`. The next
professional skeleton gap is multi-selection with one atomic batch command;
single-selection reorder and insertion should remain the primary anchor.
