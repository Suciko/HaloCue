# Adaptation and memory provenance repair — 2026-09-07

Branch: `codex/1.0-autonomous-hardening-ui`. Code commit: `45b58bc`.
No main merge, push, 1.1-worktree edit, real model call, or real AA playback.

## Scope and contracts

- 02-001: adaptation candidates must be JSON objects with the existing schema,
  nonempty text and source references, correctly shaped deviation/open-thread
  lists, and exact paragraph ID/quote matches against the pinned source chapter.
  Reject malformed output; never invent source refs to make it appear grounded.
  Reject nested NaN/Infinity as non-JSON data. Acceptance revalidates valid-hash
  legacy candidates and requires canonical pinned source metadata.
- 02-002: single-scene memory extraction verifies source revision bytes before
  provider dispatch, validates raw block IDs before normalization/truncation, and
  checks every selected item's pinned scene/revision/hash/block reference again
  at acceptance. Valid selected items need not depend on unselected bad legacy
  items. Text-only legacy revisions reconstruct stable blocks with their revision
  ID namespace before snapshot/provider dispatch, matching acceptance.
- 02-003 / 07-010: analysis aggregates all source windows per chapter in an
  additive `adaptation-analysis/1.0` projection under `dependency_json.analysis`.
  Reanalysis never replaces pending candidate or accepted manuscript projections.
  Planned/analyzed clients retain their candidate coverage view for compatibility.
- 02-004: generation captures the target formal base revision and source version
  before dispatch, checks both again before publishing, and acceptance uses CAS.
  A newer accepted manuscript cannot be overwritten by an older pending proposal.
- 02-005 / 05-001 / 06-F10: dispatched logical candidate attempts are not refunded
  after provider failure; `max_calls` must be a positive integer. This is not a
  physical HTTP retry budget, monetary hard cap, or complete provider usage ledger.

No SQLite migration is required in this batch. Real provider prompts are unchanged;
FakeWritingProvider now emits a contract-valid, explicitly synthetic adaptation
reply rather than relying on the removed invalid-output fallback. Standard direction
prompts/rules and teacher/Sel contracts were not edited.

## Verification and review

TDD reproduced malformed/missing/invented references, overwritten coverage,
reanalysis projection loss, stale acceptance, failed-attempt refunds, and late source
or target publication. Regression tests also exercise a real loopback HTTP request
with an invalid synthetic provider reply.

A scoped reviewer found text-only legacy memory regression and nested non-finite
metadata acceptance. Seven tests failed before the corrections and passed after;
the reviewer reran the seven and found no remaining blocker in those corrections.
Two further missing canonical-source-metadata cases reproduced KeyError and now
return a domain validation failure without formal writes.

Final targeted command:

`python -X utf8 -m pytest services/halocue/writing/tests/test_memory_agent.py services/halocue/writing/tests/test_adaptation_integrity.py services/halocue/writing/tests/test_adaptation_workflow.py services/halocue/writing/tests/test_adaptation_sources.py services/halocue/writing/tests/test_adaptation_prompt_contract.py services/halocue/writing/tests/test_knowledge_proposal_normalization.py -q`

Result: **77 passed, 49.15 seconds**. Earlier focused runs overlap and are not additive.
New/small adaptation files pass Ruff formatting. All six changed Python files have
no new lint findings relative to `58a0aaf`; diff whitespace check passes.

## Remaining work

The whole maintenance goal is not complete. This batch does not implement durable
adaptation jobs/cancel/restart, novel-to-scene-to-production UI handoff, physical
provider request/cost accounting, or literary fidelity verification. A valid quote
proves that a cited span exists, not that generated text is faithful to the novel.
Production handoff receipt isolation/recovery/idempotency remains a required next
slice. Missing independent group04 review and real AA playback remain explicit.

## Accepted broad verification

On unchanged code commit `45b58bcb56cc5ab529c5429354ae02d5f18e7550`:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py -q`

**1131 passed, exit code 0, 578.72 seconds.** Tracked-file SHA-256 snapshots before
and after are identical. This is the accepted broad service/prompt regression,
not a claim of an exhaustive root compatibility suite or real AA/provider acceptance.

Maintainer-local evidence under the workspace-level `output/autonomous-20260907/`:
`verified-regression-45b58bc.log`, `verified-regression-45b58bc.json`, and
`adaptation-memory-lint.json`. These are not collaborator prerequisites; the exact
reproduction command and stable commit above are authoritative shared references.

## Test-data isolation correction (2026-09-07)

Later review found that synthetic resource indexes did not isolate the repository
legacy asset database. Earlier passing counts remain actual results, but claims of
fully synthetic-only service runs are too strong. No prior hash proves the local
catalog unchanged. See `2026-09-07-handoff-replay-ui.md` for scope, corrected fixtures
and the1181-test unchanged-commit regression. No real AA playback was performed.
