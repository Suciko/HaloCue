# V3 Draft Structure Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove generated blank/unknown cards from V3 drafts, prevent redundant background directives, stabilize custom background references, and make structural problems visible to review validation without changing story text.

**Architecture:** Keep `parse_document_lossless` byte-preserving for source editing, then add a separate draft normalization pass that drops ordinary blank nodes and classifies thematic breaks as `separator`. Draft creation/loading and validation consume the normalized structure. Annotation output tracks the last emitted background key so repeated keys are suppressed.

**Tech Stack:** Python 3, pytest, vanilla JavaScript UI, local HTTP API.

## Global Constraints

- Do not change dialogue, narration, scene prose, character mapping, or the comedy content in the central game-center scene.
- Preserve source snapshots and existing unrelated worktree changes.
- Use stable AA asset keys for script references; file names remain display metadata only.
- Every production behavior change must have a failing test before implementation.

---

### Task 1: Add draft normalization primitives

**Files:**
- Modify: `document.py` near `DocNode` and `parse_document_lossless`
- Test: `tests/test_document_golden.py`

**Interfaces:**
- Produces `normalize_draft_nodes(nodes: List[DocNode]) -> List[DocNode]`.
- A thematic break node has `kind == "separator"`, `fields["marker"]` containing the original marker, and retains its original `line_no`, `raw`, and `eol`.
- Ordinary `blank` nodes are omitted from the returned list.

- [ ] **Step 1: Write the failing test**

```python
def test_normalize_draft_nodes_drops_blank_lines_and_classifies_thematic_breaks():
    from document import normalize_draft_nodes

    nodes = parse_document_lossless("旁白: 第一幕。\n\n---\n\n旁白: 第二幕。\n")
    normalized = normalize_draft_nodes(nodes)

    assert [node.kind for node in normalized] == ["line", "separator", "line"]
    assert normalized[1].fields["marker"] == "---"
    assert [node.line_no for node in normalized] == [1, 3, 5]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest tests/test_document_golden.py::test_normalize_draft_nodes_drops_blank_lines_and_classifies_thematic_breaks -q`

Expected: FAIL because `normalize_draft_nodes` does not exist.

- [ ] **Step 3: Implement the minimal normalization helper**

Add a `THEMATIC_BREAK_RE`-compatible check in `document.py`. Return a new list, preserve non-blank nodes, convert unknown thematic breaks to `separator`, and leave all other unknown nodes unchanged.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `python -m pytest tests/test_document_golden.py::test_normalize_draft_nodes_drops_blank_lines_and_classifies_thematic_breaks -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated change**

```powershell
git add document.py tests/test_document_golden.py
git commit -m "feat: normalize draft blank lines and separators"
```

### Task 2: Make diagnostics and compilation understand separators

**Files:**
- Modify: `diagnostics.py`
- Modify: `document.py` in `compile_document`
- Test: `tests/test_diagnostics.py`
- Test: `tests/test_draft_store.py`

**Interfaces:**
- `separator` nodes produce no error diagnostic and no runtime event.
- A `blank` node passed directly to validation produces `draft.blank_node` with error severity, so legacy drafts cannot silently report zero issues.
- `unknown` nodes continue to produce `line.unparsable`.

- [ ] **Step 1: Write failing tests**

```python
def test_blank_node_is_reported_but_separator_is_not():
    nodes = [
        DocNode(kind="blank", raw="\n", line_no=2, fields={}),
        DocNode(kind="separator", raw="---\n", line_no=3, fields={"marker": "---"}),
    ]
    diags = validate_script_diagnostics(nodes, {"旁白": {"narrator": True}}, {})
    assert any(d["code"] == "draft.blank_node" and d["line_no"] == 2 for d in diags)
    assert not any(d["line_no"] == 3 for d in diags)
