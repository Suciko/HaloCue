# 1.0 scene background matching and authored background precedence

- Kind: handoff; status: local implementation, uncommitted/unpushed.
- Date: 2026-09-18.
- Branch: `codex/1.0-release-readiness-20260914`; parent Issue: #15.
- Owner: production/backend and embedded production UI.
- Authority: maintainer continuation request; product-direction-1.x, backend context, ADR-0002/0006.
- Prior slice: `2026-09-18-resource-annotation-usage.md`.
- Preserve pre-existing dirty files; no remote publication or user project replacement.

## Slice
New production-local `scene_backgrounds.py` reads the current scene heading, never dialogue, and optional ephemeral picker overrides. Known place/time/space/weather annotations produce match/conflict/unknown evidence; unknown and ambiguous data never imply full match. Sorting occurs before pagination; conflicts are retained. No percentage confidence is emitted.

The existing run resources GET accepts optional `scene_card_id`, `scene_place`, `scene_time`, `scene_space`, `scene_weather`. It adds optional `scene_context` and per-item `scene_match` when used for backgrounds; older clients retain existing output shape otherwise. These are read-only API additions, no persisted or canonical schema migration.

The embedded picker shows evidence, explicit conflict confirmation and current assignment. Scene preferences sort rather than silently filter contradictions; source/text/preview filters remain available. Existing run/request/picker guards remain and stale draft selection is rejected. Default scene picker includes unpreviewable entries so catalogue absence is not silently confused with no matching background.

Authored @bg is tracked per dialogue item during parsing until a structural boundary or explicit replacement. The common annotation safety path ignores model bg/bg_request for that protected span, in standard/conservative and Agent/stateless paths. Rendering tracks raw @bg for deduplication. Existing background assignment is the source of truth; no duplicate persisted lock registry or new unlock switch.

A real integrated click revealed that existing-background replacement incorrectly used the generic PATCH route, which intentionally rejects resource directives. It now uses the dedicated background-resolution route; this accepts an existing @bg card as well as a background request. Frozen-key validation and expected draft version remain enforced; dialogue cards are rejected and card identity is preserved.

## Validation
```text
python -X utf8 -m pytest -q tests/test_authored_scene_backgrounds.py tests/test_conservative_annotation.py tests/test_annotate_main.py tests/test_annotation_constraints.py tests/test_annotation_agent.py tests/test_annotation_memory.py tests/test_annotation_protocol.py tests/test_balanced_direction_rules.py tests/test_resource_annotation_usage.py services/halocue/production/tests/test_scene_background_matching.py services/halocue/production/tests/test_scene_background_picker_ui.py services/halocue/production/tests/test_resource_annotation_ui.py services/halocue/production/tests/test_http_api.py services/halocue/production/tests/test_direction_profiles.py services/halocue/production/tests/test_service.py
# 366 passed
python -X utf8 -m pytest -q services/halocue/integrated/tests/test_production_navigation.py
# 15 passed
node --check services/halocue/production/ui/app.js
```
Scoped Ruff and git diff --check passed. Whole-repository suite was not rerun. Authored protection and raw-bg duplication tests reproduced failures before the fix. The resource input race regression fixture was adapted to the scene picker's new initial preview-filter state; its behavioral assertion remains intact.

Actual integrated UI with synthetic story/assets and real backend (no response mocking): desktop/mobile x dark/light, correct match/unknown/conflict order, cancel leaves draft unchanged, explicit conflict adoption succeeds and retains dialogue. Actual isolated task read-only check: preview loads, vague title is honestly unknown, draft unchanged. Existing feedback settings sync POST is separately recorded; no production writes on the real task.

Maintainer-local evidence is stored under `<LOCAL_SCENE_BACKGROUND_QA>`: RESULT/ISSUE_LOG, regression logs, screenshots clearly labelled synthetic/live, and JSON acceptance checks. No secrets/private assets are included in this handoff.

## Boundaries / next action
- No paid model calls, AA build/install, or automatic writing proposal adoption in this slice.
- Source text may contain already-generated @bg; current assignments are all preserved on regeneration until author replacement/deletion. No new persistent pin/unpin control.
- AI initial review locations are not treated as confirmed facts from potentially stale line numbers. Current recommendations rely on heading and ephemeral author filters.
- Next bounded work: controlled live expression-continuity comparison using frozen annotations, and trustworthy confirmed scene semantics. Do not claim complete 0.95 parity or end-to-end 1.0 certification.
