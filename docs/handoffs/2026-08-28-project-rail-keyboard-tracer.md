# Handoff: ProjectRail keyboard tracer

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Branch: `feature/1.1-ba-editor-from-1.0`
- Scope: keyboard-addressable Studio-style chapter/scene/Cue project rail
- Status: implementation complete and pushed

## Delivery

ProjectRail now presents the visible chapter, scene, and (in Professional mode)
Cue nodes as one editor-state projection. The active node owns the only `tabIndex`
of `0`; Arrow Up/Down or Left/Right, Home, and End move focus through the visible
tree and call the existing chapter/scene/Cue selection commands. Tree items expose
`role=treeitem`, their hierarchy level, and `aria-current=page` for the active
keyboard location. Focus and selection do not change project revision, undo/redo
history, autosave content, or authored event order.

The projection keeps the Simple scene rail and Professional full project rail on
the same stable IDs. When a selected scene changes and its visible Cue list is
rebuilt, an unavailable roving node falls back to the current selection instead
of leaving the tree without a tab stop.

## Studio evidence and boundary

First-party references reviewed:

- [Studio editor overview](https://docs.avg-engine.com/manual/overview/editor)
- [Studio editor overview image](https://docs.avg-engine.com/images/manual/overview/editor/editor-overview.png)
- [Studio blocks overview](https://docs.avg-engine.com/manual/writing/blocks-overview)

The public editor overview shows the project/chapter/Fragment tree as persistent
context beside ordered authoring, preview, and a contextual inspector. HaloCue
adopts the persistent hierarchy and current-object feedback while preserving its
own Chapter/Scene/Cue model and accessible keyboard semantics. The official image
was inspected as layout evidence; it is not a repository asset.

ADR-0005 remains in force. Maintainer-local recovered Studio contracts may inform
observable structure and behavior, but no decompiled implementation body, source
map, production bundle, private font, image, audio, model, or installed Studio/AA
resource was copied into this repository.

## Changed paths

- `apps/desktop-client/scene-editor/src/App.tsx`
- `apps/desktop-client/scene-editor/src/projectRailUi.test.tsx`

## Verification

- Red: the new UI test first failed because the ProjectRail had no tree-item
  projection or keyboard tab stop.
- Green: `npm test -- --run src/projectRailUi.test.tsx` -> **1 test passed**.
- Full editor: `npm test` -> **29 files, 154 tests passed**.
- Build: `npm run build` -> passed. The known external runtime font URL warning
  remains for `/scene-preview/assets/fonts/NotoSansSC-Variable.ttf`.
- `git diff --check` -> passed before commit.
- Browser desktop: `output/playwright/project-rail-desktop.png` at 1280x900
  shows the tree role, current scene tab stop, and chapter focus after ArrowUp.
- Browser narrow: `output/playwright/project-rail-narrow.png` at 390x844 keeps
  body/client widths equal; the rail hides under the existing responsive layout.
- Browser DOM: tree items reported `role=treeitem`, one `tabIndex=0`, and one
  `aria-current=page`; the embedded renderer remained unavailable at `127.0.0.1:8898`
  so its existing proxy/font errors were not treated as editor failures.

## Commit and push

- Code commit: `3d43db8 feat(1.1): navigate project rail by keyboard`
- Pushed to `origin/feature/1.1-ba-editor-from-1.0`

## Next bounded slice

Continue with one selected-object linkage behavior in Simple mode: when a Cue is
selected from the rail or Cue strip, make the preview toolbar's selected range and
the inspector's current task visibly agree without introducing new project data.
Keep tree collapse, continuous-dialogue modeling, clip resizing, absolute starts,
and audio tracks out of scope until that linkage is tested.
