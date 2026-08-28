# Handoff: BA stage media contract

## Delivery

- Issue: #24, collaborator BA editor integration
- Branch: `feature/1.1-ba-editor-from-1.0`
- Commit: `5d26488` (`feat(1.1): separate stage media from avatar previews`)
- Remote: pushed to `origin/feature/1.1-ba-editor-from-1.0`
- Owning contexts: `contexts/ba-editor/CONTEXT.md` and
  `contexts/client/CONTEXT.md`

This slice continues the 1.1 video-first presentation work. It does not add a
player menu, AUTO playback, or other controls to the exported frame.

## Contract and implementation

- Character catalog previews resolved from an AA local index are now explicit
  `thumbnail_*` metadata. The legacy actor `preview_uri`/`preview_source`
  fields remain as a compatibility alias and are marked with
  `preview_role: "thumbnail"`.
- Formal stage rendering reads only `actor.stage_media` with
  `kind: "portrait"` or `kind: "spine-frame"` and a safe `preview_uri`.
  Avatar thumbnails can therefore never be enlarged into a full-body actor.
- Canonical project validation reports stable diagnostics for missing or
  unsupported `stage_media` values. The descriptor adapter preserves the
  stage media object and background `focus_x`/`focus_y` anchors.
- The browser stage keeps a cover-cropped 16:9 background and applies the
  normalized focus anchors. Missing or unsupported stage media leaves the slot
  empty; no CSS head/body silhouette is fabricated.
- Local AA fixture metadata now labels its avatar URLs as thumbnails. Public
  fixtures remain synthetic and contain no BA/AA bytes or private paths.

No `packages/contracts/` schema changed; the additions are optional fields in
the existing plain JSON model/descriptor slice and are guarded by tests.

## Verification

```text
python -m pytest -q tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py tests/test_aa_preview_resolver.py tests/test_aa_runtime_contract.py tests/test_render_timeline.py
20 passed
node --check apps/desktop-client/scene-preview/preview.js
ruff check aa_preview_resolver.py packages/project-model/project_model.py tests/test_ba_scene_preview.py tests/test_aa_preview_resolver.py
All checks passed
git diff --check
```

The Playwright regression verifies the 16:9 ratio, focus positioning, hidden
runtime controls, avatar-only non-rendering, explicit `spine-frame` loading,
five slots, event progression, background changes, and font selection.

## Known boundary and next action

`spine-frame` is a host-provided raster output contract; the public browser
adapter does not bundle Spine or proprietary runtime code. The next bounded
slice is to connect an authorized local Spine render cache (or an independent
runtime adapter) to `stage_media` through the resource manifest, then make the
same resolved stage asset available to deterministic offline video export
(Issue #14). Keep all skeletons, atlases, textures, caches, and absolute local
paths outside the repository.

The older event-runtime handoff still records the timeline as a follow-up; the
deterministic `render-timeline/1.0` implementation landed in commit `6597675`.
