# Conservative production direction handoff

- Kind: handoff
- Status: implementation and automated validation complete; awaiting PR review
- Observed: 2026-09-06
- Scope: HaloCue 1.0 production backend and root annotation compatibility
- Issue: https://github.com/Suciko/HaloCue/issues/32
- PR: https://github.com/Suciko/HaloCue/pull/33
- Branch: `codex/1.0-conservative-direction`
- PR target: `feature/1.0-adaptation-workflow`
- Pushed code tip: `917563af6456786ff0aff518d4d68a8b2ef1a25f`
- Base: `feature/1.0-adaptation-workflow` at `3189300c83c8291bc19e9ab52ac66d5bf8d4e33e`
- Source of truth: `docs/product-direction-1.x.md`, `contexts/backend/CONTEXT.md`,
  ADR-0001, ADR-0004, ADR-0006, and the maintainer-approved scope in Issue #32.

## Slice

Keep Standard (original) behavior and add Conservative direction. Reuse frozen
expression labels, choose available backgrounds without image generation, and
freeze the selected profile and rules identity across generation and recovery.
Omitted legacy API options remain Standard; new UI imports choose Conservative.
Teacher identities, slot-zero preparation, Sel nodes, and DOCX/XLSX production
imports are separate accepted follow-up slices, not completed in this PR.

## Agreed test boundaries

- Prompt assembly: original fixed outputs and isolated conservative rules.
- Annotation input/output: frozen resource selection and unchanged source text.
- Production create/generate/read/retry APIs: durable settings, same-profile
  deduplication, cross-profile conflicts, restart and cancellation.
- Workbench: selecting a preset, reopening a run, and preserving a paused task.

Tests use synthetic resource data and provider doubles. No paid provider calls,
AA installation writes, proprietary bytes, or user documents are required.

## Baseline

- `python -X utf8 -m pytest tests/test_balanced_direction_prompt.py tests/test_resource_retrieval.py tests/test_annotation_constraints.py tests/test_director_policy.py -q`: 53 passed.
- Production service tests: 140 passed before edits.
- Integrated service tests: 8 passed, 1 pre-existing failure in
  `test_integrated_runtime_serves_both_workbenches_and_apis` (expected embedded
  API root replacement missing in returned JavaScript on this checkout).
- Writing baseline: 641 passed. Root baseline in an isolated checkout:
  1451 passed, 1 failed, 10 skipped, 5 deselected, 26 browser setup errors.
  The failure is the existing literal `gh release create` assertion in
  `tests/test_release_workflows.py`; the workflow uses `gh @args` instead.
  Browser setup errors are missing Chromium, not application assertions.
- The five excluded tests require a real local AA cache and are not part of
  this synthetic acceptance run. Do not use private assets to turn them green.
- The initial nested checkout inherited a parent Node `type: module` setting,
  causing 99 additional harness failures. They disappear for the same base SHA
  in a standalone checkout; no source fix or package metadata change was made.
- Direct Git fetch failed to connect; GitHub API independently confirmed the
  upstream SHA above before the short-lived branch was created. Retrying Git
  with HTTP/1.1 succeeded; no alternate repository or source archive was used.

## Changes

- `092a4fe`: original synthetic prompt snapshot, strict preset selection,
  versioned rules identity, and independent conservative rules.
- `2544c26`: available-background completion, checkpoint identity and inherited
  scene state, durable production settings/retry snapshots, error mappings,
  and generation-through-review-to-build tests without implicit installation.
- `202f78d`: source/generation preset controls, explicit regeneration,
  old-task recovery isolation, and standalone/embedded style loading.
- `917563a`: narrowly scoped Gateway CRLF normalization, required to serve the
  production workbench correctly from fresh Windows checkouts, plus four
  real-HTTP LF/CRLF tests for standalone and embedded production scripts.
- Changed implementation files: `direction_profiles.py`, `prompt.py`,
  `conservative_backgrounds.py`, `resource_retrieval.py`, `annotate.py`,
  `annotation_agent.py`, production `service.py` / `legacy_adapter.py`,
  production `ui/app.js` / `ui/index.html` / `ui/direction-profile.css`, and
  writing `web/production-embed.js` (stylesheet registration only), plus
  integrated `gateway.py` (two-line transport normalization).
- New tests: root `test_direction_profiles.py`, `test_conservative_annotation.py`,
  production `test_direction_profiles.py`, `test_direction_profile_ui.py`, and
  the synthetic `tests/fixtures/direction_profiles/standard_prompt.json`;
  integrated `test_production_script_line_endings.py`.

