# Professional editor command-dispatch tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `cc7e631`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

Professional keyboard operations now resolve through one command vocabulary:

- Ctrl/Cmd+S saves through the application boundary;
- Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, and Ctrl+Y resolve Undo/Redo;
- Ctrl/Cmd+D duplicates the professional event selection;
- Delete removes the professional event selection; and
- Alt+ArrowUp/Down and Alt+Home/End move the selection by one external item or
  to the first/last external boundary.

The professional event list owns one dispatcher. Row main buttons and drag
handles expose their shortcuts through `aria-keyshortcuts` but no longer carry
separate mutation algorithms. Toolbar clicks, row buttons, drag/drop, and
keyboard commands still converge on the same Store commands and transaction
outcomes.

Committed duplicate, delete, move, undo, and redo operations publish through
the list's existing polite live region. A no-op remains silent. Platform
Control/Meta differences and key normalization are isolated from project state.

## Native editing boundary

IME composition returns no editor command. Inputs, textareas, and editable DOM
subtrees retain native Duplicate/Delete/Undo behavior; the project dispatcher
does not depend on whether an Editor Transaction happens to be active. This is
important for focus-scoped dialogue and professional field transactions: native
text undo stays local while blur can still commit one canonical project edit.

Save is the only command intentionally allowed while a text field owns focus.
Simple mode retains the same command resolver for Save and project Undo/Redo,
without mounting professional selection commands.

## Changed paths

- `apps/desktop-client/scene-editor/src/editorCommands.ts`
- `apps/desktop-client/scene-editor/src/editorCommands.test.ts`
- `apps/desktop-client/scene-editor/src/eventReorderUi.test.tsx`
- `apps/desktop-client/scene-editor/src/App.tsx`

No canonical project schema, animation, preview, renderer, migration, resource,
or cross-context contract changed.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
21 test files passed; 118 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1605 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

Pure command tests cover Control/Meta parity, both Redo forms, event-list scope,
selection movement, IME suppression, and editable-target detection. Complete-App
tests prove that Duplicate and Delete dispatch once, Undo restores the exact
selection, Alt movement reaches the same block command, announcements update,
and Ctrl+Z inside the dialogue textarea does not consume project history.

A browser check selected events 02–03 and pressed Ctrl+D on the primary row.
Four rows became six exactly once, with the two duplicate rows selected and the
announcement `2 个事件已复制`. Ctrl+Z restored four rows and the original two-row
selection in one step, announcing `已撤销上一步编辑`.

## Known boundary and next action

This slice defines authoring command input, not a user-configurable shortcut
system. It does not add menus, command search, clipboard serialization, or
cross-Cue paste. Those features are unnecessary before the animation authoring
surface has a stable domain vocabulary.

The next bounded slice should begin the Resource Workspace sequence from the
long-term plan: browse `character-capabilities/1.0` expression, motion, and
emoticon states for the selected character, start a non-committing capability
trial in realtime preview, cancel without project/history/autosave changes, and
commit one supported capability through the existing Editor Transaction and
Scene Performance paths. Unknown or unavailable capabilities must remain
visible with an explicit diagnostic instead of being silently discarded.
