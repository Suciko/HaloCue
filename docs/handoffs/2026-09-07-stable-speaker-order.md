# Stable prompt speaker ordering —2026-09-07

Code95a11fd, autonomous1.0 branch.05-007 fixed set tie ordering by counting per display
name once, stable descending-frequency sort retaining first source occurrence on ties,
then existing characterID dedup. Higher-frequency alias priority retained;equal aliases
use first source mention. No Unicode spelling normalization. Standard rules/build_static
unchanged; run fingerprint adds speaker_order_version=frequency-first-mention/1 so old
checkpoint assembly can't masquerade as new input.

RED subprocess seeds1..4 produced4static hashes for same six speakers. GREEN tests
capture full annotate static+fingerprint with fake agent across seeds, reversedcast
insertion, ASCII,Unicode and alias samples; expected representative order asserted.
4newtests pass.135focused prompt/agent/checkpoint/service direction tests passed9.69s.
Reviewer independently4tests passed3.75s and found no scoped blocker. No remote cache
hit/cost/literary or real-provider benefit was measured. Final broad run on95a11fd is
pending; prior1709tests are not proof for this new assembly change.

## Accepted final regression

Commit95a11fd06e632536236f1e3335d8b4f709e3f83c unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py -q`

**1713 passed, exit code0,593.47seconds.** Tracked hashes match before/after.
Local evidence: workspaceoutput/autonomous-20260907/verified-regression-95a11fd.log
and.json. Overlapping focused counts not additive. No real provider/AA playback.
Overall goal remains active.
