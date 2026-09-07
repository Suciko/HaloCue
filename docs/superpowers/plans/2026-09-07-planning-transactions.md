# Planning calls outside SQLite write transactions — 02-008

Goal: slow model calls for story/chapter/legacy blueprint planning cannot hold the
workspace SQLite writer, and late results cannot publish against changed inputs.
User authorized autonomous repair without intermediate confirmation. No new library,
paid model, UI overhaul, standard-prompt/teacher/Sel semantic change, main merge.

Verified local RED probe: test_planning_transaction_probe.py in maintainer output.
All three paths (work/chapter/legacy) raise "database is locked" when a second
connection attempts BEGIN IMMEDIATE while Fake provider waits on an Event. After
release the provider produces normal output. This is a real SQLite lock probe,
not a mocked transaction check.

## Design and alternatives

Use existing transaction/optimistic-version patterns. First short transaction checks
work/thread/policy/pending proposal, snapshots actual provider inputs and base refs.
Release DB connection before acquiring provider lock/calling the pinned provider.
Validate model output, then second short transaction rechecks work/thread versions,
thread policy, current target/pending proposal, and only then writes candidate/message/
revision and bumps versions. No provider call or wait for provider configuration
belongs inside a SQLite transaction.

Rejected: extending SQLite timeout (hides stalled saves); sharing one broad service
lock (unrelated work still blocked); generalized distributed-transaction framework
(not required for local versioned proposals). Preserve the existing structure-plan
implementation as a consumer reference, not a reason for wholesale refactoring.

## Three bounded tasks

1. `organize_conversation_proposal` for brief-blueprint:
   Move generate_blueprint/validation outside its current transaction. Freeze brief,
   analysis context, current source thread/work versions before dispatch; reacquire
   and check versions/policy/pending proposal before reading/writing target refs.
2. `_organize_chapter_plan_proposal`:
   Same two-phase pattern for chapter context/history/target source refs. Preserve
   explicit source_thread/message IDs, base chapter-plan revision, and routing.
3. `generate_blueprint` compatibility API:
   Snapshot brief and source revision/context; call provider outside transaction;
   recheck work/source revision before creating existing accepted/proposed artifact.
   Do not silently redefine this legacy API as a new workflow in a lock fix.

For each task: RED lock reproduction, GREEN, then regressions for unrelated-work
save during the wait, same-work and thread drift rejecting late writes, simultaneous
planning yielding at most one pending proposal, provider failure leaving no candidate
or orphan assistant message, and frozen provider identity after configuration change.
Concurrency must use Event/barrier timing, not arbitrary sleep-only assertions.

These direct work/chapter APIs do not currently establish cancellable AgentRuns.
Do not claim durable cancellation/restart behavior merely because transaction
locking is fixed. Recheck existing conversation policy at publication so changed
thread authorization cannot be ignored. If a concrete cancellation contract is
found during implementation, exercise it explicitly; otherwise record the missing
API lifecycle separately rather than introducing a fake success state.

Write scope: writing/src/halocue_writing/service.py, a focused new planning
transaction test module, existing provider pinning/conversation tests only if their
contract genuinely changes. Review the completed diff, lint baseline-relatively,
run narrow tests then immutable broader writing/service regression; update ledger
02-008 with actual scope and handoff. Other accounting/adaptation pipeline findings
remain open until separately implemented.
