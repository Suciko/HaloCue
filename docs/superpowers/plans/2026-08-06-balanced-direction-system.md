# Balanced Automatic Direction System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a balanced automatic direction pass that coordinates character expressions, emoticons, actions, movement guidance, and effects, while documenting the screenplay format that gives AI reliable evidence.

**Architecture:** Keep semantic face selection and ambiguous emotional interpretation in the LLM prompt. Add a focused `direction_rules.py` module for high-confidence missing cues, provenance-aware priority, and density control; integrate it after annotation allowlist filtering and before script rendering. Preserve `script2aap.py`, `camera.py`, and `stage.py` as the authoritative AAP conversion and automatic blocking layers.

**Tech Stack:** Python 3, pytest, JSON Schema prompts, existing HTML/CSS/JavaScript Web UI, Markdown documentation.

## Global Constraints

- Work directly in the current `main` workspace; do not create a worktree.
- Do not use subagents.
- Preserve all unrelated uncommitted changes and never revert or overwrite them.
- Stage only the files or exact hunks belonging to the current task in each commit.
- Use TDD for every behavior change: failing test, confirmed failure, minimal implementation, focused pass, diff review, commit.
- Do not modify AA's EXE, configuration, AssetBundles, workspace files, or timestamps.
- Do not bundle locally unpacked AA resources with the application.
- Use the fixed balanced density; do not add a density setting UI in this change.
- Do not infer character-specific `faceId` values deterministically or rewrite user dialogue.
- Shut down the computer only after all focused and full verification commands pass.

## File Structure

- Create `direction_rules.py`: pure cue inference, source/model/supplement priority, provenance, emoticon density, and action density.
- Modify `annotate.py`: record explicit inline fields, apply legal model fields without overriding source fields, run supplement and density passes, and expose supplement proposals.
- Modify `prompt.py`: explain cross-dimension coordination, the full emoticon/action semantics needed here, and the `act` versus `move` boundary.
- Modify `ui.html`: expand the existing help drawer's recommended screenplay section without adding another help surface.
- Modify `使用说明-从这里开始.md`: add the detailed non-technical screenplay-writing guidance.
- Modify `README.md`: keep the technical screenplay format summary aligned with the user help.
- Create `tests/test_balanced_direction_rules.py`: pure rule, priority, density, annotation integration, and AAP field tests.
- Create `tests/test_balanced_direction_prompt.py`: prompt and schema contract tests.
- Create `tests/test_balanced_direction_help.py`: Web help and Markdown consistency tests.

---

### Task 1: High-Confidence Direction Cue Inference

**Files:**
- Create: `direction_rules.py`
- Create: `tests/test_balanced_direction_rules.py`

**Interfaces:**
- Produces: `infer_direction_cues(text: str, previous_text: str = "") -> dict[str, str]`
- Produces: `supplement_directions(items: list[dict], cast: dict[str, dict]) -> list[dict]`
- Each supplement record contains `item_index`, `field`, `before`, `after`, and `rule`.
- Mutated items store field provenance in `_direction_origins`, using `deterministic_supplement` for this pass.

- [ ] **Step 1: Write failing tests for the four requested examples**

```python
from direction_rules import infer_direction_cues


def test_requested_examples_receive_balanced_direction_cues():
    assert infer_direction_cues(
        "全身上下就嘴巴最灵光……走了！再不出发，才真的要偏离计划了。所有人都跟上。"
    )["emo"] == "冒烟"
    assert infer_direction_cues(
        "……你为什么要把「普通」说得那么不普通。"
    )["emo"] == "沉默"
    assert infer_direction_cues("……！")["emo"] == "惊叹"
    assert infer_direction_cues("那就更不行了！！")["act"] == "jump"
```

- [ ] **Step 2: Run the example test and confirm RED**

Run: `python -m pytest tests/test_balanced_direction_rules.py::test_requested_examples_receive_balanced_direction_cues -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'direction_rules'`.

- [ ] **Step 3: Add failing counterexample and portrait-boundary tests**

