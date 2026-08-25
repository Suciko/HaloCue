# Handoff: AA preview calibration follow-up

## Delivered

- Commit `33db88b` on `feature/1.1-ba-editor-from-1.0`.
- Official local AA background and Spine stage routes remain enabled.
- Dialogue labels support a short `dialogue_name` while preserving the full
  project character name.
- Project-model descriptor generation carries `dialogue_name`, `club_name`,
  avatar, Spine, preview, and stage-media fields.
- Preview typography is authored in the 2560x1440 design space and scales with
  the actual 16:9 stage width.
- Five stable AA slots are retained; the local two-character sample uses slots
  1 and 5.

## Verification

```text
python -m pytest -q tests/test_aa_stage_media.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py tests/test_aa_preview_resolver.py tests/test_aa_runtime_contract.py tests/test_stage_layout.py
python -m py_compile aa_stage_media.py spine_face_web_renderer.py webui.py packages/project-model/project_model.py
node --check apps/desktop-client/scene-preview/preview.js
git diff --check
```

Result: `20 passed`; the branch is pushed to `origin` and the working tree is
clean.

## Continue here

The local preview is available at:

`http://127.0.0.1:8787/scene-preview/index.html?descriptor=local-aa`

The next visual pass must compare the rendered stage against the supplied AA
captures using normalized 16:9 coordinates. The remaining known differences
are the effective Alice/Momoi stage scale and crop, the exact idle animation
frame, and final location/name/dialogue offsets. Do not replace the official
local catalog with committed game bundles; keep binary resources outside Git.

## Suggested handoff commands

```text
git fetch origin
git switch feature/1.1-ba-editor-from-1.0
git pull --ff-only origin feature/1.1-ba-editor-from-1.0
```

