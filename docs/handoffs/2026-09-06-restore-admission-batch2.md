# Recovery admission batch 2 — local handoff

- Date: 2026-09-06
- Baseline: `ee8878e` (batch 1), application 1.0.0.
- Branch: `codex/1.0-restore-admission-batch2` (stacked on batch 1).
- Review target: `01-002` — restore must not replace a workspace under an active
  durable handler or concurrent writing request.
- GitHub lookup again returned `Post https://api.github.com/graphql: EOF`.
  No remote issue/PR is claimed; local review ID is the temporary tracker reference.
- Code commit: `a9ded6b` (local only).
- This is not merged, pushed, or a new Windows release.

## Design and scope

A check of `_agent_threads` was not tied to durable claims or normal requests.
Replacing it with another query alone would still leave a check/start race.
The new `workspace_access.py` provides fail-fast shared/exclusive admission keyed
by the resolved writing data directory:

- Normal operations take a shared OS file lock. Independent writes/requests can
  still overlap; this does not serialize model calls or replace SQLite transactions.
- Restore takes an exclusive lock before inspecting live task state and holds it
  through backup validation, replacement, schema recovery, rule materialization and
  reconciliation. No busy operation waits and then unexpectedly restores stale data.
- Windows uses `LockFileEx` with nonblocking shared/exclusive byte-range locks;
  Unix uses nonblocking `flock`. The `.writing-access.lock` file is never unlinked
  or included in a user backup. OS lock ownership, not mere file existence, is used.
- One thread can reenter its existing access. A shared-to-exclusive upgrade is
  rejected, not waited on. Separate instances and current-version cooperating
  processes using the same directory share the OS exclusion.

### Boundaries

- Explicit decorators cover public instance operations on `WritingService`,
  `SourceCatalog` and `AdaptationService`, including complete waits and subsequent
  writes. `close()` stays callable to shut down workers; restore is exclusive.
- The HTTP GET/POST dispatch surrounds the complete request, including routes that
  call a source/adaptation component directly. The restore POST is separately
  admitted by the service and never upgrades a shared request.
- The dispatcher holds shared access from before claim to handler/final queue
  completion. A cancelled job whose handler has not returned still blocks restore.
  Busy/recovery-required ticks are not treated as a failed model job.
- Repository initialization, transactions and atomic files participate. Raw SQL
  handles/private internal helpers are not a supported independent long-running
  operation API; callers using lower-level pieces must hold `data_access.operation()`
  across the whole logical operation, not just one SQL statement.

## Observable behavior

- Active operations: restore returns HTTP 409 `backup_restore_busy` before any swap.
- Ready/running live jobs: restore also returns `backup_restore_busy` with a bounded
  `pending_job_ids` list; finish/cancel them first. Checking the queue occurs while
  exclusive access already prevents claims/enqueues racing it.
- During restore: ordinary requests/direct supported operations return 409
  `writing_maintenance_busy`; another restore also fails fast. Callers retry after
  maintenance, not by silently queueing the original overwrite.
- Success or fully compensated failure releases admission. The same Repository
  object is reinitialized; sources, adaptations, projections and dispatcher do not
  retain an abandoned pre-restore repository object. Existing preferences/model
  settings remain outside restored content.
- Queued work present in an incoming backup keeps the existing durable recovery
  semantics; this patch does not silently discard it or invent a new generation.

## Fail-closed incomplete restore

`.writing-restore-incomplete.json` is written before mutation and remains until the
whole service restore is healthy. It includes available staging/rollback/safety
backup locations. It is a safety marker, **not a replay journal** or auto-repair:

- Normal rollback removes it; subsequent operations can continue.
- Failed rollback, process exit during restore, or post-swap initialization failure
  leaves it present. Reopening the service also returns `writing_recovery_required`
  before Repository initialization writes into partial data.
- Do not delete this marker merely to reopen the application. Preserve safety
  backups and rollback files; an operator must recover/verify the data first.
  The marker contents may be partial after an abrupt OS failure; its existence
  alone is enough to refuse admission.
