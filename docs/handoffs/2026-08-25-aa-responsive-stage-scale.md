# Handoff: AA stage responsive scale

## Scope

The 1.1 scene preview now treats the 16:9 canvas as a 2560x1440 design
space. A `ResizeObserver` derives `--stage-scale` from the actual stage width;
dialogue typography and authored spacing use that value instead of viewport
`vw` units. This keeps the preview and the eventual video export proportional
when the browser leaves letterbox space around the stage.

The responsive override at the 640px breakpoint no longer replaces the AA
geometry. It only constrains an overlong location label, so the dialogue panel,
speaker rule, and actor slot geometry keep the same 16:9 ratios at every size.

## AA evidence used

The calibration still records the observable values from the authorized
`PreviewScene` export: script container `y=-832`, name `(-1189.9999,426)`,
dialogue `(-1184,321)`, separator `y=361`, text background `(0,272)` with
`-90` rotation, and location `(84,-250)` under the `(-1480,720)` place parent.
No decompiled source or game resource bytes were added to the repository.

## Verification

```text
python -m pytest -q tests/test_aa_stage_media.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py tests/test_aa_preview_resolver.py tests/test_aa_runtime_contract.py tests/test_stage_layout.py
python -m py_compile aa_stage_media.py spine_face_web_renderer.py webui.py packages/project-model/project_model.py
node --check apps/desktop-client/scene-preview/preview.js
git diff --check
```

Result: `20 passed`. Browser verification measured the stage at 1280x720 with
`--stage-scale=0.5` and 17px name/text fonts, and at 640x360 with
`--stage-scale=0.25` and 8.5px name/text fonts. The local 8787 preview service
was restarted so the official local Spine frame route was active.

## Known follow-up

The formal Alice/Momoi Spine frames now load from the local AA catalog through
the stage-media adapter. Their final per-character scale and alpha crop still
need a dedicated visual calibration pass against more reference captures; the
responsive text fix does not change those authored character scales.
