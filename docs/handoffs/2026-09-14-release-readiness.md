# 1.0 release readiness — completed implementation, native playback pending

- Completed: 2026-09-15; session began 2026-09-14.
- Code commit: `ef01d8798472a62344fb466f69ea764b636a7976` (local, not pushed).
- Branch: `codex/1.0-release-readiness-20260914`, based on `41c5012e`.
- Related existing Issues: #7 (desktop workspaces), #15 (production delivery).
- Owners: backend/integrated runtime and release tooling.
- Authority: maintainer release-readiness request; product-direction-1.x,
  CONTEXT-MAP, backend context, ADR-0002/0003.
- Maintainer explicitly selected bundling publicly shareable writing rules.
- Unrelated unstaged plan deletions, scratch directories and the prior untracked
  physical-request handoff were preserved. No main merge or publication.

## Result

Default launcher opens the integrated writing/AA production interface. The old
interface is explicit `--legacy-ui`, including its existing release smoke. Frozen
service resources have an explicit layout; writable integrated state lives below
`HALOCUE_USER_DATA_DIR/integrated` or `%LOCALAPPDATA%/HaloCue/integrated`. Source
integration keeps `.halocue/integrated` when no state override is supplied.
Existing source data is not silently moved. Both service roots and the compatibility
resource database are tested with isolated directories.

The public exporter now includes the three service implementations/static resources
and the narrowly selected writing rule directory. The 16-file rule subset comes
from the previously used immutable WritingPack; no character cards, official corpus,
user drafts or assets were added. Provenance and the generic directory-example
redaction are in the rule package's PUBLIC_PACKAGE.md. All four writing modes and
teacher-present rules work without a developer environment variable.

Compatibility conversion is chosen before preflight; the API requires `use_ai: true`
for model-backed preflight. Timeout/cancellation metrics are refreshed after final
request capture. Release checkout and validation bind the requested tag to HEAD;
untagged CI uses explicit `--candidate` and cannot publish through that check alone.
The scanner recognizes the project's updater. Manuals distinguish state locations,
compatibility-only update controls and integrated manual upgrades.

Headless integrated EXE verification uses a random readiness-file token to authorize
shutdown. Normal desktop mode does not enable that endpoint. It is not a general
public shutdown API. No project/schema migration was introduced.

## Validation

Executed on Windows, Python 3.13.12:

- `python -X utf8 -m pytest -q tests`: **1896 passed, 14 skipped**, 296.83s.
  Initial run had one preflight test assuming implicit AI consent; it now opts in.
- `python -X utf8 -m pytest -q services/halocue/production/tests services/halocue/integrated/tests`:
  **349 passed**, 190.72s. Final gateway/desktop changes also have focused coverage below.
- `python -X utf8 -m pytest -q services/halocue/writing/tests`:
  **1121 passed**, 614.84s. New bundled-rule completeness and actual-EXE health are
  additionally verified after that run. No paid-provider calls were used.
- Focused desktop/annotation/preflight/workflow/gateway run: **109 passed**, 39.58s.
- Final public-doc/help tests: **7 passed**. Counts overlap focused runs; do not add them.
- Combined root/service collection: **3380 tests collected** after fixing two
  ambiguous production-test imports. Whole-tree execution was not repeated as one process.
- Public export and `tools/verify_clean_source.py`: passed without local developer files.
- `tools/check_release_version.py --tag v1.0.0 --candidate`: passed.
- Added desktop/layout/verification/test modules: Ruff passes; `git diff --check` passes.
  Existing broad lint debt in legacy webui/config remains; no blanket lint-clean claim.

## Actual packaged acceptance

Built with `tools/build_public_release.py` from the audited source export.

- `tools/verify_integrated_release.py <bundle>/HaloCue.exe --screenshots <acceptance>`:
  passed. Restricted PATH has no Python; developer HALOCUE variables removed;
  integrated writing and production HTML/JS load; bundled rules report ready;
  a created work survives two starts; authenticated clean exit removes readiness;
  program directory stays unchanged. Playwright reports no page JavaScript errors.
- `tools/verify_release.py <archive>`: passed, including the compatibility
  import/review/compile/restart flow in synthetic AA/Chinese-space paths,
  no Python on PATH and zero browser console errors.
- Inspected actual packaged writing and production screenshots.
- Finalization only replaced four manual files. Export manifests confirmed no
  executable-source, JavaScript, CSS or spec differences from the tested build.
  Final bundle scan and archive/manifest generation passed again.

Maintainer-local artifacts (not committed):

- `build/release-ready-20260915/artifacts/HaloCue-1.0.0-windows-x64.zip`
- Size: **44,690,673 bytes**.
- SHA-256: `3a3cc25312cfce9a45062f3e71a42eba78cfa2ca2ccb0460f2afafcdfd14f55b`.
- Checksum sidecar and HaloCue-build-manifest.json are adjacent.
- Source export: `build/release-ready-20260915-final/HaloCue`.
- Screenshots/logs: `build/release-ready-20260915/`.

## Remaining release acceptance

This is a reviewable candidate, not a published stable release. Real AzureArchive
playback still needs slot-zero teacher, single/consecutive Sel, terminal Sel to Exit,
five portraits and CG acceptance using authorized resources. Synthetic compile tests
are not a substitute. Actual paid-provider writing quality and hard spending limits
are not claimed. The optional engine-script rule contract was absent from the source
rule snapshot and is not advertised as available.

Keep broader physical-request accounting, long-input/context limits and unrelated
1.1 work separate. Before stable publication, complete native acceptance, review the
candidate branch, create the exact version tag on the accepted commit, and run the
signed release workflow. Nothing was uploaded and no user's AA project was modified.
