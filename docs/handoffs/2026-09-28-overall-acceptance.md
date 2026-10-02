# 2026-09-28 — Overall acceptance repair follow-up

- Branch: `codex/1.0-release-readiness-20260914`; HEAD `e617f9bf3453afbf30d5204761051f41373f9c72`.
- The checkout already contained extensive unrelated tracked and untracked work before this repair. Those changes were preserved. No commit, push, PR, publish, or official release was made.
- Result: the known graph navigation defect and the previously failing integrated browser journeys now pass their focused suites. A fresh 1.0.0 QA package was built under `.tmp/overall-acceptance-20260928/package-review/` and passed its release-tree scan, ZIP integrity check, and packaged-runtime smoke test.
- This remains a local QA package, not release approval: the full writing and root compatibility suites were not rerun, and the current checkout lacks the canonical root `aa_resources.json` used by the build script. The QA build used the sanitized minimal index retained in the previous build cache.

## Repairs

- Knowledge-graph summary buttons now select their lens from both relationship endpoints. Focusing a node already visible in the current world or plot lens keeps that lens. The browser regression covers organization and event summaries, in-lens character focus, and confirms the work version is unchanged.
- Chapter refreshes now restore the mobile manuscript/Agent/review controls and the knowledge-impact disclosure. A refresh also preserves the unsent scene instruction and focus. Narrow-window chapter chat keeps the composer visible at both tested viewport heights.
- Returning to a character or world card during a scoped assistance session reopens the parent assistance panel, keeping the saved draft and request visible.
- Integrated navigation tests now follow the shipped first-use, work creation, character reuse, chapter authoring, and production recovery flows. They retain assertions for save failure, explicit adoption, route state, read-only navigation, and no model call where required.
- The release scanner now recognizes the pinned ECharts minified font-detection table as an obfuscated vendor string, while still detecting a real absolute path elsewhere in the release tree.
- `HaloCue.spec` now includes the shared `model_capabilities.py` as a data file. The frozen runtime imports this file by path from `_MEIPASS`; the previous package could not start the integrated service without it.

## Post-repair verification

- `python -X utf8 -m pytest services/halocue/integrated/tests/test_production_navigation.py -q --tb=short`: **40 passed**.
- Focused adaptation, card assistance, knowledge-impact, and reference-feedback browser suites: **14 passed**.
- Knowledge-graph interaction, chapter authoring, and balanced screenplay help suites: **19 passed**.
- `node --test services/halocue/writing/tests/*.test.cjs`: **86 passed**.
- Ruff on the five modified integrated test modules: **all checks passed**. `node --check` on `app.js`, `chapter-authoring-ui.js`, `writing-workbench.js`, `knowledge-impact.js`, and `card-assistance.js`: passed. `git diff --check`: passed.
- `python -X utf8 -m pytest tests/test_desktop_release_build.py -q --tb=short`: **3 passed**.
- The built package contains `HaloCue.exe` and `HaloCueUpdater.exe`; the ZIP contains 1,017 entries, every member passed CRC verification, and its file manifest lists 1,016 payload files. The final archive SHA-256 is `b9388e59f0f3e94630f3dee6447fd9cf6f282f0270f67fd56f11deccaa45b431`.
- Packaged-runtime smoke test: the frozen app started with an isolated user-data directory, its native window titled `HaloCue 1.0.0` remained responsive, and `/api/v1/health` returned `ok: true`. The packaged page loaded in the Codex in-app browser. No model call or user-work mutation was made.

## Evidence and limits

- The previous acceptance baseline remains recorded in `.tmp/overall-acceptance-20260928/验收报告.md`; its original broad suite results are historical baseline, not post-repair claims.
- The previous full writing run was **1,476 passed / 3 failed** before its three test-fixture corrections; those corrected focused checks passed, but the whole writing suite was not rerun. The previous root run was **1,951 passed / 1 failed / 14 skipped**; the screenplay-help failure now passes in its focused three-test file, but the entire root suite was not rerun.
- Production tests previously passed **447/447**. Production domain code was not changed during this repair follow-up; this does not claim a new production-suite run.
- `aa_resources.json` is absent from the current repository root. To produce the isolated QA package, the builder temporarily received the sanitized index from `build-cache-before-rebuild/seed/aa_resources.json`; the temporary root copy was removed after building. The package therefore uses that prior minimal index and must not replace a release built from the authorized current resource export.
- The build script's prior `build/desktop-1.0.0` cache was preserved at `.tmp/overall-acceptance-20260928/build-cache-before-rebuild/` before rebuilding.
- No real model service, AzureArchive installation, user project, or private resource was used for the browser or packaged smoke checks. Long-story chapter/volume provenance remains deferred as stated in the original acceptance report.

## Remaining release gate

Provide or regenerate the canonical sanitized `aa_resources.json` export for this checkout, then rebuild the package from that input and repeat the packaged-runtime smoke. Run the full writing and root compatibility suites if a final release signoff is required. Until those steps are complete, treat the package in `.tmp/overall-acceptance-20260928/package-review/` as a QA candidate only.
