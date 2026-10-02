# HTTP objects and preference validation — 2026-09-07

Commit85125a1, autonomous1.0 branch. No main merge/push/release/1.1 changes.

01-009: Writing HTTP bodies must decode to objects, not arrays/scalars/null. Wrong
shape or malformed/truncated UTF-8 JSON returns400 before domain writes. Content-Length
is a single nonnegative ASCII decimal, trimmed only for ASCII space/tab; duplicates,
non-ASCII whitespace, and Transfer-Encoding are rejected before reading. Existing
route limits remain; huge decimal lengths compare against the bound without huge
integer conversion. Missing/zero bodies remain{}; leading zeros remain compatible.
This is not a group04 security audit, complete HTTP hardening, or a new read deadline.

06-F09: Known preference enums/int ranges are validated; unknown keys ignored.
Missing file returns defaults. Invalid stored JSON/types/known values produce an
observable error, without silently resetting or overwriting the original. Atomic
same-directory replace and same-instance RLock protect partial updates; no general
cross-process or power-loss durability claim. Readonly inactive controls stay readonly.
Load failures clear stale displayed values and show fixed Chinese warnings without
blocking unrelated model settings. No real model/credential settings code changed.

TDD: HTTP initial16 failed/6 passed; reviewer found non-ASCII whitespace stripped
before validation. Wire-parser guarded-read tests reproduced2 failures, corrected
with ASCII trim, then32 HTTP contract tests passed. Reviewer reran6 related tests.
Store initial134 failed/18 passed;4 Node controller failures;additional3 filesystem
fault failures. Implementer196 focused passed, reviewer160 store/controller passed.
Main combined322 passed64.30s, then2 added HTTP preference integration tests passed.
All counts overlap. Five changed Python files lint clean; new tests formatted;JS
syntax/diff whitespace checks pass. Reviewers reported no scoped blockers after
corrections. Final broad verification on stable commit85125a1 is recorded separately.

Not claimed: real AA playback, real provider quality, independent security audit,
activation of reserved preferences, whole maintenance goal completion. Future work
still includes compiler semantic losses, adaptation lifecycle/UI, usage accounting,
entrypoint/docs alignment and other ledger findings.


## Broad run correction

The unchanged85125a1 broad run returned128 failed/1269 passed. All128 failures were
preference tests asserting their temporary directory contained only the expected
store files: shared service fixture eagerly requested isolated_legacy_root even for
writing tests, leaving an unrelated test directory. Product validation/error assertions
passed. Reproduced with a two-context narrow invocation (1failed/1passed).

Commit87464e5 lazily requests the isolated legacy fixture only after confirming
production/integrated context. Writing cleanup assertions are not weakened. Combined
store+production admission+integrated recovery then173 passed30.09s. A fresh broad
run targets87464e5; do not treat the initial broad run as passed or conflate scopes.


## Accepted broad verification

Commit87464e5d70fe56d82e1bb53aaa5dfc5a3a87d3a6 was unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py -q`

**1397 passed, exit code0,576.60 seconds.** Tracked-file hashes before/after match.
This is the accepted final result; earlier failing/overlapping runs are not additive.
Local evidence at workspace-level output/autonomous-20260907/verified-regression-87464e5.log
and.json; input-settings-lint.json records lint checks. No real-model or AA playback
acceptance. Goal remains active; next bounded compiler face-ID defect has a synthetic
RED probe (S2_01 becomes00, while label/numeric controls pass) but is not fixed yet.