```python
def test_punctuation_alone_does_not_over_direct_ordinary_dialogue():
    assert infer_direction_cues("好的！") == {}
    assert infer_direction_cues("那么……我们继续说明下一项。") == {}
    assert infer_direction_cues("现在出发！") == {}
    assert infer_direction_cues("今天的折扣很大！！") == {}


def test_supplement_only_fills_empty_portrait_fields():
    items = [
        {"kind": "line", "who": "凯伊", "text": "……！", "emo": None},
        {"kind": "line", "who": "老师", "text": "……！", "emo": None},
        {"kind": "line", "who": "凯伊", "text": "那就更不行了！！", "act": "stiff"},
    ]
    cast = {
        "凯伊": {"portrait": True, "narrator": False},
        "老师": {"portrait": False, "narrator": False},
    }

    changes = supplement_directions(items, cast)

    assert items[0]["emo"] == "惊叹"
    assert not items[1].get("emo")
    assert items[2]["act"] == "stiff"
    assert [(change["field"], change["after"]) for change in changes] == [("emo", "惊叹")]
```

- [ ] **Step 4: Implement cue inference and supplement mutation**

Implement in `direction_rules.py`:

```python
import re

DIRECTION_FIELDS = frozenset({"face", "emo", "act", "fx"})


def infer_direction_cues(text, previous_text=""):
    value = re.sub(r"\s+", "", str(text or ""))
    if re.fullmatch(r"[…⋯.·]+[!！]+", value):
        return {"emo": "惊叹"}
    if (
        value.startswith(("……", "……", "..."))
        and "!" not in value and "！" not in value
        and any(token in value for token in ("为什么", "怎么会", "怎么把"))
        and any(token in value for token in ("那么", "这么", "说得", "说成"))
    ):
        return {"emo": "沉默"}
    if (
        any(token in value for token in ("走了！", "走了!", "快点", "跟上", "闭嘴", "够了"))
        and any(token in value for token in ("再不", "还不", "才真的", "都给我", "偏离计划"))
        and ("！" in value or "!" in value)
    ):
        return {"emo": "冒烟"}
    if (
        len(value) <= 24
        and re.search(r"[!！]{2,}$", value)
        and any(token in value for token in ("更不行", "绝对不行", "才不是", "绝对不要", "怎么可能", "闭嘴", "住手"))
    ):
        return {"act": "jump"}
    return {}
```

Implement `supplement_directions` so it walks only `kind == "line"` items, checks `cast[who].portrait` and `not narrator`, calls `infer_direction_cues`, fills only falsey fields, records `_direction_origins[field] = "deterministic_supplement"`, and returns the documented change records.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_balanced_direction_rules.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 6: Review and commit only Task 1 files**

Run: `git diff --check -- direction_rules.py tests/test_balanced_direction_rules.py`

Stage: `direction_rules.py`, `tests/test_balanced_direction_rules.py`

Commit: `feat: supplement balanced character direction`

---

### Task 2: Annotation Priority, Provenance, and Density

**Files:**
- Modify: `direction_rules.py`
- Modify: `annotate.py`
- Modify: `tests/test_balanced_direction_rules.py`

**Interfaces:**
- Produces: `mark_explicit_directions(item: dict) -> dict`
- Produces: `apply_model_directions(item: dict, clean: dict) -> dict`
- Produces: `normalize_direction_density(items: list[dict]) -> None`
- `mark_explicit_directions` stores a tuple in `_explicit_direction_fields`.
- `apply_model_directions` returns only fields actually applied and records `model` provenance.
- `normalize_direction_density` protects explicit fields and removes only conflicting model/supplement fields.

- [ ] **Step 1: Write failing priority and density tests**

