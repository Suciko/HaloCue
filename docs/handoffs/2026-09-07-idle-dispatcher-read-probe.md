# Idle Agent polls avoid SQLite writer transactions —05-009

Local only on `codex/1.0-autonomous-hardening-ui`, baseline `88c29cb`.
No main merge/push/release, 1.1 edits, paid provider, AA playback or private data.

## Change

`Repository.claim_agent_work` performs a read-only eligibility probe, closes that
connection, and only then enters the existing BEGIN IMMEDIATE claim transaction when
there may be work. The transaction re-queries eligibility and awards the lease under
its original writer lock. Empty/future/cancelled/running-only queues return no-work
without BEGIN or DML. Whole-method workspace admission preserves incomplete-restore
and maintenance protection, including during the probe. A negative probe racing a new
job is serviced by the existing notification/next poll; this is not a no-latency claim.

The added positive-probe cost is one read connection/query; no performance percentage
is claimed. Candidate and lease selection are not moved into UI or the dispatcher.
Knowledge discovery authorization, queue priority, provider budget/accounting and
adaptation job migration remain separate findings.

## TDD and verification

During the previous immutable-source run, draft tests were placed outside the repo
and run against the unchanged baseline: **7 failed, 2 passed, 4.07s**. Failures showed
idle BEGIN IMMEDIATE statements, an actual database-is-locked error under a competing
reserved writer, lack of read/recheck sequencing and lack of a closed probe before
claim. No production source changed during that previous run.

After the minimal claim change, **9 passed, 11.91s**. Tests cover idle states, reading
while another synthetic connection holds a reserved writer, positive-probe/transaction
SQL ordering, read connection closed before cancellation wins, two workers both
passing positive probes before competing for the one lease, and incomplete restore
marker denial. Existing dispatcher/workspace tests plus initial new cases:
**26 passed, 8.28s**. Final strengthened tests, planning transactions, scoped review and
combined immutable-source broad result are recorded below when complete.

This slice fixes 05-009 only; the overall autonomous goal remains active.


## Scoped acceptance

Source commit `1c5af693f133e6f1f304516e1c9681afe327e55f`. Reviewer found no concrete
connection-lifecycle, claim-concurrency or workspace-restore regression, including
both-positive-probe race coverage. Static review is not an independently rerun suite.

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_dispatcher_idle_poll.py services/halocue/writing/tests/test_agent_dispatcher.py services/halocue/writing/tests/test_workspace_access.py services/halocue/writing/tests/test_planning_transactions.py -q
```

Result: **48 passed, 19.65s**. Ruff check of changed repository/new-test files and
Git diff check passed. An initial command referred to nonexistent `test_planning.py`
and collected no tests; it was corrected to the command above, not counted as a pass.
The combined broad suite is running on the source commit above with source hash and
HEAD stability verification. Final outcome is recorded below after it returns.


## Accepted final combined verification

`1c5af693f133e6f1f304516e1c9681afe327e55f`: **1788 passed in 585.29s**,
exit 0; unchanged HEAD and tracked non-document hashes throughout. Exact broad
command and evidence references are in the companion
`2026-09-07-runtime-path-consistency.md` handoff's final section. The total includes
the nine new idle-poll cases; do not add overlapping focused counts. Overall goal
remains active. Next bounded plan: `docs/superpowers/plans/2026-09-07-legacy-module-provenance.md`.
