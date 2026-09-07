# Reaction visibility and compiled intent —2026-09-07 (draft)

Baseline90290a7; autonomous1.0 branch. No main merge/push/1.1 edits.

03-D01: each validated inserted reaction uses one-line @camera target, not a persistent
hold. The next authored dialogue keeps its original hold. Before reactions are inserted
before the first unconsumed authored prefix since the last dialogue/scene boundary,
leaving original source prefix ordering/ownership intact. No authored camera is overwritten
and no wait/fx is silently consumed by the inserted reaction. Multiple targets, five-slot
holds, before/after,scene boundary tests cover actual compiled output and unchanged words.

Reaction sidecar holds stable beat_id/anchor_id/source_line/output_line and zero-based
compiled_index. Production augments source_card_id/source_id and persists audit metadata,
not AA ScriptData. Pure validator compiles only when reactions exist, verifies per-scene
line/event/row mapping, exact empty target dialogue, unique visible portrait slot, requested
indexed face/emo/action and exactly-one positive wait. No normal offscreen/narrator/teacher
visibility restriction. Failure raises source-located reaction_intent_lost before output
write; production maps409 with diagnostics and leaves original draft unchanged.

Local integration uncovered existing portrait-binding mismatch: kind=portrait was saved
without legacy portrait/narrator flags, so compiler/model guards considered it nonportrait.
Actual pipeline failed; two dedicated flag regressions then failed. Normalization now sets
portrait=True,narrator=False only in the explicit portrait branch. Teacher/voice/narrator
branches unchanged. Real synthetic annotation→staging→draft commit now preserves three
authored lines plus one empty reaction and original sourcecard mapping.

TDD RED placement4 failures, pipeline missing sidecar1 failure, lost-output corruption
blocked after validation, backend error/audit2 failures,sourcecard audit1 failure,portrait
flags2 failures. Validator implementer59 RED,63 dedicated GREEN. Main latest combined
373passed22.51s across reaction/annotation/prompt and productionservice/direction/teacher
regressions. Counts overlap; no immutable broad result yet. Scoped reviewer pending.

Limits: sidecar proof pins the generated candidate, not any later intentional author edit.
Existing job cancellation/generation fencing remains the publication owner. No standalone
timeline, real model, realAA playback or general literary acceptance is implied. Other
ledger findings remain active;03-C01 fresh listener policy is not automatically fixed.


## Scoped review correction

Reviewer found standalone @trans was not included in Pending but is consumed/reset
on one dialogue. Before-beat insertion therefore stole authored anchor transition.
A real compiled-row test failed (reaction1,anchor0); placement now uses Pending command
set plus trans locally, preserving first0/reaction0/anchor1. Shared terminal diagnostic
exemptions unchanged in this slice. Reviewer independently verified correction and
reported no remaining scoped findings. Final focused374 passed22.82s.

Code committed4d01195. New helper/tests format/lint clean; annotate/adapter no new lint.
Sidecar validator covers accepted generation output; intentional later author edits
are not forever constrained by old sidecars. Existing invalid portrait bindings that
were stored before this repair may require explicit reselection; this does not rewrite
all stored cast files. Current portrait selections now persist correct compiler flags.
A fresh immutable broad regression on4d01195 is running; result not yet accepted.


## Accepted immutable verification

Commit4d0119558c3a15b65520660a146954bf02475a03 stayed unchanged throughout:

`python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py -q`

**1709 passed, exit code0,642.23 seconds.** Tracked hashes before/after identical.
Overlapping focused tests must not be added. Isolated production data roots retained;
no real model/AA playback. Evidence: workspace output/autonomous-20260907/
verified-regression-4d01195.log and.json; reaction-lint.json.

03-D01 is fixed within generated reaction placement/validation/publication scope.
Reviewer transition correction is included. This does not claim literary approval,
new standalone event behavior, later author edits revalidated against obsolete sidecars,
or whole autonomous-goal completion. Fresh-listener policy03-C01, accounting, adaptation
lifecycle/UI and documentation remain on the ledger. Stable speaker assembly05-007
is now reproduced across four hash seeds but not fixed in this commit.
