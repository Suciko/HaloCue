# Handoff: resource compatibility and version boundary

## Delivery

- Resource contract commits: `efc6ed2`, `7adb5ef`
- Contract branch: `chore/contracts`
- Contract PR: `#19`
- Governance PR that carries the Matt setup: `#18`
- Receiving runtime branch: `feature/1.0-runtime`
- BA editor branch has the governance commit `06dd977`; it should consume the
  resource contract through the shared PR rather than maintaining a fork.

## Contract changes

- Added `packages/contracts/resource-manifest/1.0.schema.json`.
- Added a synthetic-only public example.
- `lookup.adapter`, `lookup.logical_key`, and `lookup.relative_path` preserve
  the observable AA/MMT/StoryForge resource location semantics needed for an
  official-looking presentation.
- Every resource has a SHA-256, provenance, and redistribution scope.
- Absolute machine paths and parent-directory traversal are rejected by the
  schema. Real bytes remain local user data.
- Added `docs/version-lineage.md` to distinguish the `v0.95-r23` release history
  from the `main` 0.9 baseline and the local 1.0 integration workspace.

## Verification

From the repository root:

```text
python -m pytest -q tests/test_resource_manifest_contract.py
python -m ruff check tests/test_resource_manifest_contract.py
python -m ruff format --check tests/test_resource_manifest_contract.py
```

Result: `7 passed`; Ruff check and format check passed.

From the read-only local integration archive:

```text
python -m pytest -q
```

Source: the maintainer's local `10-HaloCue-1.0-Integrated` research archive.

Result: `9 passed in 173.72s`.

## Version evidence

- `v0.95-r23` resolves to `df41f13795dd24d58736286531dc6e845795accf` and is the
  latest public 0.95 release snapshot.
- `v0.95-r23` is not an ancestor of `main`; migration must be explicit.
- The maintainer confirms 0.95 compiles successfully. The exact build command,
  tool versions, output archive, and SHA-256 still need to be attached before
  making a CI/release claim.
- The maintainer confirms the local 1.0 integration workspace runs. Its source
  remains a research input and is not copied into the public tree.

## Known issues

- Existing Windows CI on the 0.9 line has pre-existing failures involving
  missing `ffprobe`, a launcher fixture without `aa_assets.db`, and story-picker
  Playwright assumptions. These are not caused by the resource contract.
- PR checks for the new branches must finish before merge; governance checks
  are already passing while the Windows matrix is still running.
- The manifest importer, SHA-256 verifier, local staging cache, and AA/MMT
  renderer are intentionally separate implementation slices tracked by issues
  `#6`, `#8`, and `#13`.

## Next owner actions

1. Review and merge PR `#19` into `feature/1.0-runtime`, then promote the shared
   contract to `main` through the governance PR.
2. Implement the importer as an explicit, opt-in local-only flow with path
   validation and hash verification.
3. Attach the 0.95 compile command and archive hash to the version-lineage
   record before using it as a release gate.
4. Build the first deterministic synthetic AA scene from `scene-descriptor/1.0`;
   only then test it with a user's authorized local resource manifest.
