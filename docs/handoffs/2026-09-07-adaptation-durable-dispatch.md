# Durable chapter candidate execution —02-005, slice A

Baseline `c3e58c1`, local `codex/1.0-autonomous-hardening-ui`. This is only the first
slice of `docs/superpowers/plans/2026-09-07-adaptation-durable-authoring.md`. It does
not close the missing ordinary import UI, adaptation→formal scene→release connection,
usage/accounting completeness or actual literary/playback acceptance.

## Behavior

- HTTP chapter candidate generation now returns202 with an already persisted Agent
  run and job identity, before model completion. Existing local source-coverage `run`
  returns200 on completion; it remains deterministic coverage, not semantic model
  analysis. Direct internal synchronous generation remains available for compatibility.
- New `AdaptationJobs` coordinates existing agent_runs/work_items/job_attempts and
  AgentDispatcher jobs, not a new ad-hoc thread queue or parallel persistence schema.
  Snapshots pin source version/chapter digest, approved plan digest, target/base
  revision and public model identity. Queue admission saves a hashed input snapshot.
- Active requests for one target deduplicate transactionally across service instances.
  A new execution is possible after terminal failure/cancel/completion. Dedup requires
  BOTH active job and active bound run, avoiding the run-failed/job-not-yet-finalized
  interval returning the old failed ID as a supposedly new retry.
- Existing cancel and retry APIs operate on these runs. Queued work survives restart;
  expired running work becomes an explicit-retry failure, not automatic model replay.
  Retry preserves pinned inputs/model identity; changed source/plan/target is rejected.
- Provider identity comparison is strict for this new durable workflow, including
  simulation/unversioned→real transitions. The existing shared capture helper exempts
  those placeholder digests; relying on it alone would permit a paid-mode switch.
- Logical call budget is charged only after acquiring the provider lock and checking
  current pins/run/lease; failures after attempted calls stay charged. Cancellation
  before execution costs no call. This does not count transport retries or claim
  complete monetary/token accounting, which remains a separate review finding.
- Source/plan/base/run/lease checks occur before charging and in the proposal commit
  transaction. Late cancelled, expired or stale results cannot create candidates.
  Proposal and completed run/attempt/task receipt are atomic. Dispatcher completion
  keeps its existing lease flow. Expired jobs with an already completed proposal-bound
  run reconcile to success on restart rather than generating a duplicate.
- Postcommit response-assembly errors preserve the durable success receipt; they do
  not turn an already delivered candidate into a retryable generation failure.
- Existing creation-run summary reflects active child tasks and pending review, rather
  than continuing to say planned or hiding another active task when one finishes.

No standard director-prompt/teacher/Sel changes, real providers, AA/Spine binaries,
main merge/push/release or 1.1 edits. Temporary source chapters and providers only.

## TDD and focused evidence (overlapping counts)

- Initial durable service contract:7 RED failures, then7 passed4.65s.
- Real loopback HTTP with blocked synthetic provider timed out waiting for a response
  before the fix; now202 returns while provider remains blocked. The older synchronous
  HTTP error test now expects202 then polls the failed run's provider_output_invalid
  error, still asserting no candidate/formal acceptance.
- Completion integration and crash-after-commit:2 RED failures, corrected with normal
  dispatcher finalization plus expired completed-receipt reconciliation.
- Postcommit response error:1 RED failure, then durable success preserved.
- Scoped review reproduced simulation→real execution and retry dedup caching the old
  failed run. Both reproduced locally (2 RED failures), then strict identity and
  bound-run-aware dedup corrected them.
- Local coverage HTTP status RED202-vs200 and creation-summary REDplanned-vsrunning
  now have specific regression cases.
- Latest new dispatch suite:21 passed14.23s. Earlier adaptation/dispatcher/async/
  workspace/HTTP focused run:182 passed62.43s, before the final summary addition.
  Those totals overlap and do not constitute an immutable-source broad gate yet.
- Changed modules/new tests pass Ruff check; service baseline3 existing lint messages
  has zero new lint, HTTP module baseline0/no new. Formatting kept scoped rather than
  rewriting the large service. Final review/source commit/broad evidence below pending.

## Remaining work / boundaries

1. The normal prose import button still uses attachments/manual chat, not this durable
   adaptation plan/job UI. Do not describe unseen controls as shipped.
2. Accepted adaptation artifacts still need explicit canonical scene adoption/promotion
   and synthetic freeze→Production proof. Existing accepted artifacts must not be
   silently rewritten or automatically published.
3. Source input token limits, transport/failed usage ledger and authorized background
   knowledge discovery remain incomplete. This slice only preserves logical-attempt
   budget bounds and makes attempted execution durable/interruptible.
4. Provider calls are not forcibly killed by cancel; returned results are fenced.
   Recovery uses existing lease expiry and explicit retry, not real-provider resumability.


## Additional recovery-summary review correction

Reviewer reproduced expired adaptation failure marking the shared creation run failed
while a sibling remained queued. New regression failed with that exact state. Recovery
now recomputes summaries for affected adaptation creation runs after all expired
siblings transition; an active sibling remains running, pending review remains
waiting_user. The final pass avoids dependence on recovery row order. Normal cancel
still follows existing service policy; no unrelated dispatcher workflow was rewritten.

Previous focused run (before this final recovery-summary case):69 passed38.67s.
Fresh final focused and committed broad verification are pending below.


## Source commit and accepted scoped review

Source commit `6076ac0564f8ca9d8a72508e50efe895fdf39b1f` includes the final
recovery summary correction. Reviewer independently ran4 targeted recovery/summary
cases (4passed4.58s) and reported no remaining blocking findings from this review.
Main final focused command:

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_adaptation_dispatch.py services/halocue/writing/tests/test_adaptation_integrity.py services/halocue/writing/tests/test_adaptation_workflow.py services/halocue/writing/tests/test_agent_dispatcher.py -q
```

**70 passed49.91s**. Changed Python checks and diff checks passed. Fixed-source broad
regression is in flight on the commit above; no tracked source is edited while it runs.
Next detailed backend slice is `docs/superpowers/plans/2026-09-07-adaptation-scene-adoption.md`;
it keeps normal scene revisions authoritative instead of maintaining two manuscript
truths and preserves existing accepted artifact bytes until an explicit promotion.


## Accepted immutable-source broad verification

Commit **6076ac0564f8ca9d8a72508e50efe895fdf39b1f** stayed unchanged throughout (HEAD and
tracked non-document hashes). **1832 passed in717.12s**, exit0, wrapper718.45s.
All focused totals above overlap with this run and must not be added together.

```text
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q
```

Maintainer-local evidence: `<WORKSPACE>/output/autonomous-20260907/verified-regression-6076ac0.log`
and adjacent JSON command/SHA/stability record. Repository aa_config.json remains
absent. Main remains58d1128 and no changes were pushed/merged/released.

This accepts durable execution in sliceA only.02-005 is partially addressed pending
broader accounting/input coverage;02-007 remains pending until ordinary UI and scene
adoption/release integration are implemented and verified. No real provider literary
quality, packaged runtime or AA/Spine playback acceptance is claimed.
