# 2026-08-28 simple Cue insertion focus tracer

## Scope

This slice keeps Simple-mode authoring in a continuous keyboard/pointer flow:
after inserting or duplicating a Cue, the newly selected Cue receives DOM
focus. The behavior is editor-only and continues to project the canonical
`HaloCueProject` without introducing another script model.

## Delivery

- Branch: `feature/1.1-ba-editor-from-1.0`
- Code commit: `d6dfd51 feat(1.1): focus inserted Cue in simple mode`
- Pushed: yes, to `origin/feature/1.1-ba-editor-from-1.0`
- Pull request: https://github.com/Suciko/HaloCue/pull/27
- Parent issue: https://github.com/Suciko/HaloCue/issues/24
- Changed code:
  - `apps/desktop-client/scene-editor/src/App.tsx`
  - `apps/desktop-client/scene-editor/src/cueStripUi.test.tsx`

## Behavior

- Insert-before, insert-after, duplicate, and the visible add-Cue command set
  an editor-only pending focus target after the existing Store command returns.
- Once React renders the selected Cue, the CueStrip focuses that stable-ID
  button. Roving `tabIndex` and `aria-pressed` remain aligned with selection.
- The Store command remains responsible for the durable mutation, revision,
  undo history, autosave, and playhead clearing; the focus effect does none of
  those things itself.

## TDD and verification

- Red: the new UI test observed `document.activeElement === body` after insert.
- Green: the focus effect made the test pass; the test also asserts the new
  Cue's selection, roving tab stop, and one revision/history entry.
- Focused: `npm test -- --run src/cueStripUi.test.tsx` -> 2 tests passed.
- Full editor: `npm test` -> 26 files, 150 tests passed.
- Build: `npm run build` passed. Vite retains the known unresolved runtime
  font URL `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- Repository: `git diff --check` passed before commit.
- Python: `python -m pytest -q` -> 2200 passed, 14 skipped in 700.11s.

## Browser evidence

The in-app browser checked `http://127.0.0.1:5174/scene-editor/` at 390x844:

- Clicking `在后面插入` selected and focused the new `02 新演出` Cue.
- The new Cue was the only Cue with `tabIndex=0` and `aria-pressed="true"`.
- `document.body.scrollWidth` and `document.body.clientWidth` both remained
  390.
- Screenshot: `output/playwright/simple-cue-insert-focus-narrow.png`.

## Studio evidence and boundary

The public first-party page
`https://docs.avg-engine.com/manual/overview/editor` (currently v1.20.0)
describes a single authoring loop around the selected Block: ordered Block
editor, live preview, OP progress, contextual inspector, Tab insertion, and
continuous dialogue mode. HaloCue applies the observable focus/selection
relationship at the Cue layer while keeping its own controls and contracts.

ADR-0005 remains in force. Local recovered/decompiled implementation is
behavior evidence only and is not read into or copied into the repository. No
private Studio/AA source, bundle, font, image, audio, model, or other asset was
added.

## Next bounded slice

Continue with one Simple script-flow behavior or the smallest UI-foundation
tracer. Keep full continuous-dialogue data modeling, clip resizing, audio
tracks, and complete theme migration out of this slice until a separate seam
and acceptance test are defined.
