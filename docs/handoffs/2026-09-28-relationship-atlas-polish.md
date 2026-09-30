# 2026-09-28 — Relationship atlas visual and interaction polish

> Rendering superseded by [force-directed compact nodes](2026-09-28-force-relationship-graph.md) after subsequent user feedback. Historical verification below remains an account of the earlier implementation.

- Kind: local implementation handoff; status: implemented and narrowly verified, not packaged or published.
- Owner/review: maintainer; prompted in the current chat to improve the existing relationship graph with readable dynamic interaction.
- Baseline: `e617f9bf`; branch retained as `codex/1.0-release-readiness-20260914` because the checkout contains substantial unrelated, uncommitted work.
- Existing Issues and open PRs inspected; no existing Issue identified for this narrow graph-polish slice. No new public Issue, commit, push or PR created. Follow-up integration should isolate this delta before publication.
- Sources: AGENTS.md, CONTEXT-MAP.md, product-direction-1.x.md, client/backend contexts, long-term-memory and remote-collaboration protocols, latest authoring handoff. Read web-design-engineer, animate and webapp-testing skills. This is interactive application UI, not a video composition.

## Scope

- `services/halocue/writing/web/knowledge-graph-ui.js`: stable ID-sorted layout, expanding graph bounds for larger sets, circular-node markup, curved directional links, distinct parallel/reciprocal/self-link geometry, relationship labels with local collision avoidance, verified-neighbor highlighting, node search, label toggle, zoom readout, actual-content fit, node dragging with live edges, drag-click suppression, keyboard focus restoration, finite 250ms layout interpolation, observer/animation cleanup and reduced-motion support.
- `services/halocue/writing/web/knowledge-graph-ui.css`: theme-aware atlas header/canvas, differentiated node colors, subtle halos, floating tools, responsive search and compact-zoom readable names. Preserved all existing adjoining library/editor rules.
- `services/halocue/writing/web/index.html`: only this turn's two graph asset cache-version edits, to `20260928-atlas1`. Other pre-existing edits remain intact.
- `services/halocue/writing/tests/knowledge_graph_ui.test.cjs`: expanded to 7 logic regressions.
- `services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py`: 7 browser cases, including real WritingService/HTTP/full workbench integration with synthetic data, source-editor navigation and no revision writes.

No schema, model-provider, API, dependency or formal revision changes. The graph continues to show only the verified current projection; it does not invent links. Dragged positions are temporary view state, not persisted project data; fit restores automatic layout. No new perpetual animation or simulation loop.

## Verification

```text
node --check services/halocue/writing/web/knowledge-graph-ui.js
PASS

node --test services/halocue/writing/tests/knowledge_graph_ui.test.cjs
7 passed

python -X utf8 -m pytest services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py services/halocue/writing/tests/test_current_projection.py services/halocue/writing/tests/test_knowledge_change_impact.py -q --tb=short
25 passed in 33.05s (7 browser + 18 projection/impact checks)

python -m ruff check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
PASS
python -m ruff format --check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
PASS

git diff --check -- services/halocue/writing/web/index.html
PASS
```

The final small dangling-edge filtering guard was subsequently covered by the 7-test Node run. Browser checks used isolated temporary directories and a loopback server; no external model calls or user projects were accessed. The initial integration test used the wrong historical route; correcting it to `?section=references&view=relations&work_id=...` exercised the actual UI. Visual QA caught and fixed the existing library-form CSS overriding the new search field.

Inspected light/dark, focused and 390px mobile images. Also checked 360px resize, reduced motion, zero search results, escaped labels, empty/disconnected graphs, repeated mounts, and a 48-node/47-edge graph. Optional screenshots are produced by setting `HALOCUE_GRAPH_SCREENSHOTS` to a maintainer-local output directory; they are synthetic QA artifacts, not shared dependencies. No full-repository suite, EXE/ZIP rebuild or live release was performed.

## Next bounded action

Review the graph in the development workbench under **作品资料 → 关系图**. If accepted, reconcile this focused delta with the pre-existing local graph implementation and package a new release; the September 26 EXE/ZIP has not been updated by this slice. Avoid committing the entire dirty checkout.
