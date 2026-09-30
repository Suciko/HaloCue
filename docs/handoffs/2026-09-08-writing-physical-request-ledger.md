# Writing physical request accounting — bounded repair of05-003 /05-001

- Source commit: `41c5012ee47efb71c57d3145cb094a2638969d12`.
- Branch: `codex/1.0-autonomous-hardening-ui`; main remains `58d1128`.
- Overall autonomous goal remains active. No main merge, push, release or1.1 edits.

## Implemented boundary

The writing client's observed HTTP attempts attributed to durable AgentRuns now have
separate logical-request IDs and physical-attempt IDs/ordinals. SQLite
`provider_requests` is additive to existing writing databases and travels through the
normal backup/restore path. Dispatch intent is persisted before sending. Success,
rejection, transport/read failure and missing/partial usage remain distinguishable.
Only allowlisted provider identity and normalized usage/error metadata are recorded;
no prompts, raw responses, endpoint credentials or hidden reasoning enter this table.

The work-scoped GET `/api/v1/works/{work}/agent-runs/{run}/requests?after={requestID}`
returns `provider-request-ledger/1.0`, stable pages of at most100 records and a summary
of the whole run, not just its current page. A foreign run is not exposed. Agent and
work usage choose physical summaries where present, otherwise explicitly labelled
legacy logical summaries; they do not add both copies of the same observation.
Actual conversation/scene runtime details display physical/logical counts, unknown
usage, incomplete receipts and uncovered legacy scope.

## Failure and lifecycle invariants

- Start-persistence failure prevents the outbound request.
- A terminal delivery retry resends only the same frozen receipt, not HTTP.
- Persistent terminal delivery failure fails safely with an exact per-request receipt
  in Agent policy. That receipt provisionally preserves known consumption. Startup
  replays it idempotently and clears only an acknowledged matching receipt.
- Conversation finalization merges the policy read in its own transaction, retaining
  receipts written by the usage scope. Adaptation and conversation have regressions.
- Late receipts can settle dispatched/interrupted rows without reviving cancelled or
  failed Agent output. Another live service's running jobs are not marked interrupted.
- HTTP error diagnostics are bounded. Read/close/parse failures do not erase a known
  HTTP status or change retry classification; successfully read non-JSON bytes remain
  available to the existing diagnostic formatter, but not the request ledger.

## Review and focused evidence

Read-only scoped reviewer found terminal delivery loss, diagnostic read/close retry
regression, erased non-JSON diagnostics, and conversation policy overwrite. All four
were reproduced/fixed with tests. Final re-review found no remaining concrete blocker
in this slice; that is not a full-program audit or independent test execution.

Latest focused run: **99 passed in48.70s**. Command:

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_physical_request_ledger.py services/halocue/writing/tests/test_usage_failure_provenance.py services/halocue/writing/tests/test_usage_ui.py services/halocue/writing/tests/test_provider_http_recovery.py services/halocue/writing/tests/test_provider_tool_calling.py services/halocue/writing/tests/test_backup_sources.py services/halocue/writing/tests/test_restore_admission.py -q
```

Evidence under `<WORKSPACE>/output/autonomous-20260907`:
`physical-ledger-reviewed-focused.log`, `physical-ledger-conversation-red.log`, and
previous physical-ledger focused/RED logs. Counts overlap and are not additive.
Ruff check passes changed small Python modules/tests, JS syntax and diff checks pass.
The large service module retains preexisting lint debt; no blanket lint-clean claim.
Broad immutable-source regression is being recorded separately before acceptance.

## Explicit gaps / next work

05-003 and05-001 stay **partial_or_mitigated**. The root compatibility/Production
adapter and its SDK/internal retries are not yet integrated; separate connection-test
HTTP calls do not become attributed merely because this writing ledger exists. The
root ring/JSONL remains incomplete accounting. Whole-database failure and process
crash windows are not solved by an exact receipt that was never durably written.
No hard spending-authorization guarantee, retroactive historical physical counts,
real paid-provider acceptance or real AA/Spine playback acceptance is claimed.

Next bounded root task:05-006 result assembly currently calls build_metrics before
finally captures the current failed request. Fix and independently test timeout,
request cancellation and cancellation during retry backoff, without changing prompts,
chunk delivery or retry policies. Root physical attribution remains a separate task.

Historical test-data isolation caveats in the prior ledger/handoffs remain valid;
this slice does not rewrite them. `.scratch/`, `.tmp/`, and the unrelated8898 server
are preserved. All added fixtures use temporary synthetic workspaces/transports.
