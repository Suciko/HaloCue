# Handoff: synthetic BA scene preview

## Delivery

- Issue: [#24](https://github.com/Suciko/HaloCue/issues/24)
- Source branch: `feature/1.1-ba-editor-scene-preview`
- Target branch: `feature/1.1-ba-editor`
- Local commit: `d9d99fa feat(ba-editor): add canonical synthetic scene preview`
- PR: pending push; GitHub HTTPS reset during two push attempts

## Scope and acceptance

This is the first bounded vertical slice for the BA editor stream. It adds a
plain JSON `halocue-project/1.0` model payload for one chapter, scene, ordered
events, characters, and logical resources. It validates stable IDs and
references, supports validated JSON round-trip, and produces a deterministic
`scene-descriptor/1.0` AA presentation descriptor with six slots.

The acceptance criteria were added to Issue #24 before implementation. Advanced
node editing, StudioProject v2 export, MMT cues, and cross-context contract
changes remain outside this slice.

## Changed paths

- `packages/project-model/project_model.py`
- `packages/project-model/example.synthetic.json`
- `packages/project-model/README.md`
- `tests/test_ba_scene_preview.py`

No files under `packages/contracts/` changed. No migration is required.

## Evidence and provenance

LetsGal Studio 1.11 was inspected as a maintainer-local, read-only research
input. The implementation uses only independently written JSON model and
adapter code. No Studio bundle, recovered source, resource, cache, or absolute
machine path entered this repository. The public fixture uses logical synthetic
resource IDs only.

## Verification

From the repository root:

```text
python -m pytest -q tests/test_ba_scene_preview.py
5 passed

python -m py_compile packages/project-model/project_model.py tests/test_ba_scene_preview.py
passed

git diff --check
passed
```

The full baseline command `python -m pytest -q` is currently blocked during
collection because this computer does not have the existing development
dependency `jsonschema` installed. `python -m ruff check ...` and
`python -m ruff format --check ...` are also unavailable because `ruff` is not
installed. No dependencies were installed implicitly.

## Known issues and next action

- Push `d9d99fa` and this handoff commit when GitHub HTTPS is available.
- Open a PR from `feature/1.1-ba-editor-scene-preview` to
  `feature/1.1-ba-editor` and link Issue #24.
- The local clone has no implementation yet for editor UI, persistence store,
  or StudioProject v2 export; these require later bounded slices.

## Decisions needing review

- Confirm whether the canonical model should move to a versioned shared
  contract on `chore/contracts` before adding editor/service consumers.
- Confirm the next slice: local JSON project persistence or a minimal AA preview
  UI consuming `scene-descriptor/1.0`.
