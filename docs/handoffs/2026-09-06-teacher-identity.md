# Teacher identity handoff

- Kind: handoff
- Status: implementation and automated validation complete; awaiting PR review
- Observed: 2026-09-06
- Scope: HaloCue 1.0 production and AA compatibility
- Issue: https://github.com/Suciko/HaloCue/issues/34
- PR: https://github.com/Suciko/HaloCue/pull/35
- Branch: `codex/1.0-teacher-identity`
- Base: `codex/1.0-conservative-direction` at `a967a91267690163954bce5e84d5049b7c704045`
- Dependency: PR #33 is still open; this is a separate stacked slice.
- Governing records: product direction, backend context, ADR-0001/0004/0006,
  remote-collaboration protocol and the accepted Issue #34.

## Delivered Contract

The existing cast-bindings operation accepts `mapping.kind=teacher` with
`schema_version=teacher-identity/1.0` and `preset_id`. The four preset IDs are
`sensei_shale`, `sensei_xialai`, `teacher_shale`, `teacher_xialai`; `custom`
also accepts `display_name` (required) and `organization` (empty allowed).
Preset display values are exactly sensei/沙勒, sensei/夏莱, 老师/沙勒, 老师/夏莱.

The draft's cast configuration owns one `teacher_identity` record with
`schema_version`, `character_id`, `preset_id`, `display_name`, `organization`.
The server allocates `hc-teacher-<32 hexadecimal digits>` once. Source speaker
keys remain unchanged. Explicit aliases share a `kind=voice, role=teacher`
mapping and the same ID/name/club. Frozen resources contain the corresponding
no-portrait character declaration before generation. Ordinary voice roles are
not implicitly promoted to teacher identities.

This is an additive compatibility contract. No writing revisions, releases,
teacher Sel nodes, prompt policies or document import are changed. AA binaries,
assets, installation and paid model calls are not prerequisites for preparation.

## Agreed Test Boundaries

Teacher selection/read/restart through production APIs; optimistic versions and
atomic draft changes; compiler and BuildBundle input/output; explicit isolated
installation; real-browser preset and custom-name controls. Use synthetic
fixtures, not user source documents or real game resources.

## Baseline

On the unchanged base: production tests plus generator assets, script commands,
draft store and draft versions: 232 passed (59.54 seconds). Existing full-suite
baseline and environment limitations are recorded in the preceding conservative
direction handoff. Final results and remaining limits are recorded below.

## Implementation

- Root identity/store: `teacher_identity.py`, `teacher_identity_store.py`,
  `draft_store.py`. One identity per draft; four exact presets plus custom;
  explicit source aliases; ID reuse; no-op preservation; optimistic conflict;
  fixed-file atomic writes and checksummed rollback journal.
- Export/install: `script2aap.py`, `install_manager.py`. Validate no-portrait
  ownership from frozen resources, emit AA CharacterOverrides and slot 0, reject
  portrait collisions, preserve intentionally empty organizations, and leave
  generic voice/custom-portrait behavior intact.
- Production: `legacy_adapter.py`, `service.py`. Existing cast-bindings route,
  capability fallback, teacher resource metadata, preview name/organization,
  stable errors, CG alias preservation and late-result invalidation. Compile
  output is isolated per build to prevent same-project output contamination.
- Workbench: `ui/index.html`, `ui/app.js`, `ui/app.css`. Explicit creation/save,
  preset/custom fields, alias-change confirmation, stale-version form retention,
  no-portrait search exclusion and read-only teacher organization preview.
- A real-HTTP check found the existing direction-profile stylesheet missing from
  the static allowlist. `app.py` now serves that existing file; the HTTP asset
  test covers it. No new stylesheet or embed registration was needed.
- Documentation: this handoff, root README, production README, and the backend
  context glossary distinguish Teacher Identity from a source speaker, ordinary
  voice role, and render slot.

## Compatibility And Recovery

The request is additive to the existing API. Persisted cast rows remain
`kind=voice` plus `role=teacher`; public teacher selections use `kind=teacher`.
There is no SQLite migration, new endpoint, runtime dependency, writing release
mutation, or automatic migration of old voice mappings. A matching no-op retains
review/build claims. Real changes invalidate claims and supersede pending jobs.

