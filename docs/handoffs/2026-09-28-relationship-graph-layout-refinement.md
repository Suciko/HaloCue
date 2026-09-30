# 2026-09-28 — Relationship graph layout refinement

- Scope: follow-up to `2026-09-28-force-relationship-graph.md`; user reported that relationship names overlapped in the center and the overall arrangement did not resemble a readable Obsidian-style graph.
- Status: implemented and narrowly verified; not packaged, committed, pushed or published.
- Branch/worktree: `codex/1.0-release-readiness-20260914` with substantial pre-existing dirty changes. Do not stage the whole checkout.

## Changes

- Default relationship labels are now hidden. ECharts emphasis reveals labels only for the hovered/focused neighborhood; the explicit `显示关系名` control opts into all labels. This removes the persistent “同社团 / 参与” pile-up while retaining discoverability.
- Increased force repulsion and link distance, reduced gravity, and kept the force solver as the only layout motion source. The graph settles into a looser, Obsidian-like open arrangement rather than a tight central knot.
- Kept compact outlined cards with names inside the nodes. No new slogans, title copy or decorative legend text was added.
- `适应画布` still fits the solved graph; resize, narrow view, reduced motion, focus, search and source navigation remain covered.
- Asset cache version is now `20260928-force-layout3`.

## Verification

```text
python -X utf8 -m pytest services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py services/halocue/writing/tests/test_current_projection.py services/halocue/writing/tests/test_knowledge_change_impact.py -q --tb=short
28 passed in 53.63s

node --test services/halocue/writing/tests/knowledge_graph_ui.test.cjs
9 passed

node --check services/halocue/writing/web/knowledge-graph-ui.js
PASS

python -m ruff check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
PASS
python -m ruff format --check services/halocue/writing/tests/test_knowledge_graph_interaction_browser.py
PASS
```

Visual QA inspected the updated synthetic graph in dark mode and at mobile width. The force graph no longer shows relationship text by default; the control and emphasis path are covered by the browser test. No user work revision is written by graph exploration.

## Remaining

The September 26 EXE/ZIP is still not rebuilt. This focused slice remains uncommitted because the current checkout contains unrelated work from prior sessions.
