# Recovery safety batch 1 — local handoff

- Date: 2026-09-06
- Baseline: `58d112867ee264b72c2191ed51377db02035bc11` (`main`, HaloCue 1.0.0)
- Branch: `codex/1.0-recovery-batch1`
- Scope: writing backup/restore compensation and integrated writing-worker shutdown
- Inputs: received review findings `01-001`, `01-003` / `07-002`, and `01-007` / `02-010`.
- Tracker: GitHub issue lookup failed with `Post https://api.github.com/graphql: EOF`.
  No issue or PR number is claimed. This handoff records the local slice pending tracker reconciliation.
- Code commits (local, not pushed):
  - `820eef4`: restore compensation and SourceCatalog backup completeness.
  - `f6c969b`: integrated writing-dispatcher shutdown.
- Integration: local branch only; not merged into `main`, not a released desktop build.

## Implemented behavior

1. Restore tracks original directories moved aside separately from incoming directories
   installed. Compensation reverses only completed transitions. A staging/safety-backup
   failure cannot delete original roots that were never moved.
2. A database restore attempt is compensated even if the restore call raises after
   modifying the destination. The pre-restore database snapshot remains the rollback source.
3. Failed compensation retains the remaining rollback directory rather than deleting it
   in `finally`. `backup_restore_rollback_failed` includes `rollback_path` and
   `safety_backup` for manual recovery and tells the caller not to repeat an overwrite.
4. Backups include `sources/`. Inspection checks `source_versions.original_uri` and
   `normalized_uri` alongside the other existing content references, across historical
   source versions as well as the current one.
5. Integrated shutdown calls the existing bounded `WritingService.close()` before
   shutting down the production upstream; the idle writing poller no longer survives
   gateway shutdown.

## Contracts and compatibility

- No schema migration, new dependency, route rename, prompt change, or UI redesign.
- Backup format remains `halocue-writing-backup/1.0`. This is a source-content completeness
  fix, not automatic repair of an already incomplete archive.
- Older backups with no source-catalog table still restore. A modern archive whose
  database references missing source bytes is rejected as `backup_reference_missing`.
  Original files are not reconstructed from chapter JSON, and no silent partial restore
  is offered. Older readers may reject a new archive containing `sources/`; use the
  updated reader for these archives.
- Standard/conservative prompts, teacher/Sel, model settings, and 1.1 workspace are unchanged.
- `rollback_path` is a local recovery location, not a portable path or upload prerequisite.

## Test approach

Each core bug was first reproduced by a new failing regression on synthetic local data,
then the minimal change was applied and the regression rerun:

- Safety-backup failure: untouched original content vanished before the fix.
- Compensation failure: an unclassified OSError escaped while `finally` deleted the only
  remaining rollback originals before the fix.
- Database finalization failure: incoming database survived while original files were
  restored before the fix.
- Source round-trip: a restored catalog contained source URIs but their bytes were absent.
- Incomplete source archive/export: no error before reference checking was extended.
- Integrated close: gateway stopped but writing dispatcher still reported running.

Additional checks exercise failures before/after moving each content root, a root that
was absent in the original workspace, all source versions, old schema compatibility,
explicit confirmation/hash gates, and existing integrated routing contracts.

## Intentionally not fixed in this batch

- **01-002 remains open:** live restore admission still needs an atomic maintenance
  protocol covering durable claims and concurrent request writes. Replacing the old
  `_agent_threads` lookup with one query would leave a check/start race. Do not claim
  this batch makes live restore safe during active work.
- Restore compensation handles exceptions in this process, not power loss or a killed
  process between filesystem transitions. There is no new persistent restore journal.
- Existing shutdown is bounded; an uncooperative in-flight Provider call is not forcibly
  disconnected. The idle worker regression does not prove immediate termination of all
  active calls.
- No real Provider calls, paid evaluation, real user restore, AA installation/playback,
  or packaged Windows/WebView2 acceptance were performed.
- Review group 04 is still missing; this is not a complete security audit.

## Next bounded slice

Design and test real maintenance admission for restore (01-002), including active and
queued durable work, normal HTTP mutations, worker restart, and failure release of the
maintenance gate. Keep it separate from model configuration and screenplay semantics.

## Verification results (local Windows, Python 3.13.12)

- Baseline before edits: `python -X utf8 -m pytest services/halocue/writing/tests/test_settings_hub.py -k backup -q` — **3 passed, 9 deselected**.
- Broad regression after edits: `python -X utf8 -m pytest services/halocue/writing/tests services/halocue/integrated/tests -q` — **679 passed**, 387.45 seconds.
- Focused regression: `python -m pytest services/halocue/writing/tests/test_backup_recovery.py services/halocue/writing/tests/test_backup_sources.py services/halocue/writing/tests/test_settings_hub.py services/halocue/writing/tests/test_agent_dispatcher.py tests/test_direction_profiles.py tests/test_conservative_annotation.py -q` — **81 passed**. This overlaps the broad suite; counts must not be added.
- Integrated-only regression: `python -X utf8 -m pytest services/halocue/integrated/tests/test_runtime_lifecycle.py services/halocue/integrated/tests/test_gateway.py services/halocue/integrated/tests/test_production_script_line_endings.py -q` — **14 passed**, also included in the broad result.
- `ruff check` on the two changed implementation files and three new test files — passed.
- `ruff format --check` on the three new tests — passed. The two pre-existing implementation files fail full-file format checking both at `58d1128` and after this patch; no unrelated whole-file reformat was applied.
- `git diff --check` — passed.
- Added **24 regression cases** across the three new test files.
- A separate bounded read-only code review found no introduced blockers. It did not execute tests and did not audit the deferred concurrent-restore or power-loss boundaries.

The full root/production/browser/packaging matrix was not rerun. This remains a local
branch checkpoint, not a merge/release acceptance claim.

- Final separate standard/conservative prompt check: `python -X utf8 -m pytest tests/test_direction_profiles.py tests/test_conservative_annotation.py -q` — **36 passed** (overlaps the focused run).
