# Editor Transaction no-op and atomicity tracer handoff

Date: 2026-08-27

## Outcome

The shared editor command path now has an explicit transaction result:

- `committed` means one canonical project revision was validated and published;
- `no-op` means the canonical project did not change; and
- both outcomes carry the editor revision observed by the caller.

A no-op does not save, increment revision, append history, clear the redo
stack, change dirty state, or refresh diagnostics. In addition to structural
comparison, slot commands detect two semantic no-ops before generating fresh
event IDs: assigning the character already projected into a slot and swapping
slots with equal occupants.

## Atomic publish boundary

Normal edits, undo, redo, and project replacement validate and serialize the
candidate before publishing editor state. Rejected candidate validation
therefore leaves the canonical project, Chapter/Scene/Cue/event selection,
undo and redo stacks, dirty state, revision, autosave state, and visible
diagnostics unchanged.

Successful mutation publishes that state as one Zustand update. Event
selection is validated against the resulting Cue and repaired to its first
event, or to no event, before publication.

The repository's existing pending/current local-storage protocol remains the
durable storage seam. As of the later autosave-coalescing tracer, publishing a
valid transaction queues that complete revision for background persistence.
A storage failure never exposes a partial transaction; it leaves the complete
revision in memory and marks it retryable instead of rolling it back.

## Verification

Focused tests cover:

- candidate-validation failure with a populated redo stack;
- rejected undo and redo candidates;
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
compilation then need independent, revision-aware coalescing policies. Those
two schedulers are now recorded in their later tracer handoffs.
