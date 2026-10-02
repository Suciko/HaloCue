# Handoff recovery and admission — 2026-09-07 (working draft)

Baseline:3fd3f48. Code commits91663f5 and72f24aa. No main merge/push/release/1.1 edit.
Accepted final verification is recorded below; the overall maintenance goal remains active.

## 01-006: identity-scoped admission

Production create_run is now a public guarded template. A private _create_run holds
the existing implementation; integrated overrides that protected method so one
upstream-release guard spans lookup/create/save/asset copy/receipt write.
Standard-library file locks live under the production data dir and are never deleted.
The scope is cooperating callers sharing a local production directory, not all
production-state multi-process safety. Windows executed; POSIX branch inspected.
Different identities and manual unbound creates remain independent. Acquisition has
no timeout. No paid model call belongs to this critical section.

TDD: four deterministic race cases failed before fix, then passed: same ID/hash had
duplicate runs, conflicting hashes both succeeded, with one or two service instances.
Two unrelated-ID cases passed before and after. Added actual subprocess exclusion,
normal owner exit, terminated owner exit, and failed-local-creation retry.

## 01-005: ordinary frozen retry

An existing run plus pending asset proof now replays the existing production POST
from verified immutable release input, then reconciles receipt proof. Existing complete
or no-asset cases keep the cheap read-only path. A different returned run ID cannot
replace a known association. Retain recovered/idempotent metadata.

Missing receipt I/O errors after run save and wrong-schema/wrong-run receipt files
recover through normal handoff before and after process restart. Tests delete current
author refs before retry to verify that frozen inputs, not mutable Scene state, are
replayed. Invalid proof never masquerades as complete.

The actual custom-PNG replay test uncovered an existing integration error:
_attach_custom_copy read draft.session.draft_version; run_detail exposes the version
at draft.draft_version. Corrected the one lookup. Concurrent replay retains one task
copy and one run, with no receipt temporary-file conflict.

## Important correction to prior test evidence

The scoped reviewer identified that legacy_root=repository is not data isolation,
even with a synthetic resource index and aa_data=None. Resource snapshot building
opens legacy_root/aa_assets.db through a migration-capable connection. The reviewer
reproduced migration using an empty temporary synthetic database. We did not rerun
the probe against the actual catalog or attempt to restore/delete it.

The checkout catalog stat still showed LastWriteTime2026-08-24, but there is no
before-run hash: modification cannot be conclusively excluded. Previous passing test
counts and unchanged tracked-source checks are real; previous statements that the
entire service runs used synthetic data only are too strong. This caveat applies to
prior1131/1146 broad runs and the initial9-test admission review. No actual AA playback
or paid-provider use was performed by these tests, but fixture safety was insufficient.

Added services/halocue/conftest.py with per-test synthetic legacy/resource roots,
no discovered AA/name-baseline paths, and temporary compatibility user data for
production/integrated tests. Compatibility code stays importable from the repository;
data roots are independent. Explicit new and integrated-custom fixtures use the same
isolated root. A fixture regression failed before this correction. Runtime recovery
fixtures also assert their legacy root is inside the test temporary directory.

Post-isolation focused evidence:27 passed admission/recovery/gateway;113 passed
existing service/custom-library/admission/writing-receipt tests. These overlapping
counts are not additive. Earlier nonisolated runs are not synthetic-only evidence.

## UI and remaining work

The UI implementer is adding release-specific status and explicit safe retry while
keeping open-production navigation. Final DOM tests and review are pending. The full
autonomous ledger has many unresolved items and the goal must remain active.


## Stabilized implementation and review

Backend commit91663f5 and UI/test commit72f24aa are now local. UI contains17 real
Chromium DOM cases using extracted production functions/listeners and synthetic
transport, including integrated navigation,5s read deadline/body parsing, duplicate
POST suppression, stale-work/rerender fencing, retained integrity details, and
390/1000px layout. No automatic POST. A still-unsettled POST intentionally keeps the
submission guard; the read deadline does not promise model or POST cancellation.

UI scoped reviewer found no blockers; independently17 DOM cases passed35.60s,
zero external requests. Main focused43 passed34.96s. Synthetic screenshots under
workspace output/autonomous-20260907/screenshots/release-proof-{390,1000}.png;
they show isolated release components, not a full live-backend application session.

Backend scoped reviewer after data-fixture correction found no blockers;20 selected
tests passed30.13s with temporary-only DB/config and loopback audit guards. Main
post-isolation focused60 passed66.28s. Later production+integrated suite exposed four
bare `from test_http_api` imports resolving to writing tests after cross-context
collection. Moved identical api/request helpers to production_http_helpers.py and
updated four teacher/Sel test imports only (not teacher/Sel production contracts).
270 production+integrated tests then passed134.21s. Removed unused helper imports;
its two HTTP consumers passed again. No feature assertions were weakened.

Fresh broad verification is running against immutable72f24aa. Only its final result
should become the latest ledger result; earlier counts overlap and are not additive.
The next required slice02-008 has a synthetic RED probe proving all three planning
paths hold a SQLite writer while waiting for Fake provider; no source change yet.


## Accepted final regression

Code `72f24aa055634ad65faa4fa21336eb453485ca2a` was unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py -q`

**1181 passed, exit code0,665.29 seconds.** Tracked-file snapshots match. This run
includes the corrected service data-root fixtures. No real provider or AA playback
acceptance is implied.17 changed Python files have no new lint findings versus
3fd3f48; JS syntax and diff-whitespace checks pass. Screenshots were inspected at
390px and1000px; isolated card layout has no horizontal clipping and both retry and
open-production remain reachable. This is not a full-app end-to-end visual claim.

Local evidence (workspace-level output/autonomous-20260907):
- verified-regression-72f24aa.log and.json
- verified-lint-72f24aa.json
- screenshots/release-proof-390.png and release-proof-1000.png

01-005/006 are fixed within the stated local creation/receipt replay boundary.
The broader ledger, physical provider accounting, adaptation lifecycle/UI, planning
transaction fixes, compiler semantics and documentation remain unfinished. Keep the
whole goal active. No completion or real-AA readiness claim is justified.
