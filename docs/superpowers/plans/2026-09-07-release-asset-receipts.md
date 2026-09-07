# Release-scoped asset receipts implementation plan

> Execution: local, test-first, followed by a scoped review. User authorized autonomous
> repair without intermediate design confirmations. No feature expansion or main merge.

**Goal:** Fix 01-004: production receipts must not become author inputs or leak across
frozen releases/runs; repeated release of unchanged source assets must remain valid.

**Architecture/spec:** Keep the existing scene-source snapshot wire shape but always
set its production_copy field to null. A shared pure serializer feeds service and
harness. Store validated usage receipts in an additive SQLite table keyed by
(release_id, production_run_id, scene_id, reference_id), independent of mutable author
rows. The receipt status endpoint returns only that release/run's validated projection.
Old frozen bytes and hashes are immutable; old unscoped scene copy columns cannot
establish historical ownership. Reconcile only from a verified production receipt.

**Alternatives rejected:** Clearing production_copy on every freeze mutates author
state and still loses history. Dropping the production preclaimed-copy guard accepts
forged consumption evidence. Rewriting old manifests invalidates immutable releases.
No alternative satisfies both author purity and run-local historical evidence.

**Stack:** Existing Python/SQLite services, existing vanilla-JS workbench. No dependency.
**Global constraints:** synthetic data only; unchanged standard direction prompts and
teacher/Sel; additive migration; no edits outside the 1.0 autonomous branch.

## Slice 1: Author-owned source snapshots

Files: new writing `asset_references.py`; existing service/harness snapshot helpers;
writing workbench/app.js source reference projection; tests/test_scene_asset_references.py.

1. Add failing source-purity regression: after a matching receipt, current source
   reference snapshots from service/harness are equal and production_copy is null.
   Confirm the current implementation fails before modifying it.
2. Implement one serializer and use it in both helpers. Do not change frozen files.
   The public author row retains production_copy:null for wire compatibility, with no
   legacy copy ID presented as a current author's confirmation.
3. Keep client source fingerprints consistent (production_copy:null). Replace the
   ambiguous global-copy status text with release-scoped wording.

## Slice 2: Historical receipt projection

Files: writing repository.py additive table; service.py receipt/status paths;
new tests/test_release_asset_receipts.py; contract note under packages/contracts.

1. RED: R1 reconciled then R2 using the same refs starts unconfirmed, accepts its own
   receipt, and reports separate copy IDs. R1 remains queryable after current refs
   change/delete. R1 manifest bytes/hash remain unchanged. Legacy unscoped copy data
   does not count as a run receipt. Existing wrong run/source/hash/duplicate rejections
   remain in force. A partial receipt accumulates only within its own release/run.
2. Add release_asset_receipts with identity primary key and receipt JSON; no FK to
   mutable scene reference rows. Reconcile checks the immutable manifest rather than
   current rows. It writes receipts transactionally without bumping author work version.
3. Status queries the release/run key and returns additive references for consumers.
   No global count of scene_asset_references.production_copy_json remains.
4. Adapt old tests that required author-row receipt mutation to assert a separate
   verified status projection instead. These tests still check the actual receipt IDs.

## Slice 3: Integrated round trip and compatibility

Files: integrated/tests/test_gateway.py; writing backup/release-integrity tests.

1. Extend the synthetic integration workflow: freeze R1, handoff, re-review and freeze
   R2 using unchanged refs, handoff, assert two different run copy IDs and unchanged R1.
2. Test legacy database startup adds the empty projection table; do not infer run
   ownership from existing scene rows. Existing old frozen releases still verify and
   any preclaimed-copy handoff remains explicitly rejected rather than rewritten.
3. Run narrow source/gate/release/handoff tests, then a scoped reviewer. Verify the
   combined writing/production/integrated suite against an unchanged commit. Record
   exact counts and limitations in handoff/ledger; keep 01-005/006 and goal active.

## Execution

Implemented in `6f28ebb` and test assertion migration `12389a2`. All three slices
are verified by the 1146-test unchanged-commit broad run. Exact evidence, failed
fixture history, migration and boundaries: `docs/handoffs/2026-09-07-release-asset-receipts.md`.
01-005/006 remain separate required work.
