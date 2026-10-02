# 2026-09-28 — Story-scale relationship graph allocation

- Scope: product-structure follow-up to the force graph and layout refinements.
- Status: implemented and narrowly verified; not packaged, committed, pushed or published.
- Branch remains `codex/1.0-release-readiness-20260914` with unrelated dirty work; do not stage the entire checkout.

## Product behavior now

- The graph no longer opens as the default for every work. The UI derives a conservative story-complexity tier from the current formal graph plus saved structure:
  - `short`: up to 3 chapters, 8 scenes, 8 characters and 12 explicit edges → relation summary first, with an explicit “展开关系图” action.
  - `medium`: local force graph is available with a chosen lens.
  - `long`: full-work graph opens with the three lenses and an explicit note that chapter-level scope needs chapter provenance in the projection.
- Lenses are separated instead of mixing everything:
  - 人物关系: character-character edges;
  - 世界关联: character/entity/rule associations, excluding timeline/fact clutter;
  - 剧情线索: edges involving events/facts.
- Short-work summary rows are clickable and promote into the relevant lens. Existing source editing remains available after node focus.
- The graph still reads only the verified current projection. It does not infer edges or write revisions while being explored.
- A future chapter/current-volume scope control is intentionally not faked: the current projection exposes source item IDs but not a reliable chapter/volume provenance for every node/edge. This slice leaves the scope as whole-work until that contract is added.

## Changed paths

- `services/halocue/writing/web/app.js`: story metrics, tiering, lens filtering, short-work summary, lens controls, expand/focus handlers.
- `services/halocue/writing/web/knowledge-graph-ui.js`: compatibility classes for the tiered list/canvas and existing force graph behavior.
- `services/halocue/writing/web/knowledge-graph-ui.css`: progressive-disclosure controls, relation summary and legacy-selector compatibility styling.
- `services/halocue/writing/web/index.html`: cache version `20260928-graph-tiered1`.
- `services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py`: short-work summary/expand and lens assertions in the workbench integration test.

## Verification

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py services/halocue/writing/tests/test_current_projection.py services/halocue/writing/tests/test_knowledge_change_impact.py -q --tb=short
28 passed in 80.51s

node --test services/halocue/writing/tests/knowledge_graph_ui.test.cjs
9 passed

node --check services/halocue/writing/web/app.js
node --check services/halocue/writing/web/knowledge-graph-ui.js
python -m ruff check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
python -m ruff format --check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
git diff --check -- services/halocue/writing/web/app.js services/halocue/writing/web/index.html
```

Visual QA inspected the long-form force view and the short-work workbench flow. The short synthetic work now starts with a readable relation list and only shows the graph after an explicit action; switching to 世界关联 changes the graph lens without changing project data.

## Visual polish follow-up

- Added a visual refinement pass in `knowledge-graph-ui.css`: quieter page header, segmented lens control, compact summary rows, restrained canvas chrome, cleaner relation form card, improved mobile stacking, and reduced-motion transitions.
- Visual QA screenshot: maintainer-local `graph-visual-polish-20260928/workbench-light.png`.
- Full workbench interaction test after the polish: 1 passed. The earlier focused suite remains 28 browser/projection tests plus 9 graph logic tests.

## Next bounded slice

If chapter-level graphs are wanted, extend the versioned current-projection contract with node/edge scope provenance (`scene_id`, `chapter_id`, `volume_id` or equivalent) and add round-trip tests before exposing current-chapter/current-volume filters. The old EXE/ZIP remains unbuilt.