## Compatibility

No database migration, route rename, source release mutation, or new runtime
dependency. The API change is additive; see the Direction presets section in
`services/halocue/production/README.md` for JSON examples and error codes.
Standard prompt strings retain their baseline hashes. Existing tasks default
to Standard; new UI imports explicitly request Conservative. An external older
annotation module without preset support still offers Standard; unsupported
Conservative requests are rejected instead of breaking capabilities/imports.

The model still makes semantic face and staging choices; there is no blanket
backend face-change quota. Only background completion is deterministic. Its
label scores are retrieval signals, not calibrated model confidence. Existing
labels are reused without another vision call. Background advice is persisted
with source IDs and cannot masquerade as an approved release.

## Validation And Limits

All model requests in this delivery use provider doubles. No real key, source
document, AA bytes, Spine, or paid model run was used. Development-only
`jsonschema` (4.26.0) and `ruff` (0.12.12) were installed outside the checkout;
these already fall within `requirements-dev.txt`. Browser acceptance uses
installed Edge via `HALOCUE_TEST_BROWSER_CHANNEL=msedge`.

Actual tests and eight screenshots cover Standard/Conservative at 1280px and
390px, page/confirmation layout, new imports, reopening, pause/cancel/restart,
explicit regeneration and blocked late commits. Screenshots contain only
synthetic task data and remain local test artifacts.

The baseline Gateway CRLF defect was reproduced through real HTTP with both
line endings before the fix (2 passed, 2 failed). The fix normalizes only the
production JavaScript response before existing API/ShadowRoot rewrites. The
four cases and the formerly failing integrated runtime test now pass. It does
not move production logic into the Gateway or normalize arbitrary user files.

Regeneration annotates the current draft and preserves existing authored
directions; it does not remove previously generated directions or reset to the
original release. Real-provider quality, expense comparison and native AA
playback remain explicitly separate manual acceptance. Shorter rules are not
evidence of a particular fee reduction.

## Final Test Results

Production/root/writing suites ran from isolated fixed commit
`202f78d2cb15e0495a978774621d2bed8ea1694d`, without a parent Node package.
Integration was rerun after the Gateway-only fix at `917563a` in a fresh
Windows CRLF checkout. Results:

| Suite | Baseline | After |
| --- | --- | --- |
| Production | 140 passed | 179 passed, including 18 browser cases and one embed-style contract |
| Writing | 641 passed | 641 passed |
| Integrated | 8 passed, 1 failed | 13 passed |
| Root | 1451 passed, 1 failed, 26 setup errors | 1487 passed, same 1 failure and 26 setup errors |

Root retains 10 existing skips and the same 5 real-AA exclusions. Structured
JUnit results were compared to the fixed baseline: the root failure/error
identity set is unchanged (27 before and after, zero new failures). The
remaining release-workflow assertion and missing Chromium are documented above,
not silently skipped or described as passing. This delivery adds 79 passing
cases across the three changed test groups.

Commands (install existing `requirements-dev.txt` in an isolated environment;
select `HALOCUE_TEST_BROWSER_CHANNEL=msedge` on this Windows test machine):

```text
python -X utf8 -m pytest services/halocue/production/tests -q
python -X utf8 -m pytest services/halocue/writing/tests -q
python -X utf8 -m pytest services/halocue/integrated/tests -q
python -X utf8 -m pytest tests -q -ra --tb=short -k "not test_real_cache_contains_known_flatdata_bundle and not test_reads_traditional_name_and_native_id_from_real_character_table and not test_locates_character_table_bundle_from_the_addressables_catalog and not test_matches_observed_native_variant_id_to_its_traditional_label and not test_build_index_harvests_official_native_records_with_observed_variant_ids"
```

Ruff checks passed for all changed Python implementation/test files; format
checks passed for the new Python files. Existing large modules were not bulk
reformatted. `node --check` passed for both changed JavaScript files, and
`git diff --check` passed. Logs, JUnit XML and synthetic screenshots are local
test artifacts, not public repository inputs.

## Delivery And Next Slice

PR #33 is open against `feature/1.0-adaptation-workflow`; the four code commits
are pushed. This document and the README are a separate documentation commit
in the same PR. No code has been merged into a shared branch. Continue with teacher
identity preparation (four exact name/organization presets plus custom,
stable IDs, reusable no-portrait registration) in its own issue/branch, then
single-response Sel nodes, then DOCX/XLSX production imports. Do not describe
those follow-ups as implemented by this PR.
