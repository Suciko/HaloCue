# Idle dispatcher read probe —05-009 Implementation Plan

> Execute locally with TDD and scoped review; preserve durable lease transitions.

**Goal:** An idle writing Agent dispatcher must not acquire a SQLite writer lock
just to learn that no eligible work is ready.

**Architecture:** Add a read-only eligibility probe before the existing atomic claim
transaction. If no candidate is ready, return the existing no-work response. If a
candidate exists, close the read connection and retain the current BEGIN IMMEDIATE
transaction and authoritative re-query/update. Do not upgrade an open read snapshot
into a write transaction. A queue insert racing a negative probe waits at most the
existing next poll/notification; cancellation or another worker winning between probe
and transaction must remain safe. Keep workspace restore admission/locking intact.

**Alternatives:** Making the existing claim transaction deferred risks SQLite snapshot
upgrade races; removing transactional re-check risks duplicate claims. A read probe
plus re-check is deliberately small and retains the proven lease state machine.

**Files:** `services/halocue/writing/src/halocue_writing/repository.py` (claim only),
new `services/halocue/writing/tests/test_dispatcher_idle_poll.py`. Reuse existing
repository/dispatcher helpers rather than modifying the whole scheduling framework.

- [x] Reproduce: trace SQL for an empty claim, asserting no BEGIN IMMEDIATE or DML.
- [x] Cover future available_at and cancellation as noneligible read-only cases.
- [x] Verify the read connection is closed before entering a write transaction.
- [x] Implement read-only candidate probe, retain authoritative transaction selection.
- [x] Simulate two claimers / candidate cancelled or claimed after probe; exactly one
      lease owner, correct no-work result for loser, no unlocked state transitions.
- [x] Run existing Agent dispatcher/workspace restore suites and new tests.
- [x] Scoped review, exact-SHA regression, bounded ledger/handoff update; no main push.

No scheduler priority, automatic knowledge authorization or usage accounting changes
belong in this slice; 05-010/02-009 and related accounting findings remain separate.
No paid provider or user data is required. Do not claim quantified performance gains
without measurement; the acceptance target is removal of idle writer transactions.


## Baseline reproduction prepared during runtime-path regression

Synthetic tests were drafted outside the repository in maintainer-local output so
runtime-path source remained fixed. On `459f3f2`, the draft produced **7 failed,
2 passed, 4.07s**: empty/future/cancelled/running claims all begin writer transactions;
an external reserved writer blocks even an empty claim; eligible claims lack the
read probe; there is no closed probe connection before entering the transaction.
Existing one-winner and restore-marker behaviors passed. This is RED evidence only;
implementation must wait until the in-flight immutable-source regression finishes.

Completed bounded slice at1c5af69: scoped review accepted; 48 focused tests and1788 unchanged-source combined regression tests passed. See companion handoff.
