# Stable event insertion tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `38392ef`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

The professional add-event menu no longer appends every new event blindly:

- its summary names the selected one-based event position and current
  before/after placement;
- a two-option control changes placement without closing the menu;
- choosing an event type inserts one factory-created event relative to the
  selected stable event ID;
- the new event becomes the primary selection immediately; and
- one Undo removes it and restores the prior anchor selection and order.

Keeping placement in the open menu makes repeated insertion predictable while
avoiding a separate modal or a second event-creation path.

## Canonical insertion boundary

`eventInsertion.ts` owns the pure stable-anchor-to-index rule. It receives only
the ordered stable IDs plus `{ anchorEventId, placement }`. A valid anchor maps
to its index or the following index. Missing, stale, or null anchors append;
an empty Cue therefore resolves to index zero.

`projectStore.addEvent` remains the only professional creation command. It asks
the existing event factory for the typed event, inserts it at the resolved
index, and publishes `selectedEventId` in the same validated revision. The UI
does not retain an array index as project truth.

## Changed paths

- `apps/desktop-client/scene-editor/src/eventInsertion.ts`
- `apps/desktop-client/scene-editor/src/eventInsertion.test.ts`
- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/projectStore.test.ts`
- `apps/desktop-client/scene-editor/src/eventReorderUi.test.tsx`
- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`

No schema, migration, renderer, resource, or cross-context contract changed.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
18 test files passed; 96 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1602 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Pure tests cover before/after resolution, missing/null/stale anchors, append
fallback, and an empty Cue. Store coverage proves relative stable-ID order,
factory output, new selection, one revision/history entry, and one-step undo
with anchor restoration. The complete-App DOM test drives selection, placement,
event type, final order, and undo through the rendered professional UI.

A 1280 x 720 browser check selected event 02, opened the menu, changed the
summary from “在 02 后添加” to “在 02 前添加”, inserted a Wait event at position
02, selected its generated stable ID in the inspector, and enabled one Undo.
One Undo restored the original four-event order and the prior event/enter/yuuka
anchor.

## Known boundary and next action

Insertion is scoped to the currently selected Cue. It does not yet duplicate an
existing event, insert from the timeline track, or paste a copied event payload.
Those operations should reuse the same stable insertion intent when added.

The multi-selection and atomic batch-delete follow-up is delivered in
implementation commit `43d5725` and documented by
`docs/handoffs/2026-08-27-event-multiselect-batch-delete-tracer.md`. The next
batch command should duplicate the selected stable payloads with fresh IDs and
reuse the existing insertion boundary.
