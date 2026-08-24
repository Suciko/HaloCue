# Handoff: AA-compatible five-slot runtime

## Scope

This slice completes the runnable AA-style preview for the BA editor branch.
It uses the authorized AA PreviewScene values as compatibility evidence and
keeps the implementation native to HaloCue.

- five stable foreground slots: `-925, -435, 0, 435, 925`
- 1280 x 720 preview coordinate mapping
- dialogue container, name label, text label, separator and text background
  positions recorded in `docs/aa-runtime-evidence.md`
- `setPos`, `setLuminance`, `setOnTop`, `setCloseup`, move/fade/hide and queued
  typewriter operations in `aa-runtime.js`
- HarmonyOS Sans Medium default, with Noto Sans and Nowar Rounded choices
- synthetic conference-room preview background and three-line dialogue fixture

## Changed paths

The implementation is limited to `apps/desktop-client/scene-preview`, the
project-model preview adapter, focused tests, evidence, and this handoff.
The AA unpacked directory, database, bundles and local acceptance screenshots
are not part of the delivery.

## Verification

```text
python -m pytest -q tests/test_aa_runtime_contract.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py
9 passed, 1 skipped
node --check apps/desktop-client/scene-preview/aa-runtime.js
node --check apps/desktop-client/scene-preview/preview.js
git diff --check
```

The browser screenshot was inspected locally at 1280 x 720 after three event
advances. It showed all five slots, the conference-room background, the white
speaker name, blue `StoryForge` club label, three body lines, and the caret at
the end of the final line.

## Follow-up

This is a presentation-adapter slice. Authorized real resources remain a
future local resource-manifest concern; no AA source or game asset is required
for CI or public checkout.
