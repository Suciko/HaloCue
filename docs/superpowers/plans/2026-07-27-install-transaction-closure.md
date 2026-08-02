# AA Install Transaction Closure Implementation Plan

> **For agentic workers:** Use strict TDD and an independent task review.

**Goal:** Put the complete `script2aap.py --install` write path inside the same
canonical project/save transaction used by Web asset registration, and mirror
generated custom-character state to both targets.

**Requirements:**

- The outer install transaction must hold `project_target_lock(target)` across
  AA process guard, resource sidecar, voice/manifest work, custom-character
  copy/registration, AAP write, and rollback.
- Nested character registration must reuse the already-held transaction without
  re-acquiring the cross-process lock.
- Install and concurrent Web/API registration for the same project must
  serialize; after both finish, project/save manifests must be semantically
  equal and contain both sets of entries.
- A custom-cast install must copy all four Spine files to project and save and
  write identical `CharacterOverrides`.
- Existing ordinary character overrides created by the generator must have an
  explicit mirror policy and leave project/save verification clean.
- An install failure after one write must restore both prior manifests, remove
  only files created by the attempt, and preserve pre-existing assets.
- Non-install generation remains project-external and does not create save
  state or acquire the AA install lock.
- No path-safety, face-evidence, symbol, camera, or model-constraint regression.

**Tests:**

1. Pause install after reading manifests, start a background registration, then
   release install. Both operations must complete serially with identical
   project/save manifests and all files present.
2. Install a real-shaped synthetic custom cast and verify both mirrors contain
   `.skel`, `.atlas`, texture, avatar, and identical character metadata.
3. Run `verify_project_assets(..., save_dir=...)` on the generated custom-cast
   project and require zero errors/warnings.
4. Inject an install failure and require both mirrors to return to their exact
   pre-operation bytes.
5. Confirm non-install output creates no save directory.

Run the focused tests, the previous final-fix tests, and the full suite.
