# Professional field transaction tracer handoff

Date: 2026-08-27

## Outcome

Professional event fields now share the focus-scoped transaction behavior
introduced for dialogue composition:

- text and multiline fields preview every input/IME value and commit on blur;
- slot, numeric effect, and duration fields preview valid values and commit
  once;
- Escape cancels and restores the focus baseline; and
- Enter finishes numeric fields without creating a separate command.

Select controls remain immediate commands because one selection is already one
semantic edit.

## Numeric draft boundary

Numeric controls keep their raw editing string in component state. Empty text,
whitespace, a standalone minus sign, a standalone decimal point, non-finite
values, and values outside the field's declared min/max are not written into
the HaloCueProject.

While a draft is invalid the field exposes `aria-invalid` and a visible error
border. Blurring an invalid draft cancels the transaction and restores the
original value. Blurring a valid draft previews the parsed number once more and
commits one revision. This prevents the previous `Number("") -> 0` behavior
from corrupting durations, slots, and bounded effect parameters.

## Shared command path

`previewEvent` is an event-ID adapter over the Store's generic active
transaction preview function. It validates Scene/Cue ownership and event
existence before patching the cloned working project. Direct professional
commands and focus transactions use the same event patch helper, so simple and
professional editing do not acquire competing mutation semantics.

## Verification

Pure parser tests cover partial strings, finite decimals, negative values, and
min/max rejection. Store coverage previews three professional event values and
proves that they become one project revision and one history entry.

Verification completed with 79 scene-editor tests and the production
TypeScript build. A browser interaction check confirmed that clearing a 550 ms
duration marks the field invalid and restores 550 on blur; entering 800 enables
one project Undo, which restores 550 in a single step. The focused 40-test
contract/model/browser boundary remains unchanged by this editor-only slice.

## Remaining work

The duration-handle follow-up is delivered in implementation commit `78f1d0b`
and documented by
`docs/handoffs/2026-08-27-timeline-event-resize-tracer.md`. Professional event
reordering is the next bounded direct-manipulation gap: the list already shows
grips and up/down commands, but it does not yet provide a pointer reorder
gesture with an equivalent keyboard path.