```python
from direction_rules import (
    apply_model_directions,
    mark_explicit_directions,
    normalize_direction_density,
)


def test_source_direction_has_priority_over_model_and_supplement():
    item = {"kind": "line", "who": "凯伊", "text": "……！", "emo": "疑问", "act": "stiff"}
    mark_explicit_directions(item)
    applied = apply_model_directions(item, {"emo": "惊叹", "act": "jump", "face": "03"})
    supplement_directions([item], {"凯伊": {"portrait": True, "narrator": False}})

    assert item["emo"] == "疑问"
    assert item["act"] == "stiff"
    assert item["face"] == "03"
    assert applied == {"face": "03"}


def test_balanced_density_limits_automatic_symbols_and_strong_actions():
    items = [
        {"kind": "line", "who": "凯伊", "emo": "惊叹", "_direction_origins": {"emo": "model"}},
        {"kind": "line", "who": "桃井", "emo": "沉默", "_direction_origins": {"emo": "model"}},
        {"kind": "line", "who": "凯伊", "act": "jump", "_direction_origins": {"act": "model"}},
        {"kind": "line", "who": "桃井", "act": "jump", "_direction_origins": {"act": "model"}},
    ]

    normalize_direction_density(items)

    assert items[0]["emo"] == "惊叹"
    assert not items[1].get("emo")
    assert items[2]["act"] == "jump"
    assert not items[3].get("act")
```

Add a test proving two adjacent explicitly authored emoticons/actions remain untouched, and a test proving the same automatic emoticon has a four-dialogue cooldown while `脸红` has an eight-dialogue cooldown.

- [ ] **Step 2: Run priority and density tests and confirm RED**

Run: `python -m pytest tests/test_balanced_direction_rules.py -q`

Expected: FAIL because the three new functions are not defined.

- [ ] **Step 3: Implement provenance-aware priority and density**

Implement `mark_explicit_directions` from truthy `face`, `emo`, `act`, and `fx` fields. Implement `apply_model_directions` so protected direction fields remain unchanged while non-direction fields continue to apply normally.

Implement `normalize_direction_density` with these exact rules:

- automatic emoticons are never consecutive;
- the same automatic emoticon has a four-dialogue cooldown, except `脸红` has eight;
- explicit emoticons are never removed and still update cooldown state;
- `jump`, `shake`, and `hophop` are not automatically retained on adjacent dialogue lines;
- the same non-explicit action for the same speaker is not retained within that speaker's next three turns;
- when a field is removed, remove its entry from `_direction_origins` too.

- [ ] **Step 4: Add failing annotation and AAP integration tests**

Use the existing fake provider pattern from `tests/test_annotate_main.py`. Create a three-line temporary script whose first line has an explicit `[疑问]`, whose second line is an unaccented reply, and whose third line is `凯伊: ……！`. Return `惊叹` for the first line and empty fields for the other lines. Assert the output preserves `[疑问]` on line one and supplements `[惊叹]` on line three after the separating line.

In the same test file, construct the four requested examples, run the intended annotation path, and pass the result through the existing script parser/build helpers. Assert that `沉默`, `惊叹`, and `冒烟` resolve to emoticon IDs `2`, `3`, and `17`, while `jump` resolves only to action ID `6`.

Run: `python -m pytest tests/test_balanced_direction_rules.py -q`

Expected: FAIL because `annotate.py` still overwrites source direction fields and does not call the supplement pass.

- [ ] **Step 5: Integrate the direction module into `annotate.py`**

- Import the new helpers.
- In `parse_lines`, call `mark_explicit_directions` for each parsed dialogue item.
- Replace direct `it.update(clean)` with `applied_clean = apply_model_directions(it, clean)` and build model proposals only for `applied_clean`.
- After all model batches, call `supplement_directions(items, cast)`, convert each change to an `applied_pending` proposal with origin `deterministic_supplement` and its exact rule name, then call `normalize_direction_density(items)`.
- Keep `normalize_emoticon_density` import-compatible by making it a wrapper around the emoticon portion or re-exporting it from `annotate.py`.
- If supplement inference raises unexpectedly, preserve legal model output and append a diagnostic instead of aborting the draft.

- [ ] **Step 6: Run focused annotation tests and confirm GREEN**

Run: `python -m pytest tests/test_balanced_direction_rules.py tests/test_annotation_constraints.py tests/test_annotate_main.py tests/test_direction_feedback_rules.py tests/test_postprocessor_proposals.py -q`

Expected: all focused tests pass.

- [ ] **Step 7: Review the mixed dirty-file diff and commit only Task 2 changes**

Run: `git diff --check -- direction_rules.py annotate.py tests/test_balanced_direction_rules.py`

Before staging `annotate.py`, compare its pre-task dirty hunk for `usage_chain` and exclude that unrelated existing hunk from the staged patch. Confirm with `git diff --cached --name-only` and `git diff --cached`.

