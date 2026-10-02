# Release-owned asset receipts — 2026-09-07

Code commit: `6f28ebb8878dfdc15f328a260db4000da375d2f4`.
Branch: `codex/1.0-autonomous-hardening-ui`; no main merge, push, or 1.1 edits.

## Repair scope (01-004)

Author Scene references are source inputs; ProductionRun copies are output receipts.
They no longer share a mutable column as the source of truth:

- One pure serializer feeds writing-service and harness source snapshots. New source
  snapshots and client gate fingerprints keep `production_copy:null`.
- Validated receipts are stored in an additive SQLite table keyed by release/run/
  scene/reference. Acceptance compares against the immutable verified manifest,
  not current author rows. A final transaction rechecks the release/run binding.
- Receipt status includes a new additive `references` projection for that release/run.
  Partial receipts accumulate only there; another release/run cannot borrow them.
- Receiving proof does not change author work version, source rows, or timestamps.
  Changing/deleting current references does not remove old release receipt history.
- Old unscoped copy columns are retained, but neither promoted to ownership proof nor
  forwarded to providers/new releases. Old frozen manifests and gate records remain
  byte-identical. Previously frozen non-null copies are still rejected on handoff;
  re-review and make a fresh source-only release instead of rewriting old history.
- Source-detail UI no longer claims one global task-copy status. It explains that
  receipts belong to release versions. The existing production navigation remains.

The migration and wire-compatibility contract is documented in
`packages/contracts/production-assets/README.md`. No new dependency is introduced.

## Tests and independent review

Four original regression cases failed before the fix, then passed: author purity,
R1/R2 isolation, history after current reference deletion, and legacy projection not
being promoted. Two Node/UI checks reproduced stale client copy fingerprints and
misleading global copy text before correction.

The first broader development run returned 3 failed / 38 passed, solely the old tests
that required writing a receipt into the author row. They now assert the release/run
receipt projection and still verify exact copy IDs. Subsequent targeted run: 50 passed.

Further regressions cover wrong run/source/version/hash/duplicate proof, partial
accumulation, run rebinding isolation, old-database table addition, backup/restore
with deleted current references, and legacy frozen bytes plus the preclaimed guard.
An actual synthetic loopback integration freezes and hands off R1 and R2 with the
same source asset: distinct runs/copy IDs, preserved R1 manifest and separate proof.

A focused backend reviewer reported no actionable findings. It reran the four
original regressions and independently exercised partial receipts, invalid identity
proof, unchanged author state, run isolation, and history after edit/restart. Its
extra probe assertions passed, but temporary-directory cleanup exited nonzero due
to a Windows SQLite file lock; do not call that probe a clean command pass.

The final expanded targeted command initially completed with **77 passed in 68.79s**.
A subsequent fixture cleanup edit mistakenly called gateway.shutdown() without
starting that gateway. The interrupted run was not counted as a pass; the known
owned test process was stopped, and the fixture now calls close(stop_gateway=False)
so the writing dispatcher is closed without waiting for a nonexistent gateway loop.
That updated integration test passed (1 passed, 9 deselected).

Two new Python files pass Ruff formatting. Eight changed Python files have no new
lint findings versus `53a1afd`. Both JS files pass node --check; diff whitespace
check passes. Stable-commit broad verification is recorded separately below when
complete; no source edits are made during that run.

## Remaining scope

01-005 (ordinary handoff retry does not replay missing receipt creation) and 01-006
(concurrent production create can publish duplicate runs) remain required work.
This commit does not implement those repairs or claim whole-pipeline idempotence.
The full maintenance goal remains active. Real providers, actual AA playback, and
independent group04 security review are not covered by these synthetic tests.

## Broad validation correction

The first broad run on `6f28ebb` encountered one obsolete UI text assertion in
`test_http_api.py::test_main_user_surfaces_use_plain_language_and_fold_run_metrics`.
A focused run reproduced that exact assertion; it still required the removed global
"no production copy" text. The owned broad child was intentionally stopped after
this known failure (not counted as a complete result); source snapshots remained
unchanged. The retained log/JSON records exit code 4294967295 and 285.37s.

Commit `12389a2` updates that plain-language assertion to require the new release-
scoped wording and reject the old misleading text. Four focused UI/source checks
passed. A fresh full broad run targets this immutable commit; its final result is
the only accepted broad result for this slice.

## Accepted final verification

Commit `12389a254c2effa6b1a383263ef89652c40c67bd` was unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py -q`

**1146 passed, exit code 0, 689.15 seconds.** Tracked-file snapshots before and
following the run match. Do not add the overlapping focused counts to this total.
This is the accepted broad service/prompt regression, not a real-provider/AA test.

Maintainer-local evidence at the workspace-level `output/autonomous-20260907/`:
`verified-regression-12389a2.log`, `verified-regression-12389a2.json`, and
`release-assets-lint.json`. The interrupted/failed earlier logs are retained and
are not represented as successful complete runs.

Next-slice independent synthetic probes already reproduced 01-006 (four failures,
two unrelated-release successes) and 01-005 (two failures before/after restart).
They do not change this commit's verification scope; the required repairs remain
open. See the next handoff-replay plan. The whole autonomous goal is not complete.

## Test-data isolation correction (2026-09-07)

Later review found that synthetic resource indexes did not isolate the repository
legacy asset database. Earlier passing counts remain actual results, but claims of
fully synthetic-only service runs are too strong. No prior hash proves the local
catalog unchanged. See `2026-09-07-handoff-replay-ui.md` for scope, corrected fixtures
and the1181-test unchanged-commit regression. No real AA playback was performed.