```

Update the existing Markdown separator draft-store test to assert the normalized identity has one separator and no `line.unparsable` diagnostic.

- [ ] **Step 2: Run tests and verify the new assertions fail**

Run: `python -m pytest tests/test_diagnostics.py::test_blank_node_is_reported_but_separator_is_not tests/test_draft_store.py::test_markdown_thematic_break_is_preserved_without_blocking_diagnostic -q`

Expected: FAIL because `draft.blank_node` and `separator` handling are absent.

- [ ] **Step 3: Implement minimal diagnostic and compiler branches**

Register `draft.blank_node` in `DIAGNOSTIC_CODES`; handle `kind == "blank"` before unknown logic; add an explicit no-op branch for `separator` in `compile_document`.

- [ ] **Step 4: Run focused tests and then the document/diagnostic suite**

Run: `python -m pytest tests/test_diagnostics.py::test_blank_node_is_reported_but_separator_is_not tests/test_draft_store.py::test_markdown_thematic_break_is_preserved_without_blocking_diagnostic tests/test_document_golden.py tests/test_diagnostics.py -q`

Expected: PASS with no new warnings.

- [ ] **Step 5: Commit the isolated change**

```powershell
git add document.py diagnostics.py tests/test_document_golden.py tests/test_diagnostics.py tests/test_draft_store.py
git commit -m "fix: validate draft structural nodes"
```

### Task 3: Apply normalization at draft boundaries

**Files:**
- Modify: `draft_store.py` in `create_draft` and draft loading/identity rebuild paths
- Test: `tests/test_draft_store.py`

**Interfaces:**
- New drafts build `identity.json` and persisted diagnostics from `normalize_draft_nodes(parse_document_lossless(text))`.
- `edited.txt` keeps the source text unchanged until a user edit; normalization affects cards/validation, not source snapshots.
- Legacy drafts with stale identities rebuild from normalized nodes on load.

- [ ] **Step 1: Write failing regression tests**

```python
def test_create_draft_does_not_create_blank_cards(temp_draft_dir):
    created = temp_draft_dir.create_draft(
        token="blank-card-regression",
        text="旁白: 第一行。\n\n---\n\n旁白: 第二行。\n",
        project="结构测试",
        cast={"cast": {"旁白": {"narrator": True}}},
    )
    assert [card["kind"] for card in created["identities"]] == ["line", "separator", "line"]
    assert not any(d["code"] == "draft.blank_node" for d in created["diagnostics"])
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run: `python -m pytest tests/test_draft_store.py::test_create_draft_does_not_create_blank_cards -q`

Expected: FAIL because `create_draft` currently persists every parsed node.

- [ ] **Step 3: Implement boundary normalization**

Centralize node construction in the existing identity-building path. Normalize before identity generation and before `compile_document`; use the same helper in the hash/legacy rebuild path so card IDs, diagnostics, and card counts agree.

- [ ] **Step 4: Run focused and draft-store tests**

Run: `python -m pytest tests/test_draft_store.py -q`

Expected: PASS, including existing round-trip and legacy-diagnostics tests.

- [ ] **Step 5: Commit the isolated change**

```powershell
git add draft_store.py tests/test_draft_store.py
git commit -m "fix: normalize draft cards at storage boundaries"
```

### Task 4: Suppress redundant background directives and stabilize references

**Files:**
- Modify: `annotate.py` in the annotated text writer
- Modify: `background_workflow.py` or the existing asset-key mapping helper only if needed to separate `aa_key` from display name
- Test: `tests/test_annotate_main.py`
- Test: `tests/test_background_workflow.py`

**Interfaces:**
- `render_annotated_items(items: List[Dict[str, Any]]) -> str` emits one `@bg` for a run of identical non-empty background keys.
- `@place` is emitted independently and remains present when only the place changes.
- The emitted background argument is the item `bg` key already validated against `constraints["ok_bg"]`; display labels are not substituted into this field.

- [ ] **Step 1: Write failing tests**

