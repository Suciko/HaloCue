# Resource annotation usage — first 1.0 slice

- Kind: handoff; status: implemented locally, not committed or pushed.
- Date: 2026-09-18.
- Release/owner: 1.0 production backend and embedded production UI.
- Branch: `codex/1.0-release-readiness-20260914`; related parent Issue: #15.
- Authority: maintainer request to use existing background/face annotations; product direction, backend context, ADR-0002/0006.
- Existing unrelated modifications remain untouched. No automatic revisions, compilation, installation, or remote publication.

## Changes
- `resource_retrieval.py`: merge frozen scene background annotations with bg_label; positive retrieval fields include weather/season/space/search aliases/usage. Negative usage is not a positive query source. Existing pinned keys remain preserved.
- `asset_catalog.py`: retain face usage hints/primary emotion/search terms from vision evidence.
- `prompt.py`: bounded face usage/beat/hold/avoid metadata and background usage constraints; both direction profiles use them. Resource annotations are reference data, not instructions; no changes to writing/scene-judgement separation.
- Production legacy adapter: additive read-only background/face metadata, exact variant scope, no expansion of frozen face IDs, whitelist public fields, normalize old numeric-string intensity.
- Production UI: readable face annotations, Chinese semantic labels, matching reasons and warnings in the background picker/detail. Selection does not save a revision. Resource search is latest-request-wins, guarded by picker identity/run/request epoch; pagination remains single-flight.
- Writing `production-theme.css`: fix dark-mode performance editor white surfaces and background count contrast.

## Contracts
No canonical project or persisted schema migration. Production resource responses gain optional annotation fields; legacy id/raw/label remain. No guessed resource keys and no cross-outfit annotation borrowing. Prompt changes need a subsequent live model comparison, not a claim of end-to-end model quality certification.

## Validation
Commands (repository root):

```text
python -X utf8 -m pytest -q tests/test_resource_annotation_usage.py tests/test_resource_retrieval.py tests/test_balanced_direction_prompt.py tests/test_face_evidence.py tests/test_face_variant_scope.py tests/test_semantic_face_allowlist.py tests/test_semantic_face_catalog.py services/halocue/production/tests/test_resource_annotations.py services/halocue/production/tests/test_resource_annotation_ui.py services/halocue/production/tests/test_scene_background_preview_ui.py services/halocue/production/tests/test_http_api.py services/halocue/production/tests/test_service.py
python -X utf8 -m pytest -q services/halocue/integrated/tests/test_production_navigation.py
node --check services/halocue/production/ui/app.js
```

- Focused resource/prompt/production regression: 155 passed.
- Integrated navigation suite: 15 passed.
- Resource browser suite: 4 passed, including input during a delayed filter request and rejection of stale results. The new race test failed before the guard fix.
- Local live read-only acceptance: 21 annotated faces; desktop/mobile; dark/light; no page JS errors or horizontal overflow; identical draft before/after. Shell feedback settings sync remains an unrelated POST; no production write occurred.
- Background restriction screenshots use explicitly labelled synthetic responses, not a fabricated claim of full real-catalogue acceptance. The real isolated task has only one available background despite a larger annotation catalogue.
- Narrow Ruff and diff checks pass. The entire repository suite was not rerun.

Maintainer-local evidence under `<LOCAL_RESOURCE_ANNOTATION_QA>` includes screenshots, regression output, race before/after, and unchanged-draft checks. No private assets, provider credentials, or local machine paths included here.

## Next slice
Implement scene-specific background hard-condition conflict explanations and author-visible pinning; then live model comparison for expression continuity. Current metadata/prompt improvements are not a deterministic expression-duration engine. No full 0.95 parity or complete 1.0 chain claim.
