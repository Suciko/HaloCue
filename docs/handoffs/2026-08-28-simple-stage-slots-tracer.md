# 2026-08-28 simple stage slots tracer

## Scope

This slice makes the Simple-mode five-position stage strip keyboard
addressable. It preserves the BA stage contract: visible positions are `1..5`;
off-stage speaker `#0` is not a sixth portrait.

## Delivery

- Branch: `feature/1.1-ba-editor-from-1.0`
- Code commit: `d253390 feat(1.1): navigate simple stage slots by keyboard`
- Pushed: yes, to `origin/feature/1.1-ba-editor-from-1.0`
- Pull request: https://github.com/Suciko/HaloCue/pull/27
- Parent issue: https://github.com/Suciko/HaloCue/issues/24
- Changed code:
  - `apps/desktop-client/scene-editor/src/App.tsx`
  - `apps/desktop-client/scene-editor/src/simpleStageSlotsUi.test.tsx`

## Behavior

- Stage slot buttons use one roving `tabIndex`; the selected slot is `0`, the
  other four visible slots are `-1`.
- Arrow Left/Right and Up/Down move within positions `1..5`; Home and End move
  to the first and last visible slot without wrapping.
- Keyboard and pointer selection use the existing `selectSlot` path, so the
  contextual Inspector switches to `角色` without changing project revision,
  history, autosave, or authored stage events.
- `aria-pressed` mirrors `selectedSlot` for assistive technology.

## TDD and verification

- Red: the new UI test found all five slot buttons at the default `tabIndex=0`
  and ArrowRight left the first slot selected.
- Green: refs, navigation, roving tab stops, and ARIA state were added behind
  the existing Store selection setter.
- Focused: `npm test -- --run src/simpleStageSlotsUi.test.tsx` -> 1 test passed.
- Full editor: `npm test` -> 28 files, 153 tests passed.
- Build: `npm run build` passed. The known unresolved runtime font URL warning
  remains: `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- Repository: `git diff --check` passed before commit.
- Python: `python -m pytest -q` -> 2200 passed, 14 skipped in 737.28s.

## Browser evidence

The in-app browser checked `http://127.0.0.1:5174/scene-editor/` at 390x844:

- `#1` was the only initial tab stop; ArrowRight selected/focused `#2` and
  changed the Inspector to `角色`.
- End and Home selected/focused `#5` and `#1` respectively.
- `tabIndex` and `aria-pressed` followed the selected slot, and body/client
  widths stayed equal at the narrow viewport.
- Screenshot: `output/playwright/simple-stage-slots-narrow.png`.

## Studio/AA evidence and boundary

The long-term plan and public Studio/AA evidence establish five visible BA
positions plus an off-stage `#0` speaker, while Studio's selected-object loop
keeps preview and contextual properties together. This slice applies the
keyboard selection part independently in HaloCue.

ADR-0005 remains in force: recovered/decompiled implementations are behavior
evidence only. No private Studio/AA source, bundle, font, image, audio, model,
or other proprietary asset was read into or copied into this repository.

## Next bounded slice

Continue with one Simple script-flow or UI-foundation behavior. Keep #0 out of
the visible slot navigation and avoid mixing this with full theme migration,
continuous-dialogue data modeling, clip resizing, or audio tracks.
