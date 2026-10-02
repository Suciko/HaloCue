# Fresh model camera rejection feedback —03-C01

Baseline9201ef2. Existing standard prompt requires ordinary portrait speakers visible,
listener focus shared shot; user prohibited changing those prompt semantics. This fix
preserves existing normalization fallback rather than silently permitting offscreen
portrait dialogue. New fresh-camera tracking before redundancy removal distinguishes
requested listener-only camera from inherited stale holds. Rejected fresh camera
records before-value in postprocessor proposal and sourceid/line warning explaining
sharedshot/reaction/manual alternatives. No rendering policy or standard text changed.

TDD2failures before,6new tests pass.125policy/officiale2e/golden/reaction tests pass.
Bond e2e now asserts normal source speaker visible and matching located rejection,
not only camera command existence.48synthetic baseline/current combinations of
visibility/portrait/manual/fresh flags yielded byte-identical rendered scripts; only
diagnostics/proposal metadata differ. Baseline-relative lint/diff checks pass.

This is a documented restriction/rejection path, not support for AI listener-only
ordinary dialogue. Manual camera and validated independent reaction nodes stay valid.
No paid model,realdata,AAplayback or whole-goal completion. Scoped review/broad final
verification pending. Local evidence listener-render-compat.json records48comparisons.

## Accepted scoped review and broad regression

Reviewer found no blockers in fresh/repeated/inherited/manual feedback behavior.
Commitdb0e8faf91e988a13be27c64becdd99621ea7776 unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q`

**1737 passed, exitcode0,640.51seconds.** Tracked hashes match before/after.
Local evidence workspaceoutput/autonomous-20260907/verified-regression-db0e8fa.log
and.json; listener-render-compat.json. Existing standard rules/prompt source unmodified.
No real provider/AAplayback or full-goal completion; ledger remains active.
