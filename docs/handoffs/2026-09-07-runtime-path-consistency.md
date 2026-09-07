# Runtime settings and effective paths —06-F11/06-F12

Local repair branch `codex/1.0-autonomous-hardening-ui`, baseline `c5dd9c4`.
No main merge, push, release, 1.1 edits, paid model calls or real AA/Spine execution.
Standard prompts, teacher identity and selection contracts are unchanged by this slice.

## Behavior

- Spine's selected path, actual renderer argument, capability and settings display use
  one descriptor. An explicitly saved path wins environment/legacy discovery. A missing
  saved path is visible but fails closed; it never silently runs another executable.
  Clearing removes the saved choice and reports the actual fallback path/source.
- File existence is all that is verified; a displayed available CLI is not evidence of
  an executable's authenticity, license, compatibility or successful real rendering.
- Existing fallback config merging stays intact: first config key wins, even if its
  file is missing. Characterization tests cover this; see the runtime-path plan.
- AA startup settings remain authoritative on restart. Adopting B while startup A is
  configured switches the current service to B and saves B, while disclosing restart A.
  Current/saved/startup/source/restart fields distinguish these states. Invalid saved
  workspaces are retained as saved selections but not falsely predicted as restart
  targets if startup would reject them.

## Test-isolation incident and correction

A production-only pytest invocation selected the production pyproject as its root;
parent `services/halocue/conftest.py` was not loaded. The old production settings
fixture then used the repository as its legacy-data root. A new runtime-path test
created repository `aa_config.json` containing only a synthetic temporary Spine path.

The first warning suspected overwrite; investigation corrected that conclusion:
creation and modification times both matched the test at 2026-09-07 20:57:35 and an
older thread directory listing contained no aa_config.json. Available evidence
indicates a newly test-created file, not an overwritten preexisting configuration.
The exact synthetic file was moved, not deleted, to maintainer-local evidence
`<WORKSPACE>/output/autonomous-20260907/incident-new-aa-config-205735.json`; relevant
history excerpts are adjacent. No legacy config was copied in as a guessed restore.
Repository aa_config.json is absent after the corrective focused tests.

Shared test fixtures now live in `services/halocue/_test_support.py` and are imported
by both parent and standalone production/integrated child conftests. Production's
settings fixture explicitly depends on the temporary legacy root. Writing tests retain
lazy isolation setup and don't create unrelated fixture directories. The previous
pre-91663f5 catalog caveat still applies: no before-hash proves repository aa_assets.db
unchanged by those older tests; this correction cannot retroactively prove that.

## Verification so far (overlapping counts, do not add)

- Initial runtime-path RED: five mismatches, then five passed after backend change.
- Production standalone default-fixture isolation regression failed before fixture
  correction, then passed. Standalone integrated suite: 22 passed, 32.20s.
- Standalone production fixture: 1 passed, 0.11s. Combined production fixture plus
  integrated lifecycle: 2 passed, 2.54s. Repository aa_config.json remained absent.
- Invalid saved AA restart target: 1 RED, corrected with constructor validation.
- Whitespace-padded fallback provenance: 3 RED, corrected with normalized comparisons.
- Latest backend runtime-path suite including config-priority characterization:
  17 passed, 0.75s. Runtime/UI/custom-asset/HTTP focused suite earlier: 67 passed,
  19.05s (before the two additional config-priority characterization cases).
- Initial UI worker's scoped DOM tests: 14 RED/1 pass, then 18 passed. Independent
  runtime/UI combined run: 30 passed before subsequent provenance tests. Scoped UI
  review identified two additional disclosure gaps; fixes and final evidence pending.
- Backend review found restart validation/provenance normalization issues; addressed
  with the RED tests above. Final review and immutable-source broad regression pending.

The overall autonomous repair goal remains active; this handoff is not full product
acceptance. Real licensed Spine/AA playback is still outside synthetic verification.


## Scoped review closure and committed focused verification

Source commit: `459f3f24d4faf120ab0564fad3c469172cadd394` (local only).
Backend reviewer accepted the saved-AA validation and normalized Spine provenance
corrections. UI review caught contradictory active/candidate headlines and loss of
restart disclosure on Writing reinspection. Both were fixed with another RED cycle
(6 failed, 19 passed), then 25 DOM tests passed. Reviewer independently reran seven
relevant cases and found no remaining blockers. Writing's invalid-adoption guard is
also covered. These tests run extracted shipping JS against real DOM with synthetic
API responses; they are not full live-application/Spine execution evidence.

Final precommit focused command:

```text
python -X utf8 -m pytest services/halocue/production/tests/test_runtime_paths.py services/halocue/production/tests/test_runtime_path_ui.py services/halocue/production/tests/test_custom_asset_library.py services/halocue/production/tests/test_http_api.py -q
```

Result: **76 passed, 19.94s**. Ruff check passed on changed backend/fixture/new-test
Python files; both production/writing JavaScript passed `node --check`; Git diff check
passed. Existing large service formatting was not globally rewritten. Full committed
regression is running against the immutable source commit above; no source is edited
while that run is active. Subsequent record below supplies its actual result.


### First immutable-source broad run found one stale contract assertion

`459f3f24d4faf120ab0564fad3c469172cadd394`: **1 failed, 1778 passed,
615.06s**. The only failure was `test_aa_workspace_configuration_persists_and_enables_capabilities`,
which expected exact equality to the old three-field AA descriptor. The original three
values still matched; the six new provenance/restart fields caused the assertion to
fail. Commit `88c29cb` explicitly asserts all nine fields (does not weaken this to a
subset check). Runtime/UI plus that test: **43 passed, 6.08s**. This failed broad run
is retained as evidence, not described as a green regression. A fresh combined broad
run after the idle-poll slice will supply the accepted immutable-source result.


## Accepted combined immutable-source regression

Commit **1c5af693f133e6f1f304516e1c9681afe327e55f** stayed unchanged throughout the run
(HEAD plus hashes of tracked non-document files checked before/after). Result:
**1788 passed in 585.29s**, exit 0; wrapper elapsed 586.52s. This count includes
runtime-path fixes, the updated exact descriptor assertion, idle-poll regressions,
all writing/production/integrated suites and selected compiler/prompt/reaction/teacher
compatibility coverage. Counts above overlap and must not be added together.

```text
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/production/tests services/halocue/integrated/tests tests/test_direction_profiles.py tests/test_conservative_annotation.py tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_balanced_direction_prompt.py tests/test_terminal_directive_diagnostics.py tests/test_compiler_face_ids.py tests/test_script_commands.py tests/test_diagnostics.py tests/test_document_golden.py tests/test_official_style_direction_e2e.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py tests/test_annotation_constraints.py tests/test_annotation_protocol.py tests/test_reaction_placement.py tests/test_reaction_integrity.py tests/test_annotation_speaker_order.py tests/test_listener_policy_diagnostics.py tests/test_director_policy.py -q
```

Maintainer-local evidence: `<WORKSPACE>/output/autonomous-20260907/verified-regression-1c5af69.log`
and its adjacent JSON command/SHA/stability record. The previous failed run at459f3f2
is retained alongside it. Repository aa_config.json remains absent. This is synthetic
engineering regression, not real AA/Spine playback or proof all review findings closed.