Teacher preparation writes cast/resources/identity/diagnostics/session together.
An interrupted write restores the before-images when DraftStore next acquires
the draft lock. Corrupt recovery data blocks writes instead of rebuilding it.
Tests include a child process exiting during replacement and a fresh store
recovering the draft, fault injection at each file boundary, concurrent CAS,
path traversal and hash corruption. Directory-sync failure after journal removal
reports `teacher_identity_durability_uncertain`: reload before retrying; it does
not falsely claim rollback. Windows flushes file contents but does not use POSIX
directory fsync. This is not a claim of hardware power-loss durability or support
for multiple independent service processes writing the same data directory.

Old BuildBundles are immutable, and both ordinary dialogue and CG preserve the
teacher ID. A synthetic release -> teacher -> review -> job -> BuildBundle ->
explicit isolated install test checks these properties and unchanged releases.
Five visible portrait slots plus teacher slot 0 are verified in generated AAP
data, not inferred from the card-preview UI.

## Final Validation

| Suite | Baseline | Final |
| --- | --- | --- |
| Production | 179 passed | 202 passed |
| Writing | 641 passed | 641 passed |
| Integrated | 13 passed | 13 passed |
| Root | 1487 passed, 1 failed, 26 setup errors | 1589 passed, same 1 failure and 26 setup errors |

Root retains the same 10 skips and five private-AA exclusions. The final JUnit
failure/error identity set was compared with the preceding delivery: 27 before,
27 after, zero new failures. The release-workflow literal assertion and missing
Playwright Chromium remain pre-existing limitations, not passing tests.

New test files: root `test_teacher_identity.py`, `test_teacher_store.py`,
`test_teacher_export.py`; production `test_teacher_identity_service.py`,
`test_teacher_identity_delivery.py`, `test_teacher_identity_ui.py`. Together they
add 125 passing cases. Updated existing HTTP and compile-probe tests check the
stylesheet and isolated output location. Root teacher-only rerun: 102 passed.

The 13 new browser cases use installed Edge, including real ProductionService
HTTP (no request interception) with a service restart, identity reuse and name/
organization preview. Synthetic screenshot checks cover widths 1280/390/320.
No real model, paid API, private source text, AA installation, Spine, game assets
or packaged release was used. Native AA playback is still manual acceptance.
The standalone UI still probes a writing endpoint that can return an existing
404; these checks assert no uncaught JavaScript exceptions, not a globally clean
browser Console. Screenshots/logs remain local artifacts, not public repo inputs.

Commands (existing development dependencies; on this machine the installed Edge
channel is selected through `HALOCUE_TEST_BROWSER_CHANNEL=msedge`):

```text
python -X utf8 -m pytest services/halocue/production/tests -q
python -X utf8 -m pytest services/halocue/writing/tests services/halocue/integrated/tests -q
python -X utf8 -m pytest tests/test_teacher_identity.py tests/test_teacher_store.py tests/test_teacher_export.py -q
python -X utf8 -m pytest tests -q -ra --tb=short -k "not test_real_cache_contains_known_flatdata_bundle and not test_reads_traditional_name_and_native_id_from_real_character_table and not test_locates_character_table_bundle_from_the_addressables_catalog and not test_matches_observed_native_variant_id_to_its_traditional_label and not test_build_index_harvests_official_native_records_with_observed_variant_ids"
node --check services/halocue/production/ui/app.js
git diff --check
```

Changed Python files pass Ruff except `script2aap.py`, whose six existing
diagnostics were compared with base `a967a91` and are unchanged. New Python files
pass Ruff formatting. Existing large files were not bulk reformatted. No
TypeScript/Rust source changed, so their build suites were not run for this slice.

## Delivery And Next Action

Code commits:

- `deb1e26`: persistent identity, atomic recovery, AA export/install and root tests.
- `67da142`: existing direction-profile stylesheet HTTP allowlist fix.
- `ffbd965`: production API, presets UI, preview and service/browser tests.

Git HTTPS repeatedly reset the connection. The GitHub Git Data API uploaded
the same blobs/trees/commits and verified every SHA against local Git objects;
no alternate history or force update was used. The code tip on GitHub was
independently read back as `ffbd965719e736867a4c40c9b14e5fda47cea8fe` before this
documentation follow-up. The upload helper and local synthetic preview data
are outside the repository and are not part of the delivered product.

This branch is stacked on PR #33, targeting `codex/1.0-conservative-direction`.
Review it in dependency order; do not merge it directly into main or duplicate
the base commits. No shared branch was automatically merged.

Next accepted slice: choose between the prepared slot-zero teacher and a
single-response Sel node. It needs its own issue/branch/tests; it is not part of
this delivery. DOCX/XLSX production imports remain a later slice. No new product
decision is required for the delivered identity presets.
