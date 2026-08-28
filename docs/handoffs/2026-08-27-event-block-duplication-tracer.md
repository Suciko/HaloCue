# Selected event-block duplication tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `0861271`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

Professional event editing can now duplicate the current selection as one
ordered block. The command:

- resolves selected stable IDs back to canonical Cue order, including disjoint
  selections;
- deeply clones every known, unknown, and namespaced payload field;
- replaces only `event_id`, using one fresh stable ID per duplicate;
- inserts the complete duplicate block after the last selected source through
  the existing stable insertion rule;
- selects every duplicate and maps the original primary event and range anchor
  to their corresponding duplicates; and
- commits the project, selection, history, revision, diagnostics, and autosave
  request once.

The professional list exposes the command in a sticky multi-selection toolbar,
on each row, and through Ctrl/Cmd+D. If a row outside the current selection is
used, it first becomes the single selection. A live announcement reports the
number of copied events.

## Module boundary

`eventDuplication.ts` is a pure event-list operation. It owns source ordering,
fresh-ID validation, deep cloning, and stable block placement without knowing
about React, history, persistence, or preview state. `projectStore.ts` supplies
IDs and wraps the result in the existing Editor Transaction boundary.

Duplication changes author data, so it creates a durable revision. The selected
ID set, primary event, and range anchor remain editor-only state and do not
enter `HaloCueProject`, JSON schemas, render descriptors, preview intent, or
export contracts.

## Changed paths

- `apps/desktop-client/scene-editor/src/eventDuplication.ts`
- `apps/desktop-client/scene-editor/src/eventDuplication.test.ts`
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
20 test files passed; 106 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1604 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Pure tests cover canonical ordering for disjoint selection, preservation of
nested unknown payload, deep-clone independence, and rejection of empty or
colliding generated IDs. Store tests prove fresh IDs, source-relative primary
and anchor mapping, one history entry, and exact Undo restoration. The complete
App test drives Shift range selection, toolbar duplication, announcement, new
primary selection, and Undo.

A browser check selected events 02 through 04, duplicated them, and observed
seven rows with the three new rows selected. The primary inspector was bound to
the new dialogue event, the toolbar remained scoped to three selected items,
and the live region announced `3 个事件已复制`. One Undo restored four rows, the
original three selected events, and `event/dialogue/001` as the dialogue
primary.

## Known boundary and delivered next action

Duplication is scoped to one Cue and preserves relative source order. It does
not yet let a multi-selection move as one atomic block; existing grip, arrow,
and pointer reorder semantics still operate on one event and collapse to one
primary selection.

The selected-block reorder slice was delivered in implementation commit
`824b599` and is handed off in
`docs/handoffs/2026-08-27-event-block-reorder-tracer.md`. It preserves relative
order, rejects a drop inside the source block as a no-op, retains the complete
selection and primary/anchor identity, creates one revision and one undo entry,
and routes pointer, keyboard, and direction-button entry points through the
same stable block-placement operation.
