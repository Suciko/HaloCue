# Handoff: Simple Cue context tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: selected Cue to preview range, locate action, and contextual Inspector
- Status: implementation complete and pushed

## Delivery

Simple mode now treats a selected Cue as the preview selection unit. The preview
toolbar derives the Cue's minimum start and maximum end frame from the shared
render timeline and labels it `Cue F<start>-<end>`. Its locate action seeks to the
Cue start through the existing editor-only playhead state. Professional mode
continues to show the selected event range and event locate semantics.

Selecting a Cue in Simple mode also chooses the contextual Inspector task from
its authored events: dialogue takes priority, then character staging, then
environment, with dialogue as the safe fallback. This changes only interaction
state; it does not modify project JSON, revision, history, autosave, or event
ordering.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/manual/overview/editor)
- [Studio editor overview image](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio blocks overview](https://docs.avg-engine.com/manual/writing/blocks-overview)
- [Studio Stage Animation timeline](https://docs.avg-engine.com/images/manual/writing/blocks/stage-animation/timeline-overview.webp)

The public editor layout keeps the current Block/Cue context, preview, and
contextual properties in one authoring path. HaloCue applies the same observable
relationship at the Cue level in Simple mode while keeping its canonical ordered
event list and derived timeline as the only source of truth. Official images are
layout evidence only and are not repository assets.

ADR-0005 remains in force. Maintainer-local recovered Studio contracts can guide
observable behavior, but no decompiled implementation body, source map,
production bundle, private font, image, audio, model, or installed Studio/AA
resource was copied into this repository.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/projectStore.ts`
- `apps/desktop-client/scene-editor/src/cueStripUi.test.tsx`

## Verification

- Red: the new UI test first observed the old first-event range (`F143-158`)
  instead of Cue2's complete derived span (`F143-260`).
- Green: `npm test -- --run src/cueStripUi.test.tsx` -> **4 tests passed**.
- Full editor: `npm test` -> **29 files, 155 tests passed**.
- Build: `npm run build` -> passed. The known external runtime font URL warning
  remains for `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- `git diff --check` -> passed before commit.
- Browser desktop: selecting “意外来客” produced `Cue F143-260`, selected the
  “对白” Inspector tab, and clicking locate changed the preview label to
  `精确帧 143` while preserving the Cue range.
- Browser narrow: `output/playwright/simple-cue-context-narrow.png` at 390x844
  showed the range, Cue selection, and dialogue task without body overflow
  (`bodyScrollWidth=390`, `bodyClientWidth=390`).
- The optional renderer on `127.0.0.1:8898` was stopped; existing preview proxy
  errors were isolated from the editor-side state and DOM checks.

## Commit and push

- Code commit: `b2b8acd feat(1.1): align simple Cue preview context`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Continue with a single Simple-mode selection feedback tracer, preferably an
explicit selected Cue context line in the Inspector header or a keyboard focus
return path when the Cue is changed by the project rail. Keep continuous-dialogue
data modeling, clip resizing, absolute starts, audio tracks, and theme migration
out of scope until the current Cue projection has maintainer review.
