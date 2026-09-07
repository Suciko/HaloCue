# Production handoff admission and ordinary receipt replay (01-006, 01-005)

Goal: one run for a repeated upstream release; normal writing handoff retries repair
an interrupted receipt phase using verified frozen input. No model/prompt changes.

## Verified RED evidence

Maintainer-local probes live beside this plan, outside the currently verified code:
- test_production_handoff_concurrency_probe.py: 4 failed / 2 passed. Same release
  yields two runs and conflicting hashes both succeed, with either one service or
  two service instances sharing the data directory. Different releases can progress.
- test_missing_receipt_retry_probe.py: 2 failed. Receipt I/O failure after run save
  leaves ordinary writing retry pending both before and after runtime restart.
  Both cases retain exactly one production run before the retry.

All probes use synthetic rule/resource files, temporary service directories and
loopback only; no real provider or AA. When promoting into tracked tests, replace
HALOCUE_TEST_REPO with repository-relative fixtures and keep explicit safe settings.

## Admission design

Reject a service-wide state lock (unrelated releases and cancellation should not
wait) and a new production SQL/claim database (unnecessary storage migration).
Use a stable lock per validated upstream release in the production data directory.
A standard-library OS file lock can coordinate threads, separate service instances
and cooperating processes. Never unlink lock files while participants may exist.
Keep the guard independent of model execution and do not claim all production state
is now multi-process-safe. This contract is only creation/receipt admission.

ProductionService.create_run becomes a thin guarded public template method; move
its current body to _create_run. The IntegratedProductionService overrides
_create_run and calls super()._create_run, so the one outer guard spans lookup,
create, run publication, copy attachment and receipt publication. Avoid recursively
acquiring an OS lock. Inline/manual sources without an upstream release continue
to create distinct runs normally. Existing ID/hash conflict errors must remain.

Tests: promote the RED probe; add lock release after failure, cached run after
restart, same-ID different-hash rejection, unrelated-ID progress. If implementing
cross-process locking, add an actual subprocess exclusion test and document its
bounded scope; do not infer it from a thread test.

## Receipt replay design

Retain the existing POST create_run endpoint as a replayable command. GET resource
usage stays read-only. Do not invent receipts from current mutable Scene rows.

WritingService._handoff_release_locked currently returns early whenever it finds
an existing run. Preserve this cheap path for no-assets/complete-proof cases. For
an existing run with pending asset proof, replay build_production_handoff from the
already verified immutable release, then reconcile the resulting usage. Preserve
the recovered/idempotent response fields and guard against an unexpected run ID.
The integrated create path already owns copy creation; serialization from 01-006
must also cover its .tmp receipt write and custom-copy check/attach sequence.

Do not interpret a missing/invalid-schema receipt as complete. Failures remain
visible and retryable; no duplicate paid work is introduced (creation is local).
Before optimizing to reuse existing receipts, validate their identity against the
frozen requested source refs. Source disappearance/version drift may remain an
explicit blocked dependency; never fabricate copy hashes to make replay succeed.

Tests: promote both I/O/restart RED cases; inject interruption at receipt write,
verify normal handoff converges to complete with run_count=1. Cover concurrent replay,
no duplicate custom copies or .tmp collisions, invalid receipt schema/identity not
accepted, frozen sources despite current author changes, response loss, and no
regression of the existing sequential handoff tests.

## Boundaries and delivery

Keep source-only snapshot/receipt projection from 6f28ebb; do not edit old frozen
manifests, standard direction prompts/rules, teacher/Sel, main, or the 1.1 worktree.
Implement test-first, obtain a scoped review, then run a broad regression on an
unchanged commit. Update ledger/handoff only with actual verified scope. UI should
eventually distinguish a linked run from completed asset proof and allow safe retry;
do not claim a new UI exists until it is implemented and behavior-tested.

## Confirmed UI consequence for the replay slice

`app.js` around renderRelease and renderReleaseBeforeProductionNavigation converts
an already-linked handoff button into "打开 AA 制作任务" (it removes data-handoff).
The normal toast also reports only that a run was created. Therefore backend replay
alone is not the entire user-facing fix when proof remains pending: preserve the
open-production button, add release-scoped proof status and a separate safe replay
button for incomplete/error states, and avoid calling a linked run full delivery.
Use the existing writing release asset-status endpoint and the existing handoff POST;
keep status requests independently bounded and stale-response-fenced so they cannot
stall/change another work's release view. Test via Node/browser DOM events, not just
presence of labels. This is a necessary consumer change, not a new production UI.

A small public-template-method split is preferable to double locking: base
create_run obtains the identity guard and dispatches to self._create_run; integrated
moves its override to _create_run and calls super()._create_run. That spans both
stages without recursively reacquiring an OS file lock.
