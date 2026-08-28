# Timeline event resize tracer handoff

- Kind: handoff
- Scope: release 1.1, `contexts/ba-editor`, Issue #24, PR #27
- Status: implemented
- Observed at: 2026-08-27
- Owner: HaloCue maintainers
- Source branch: `feature/1.1-ba-editor-from-1.0`
- Implementation commit: `78f1d0b`
- PR: <https://github.com/Suciko/HaloCue/pull/27>

## Outcome

Professional timeline event bars now have a dedicated duration handle. It is a
separate control from event selection and from the transient preview playhead:

- pointer movement previews the event's candidate duration;
- pointer release or an unexpected capture loss commits one edit;
- pointer cancellation and Escape restore the transaction baseline;
- Arrow keys adjust one frame, Page Up/Down adjust one second, and Home reduces
  the event to one frame; and
- the current milliseconds and frame count remain visible in the event bar and
  in the handle's accessible name.

The interaction uses the existing `beginTransaction` / `previewEvent` /
`commitTransaction` / `cancelTransaction` path. Intermediate pointer and key
repeat values therefore update deterministic preview compilation without
appending history or scheduling autosave. A completed gesture produces one
project revision and one undo entry.

## Frame boundary

`timelineResize.ts` owns the pure pointer, keyboard, and frame-to-millisecond
math. A pointer session captures the event bar width and starting frame count
once; later layout changes cannot feed back into the drag scale. Durations clamp
to at least one frame.

The project format stores integer milliseconds while the timeline evaluates
integer frames. The encoder chooses a millisecond value that resolves back to
the requested frame count at the active frame rate. If a gesture stays on or
returns to its starting frame, it restores the exact authored millisecond value
instead. This prevents a click or sub-frame drag from changing `550 ms` to a
different but visually equivalent value.

## Changed paths

- `apps/desktop-client/scene-editor/src/TimelineEventSegment.tsx`
- `apps/desktop-client/scene-editor/src/timelineResize.ts`
- `apps/desktop-client/scene-editor/src/timelineResize.test.ts`
- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`
- `apps/desktop-client/scene-editor/src/projectRepository.test.ts`

No cross-context contract, migration, resource, or proprietary research input
changed in this slice.

## Verification

From `apps/desktop-client/scene-editor`:

```text
npm run test
15 test files passed; 84 tests passed.

npm run build
TypeScript no-emit and Vite production build passed; 1600 modules transformed.
The existing unresolved preview-font build warning remains unchanged.
```

The pure resize tests cover pointer scaling, minimum clamping, keyboard steps,
and frame/millisecond round trips at 24, 30, and 60 fps. The store test previews
three duration candidates, proves that revision/history/autosave do not advance
during the gesture, commits one revision, and restores the original duration
with one undo.

A 1280 x 720 browser check confirmed the visible right-edge handles and their
accessible names. Arrow Right changed the selected background from 17 to 18
frames (`550 ms` to `600 ms`), enabled one Undo, and one Undo restored the
baseline. After correcting the baseline-preservation edge case, a sub-frame
pointer drag left the authored duration unchanged and kept Undo disabled.

## Known boundary and next action

This is a single-track event-duration tracer, not the multi-track shot timeline
promised later in the 1.1 plan. It does not add timeline zoom, audio tracks,
clip trimming from the left edge, or overlapping events.

The event-grip follow-up is delivered in implementation commit `8befda3` and
documented by
`docs/handoffs/2026-08-27-professional-event-reorder-tracer.md`. The next
professional skeleton gap is insertion placement: adding an event still appends
to the Cue rather than inserting before or after the selected stable event.
