# Compiler resource consumption and prefix diagnostics — working draft

Face commit a8635f5 on autonomous1.0 branch, baseline57646a3. No main merge/push/1.1.

03-D02: res_lookup separates exact canonical face IDs from casefold label aliases
within the current character identifier. resolve_face uses canonical ID first,
legacy1–2digit normalization next, then labels. Canonical IDs cannot be shadowed by
an alias; arbitrary unregistered nonnumeric tokens remain warnings. No annotation
allowlist/evidence/teacher/Sel/prompt change. A registered canonical"7" stays"7";
otherwise legacy"7" still pads to"07". No representation is added to AA output.

TDD:4 failures before fix (S2_01 compiled00,no-label ID,casefold alias,collision),
then14 new tests pass. Evidence guard→render→parse→build verifies S2_01 consumption,
context_inferred/unknown remain rejected.158 root compiler/script-command/face scope/
semantic catalog/annotation protocol/official-style/diagnostics tests passed2.04s.
Reviewer reran14 tests and34 in-memory probes;366 numeric baseline comparisons
matched fallback values/warnings. No scoped blockers. New test lint/format and
baseline-relative compiler lint pass. Existing source-line warnings retained;
03-D01 target reaction loss and03-D03 terminal-prefix errors are separate scopes.

03-D03 work is delegated to agent01a07b8b-f66c-7ba1-952f-76fbbd58525f (Harvey),
write scope diagnostics.py,optional document.py,production legacy_adapter preflight,
new terminal tests; do not overlap until returned. Plan already local untracked.
No final combined immutable regression yet for compiler batch. Latest accepted broad
settings/input snapshot is87464e5 with1397 passes; not reused as compiler proof.


03-D03 implementation adds shared dir.unconsumed error checks for21 actual Pending
prefix command kinds, not persistent scene/camera_hold commands. Each occurrence
gets its original line, flushed at EOF/scene/separator unless consumed by a valid
compile_document dialogue event. No mutation or standalone event added. Static
preflight calls the same helper cast-free, normal draft compile uses current cast;
existing error→card/source identity mapping and blocking gates are reused.

Implementer corrected RED36failed31passed (after a fixture-only missing enums
correction),GREEN67passed,focused79passed. Main combined1failed199passed found an
old preflight expectation listing only unknown/missing-arg; now explicitly asserts
additional dir.unconsumed at line4. Combined200passed11.37s. New tests verify a
persisted/stale ready_to_compile run cannot bypass current blocking diagnostics.
Root CLI parse still returns events and warns; this patch does not claim every
legacy caller independently refuses build, only existing structured review gates.

Terminal reviewer pending. No final combined regression/whole-goal completion yet.


## Accepted final review and verification

03-D03 code committed dba22d7. Reviewer independently68 new/gate cases passed1.00s,
no blockers. Full fixed snapshot dba22d77f748372712b8d8e1845966444b466ec6 unchanged:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py -q`

**1629 passed, exit code0,578.94 seconds.** Tracked hashes before/after identical.
This suite adds root compiler/safety tests to the previous service selection; counts
must not be described as only new tests or added to earlier overlapping results.
Seven changed Python files have no new lint versus57646a3. No standard prompt/rules
or teacher/Sel production file modified. Real AA playback still not done.

Local evidence: workspace-level output/autonomous-20260907/verified-regression-dba22d7.log
and.json; verified-lint-dba22d7.json. Code and exact command above are collaborator-
portable references, local outputs are not required prerequisites.

03-D02 fixed in bounded canonical-ID consumption scope; invalid-ID existing warnings
retained, no new general structured-invalid-face catalog.03-D03 fixed for shared
diagnostics/static preflight/current production review/compile gates. Raw legacy
callers that intentionally bypass diagnostics are not given new standalone-event or
global strict-build behavior.03-D01 reaction target visibility remains open, now
synthetically reproduced. Other ledger items and whole goal remain active.
