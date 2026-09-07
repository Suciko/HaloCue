# Canonical scene adoption and legacy promotion —02-007 slice B

Baseline4ba7dd3; source commit `45d000d61af9e46d4437326e810131a30cf56630` on
local `codex/1.0-autonomous-hardening-ui`. No main merge/push/release, 1.1 edits,
standard director-prompt/rule/teacher/Sel changes, real model or AA/Spine execution.

## Canonical path

- New adaptation acceptance writes only ordinary `scene_script` / `scene-blocks/1.0`
  revisions. It no longer creates a parallel authoritative adaptation_manuscript.
  The pending candidate remains a proposal/audit record, not a second editable truth.
- A shared target resolver is used by synchronous generation, durable queue pins,
  pre-call/post-call validation and acceptance. Candidates disclose the target chapter,
  whether a new scene will be created, the mapped scene and base revision.
- The first candidate defaults to the work's first structurally ordered chapter and
  pins that selection for review. Acceptance cannot redirect to an unrelated scene or
  a different chapter. Missing/reordered targets must be resolved before a new candidate.
  The forthcoming UI must display this target, not imply arbitrary target choice ships.
- Adoption associates the adaptation chapter with its new scene in durable dependency
  metadata. Regeneration then pins the mapped scene's current revision; manual edits,
  a new accepted candidate or target deletion prevent stale overwrite. Scene mode
  inherits the verified work brief rather than hardcoding every adoption to bond_short.
- Acceptance checks exact source references, source/adaptation chapter+version binding,
  proposal/base/target/current work version, then creates scene/revision/association
  and decision in one database transaction. Structure recording, memory maintenance
  and commit projections use the existing scene pipeline; normal review gates remain.
- Canonical blocks and text are normalized with the existing shared renderer. Original
  candidate bytes/hash remain in the proposal record, source refs in revision provenance,
  and `normalization_changed_text` reports formatting differences instead of pretending
  raw input and canonical rendering are always identical.

## Explicit legacy promotion / compatibility

`POST /api/v1/works/{work}/adaptations/{adaptation}/chapters/{sourceChapter}/manuscript:promote`
requires `expected_version`, `expected_revision_id` and an explicit owned
`target_chapter_id`. It verifies the existing accepted legacy artifact/current source,
creates a normal scene revision, and retains the original artifact pointer/bytes/hash.
A matching durable receipt makes a network retry return the prior result without a
second scene/revision, even though the original expected work version is now stale.
Different target/revision requests cannot reuse that receipt to overwrite another scene.
Startup never silently promotes old artifacts.

Old pending candidates without target metadata require explicit target confirmation.
Previous-slice queued snapshots lacking target fail closed with non-retryable
`adaptation_target_confirmation_required`; the user must issue a fresh generation,
not endlessly retry an unpinned snapshot. New input snapshots use
`adaptation-agent-input/1.1`; this is internal schema versioning, not work in the1.1
product branch. Shared model identity/cancellation/lease guards remain in effect.

## Tests and scoped review

- Initial5 REDs proved missing target preview, orphan acceptance, absent manual-edit
  fencing, absent target-deletion rejection and arbitrary payload target ignored.
- Writing-mode regression failed then inherited verified brief mode correctly.
- Legacy promotion2 REDs → explicit promotion/replay preserving old bytes and hash.
- Scoped reviewer identified canonical-text disagreement and old unpinned jobs being
  advertised retryable. Both reproduced (2 REDs), then fixed; reviewer closure accepted.
- A valid other-chapter quote/evidence with wrong adaptation scope was initially
  accepted. A new RED and scope-binding checks prevent this before any scene write.
- Two concurrent approvals produce exactly one ordinary scene/revision. HTTP promotion
  verifies the shipping route, not only an internal method.
- An existing test fixture initially supplied an invalid manual block ID, then used a
  stale work version after supersession recorded a decision. Fixed the fixture/refresh,
  not the product's validation or version checks.
- Combined writing/integrated tests exposed an ambiguous bare `test_http_api` import
  (production/writing have different helper shapes). New tests use local stdlib HTTP
  requests; the prior adaptation-dispatch tests now do likewise. No product behavior
  was weakened to fit the conflicting helper.

## Integrated release proof

`integrated/tests/test_adaptation_scene_handoff.py` uses temporary source prose,
synthetic rule files/provider, isolated production data and real loopback services.
It creates normal brief/blueprint prerequisites, generates and adopts a source-bound
candidate, performs ordinary scene review, explicit memory-maintenance skip,
continuity review and release review, freezes the normal scene set, then sends the
release through the actual Production HTTP handoff. It checks revision inclusion,
frozen dialogue text, retained source refs, upstream release identity and production
draft dialogue. No gate is bypassed and no AA rendering/binary runs.

The first fixture omitted brief/blueprint and correctly hit context_incomplete; those
normal prerequisites are now explicit. It also initially guessed incorrect internal
field names, corrected after inspecting source. The freeze API includes the ordinary
scene set, not a new selected-scene endpoint; plans were corrected to avoid inventing
that feature. UI integration must handle these real prerequisites coherently.

Focused evidence (overlapping):8 adoption tests passed6.58s earlier; final new adoption
plus integrated14passed12.64s; broader dispatch/adoption/integrity/integrated71passed
49.52s. Changed files pass Ruff; large service baseline3 issues has zero new issues;
HTTP baseline0/no new. Scoped reviewer found no remaining blocker after corrections.
The final fixed-source broad regression is running on45d000d; append its actual outcome
below when complete. 02-007 stays partial until sliceC shipping UI is implemented and
verified end-to-end. Overall goal, full usage/input bounds and real playback remain open.


## Accepted final immutable-source regression

**45d000d61af9e46d4437326e810131a30cf56630** stayed unchanged throughout, verified by HEAD
and tracked non-document file hashes. **1846 passed in833.72s**, exit0; wrapper835.07s.
Focused/earlier totals above overlap with this run and must not be added together.

```text
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q
```

Maintainer-local evidence: `<WORKSPACE>/output/autonomous-20260907/verified-regression-45d000d.log`
and adjacent JSON command/SHA/stability record. Source and tests are local only;
main remains58d1128 and was not merged, pushed or released. Repository aa_config.json
remains absent. Existing untracked scratch/tmp directories were preserved.

02-007 is now partially mitigated by the real canonical backend and synthetic normal
freeze/Production handoff trace. The ordinary TXT/DOCX UI still goes through its older
manual-chat route; do not call the entire import experience finished. Next slice is
`docs/superpowers/plans/2026-09-07-adaptation-import-ui.md`, with actual API constraints,
paper/ink/green workbench styling, reload/cancel/retry/target review and browser gates.
No real literary/model quality, packaged-runtime or AA playback acceptance is implied.
