# Dialogue composition transaction tracer handoff

Date: 2026-08-27

## Outcome

Dialogue display-name and body fields now use a focus-scoped editor
transaction:

```text
focus/composition start -> preview each input value -> blur commits once
                                             Escape -> cancel
```

Intermediate values update the controlled field and live working preview, but
do not increment project revision, append history, clear redo, or request
autosave. Blur validates the final project and produces one canonical revision,
one undo entry, and one pending autosave regardless of how many input or IME
composition updates occurred.

## Keyboard and focus semantics

Escape restores the transaction baseline and moves focus out of the field.
Ctrl/Cmd+Z remains native to an input, textarea, or content-editable element
while its text transaction is active. This lets users undo composition and
typing locally before the field is committed. After blur, project Undo reverts
the entire focus session as one edit.

Ctrl/Cmd+S still finishes the active transaction, flushes autosave, and exports
the latest complete project. Clicking another editor command or canonical
selection also commits the text session before continuing, using the shared
transaction boundary rather than component-local snapshots.

## Architecture

The Store now has a generic active-transaction preview path used by both
environment zoom and dialogue composition. Field-specific adapters only apply
their canonical event patch; cloning, target validation, working revision,
commit, cancel, history, and autosave remain centralized.

## Verification

Store coverage sends three Chinese intermediate values through one dialogue
session and proves zero revision/history/autosave changes before commit, then
one revision, one history entry, and one autosave afterward. Undo restores the
complete original project.

Verification completed with 75 scene-editor tests and the production
TypeScript build. A browser interaction check confirmed the active preview
status, blur commit, enabled project Undo, and one-step restoration of the
original full dialogue. The focused 40-test contract/model/browser boundary
from the preceding playhead slice remains green and is unaffected by this
editor-only change.

## Remaining work

Professional string/text fields and numeric inputs still use immediate
per-change commands. They should adopt the same focus transaction adapter.
Numeric fields additionally need empty/intermediate-string handling so invalid
partial text is not coerced to zero before commit. Timeline duration handles
should reuse the pointer form of this transaction lifecycle.