Commit: `feat: preserve and balance automatic direction`

---

### Task 3: Coordinated Direction Prompt

**Files:**
- Modify: `prompt.py`
- Modify: `annotate.py`
- Create: `tests/test_balanced_direction_prompt.py`

**Interfaces:**
- `prompt.build_rules() -> str` contains the coordinated behavior contract.
- `annotate.SCHEMA` uses the same `face`, `emo`, `act`, `move`, `fx`, and `bgfx` terminology.
- `annotate.build_batch_context` exposes recent `emo` and `act` choices.

- [ ] **Step 1: Write failing prompt contract tests**

```python
from annotate import SCHEMA, build_batch_context
from prompt import build_rules


def test_prompt_coordinates_direction_dimensions_and_explains_boundaries():
    rules = build_rules()
    for phrase in (
        "先判断这一句的情绪阶段、身体反应和镜头重点",
        "Dot / 沉默",
        "Exclaim / 惊叹",
        "Steam / 冒烟",
        "动作 act 是原地身体反应",
        "走位 move 是真实位置变化",
        "普通感叹号不能单独触发 jump",
    ):
        assert phrase in rules


def test_batch_context_includes_recent_emoticon_and_action_choices():
    items = [{"kind": "line", "who": "凯伊", "text": "不行。", "face": "05", "emo": "冒烟", "act": "jump"}]
    context = build_batch_context(items, [0])
    assert "emo=冒烟" in context
    assert "act=jump" in context
```

Add assertions that the schema describes `emo` as a momentary psychological symbol, `act` as an in-place body reaction, `move` as a real position change, and `fx` using the actual values `通讯 / 黑屏剪影 / 特写`.

- [ ] **Step 2: Run prompt tests and confirm RED**

Run: `python -m pytest tests/test_balanced_direction_prompt.py -q`

Expected: FAIL on the missing coordinated phrases, missing action context, and old schema descriptions.

- [ ] **Step 3: Update prompt guidance, context, and schema**

- Add a short coordination decision order before the per-dimension sections.
- Expand emoticon guidance for `Dot`, `Exclaim`, and `Steam`, including ordinary punctuation counterexamples.
- Expand all seven action meanings from the registered resource enum and distinguish momentary `jump` from sustained `hophop`.
- State that one strong layer is usually enough, while semantically compatible model choices may combine at a true peak.
- Clarify that automatic camera/stage layout remains authoritative unless text explicitly describes movement.
- Add recent `act` to `build_batch_context` alongside existing `face` and `emo`.
- Correct `SCHEMA` field descriptions to match actual supported values.

- [ ] **Step 4: Run focused prompt and annotation tests**

Run: `python -m pytest tests/test_balanced_direction_prompt.py tests/test_direction_feedback_rules.py tests/test_annotation_constraints.py -q`

Expected: all tests pass.

- [ ] **Step 5: Review and commit only Task 3 changes**

Run: `git diff --check -- prompt.py annotate.py tests/test_balanced_direction_prompt.py`

Stage all of clean `prompt.py` and `tests/test_balanced_direction_prompt.py`; stage only Task 3 hunks from dirty `annotate.py`. Verify the cached diff excludes the pre-existing `usage_chain` change.

Commit: `feat: coordinate AI direction decisions`

---

### Task 4: Recommended Screenplay Format Help

**Files:**
- Modify: `ui.html`
- Modify: `使用说明-从这里开始.md`
- Modify: `README.md`
- Create: `tests/test_balanced_direction_help.py`

**Interfaces:**
- The existing `helpDrawer` remains the only in-app help surface.
- All three help surfaces use the same example and the same seven guidance points.

- [ ] **Step 1: Write failing help consistency tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_help_surfaces_explain_how_to_give_ai_direction_evidence():
    texts = [
        (ROOT / "ui.html").read_text(encoding="utf-8"),
        (ROOT / "使用说明-从这里开始.md").read_text(encoding="utf-8"),
        (ROOT / "README.md").read_text(encoding="utf-8"),
    ]
    for text in texts:
        for phrase in ("商店街，午后", "一行一个角色", "真实动作", "位置变化", "不要为了触发演出", "审查草稿"):
            assert phrase in text