```python
def test_annotation_writer_does_not_repeat_same_background():
    result = render_annotated_items([
        {"kind": "line", "raw": "旁白: 一\n", "bg": "BG_ShoppingDistrict", "place": "商店街"},
        {"kind": "line", "raw": "旁白: 二\n", "bg": "BG_ShoppingDistrict", "place": "可丽饼摊前"},
        {"kind": "line", "raw": "旁白: 三\n", "bg": "BG_GameCenter", "place": "游戏中心"},
    ])
    assert result.splitlines()[:4] == [
        "@bg BG_ShoppingDistrict",
        "@place 商店街",
        "旁白: 一",
        "@place 可丽饼摊前",
    ]
    assert result.count("@bg BG_ShoppingDistrict") == 1
    assert "@bg BG_GameCenter" in result
```

Use the existing writer/helper name if the current module exposes a different seam; keep the assertion against the public text result rather than an internal mock.

- [ ] **Step 2: Run the focused tests and verify the new test fails**

Run: `python -m pytest tests/test_annotate_main.py::test_annotation_writer_does_not_repeat_same_background -q`

Expected: FAIL because the writer emits `@bg` for every item carrying a background.

- [ ] **Step 3: Extract the writer and implement last-background tracking**

Extract the current `out_lines` loop into `render_annotated_items`. Track `last_bg` through the writer loop, reset it only when a real background change is emitted, and compose `@bg` from the validated `item["bg"]` key. Do not touch dialogue fields or asset registration metadata.

- [ ] **Step 4: Run annotation and background-workflow tests**

Run: `python -m pytest tests/test_annotate_main.py tests/test_background_workflow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated change**

```powershell
git add annotate.py background_workflow.py tests/test_annotate_main.py tests/test_background_workflow.py
git commit -m "fix: avoid redundant background directives"
```

### Task 5: Rebuild the current V3 draft and verify the UI contract

**Files:**
- Modify: `webui.py` only if the API currently derives review counts from unnormalized nodes
- Test: `tests/test_web_draft_endpoints.py`
- Test: `tests/test_ui_workbench.py`

**Interfaces:**
- `/api/validate` reports structural diagnostics and nonzero `blocking_errors` when legacy blank/unknown cards remain.
- Review card payload contains no `kind == "blank"` cards for the rebuilt V3 draft and contains `separator` for each intended scene break.

- [ ] **Step 1: Write failing endpoint/UI tests**

Add a draft endpoint fixture containing blank lines and `---`; assert `/api/validate` returns a structural issue before normalization and no issue after the store rebuild. Add a UI contract assertion that the card renderer does not render an empty `card-kind-blank` element for normalized review data.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/test_web_draft_endpoints.py tests/test_ui_workbench.py -q`

Expected: FAIL on the new structural assertions.

- [ ] **Step 3: Implement the smallest API/UI compatibility changes**

Use the normalized cards/counts already returned by `DraftStore`; only adjust `webui.py` or `js/cards.js` if a stale payload path still exposes blank nodes. Do not hide diagnostics in the UI.

- [ ] **Step 4: Run the complete relevant suite**

Run: `python -m pytest tests/test_document_golden.py tests/test_diagnostics.py tests/test_draft_store.py tests/test_annotate_main.py tests/test_background_workflow.py tests/test_web_draft_endpoints.py tests/test_ui_workbench.py -q`

Expected: PASS.

- [ ] **Step 5: Rebuild current V3 without changing prose**

Use the existing draft token for “本日行程全部作废”, rebuild identities and diagnostics from its `edited.txt`, and preserve the same project/generation metadata. Verify the normalized text content differs only by structural card representation, not by non-empty source lines.

- [ ] **Step 6: Open V3 in the local browser and verify**

Confirm the card count no longer includes ordinary blank lines, `---` appears as a separator rather than unknown, repeated `BG_ShoppingDistrict` is absent from the generated text, and the review status reflects any remaining real issue.

- [ ] **Step 7: Commit the integration change**

```powershell
git add webui.py js/cards.js tests/test_web_draft_endpoints.py tests/test_ui_workbench.py
git commit -m "fix: surface structural draft review issues"
```
