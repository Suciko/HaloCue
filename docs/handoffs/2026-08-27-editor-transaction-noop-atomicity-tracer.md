# Editor Transaction no-op and atomicity tracer handoff

Date: 2026-08-27

## Outcome

The shared editor command path now has an explicit transaction result:

- `committed` means one durable project change was saved and published;
- `no-op` means the canonical project did not change; and
- both outcomes carry the editor revision observed by the caller.

A no-op does not save, increment revision, append history, clear the redo
stack, change dirty state, or refresh diagnostics. In addition to structural
comparison, slot commands detect two semantic no-ops before generating fresh
event IDs: assigning the character already projected into a slot and swapping
slots with equal occupants.

## Atomic publish boundary

Normal edits, undo, redo, and project replacement persist the candidate project
before publishing editor state. A rejected save therefore leaves the canonical
project, Chapter/Scene/Cue/event selection, undo and redo stacks, dirty state,
revision, and visible diagnostics unchanged.

Successful mutation publishes that state as one Zustand update. Event
selection is validated against the resulting Cue and repaired to its first
event, or to no event, before persistence and publication.

The repository's existing pending/current local-storage protocol remains the
durable storage seam. This slice strengthens the editor-side boundary around
it rather than introducing another persistence mechanism.

## Verification

Focused tests cover:

- commit failure with a populated redo stack;
- failed undo and failed redo;
- no-op preservation of save count, history, redo, dirty state, and revision;
- equivalent character assignment; and
- swapping equal empty occupants.

Verification completed with 58 scene-editor tests and 35 focused
Python/model/browser regression tests. The production TypeScript build and
whitespace check also passed.

## Remaining work

This is the first Editor Transaction tracer, not the complete Module. The next
slice should separate high-frequency preview edits from durable commits so one
timeline drag creates one undo entry. Edit commit, autosave, and preview
compilation then need independent, revision-aware coalescing policies.
