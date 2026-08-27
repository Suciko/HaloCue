# Handoff: Simple Inspector Cue context tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: visible current-Cue context in the Simple Inspector heading
- Status: implementation complete and pushed

## Delivery

The Simple Inspector heading now keeps the selected Cue title visible under
`当前演出` and exposes it as a polite live region. Switching Cues updates this
derived context without changing project JSON, revision, undo/redo history,
autosave state, or authored event ordering. The title is constrained with the
existing inspector width so long Cue names do not resize the workbench.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/manual/overview/editor)
- [Studio editor overview image](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)

The public editor overview keeps the selected authoring object and its
contextual inspector adjacent to the preview and ordered script. HaloCue makes
the current Cue identity equally explicit in Simple mode while retaining the
canonical Chapter/Scene/Cue model and existing contextual fields. The official
image is layout evidence only and is not a repository asset.

ADR-0005 remains in force. Local recovered Studio contracts are behavior
evidence only; no decompiled implementation body, source map, production bundle,
private font, image, audio, model, or installed Studio/AA resource was copied
into this repository.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`
- `apps/desktop-client/scene-editor/src/simpleInspectorUi.test.tsx`

## Verification

- Red: the new UI test found no `[data-simple-cue-context]` after changing Cue.
- Green: `npm test -- --run src/simpleInspectorUi.test.tsx` -> **2 tests passed**.
- Full editor: `npm test` -> **29 files, 156 tests passed**.
- Build: `npm run build` -> passed. The known external runtime font URL warning
  remains for `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- `git diff --check` -> passed before commit.
- Browser desktop: selecting “意外来客” showed the title in the Inspector,
  preserved `Cue F143-260`, and kept the page width at 1280px.
- Browser narrow: `output/playwright/simple-inspector-cue-context-narrow.png`
  at 390x844 showed the title under `当前演出`; `bodyScrollWidth` and
  `bodyClientWidth` were both 390.
- The optional renderer on `127.0.0.1:8898` was stopped; its known proxy/font
  errors were isolated from the editor-side DOM and state checks.

## Commit and push

- Code commit: `7ba17ba feat(1.1): surface simple Cue context`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Continue with one editor-state-only focus continuity behavior, such as restoring
focus to the selected Cue after selection from the ProjectRail or making the
Simple Cue selection summary announce its title and range together. Keep
continuous-dialogue data modeling, clip resizing, absolute starts, audio tracks,
and theme migration out of scope.
