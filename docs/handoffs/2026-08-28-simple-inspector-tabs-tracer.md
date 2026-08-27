# 2026-08-28 simple Inspector tabs tracer

## Scope

This slice makes the Simple Inspector's `角色` / `对白` / `环境` tabs a
keyboard-addressable task surface. The selected tab remains editor state and
does not create a project revision or undo entry.

## Delivery

- Branch: `feature/1.1-ba-editor-from-1.0`
- Code commit: `ea95f7e feat(1.1): navigate simple inspector tabs by keyboard`
- Pushed: yes, to `origin/feature/1.1-ba-editor-from-1.0`
- Pull request: https://github.com/Suciko/HaloCue/pull/27
- Parent issue: https://github.com/Suciko/HaloCue/issues/24
- Changed code:
  - `apps/desktop-client/scene-editor/src/App.tsx`
  - `apps/desktop-client/scene-editor/src/simpleInspectorUi.test.tsx`

## Behavior

- Inspector tabs use one roving `tabIndex`; the selected tab is `0`, the other
  tabs are `-1`.
- Arrow Left/Right and Up/Down move between tabs; Home and End move to the
  first and last tab. Focus and `aria-selected` follow `inspectorTab`.
- Existing `setInspectorTab` remains the only state transition. No project
  JSON, revision, history, autosave, or preview playhead changes.
- The tablist now has the accessible name `当前演出属性`.

## TDD and verification

- Red: the new UI test found all three buttons at `tabIndex=0` and ArrowRight
  left `inspectorTab` unchanged.
- Green: refs, keyboard navigation, roving tab stops, and ARIA state were added
  behind the existing Store setter.
- Focused: `npm test -- --run src/simpleInspectorUi.test.tsx` -> 1 test passed.
- Full editor: `npm test` -> 27 files, 152 tests passed.
- Build: `npm run build` passed. The known external runtime font URL warning
  remains: `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- Repository: `git diff --check` passed before commit.
- Python: `python -m pytest -q` -> 2200 passed, 14 skipped in 734.59s.

## Browser evidence

The in-app browser checked `http://127.0.0.1:5174/scene-editor/` at 390x844:

- Initial state exposed only `对白` as the tab stop.
- ArrowRight moved focus and selection to `环境`; Home returned to `角色`.
- `aria-selected` and `tabIndex` matched the visible tab after each move.
- `document.body.scrollWidth` and `document.body.clientWidth` both remained
  390.
- Screenshot: `output/playwright/simple-inspector-tabs-narrow.png`.

## Studio evidence and boundary

The public first-party editor page
`https://docs.avg-engine.com/manual/overview/editor` describes the selected
Block's contextual inspector as part of the same ordered-script and live
preview workflow. HaloCue applies that relationship to its Simple task tabs
with independent labels and controls.

ADR-0005 remains in force: recovered/decompiled Studio implementation is
behavior evidence only. No private source, bundle, font, image, audio, model,
or other proprietary asset was read into or copied into this repository.

## Next bounded slice

Add keyboard selection and roving focus for the five visible stage slots in
Simple mode. Preserve the `1..5` stage contract and keep off-stage `#0` out of
the visible slot list.
