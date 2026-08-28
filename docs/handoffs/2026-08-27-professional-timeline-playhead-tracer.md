# Professional timeline playhead tracer handoff

Date: 2026-08-27

## Outcome

The professional timeline now has an interactive, frame-addressed playhead.
Users can:

- click or drag across the selected Cue's rendered frame range;
- move one frame with arrow keys;
- move one second with Page Up or Page Down;
- jump to Cue range boundaries with Home or End; and
- press Escape to return to the selected event/Cue intent.

The ruler and playhead readout derive from the actual timeline frame rate and
frame range rather than fixed decorative timestamps. The control exposes
slider semantics and frame/time text to assistive technology.

## Preview intent 1.1

The additive `preview-intent/1.1` contract adds:

- `selection_kind: "playhead"`;
- `resolution: "explicit-frame"`; and
- `alignment: "exact"`.

The target event is the deterministic timeline event containing the requested
frame. The browser runtime accepts both 1.0 and 1.1, rejects playhead semantics
under 1.0, and validates that the exact frame lies inside its target event.
Cue and event intents remain on 1.0 for backward compatibility.

## Editor semantics

Playhead state is transient editor state. Scrubbing does not mutate the
HaloCueProject, increment project revision, append undo history, or request
autosave. Selecting a Scene, Cue, or event clears explicit playhead state and
restores the corresponding selection intent.

Preview Compilation treats playhead movement as an intent-only address change.
It reuses the existing Scene Evaluation and calls `applyIntent` on the current
Preview Session, so stage media is not remounted while scrubbing. Out-of-range
playhead state caused by a later duration edit is clamped to the compiled
timeline before intent construction.

## Verification

Verification completed with 74 scene-editor tests and 40 focused
contract/model/browser tests. Coverage includes exact-frame resolution,
evaluation reuse, transient Store semantics, JSON Schema validation, runtime
acceptance without session generation change, TypeScript production build, and
whitespace validation.

A 1440 × 1000 manual render check confirmed the ruler, hit area, playhead,
progress fill, and exact frame/time readout remain legible in the full
professional workspace. The standalone editor dev server did not have its
preview proxy backend running during that layout check; the Preview Session
integration itself was verified by the browser harness above.

## Remaining work

The event bars still represent the selected Cue rather than a zoomable,
multi-track sequence. Later slices can add timeline zoom, scroll anchoring,
duration handles, snapping, and multi-selection on top of this exact-frame
playhead contract. Duration and position handles should use the existing
begin/preview/commit gesture transaction rather than writing one history entry
per pointer move.
