# Handoff: AA-compatible five-slot runtime presentation

## Scope

This slice updates the BA scene preview to five stable AA-compatible slots,
uses the authorized PreviewScene layout evidence, adds independently written
character and typewriter runtime operations, and keeps the conference-room
fixture plus three licensed fonts available for local preview.

## Changed areas

- `apps/desktop-client/scene-preview/aa-runtime.js`
- `apps/desktop-client/scene-preview/preview.js`, `preview.css`, `index.html`
- synthetic descriptor, demo background, and font fixtures/licenses
- `packages/project-model` five-slot adapter
- `tests/test_aa_runtime_contract.py` and scene preview tests
- `docs/aa-runtime-evidence.md`

No AA source, database, bundle, or game resource is committed.

## Verification

`python -m pytest -q tests/test_aa_runtime_contract.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py` -> `9 passed, 1 skipped`.

`node --check apps/desktop-client/scene-preview/aa-runtime.js` and
`node --check apps/desktop-client/scene-preview/preview.js` pass. `git diff
--check` passes.

## Remaining review

The preview still uses synthetic portrait placeholders. Authorized local assets
remain a future resource-manifest concern. Review and merge this branch through
the existing HaloCue PR; do not merge directly to `main`.
