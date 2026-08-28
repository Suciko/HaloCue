# Handoff: Simple Cue live selection-context tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: one atomic title-and-range context for the selected Simple Cue
- Status: implementation complete and pushed

## Delivery

The Simple Inspector's `当前演出` context now announces the selected Cue title
and its derived render range together, for example
`意外来客 · F143-260`. The range comes from the existing evaluated render
timeline and `buildShotTimeline` projection, so the Inspector and preview
toolbar share one canonical timing interpretation.

The context is a polite, atomic live region. Cue selection still updates the
task-appropriate Inspector tab and clears a stale playhead through existing
Store behavior. This change does not modify project JSON, revision, history,
autosave, stable IDs, or timing inputs.

## Studio evidence and boundary

Public first-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)

Studio's public editor keeps selected Block identity, playback position,
preview, and the contextual inspector visibly connected. HaloCue applies that
information relationship to a Cue-sized Simple workflow while retaining its
own labels, five-position stage, and ordered event model. No private
implementation, source map, application bundle, font, or asset was copied.

## TDD and verification

- Red: the Inspector live region exposed only the Cue title.
- Green: it now reuses the current Cue's render-timeline projection to append
  its start/end frame range.
- Focused: `npm test -- --run src/simpleInspectorUi.test.tsx` -> **3 tests passed**.
- Related: Simple Inspector, Cue strip, and Shot Timeline projection ->
  **9 tests passed**.
- Full editor: `npm test -- --run` -> **30 files, 161 tests passed**.
- Build: `npm run build` -> passed with the known external preview-font URL
  warning.
- Browser narrow (390x844): selecting `意外来客` produced
  `意外来客 · F143-260`, `aria-atomic=true`, and no body overflow
  (`bodyScrollWidth=390`, `bodyClientWidth=390`). Screenshot:
  `output/playwright/simple-cue-live-context-narrow.png`.
- `git diff --check` passed before commit.

The optional renderer was stopped during the browser check. The selected Cue
range is a deterministic editor-side projection and remained independently
verifiable.

## Commit and push

- Code commit: `4873c41 feat(1.1): unify simple Cue selection context`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Continue the Simple selection-feedback loop by associating the current Cue
context with the Inspector tablist and active panel through a stable described-
by relationship. Keep it presentation-only and do not begin continuous-dialogue
modeling, absolute timing, or theme migration in that slice.
