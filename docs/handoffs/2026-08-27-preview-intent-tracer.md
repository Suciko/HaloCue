# Preview Intent tracer handoff

Date: 2026-08-27

## Outcome

Editor selection now crosses the host/preview boundary as the versioned
`preview-intent/1.0` contract. The preview no longer infers every selection as
"show the last frame".

The intent carries:

- the current `scene_id` and `cue_id`;
- whether the user selected a Cue or an event;
- the selected event identity when applicable; and
- one resolved timeline event/frame with start/end alignment and a resolution
  reason.

## Resolution rules

- Simple mode selects the completed state of the last renderable event in the
  Cue (`cue-terminal`).
- Professional mode selects the exact start frame of the selected renderable
  event (`selected-event`).
- A selected extension event without a preview adapter resolves to the end of
  the nearest preceding renderable event (`prior-renderable`).
- If no preceding renderable event exists, it resolves explicitly to the first
  timeline event's start (`scene-start`).
- A stale event ID is rejected rather than silently targeting another event.

The preview toolbar tells the user which resolution is active, and the
professional timeline highlights the selected renderable event.

## Session behavior

`applyIntent` validates scene identity, target event membership, frame range,
alignment, and selection/resolution consistency. It seeks within the current
Preview Session, so selecting another event does not reload backgrounds, actors,
or Spine resources. An intent supplied during mount is validated before the
current session is replaced.

The browser exposes the applied Cue, selected event, target event, and fallback
resolution as stage data for diagnostics and integration tests.

## Verification

Verification completed with 53 scene-editor tests and 63 Python/model/browser
integration tests. The TypeScript production build, JSON Schema validation,
Ruff, browser JavaScript syntax check, and whitespace check also passed.

## Remaining work

Canonical Scene selection and Editor Transaction work are recorded in later
tracers. The additive `preview-intent/1.1` timeline tracer now extends this
contract with exact intermediate-frame playhead selection while retaining 1.0
compatibility for Cue and event intents.
