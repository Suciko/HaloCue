# 2026-08-28 simple Cue keyboard tracer

## Scope

This slice makes the Simple-mode Cue strip a keyboard-addressable editing
surface. It is a projection over the canonical `HaloCueProject`; it does not
introduce a second script model or change durable project data.

## Delivery

- Branch: `feature/1.1-ba-editor-from-1.0`
- Commit: `ba66384 feat(1.1): navigate simple cue strip by keyboard`
- Pushed: yes, to `origin/feature/1.1-ba-editor-from-1.0`
- Pull request: https://github.com/Suciko/HaloCue/pull/27
- Parent issue: https://github.com/Suciko/HaloCue/issues/24
- Changed code:
  - `apps/desktop-client/scene-editor/src/App.tsx`
  - `apps/desktop-client/scene-editor/src/cueStripUi.test.tsx`

## Behavior

- Cue buttons use roving `tabIndex`: only the selected Cue is `0`, the other
  Cues are `-1`.
- `ArrowRight`/`ArrowDown` move to the next Cue; `ArrowLeft`/`ArrowUp` move to
  the previous Cue; `Home` and `End` select the first and last Cue.
- Keyboard navigation uses the existing `selectCue` command, so selecting a
  Cue clears the preview playhead while preserving the existing revision and
  undo/history lengths.
- `aria-pressed` and focus follow the selected Cue.
- No contract or project-model version changed.

## Verification

Frontend, from `apps/desktop-client/scene-editor`:

- `npm test -- --run src/cueStripUi.test.tsx`: 1 passed.
- `npm test`: 26 files, 149 tests passed.
- `npm run build`: passed. Vite retained the existing runtime font warning for
  `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.

Python, from repository root:

- `python -m pytest -q`: 2200 passed, 14 skipped in 693.89s.

Browser acceptance used the in-app browser against `http://127.0.0.1:5174/scene-editor/`:

- Quick Edit mode rendered one selected Cue with one `tabIndex=0`.
- Arrow navigation, `End`, and `Home` updated selection, focus, and
  `aria-pressed` as expected.
- At 390x844, `document.body.scrollWidth === document.body.clientWidth === 390`.
- Screenshot: `output/playwright/simple-cue-keyboard-narrow.png`.

## Research and provenance

This slice follows ADR-0005: Studio official documentation and already-recorded
public UI evidence remain the source for task-workspace and keyboard-focus
direction. Local recovered/decompiled implementation is behavior evidence only
and is not read into or copied into the repository. No private Studio/AA code,
assets, or bundles were added.

## Next bounded slice

Continue with the long-term plan's Simple script-flow or UI-foundation work.
Prefer one demonstrable behavior at a time, retaining the existing shared
preview/timeline and canonical project invariants. Do not combine this with
clip resizing, audio tracks, or a full theme migration.
