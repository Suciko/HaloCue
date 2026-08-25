# Handoff: synthetic AA preview UI

## Delivery

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Source branch: `feature/1.1-ba-editor-scene-preview`
- Target branch: `feature/1.1-ba-editor`
- UI slice commit: `3d973b6 feat(ba-editor): add synthetic scene preview UI`
- Background commit: `11ef73b feat(ba-editor): use conference room demo background`
- Composition commit: `426580a feat(ba-editor): restore six-slot preview composition`
- PR: [#25](https://github.com/Suciko/HaloCue/pull/25), pushed and open

## Scope and acceptance

This slice consumes the existing `scene-descriptor/1.0` output with a minimal
runnable browser preview. It renders six deterministic slots, keeps state in a
small presentation controller, advances ordered enter/exit/dialogue events,
highlights the active speaker, and switches among three named dialogue font
stacks. The fixture uses synthetic logical IDs plus one user-provided
conference-room image for the local demonstration preview.

The canonical `HaloCueProject` model remains the source of truth. The page does
not edit the project, resolve physical paths, or import AA/Studio data.

## Changed paths

- `apps/desktop-client/scene-preview/index.html`
- `apps/desktop-client/scene-preview/preview.css`
- `apps/desktop-client/scene-preview/preview.js`
- `apps/desktop-client/scene-preview/example.scene-descriptor.json`
- `apps/desktop-client/scene-preview/assets/demo-conference-room.jpg`
- `apps/desktop-client/scene-preview/README.md`
- `tests/test_ba_scene_preview_ui.py`

No cross-context contract or migration changed. The image is a user-provided
demo asset, not an AA/BA/Studio resource or recovered source file.

## Verification

```text
python -m pytest -q tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py
6 passed, 1 skipped (standalone Chromium was unavailable to the local pytest process)

ruff check packages/project-model/project_model.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py
passed

git diff --check
passed
```

The new UI flow is marked `browser` and writes a local screenshot under the
ignored `acceptance-output/` directory when Chromium is installed. The full
legacy suite remains noisy on this machine: existing 0.9 UI harness failures,
missing historical fixtures, and browser setup errors are recorded separately
from this slice. The same page was also opened through the local in-app browser:
six slots were visible, three event advances showed Alice's dialogue with the
active-slot highlight, and the screenshot was inspected with the user-provided
conference-room background and the `Background ready` state.

## Known issues and next action

- The preview currently displays synthetic placeholder portraits. The optional
  local image is loaded only through the relative `preview_uri` in the
  descriptor; a future resource-manifest slice can resolve authorized local
  resources without changing the descriptor API.
- The page is a presentation adapter, not yet a Tauri/React workspace. The next
  bounded slice should add local JSON project persistence or a host bridge that
  feeds descriptors from the canonical model.
- PR review is required before merging into `feature/1.1-ba-editor`; do not
  merge or push to `main` from this branch.
