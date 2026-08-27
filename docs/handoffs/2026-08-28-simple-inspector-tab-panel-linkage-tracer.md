# Handoff: Simple Inspector tab-panel linkage tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: accessible tab-to-panel linkage for the Simple Inspector
- Status: implementation complete and pushed

## Delivery

The Simple Inspector's `角色`, `对白`, and `环境` tabs now expose stable IDs
and `aria-controls` references. The active property surface is a matching
`role=tabpanel` with `aria-labelledby`, while the existing Inspector child
forms remain unchanged inside it. The panel wrapper is editor UI state only and
does not change project revision, history, autosave, event IDs, or payloads.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio editor manual](https://docs.avg-engine.com/manual/overview/editor)

The public Studio editor keeps the selected authoring object, preview, and
contextual property surface in one workspace. HaloCue makes the existing
Simple Inspector's tab relationship explicit to assistive technology while
retaining its own surface and terminology. The official image is behavior/layout
evidence only and is not a repository asset.

ADR-0005 remains in force. No decompiled implementation body, source map,
production bundle, private font, image, audio, model, or installed Studio/AA
resource entered this change.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/styles.css`
- `apps/desktop-client/scene-editor/src/simpleInspectorUi.test.tsx`

## Verification

- Red: the new UI test failed because the active tab had no `aria-controls` and
  no associated property panel.
- Green: `npm test -- --run src/simpleInspectorUi.test.tsx` -> **3 tests passed**.
- Full editor: `npm test` -> **29 files, 157 tests passed**.
- Build: `npm run build` -> passed. The known external runtime font URL warning
  remains for `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- `git diff --check` -> passed before commit.
- Browser DOM at 390x844 confirmed `simple-inspector-tab-dialogue` controls
  `simple-inspector-panel-dialogue`, with `role=tabpanel`, matching
  `aria-labelledby`, and equal body/client widths.
- Screenshot: `output/playwright/simple-inspector-tabpanel-narrow.png`.
- The optional renderer on `127.0.0.1:8898` was stopped; its known proxy/font
  errors were isolated from the editor-side accessibility and layout checks.

## Commit and push

- Code commit: `1197306 feat(1.1): link simple inspector tabs`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Continue with one focused selection-feedback behavior in Simple mode, such as
announcing the selected Cue title and derived frame range together from one
live context node. Keep continuous-dialogue data modeling, clip resizing,
absolute starts, audio tracks, and theme migration out of scope.