- Python interruption participates in compensation, including a second interruption
  during rollback; remaining originals are not cleaned up as disposable files.

## Explicit limitations

This is cooperative access control, not a security boundary against another
application that ignores the lock or removes/changes files. All processes accessing
one workspace need the updated code. Legacy running copies, raw SQLite clients,
network filesystems, and external sync/backup tools are not coordinated here.

The current Windows tests cover real OS locks across local child processes and
abrupt child exit, not full power-loss durability, Unix execution, real providers,
Windows UI/packaging or actual AA playback. There is no promise of automatically
repairing an interrupted restore or forcibly stopping an in-flight provider.

Live backup export still uses its existing content-snapshot behavior; this patch
protects it from a concurrent **restore**, not a new globally frozen export design.
No settings, prompts, teacher/Sel, production semantics or 1.1 code were changed.

## Tests and regression strategy

- First failing test observed the actual durable handler running while restore
  incorrectly returned success. Then add ready-job and complete-operation tests.
- Deterministic events cover request-before-restore and restore-before-request;
  no sleep-based correctness assertions.
- New tests cover shared concurrency, cross-process contention, nested access,
  distinct workspaces, abrupt process exit, pre/post-swap failure, direct component
  access, HTTP source/adaptation routes, repository identity, settings preservation,
  cancellation, dispatcher resume and fail-closed recovery.
- Existing successful backup test now drains the deterministic projection queue
  created by `save_work_canon` before restore; it must no longer silently discard
  ready tasks. This is an intentional new admission precondition, not a skipped test.
- A guard-coverage test prevents future public service/source/adaptation methods
  from accidentally bypassing operation admission.


## Review corrections and evidence boundaries

A bounded read-only review identified a shutdown interleaving in the first draft:
restore sampled a running worker, concurrent `close()` stopped it, then restore
called `start()` and restarted it. A new regression first failed on that exact
interleaving. Restore now invokes only `_reconcile_dispatcher_state()` (reconcile
and notify), never `start()`. The regression passes; review follow-up found no
remaining blocker in that adjustment.

The first broad run returned **699 passed, 1 failed**. The failure was the existing
optional-corpus permission test: its global `Path.is_dir` stub also caught the new
per-operation `mkdir(exist_ok=True)`. Directory creation was moved to access-object
initialization; the unchanged existing test and all 24 new admission cases then
returned **25 passed**. This initial failed run is retained, not reported as green.

The four new Python files pass Ruff lint/format checks. The changed pre-existing
files have no new lint findings compared with `ee8878e`; existing findings in
`adaptation.py` (19), `service.py` (3) and `test_settings_hub.py` (1) were not treated
as permission for unrelated cleanup. Full-file formatting of old large modules
was deliberately avoided.


## Final verification (Windows, Python 3.13.12)

- `python -X utf8 -m pytest services/halocue/writing/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py -q`
  — **739 passed**, 441.56 seconds, exit code 0.
- This includes **24 new admission/restore tests**, all batch-1 recovery tests,
  integrated routing/lifecycle checks, and the **36 standard/conservative prompt
  and annotation tests**. These are overlapping subsets, not additional counts.
- `ruff check` and `ruff format --check` on the four new Python files — passed.
- AST parsing and baseline-relative lint comparison across all 12 touched/new
  Python files — no new lint findings. Existing old-file findings described above remain.
- `git diff --check` — passed.
- Separate scoped code review: the identified shutdown race was reproduced and
  fixed; follow-up found no remaining blocker. No real providers or user data were used.

Maintainer-local logs are kept outside the repository under the batch-2 output
folder. No full root/production/browser/packaging matrix or Unix runtime test was
performed. These results do not certify a complete independent security audit.

## Next batch

Proceed separately to model-key/endpoint binding and the AA environment detect/adopt
contract (`06-F01`, `06-F03`). Keep configuration fixes separate from adaptation,
accounting, direction semantics and this restore protocol.
