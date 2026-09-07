# Model resume identity, late preflight results, and UI clarity — autonomous slice

- Date: 2026-09-07
- Baseline: `b988d53` (completed safety batches 1–3).
- Branch: `codex/1.0-autonomous-hardening-ui`.
- Code commits: `73d0237` (backend) and `0721761` (UI), local only.
- User authorized continued batch work without intermediate decisions, including UI polish.
- No main merge, push, release, real provider call, AA installation or user-data migration.

## Backend scope

### 06-F05 / 05-002: checkpoint and model identity

Direction generation now records a non-secret `direction-model-identity/1.0` in its
private retry context. It covers an allowlisted canonical digest of the saved endpoint,
model, execution limits/reasoning options, opaque credential revision and environment
reference (not the key value). Capture and provider construction occur under the existing
activation lock, with a subsequent identity comparison to detect an external file switch.

Retry compares the captured identity before creating a new job or invoking the provider.
Changed/missing identities require a new generation; missing legacy identities no longer
offer a safe-resume button. New generation and unchanged-configuration resume remain valid.
Any save that creates a new credential revision conservatively invalidates old retries.
Changing an environment variable's **value** without saving configuration is not captured
by this public identity; no plaintext keys or secret-derived hashes are persisted here.

Annotation checkpoint fingerprints now include effective static context, context window
strategy/limits, before/after windows, background/usage plans, and endpoint identity in
both Standard and Conservative modes. `fingerprint_version=2` prevents old fingerprints
from silently comparing equal. No standard prompt text or direction rule was changed.
Existing checkpoint data remains on disk; a changed identity starts a separate checkpoint.
This is not full verification of all possible future provider options.

### 06-F04: local keyless provider construction

The 1.0 adapter supplies a transient inert authorization placeholder only for keyless
OpenAI-compatible localhost/127.0.0.1/::1 connections. This reconciles the existing
"configured" status with the legacy transport's nonempty-key requirement, without
weakening external-endpoint validation or persisting a fake key. This does not certify
that a user's local server or model actually responds; connection testing remains required.

### 02-006: preflight cancellation and publication

The production cancel endpoint no longer requires read-only preflight work to own the
mutating draft fence. A short `commit_side_effect` operation linearizes preflight file
publication against cancellation using the existing registry lock. Model IO is outside
that lock. A cancellation that wins blocks late publication; publication that wins prevents
a subsequent cancel from claiming that the already-published result was discarded.
Temporary preflight files are cleaned on failed writes. Existing mutating generation/compile
fences remain unchanged. This is not a general transaction system for every job kind.

## User-facing settings and visual polish

- The settings overview independently reads writing and direction model state. It labels
  unavailable, unconfigured, saved-but-untested and tested configurations separately.
  Writing settings alone no longer claim that AA production is configured too.
- Detailed writing connection metadata is progressively disclosed below two role cards.
  The editing form explicitly states it starts from writing configuration and asks for
  activation scope; this does not solve every cross-domain field equivalence issue.
- Four historical preferences with no execution consumer are visibly read-only and labelled
  as inactive, rather than promising an effect on generation. Values are preserved in the
  backend. No automatic text splitting, timing rewrite or global mode override was added.
- Existing paper/green visual language is retained: clear status cards, quieter borders,
  consistent buttons/field sizing, readable focus rings, and a horizontal mobile settings nav.
- Production source tabs and form grouping use the same restrained palette and hierarchy.
  Source copy now correctly describes a frozen source snapshot, not a writing ScriptRelease.
- No external fonts/images/dependencies, route changes or new static-asset prerequisites.
  Existing CSS files are extended; standard/teacher/Sel controls and IDs are preserved.

## Verification design

New regressions were observed RED before fixing changed-model retry, missing fingerprint
inputs, keyless local provider construction, late preflight publication, missing independent
role state and legacy retry availability. Endpoint-change probes never connect to network.

Visual tests use real browser DOM and the shipped CSS at 1440, 430 and 375 px widths for
settings; 1440 and 430 for the standalone production source page. They check bounds and
horizontal overflow; screenshots were inspected manually. Screenshots use synthetic state,
not a logged-in user's model configuration, and do not prove complete app workflows.

## Remaining goal scope

This is another slice, not completion of the entire audit goal. Pending major areas include
adaptation source/acceptance/coverage contracts, memory provenance, production handoff
receipt ownership and idempotency, failure-attempt usage accounting, long-input budgets,
compiler intent loss, and current user documentation. Group04 independent security review
is still absent. No "all defects fixed" or full-AA-acceptance claim is justified yet.


## Review corrections

- Backend reviewer reproduced activation lock contention that could delay unrelated
  cancellation, and a retry-to-new-active-job deduplication bypass. Both got failing
  regression tests. Generation now enters a nonblocking model-configuration guard
  before the service state lock, validates frozen identity before deduplication, and
  rejects an incompatible active generation/configuration. Follow-up found no blocker.
- Cancellation-fence exemption was narrowed to `ai_preflight`, not unrelated CG advice.
- UI reviewer reproduced an unavailable production-status request delaying all writing
  settings. It now runs independently with version fencing and a 5-second timeout;
  writing-only activation completion does not wait for it. Added hanging/timeout tests.
- Model-role status and endpoint text colors were darkened; actual computed contrast
  tests require >=4.5:1. Reviewer calculated 6.06:1 and 5.64:1 for the final colors.
- Mobile settings navigation now occupies one horizontally scrollable row, with layout
  regression checks; reduced-motion also disables the dialog root's legacy transition.

## Validation history (do not collapse failed runs into a pass)

- First broad development run: 1 failed, 1079 passed. A manually constructed empty-output
  job fixture lacked the newly required model identity. Updated the modern-job fixture;
  legacy no-identity rejection remains separately covered.
- The next development run overlapped the UI review correction and returned 1 failed,
  1081 passed (its controller test had not yet waited for the newly independent status
  microtask). It is not accepted as verification of the final source state.
- Final-state targeted regression: **118 passed**, covering backend identity/preflight,
  local provider construction, annotation fingerprints, current controller and responsive
  layout tests. No source edits were made during that targeted run.
- Fresh broad verification is run against the committed `0721761` snapshot with an
  unchanged-source check; use its separately recorded final result, not development logs.

The repair ledger `2026-09-07-review-repair-ledger.json` explicitly retains unresolved
findings. UI snapshots in the maintainer-local output are synthetic examples, not records
of a user's real model configuration. No goal-completion claim is made in this handoff.


## Accepted final verification

Committed code `072176137b1535ad2b1577276b268205b2278743` was unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py -q`

**1084 passed, exit code 0, 543.33 seconds.** This is the accepted broad result.
Earlier development passes/failures overlap this suite and must not be added to it.

Both backend and UI scoped reviews were followed up after their findings were fixed;
no scoped blockers remained. New Python files pass formatting; all 14 changed Python
files have no new lint findings versus `b988d53`. JavaScript syntax and diff-whitespace
checks pass. Git comparison confirms standard prompt/rules and teacher/Sel source
files were not modified by these commits.

Local evidence:
- `output/autonomous-20260907/verified-regression-0721761.log` and `.json`
- `output/autonomous-20260907/verified-lint-0721761.json`
- `output/autonomous-20260907/screenshots/` (synthetic settings/production state)

The next autonomous slice should target `02-001`, `02-003`, `02-004` and the related
memory-source validation before broadening feature scope. Keep the ledger current and
retain the known limitations of each accepted fix. Main remains unmerged.
