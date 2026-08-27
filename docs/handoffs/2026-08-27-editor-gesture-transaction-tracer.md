# Editor gesture transaction tracer handoff

Date: 2026-08-27

## Outcome

The editor now has an explicit gesture lifecycle for controls that emit many
intermediate values:

```text
begin -> preview* -> commit
                  -> cancel
```

Preview steps update the working project and therefore the live stage, but do
not save, append history, clear redo, change dirty state, or increment the
durable revision. Commit compares the final project with the gesture baseline,
creates one canonical revision and one undo entry, then queues that revision
once for autosave. Returning to the baseline commits as a no-op.

Environment zoom is the first vertical tracer. Pointer dragging previews every
range value and commits on release or blur. Keyboard range adjustment begins
on the first navigation key and commits on key release. Escape cancels and
restores the baseline.

## Interaction boundaries

Starting another gesture first commits the active one. Durable editor commands,
mode changes, and canonical Chapter/Scene/Cue/event selection changes also
finish the active gesture before continuing. Undo first commits the gesture and
then undoes it, matching the user's visible working state.

Project export explicitly finishes an active gesture and then reads the latest
store state, so a keyboard save cannot export a transient value under an older
revision.

If final candidate validation fails, the working project, selection, dirty
state, diagnostics, and autosave state roll back to the baseline and the
gesture closes. Cancel performs the same visual rollback. A later background
persistence failure keeps the complete committed revision in memory and marks
it retryable.

## Verification

Tests prove that multiple zoom previews produce zero saves and zero history
entries, followed by one queued autosave and one undo entry at commit. Separate
coverage checks validation rollback and cancellation. Verification completed with 62
scene-editor tests and 35 focused Python/model/browser regression tests; the
production TypeScript build and whitespace check also passed.

## Remaining work

Only environment zoom uses the gesture lifecycle so far. The same boundary can
be adopted by timeline drag, numeric scrubbing, stage positioning, and camera
motion when those controls become interactive.

Preview compilation and autosave now have independent revision-aware
coordinators in later tracer slices. Further work should adopt the gesture
boundary for additional continuous controls without weakening these semantics.
