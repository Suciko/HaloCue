# 2026-08-28 simple Cue delete focus tracer

## Scope

This slice keeps the Simple-mode Cue strip in a continuous authoring loop when
the selected Cue is deleted. The focus target follows the existing Store
selection repair; no new project-model or timeline state is introduced.

## Delivery

- Branch: `feature/1.1-ba-editor-from-1.0`
- Code commit: `e05cbd9 feat(1.1): focus repaired Cue after deletion`
- Pushed: yes, to `origin/feature/1.1-ba-editor-from-1.0`
- Pull request: https://github.com/Suciko/HaloCue/pull/27
- Parent issue: https://github.com/Suciko/HaloCue/issues/24
- Changed code:
  - `apps/desktop-client/scene-editor/src/App.tsx`
  - `apps/desktop-client/scene-editor/src/cueStripUi.test.tsx`

## Behavior

- The existing `deleteCue` Store command remains the only durable mutation.
- The CueStrip routes the delete action through the existing pending-focus
  helper, so the repaired neighboring Cue receives focus after React renders.
- Selection, `aria-pressed`, roving `tabIndex`, revision, history, autosave,
  and playhead behavior remain owned by the Store.
- Deleting the final Cue remains unavailable because the existing button stays
  disabled when the Scene contains one Cue.

## TDD and verification

- Red: the new UI test observed `document.activeElement === body` after delete,
  even though Store selection repair chose the previous Cue.
- Green: the delete button uses the focus helper; the test asserts focus,
  selection, roving tab stop, and one revision/history increment.
- Focused: `npm test -- --run src/cueStripUi.test.tsx` -> 3 tests passed.
- Full editor: `npm test` -> 26 files, 151 tests passed.
- Build: `npm run build` passed. The known external runtime font URL warning
  remains: `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- Repository: `git diff --check` passed before commit.
- Python: `python -m pytest -q` -> 2200 passed, 14 skipped in 700.78s.

## Browser evidence

The in-app browser checked `http://127.0.0.1:5174/scene-editor/` at 390x844:

- After selecting Cue `02` and clicking `删除当前 Cue`, focus and selection
  returned to Cue `01`.
- Cue `01` was the only Cue with `tabIndex=0` and `aria-pressed="true"`.
- `document.body.scrollWidth` and `document.body.clientWidth` both remained
  390.
- Screenshot: `output/playwright/simple-cue-delete-focus-narrow.png`.

## Studio evidence and boundary

The public first-party editor page
`https://docs.avg-engine.com/manual/overview/editor` documents a selected
Block loop across ordered script content, live preview, progress, and a
contextual inspector. HaloCue applies the same observable selected-object
continuity at the Cue layer with independent controls and contracts.

ADR-0005 remains in force: recovered/decompiled Studio implementation is
behavior evidence only. No private source, bundle, font, image, audio, model,
or other proprietary asset was read into or copied into this repository.

## Next bounded slice

Add keyboard navigation to the Simple Inspector's `角色` / `对白` / `环境`
tabs using the same editor-only roving-focus pattern. Keep full UI token
extraction, continuous-dialogue data modeling, clip resizing, and audio tracks
out of scope.