```

Add a UI assertion that `helpDrawer` still occurs once and the new content remains inside its `推荐剧本写法` section.

- [ ] **Step 2: Run help tests and confirm RED**

Run: `python -m pytest tests/test_balanced_direction_help.py -q`

Expected: FAIL because the current help only has a one-paragraph overview.

- [ ] **Step 3: Update the in-app help and Markdown documents**

Use this canonical example in all three surfaces:

```text
## 场景一：商店街，午后
旁白: 商店街人声嘈杂，凯伊已经在服装店门口等候。
老师: 久等了。
凯伊: ……你为什么要把「普通」说得那么不普通。
旁白: 凯伊短暂地噎住，随后向老师走近一步。
凯伊: 那就更不行了！！
```

Explain one dialogue per line, stable speaker names, scene headings, location/time/light/ambient sound, explicit physical action and position change, meaningful punctuation, evidence for background/sound/physical impact, no need to type AA enums, and mandatory draft review.

- [ ] **Step 4: Run help and existing UI contract tests**

Run: `python -m pytest tests/test_balanced_direction_help.py tests/test_ui_workbench.py tests/test_ui_polish_contract.py -q`

Expected: all tests pass.

- [ ] **Step 5: Inspect the help drawer in the running local app**

Open `http://127.0.0.1:8770/`, click the existing Help button, and verify at desktop and a narrow mobile viewport that the example wraps without horizontal overflow and that the close control remains usable.

- [ ] **Step 6: Review and commit only Task 4 changes**

Run: `git diff --check -- ui.html 使用说明-从这里开始.md README.md tests/test_balanced_direction_help.py`

Because `ui.html` already contains unrelated dirty changes, stage only the exact help-section hunk and verify the cached diff does not include other UI work.

Commit: `docs: explain AI-friendly screenplay format`

---

### Task 5: Final Regression Verification and Review

**Files:**
- No planned file changes. A scoped fix and its regression test are required if this verification exposes a defect.

**Interfaces:**
- Consumes: annotated screenplay syntax from `annotate.render`.
- Consumes: `script2aap.build(events, cfg, cast, idx, project)`.
- Verifies: AAP character `emoticon` and `action` fields remain separate and use registered IDs through the Task 2 integration coverage.

- [ ] **Step 1: Re-run the annotation-to-AAP integration contract**

Confirm the Task 2 integration test still asserts:

```python
assert exclaim_character["emoticon"] == 3
assert steam_character["emoticon"] == 17
assert jump_character["action"] == 6
assert jump_character["emoticon"] == -1
```

Run: `python -m pytest tests/test_balanced_direction_rules.py -q`

Expected: all rule, priority, density, annotation, and AAP integration tests pass. If this fails, first add or tighten the smallest regression assertion that isolates the defect, confirm it fails alone, then implement the scoped fix and rerun it.

- [ ] **Step 2: Run all focused direction and compiler tests**

Run: `python -m pytest tests/test_balanced_direction_rules.py tests/test_balanced_direction_prompt.py tests/test_balanced_direction_help.py tests/test_script_commands.py tests/test_symbol_constraints.py tests/test_direction_feedback_rules.py tests/test_annotation_constraints.py tests/test_annotate_main.py -q`

Expected: all focused tests pass.

- [ ] **Step 3: Run complete verification**

Run:

```powershell
python -m pytest -q
node --check js/app.js
python prepare_release.py --check
```

Expected: pytest reports zero failures, Node syntax check exits 0, and release check exits 0.

- [ ] **Step 4: Review final scope and staged state**

Run:

```powershell
git status --short
git diff --check
git log -6 --oneline
```

Confirm every task commit contains only its intended files or hunks and all unrelated pre-existing changes remain present and unstaged.

- [ ] **Step 5: Commit only if regression verification required a scoped fix**

Stage only the regression test and the exact production hunk that fixed it. Use commit message `fix: preserve balanced direction in AAP output`.

- [ ] **Step 6: Shut down after successful completion**

Only after Steps 3-6 succeed, run: `shutdown.exe /s /t 0`

Do not run shutdown if any required verification fails or a required implementation item remains incomplete.
