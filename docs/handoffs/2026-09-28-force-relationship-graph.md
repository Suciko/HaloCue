# 2026-09-28 — Force-directed relationship graph, compact nodes

- Owner: maintainer; status: local implementation, not packaged/published.
- Scope: writing graph visualization only; follows the user's request for force-directed interaction, followed by explicit feedback to remove slogans, large solid circles and external node names.
- Supersedes the rendering details in [earlier atlas polish](2026-09-28-relationship-atlas-polish.md), not its verified-revision/no-write boundary.
- Branch remains `codex/1.0-release-readiness-20260914`, baseline HEAD `e617f9bf`, with substantial pre-existing dirty changes. No commit, push, public Issue or PR created; do not stage the entire checkout.

## Implementation

- Independent native Apache ECharts graph/force implementation, with compact small-radius outlined cards and node names INSIDE. Node type is a smaller second line. No promotional headline, English eyebrow, large solid circles, external names, or size-as-importance encoding.
- Native force attraction/repulsion responds to dragging adjacent nodes and cools to a stop. No perpetual orbit/pulse loop. Freeze/resume, zoom, pan, fit, type filters, verified-neighbor focus, search, relation-label toggle and source-editor navigation remain available.
- Forces supply the animation directly; generic graphic transform tweening is disabled so pointer targets and native symbol positions stay aligned.
- Theme changes, canvas resize and remounts preserve relevant view state. Keyboard navigation uses ordinary buttons in an expandable node list; reduced-motion preference disables animated layout. The list remains usable if the graph bundle fails to load.
- Narrow views use smaller cards and default to hiding relation labels; users can explicitly toggle labels. Controls flow below the canvas on small screens instead of obscuring nodes.
- Repeated mounts dispose the chart, force timer, media listeners, observers and pointer listeners. Navigating away closes the engine. Graph exploration remains local presentation state and does not write work revisions.
- Stable node IDs, duplicate display names, parallel/reverse/self links, dangling references and unresolved targets retain their original semantics. No fabricated category hubs or inferred edges.

## Skill / dependency boundary

The installed `lieflat-charts` skill and B2 `big-force.html` were inspected. Its template is licensed PolyForm Noncommercial, while this repository uses MIT. It informed the requested interaction direction ONLY: no template implementation or synthetic sample data was copied into the repository. HaloCue's adapter is independently implemented against Apache ECharts APIs. The subsequent explicit user feedback overrides the template's bubble styling.

`web/vendor/echarts/` contains the unmodified `echarts@6.0.0` distribution plus its LICENSE, NOTICE and provenance README. Official npm tarball integrity was verified. Runtime uses the local bundle and system fonts, no CDN or font service. Existing `HaloCue.spec` already includes the complete writing/web tree. No package manager/build dependency changes were required.

## Changed paths

- `services/halocue/writing/web/knowledge-graph-ui.js`
- `services/halocue/writing/web/knowledge-graph-ui.css`
- `services/halocue/writing/web/vendor/echarts/`
- `services/halocue/writing/web/index.html`: local bundle script and graph cache version `20260928-force-cards2`.
- `services/halocue/writing/web/app.js`: graph scope key and local graph copy simplification; redundant successful source-verification banner hidden only for the graph, with failure notices retained. Unrelated existing edits preserved.
- `services/halocue/writing/tests/knowledge_graph_ui.test.cjs`
- `services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py`

## Verification

The browser suite uses a real temporary WritingService/HTTP workbench for its integration case and synthetic graph data elsewhere. It covers actual canvas clicks and drag-induced neighbor motion, freeze/resume, search, keyboard, node-list navigation, source editing, theme changes, resize, 360px fit, no slogans, inside labels, escaped labels, empty/48-node graphs, duplicate names, loops, instance disposal and bundle-failure fallback. External HTTP is blocked in the workbench test and none was requested; the work revision remains unchanged.

Final commands:

```text
node --check services/halocue/writing/web/knowledge-graph-ui.js
node --check services/halocue/writing/web/app.js
python -m ruff check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
python -m ruff format --check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
git diff --check -- services/halocue/writing/web/app.js services/halocue/writing/web/index.html
python -X utf8 -m pytest services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py -q --tb=short
node --test services/halocue/writing/tests/knowledge_graph_ui.test.cjs
```

Final result: **10 browser tests passed in 29.63s; 9 Node tests passed.** Both JavaScript syntax checks, Ruff lint/format checks, and the scoped tracked-file whitespace check passed. Earlier in this slice, the 10 browser + 18 current-projection/knowledge-impact tests passed together (28), and the 9 Node tests passed; these are overlapping runs, not additive totals.

Visual QA inspected the complete workbench in dark/light themes and at 390px. Optional synthetic screenshots are emitted only to the maintainer-local path selected by `HALOCUE_GRAPH_SCREENSHOTS`; no user work or model credentials are included. The short-lived QA server is closed after each test. No external model requests, full-repository test run, EXE/ZIP rebuild or release was performed.

## Next action

Review **作品资料 → 关系图** in the source-based workbench. If accepted, isolate the graph delta from pre-existing uncommitted work before preparing a release. The September 26 executable/archive has not been updated.
