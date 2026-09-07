# Adaptation candidates become ordinary scene revisions —slice B

> Continue after durable dispatch verification. This plan preserves the original
> user-visible outcome; do not stop at another disconnected artifact endpoint.

**Goal:** Explicitly accepting a source-grounded adaptation candidate creates a normal
scene manuscript revision that work reload, review, normal scene-set release freeze and
Production handoff already consume. Old accepted adaptation artifacts remain immutable
and require an explicit promotion action.

## Proposed data ownership

- Ordinary `scene_script` / `scene-blocks/1.0` revisions are the sole new canonical
  manuscript after adoption. Do not keep generating a parallel authoritative
  `adaptation_manuscript` revision plus a divergent scene copy.
- Preserve preexisting `adaptation_manuscript` artifacts as historical records. A
  new explicit promotion can read/verify that old revision and create a scene revision
  referencing its provenance; it does not rewrite the old artifact or frozen release.
- Persist the adopted target scene ID as adaptation-chapter dependency/association,
  not only in transient UI state. Pending regeneration uses the current mapped scene
  revision as its base. For a never-promoted legacy chapter, retain its legacy base
  identity until explicit promotion so old proposal supersession remains meaningful.
- Add one shared target-resolution helper used by synchronous candidate generation,
  durable snapshot pins and acceptance. Do not let these three paths separately guess
  the latest base or miss a manual edit to the adopted scene.

## Explicit acceptance behavior

1. The UI shows the source chapter, target chapter and whether a new scene is created
   or the existing mapped scene is replaced. No automatic acceptance after generation.
2. First acceptance creates a dedicated scene under the chosen work chapter, preserving
   normal structure order, work version and scene-contract defaults. If no chapter was
   supplied, the UI/server must present a stable explicit default before approval;
   never silently choose a different target on retry or move an unrelated scene.
3. Regeneration updates only the already mapped scene if both pinned base revision
   and expected work version match. An arbitrary existing scene cannot be overwritten
   merely by passing its ID as a target. Different target semantics need separate
   explicit author action, not automatic model inference.
4. Convert reviewed text to stable SceneBlocks with the existing shared parser and
   validate it. Retain verbatim candidate/source references in provenance, normalize
   scene rendering consistently with normal manual saves, and make any normalization
   inspectable instead of silently claiming byte equality where formatting changes.
5. In one SQLite transaction: check proposal/current source/hash/target/base, create
   scene if needed, add ordinary revision, update scene current revision/status and
   adaptation association/candidate state, record decision and bump work version.
6. Use existing postcommit projection scheduling and invalidation paths. Do not bypass
   scene review/memory/continuity/release gates just because the candidate was accepted.
   Separate automatic-knowledge authorization issue must not be falsely closed here.

## Files and tests

- New bounded adoption helper under `halocue_writing`, thin service acceptance hook.
- Shared adaptation target resolver used by `adaptation.py` and `adaptation_jobs.py`.
- New synthetic acceptance/reload/manual-edit/regenerate tests; update existing
  adaptation tests only when their assertion truly changes to the canonical contract.
- Synthetic full release test uses ordinary scene review, memory maintenance decision,
  continuity review, release review/freeze and `build_production_handoff`; Production
  integration checks teacher/source dialogue and IDs without executing real AA.
- Legacy accepted artifact promotion test verifies original bytes/hash remain intact,
  no silent migration, source still current, explicit action can be retried safely.
- Two competing approvals/old pending candidate after manual scene edit/target chapter
  deleted/wrong-work target/changed source must fail without partial formal data.
- Candidate not accepted must not create a scene, change work version, or enter freeze.

## Gates

TDD each behavior, scoped review, focused regression then immutable-source broad run.
Do not change standard director prompts, teacher/Sel, 1.1, main or real user data.
After this backend slice, the existing manual-chat prose import UI still needs sliceC;
02-007 closes only after a real-DOM/browser vertical trace through the shipping UI.


## Accepted implementation

45d000d implements canonical scene-only new adoption, shared target/base resolver,
explicit idempotent legacy promotion retaining original bytes, normalized blocks/text,
source/scope validation, and a full synthetic normal-gate→freeze→Production HTTP trace.
Scoped review accepted after normalization and old-queued-target compatibility fixes.
1846 tests passed833.72s on unchanged source; see companion handoff. The selected-scene
wording was corrected to the actual ordinary scene-set freeze contract. SliceC UI and
real playback remain unimplemented/unverified, respectively.
