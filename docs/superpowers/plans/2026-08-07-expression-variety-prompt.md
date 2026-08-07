# Expression Variety Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the staging prompt prefer a different semantically suitable registered expression on each character line, keeping the current expression only when no suitable alternative exists.

**Architecture:** This is a prompt-contract change only. Update the face-selection policy in `prompt.py` and protect the intended priority order with the existing `build_rules()` contract test; do not change schemas, resource validation, or annotation post-processing.

**Tech Stack:** Python 3, pytest, prompt text assembled by `prompt.build_rules()`

## Global Constraints

- Apply the rule to every portrait character, including characters with few available expressions.
- Semantic suitability and registered-expression validation remain mandatory.
- Do not mechanically rotate expressions or guess unlabeled numeric face IDs.
- Preserve unrelated uncommitted changes in both target files.

---

### Task 1: Prefer Suitable Expression Changes

**Files:**
- Modify: `tests/test_direction_feedback_rules.py:255`
- Modify: `prompt.py:113`

**Interfaces:**
- Consumes: `prompt.build_rules() -> str`
- Produces: A system-prompt contract in which expression changes are the default and expression retention is the fallback.

- [x] **Step 1: Write the failing test**

Replace the old continuity-focused assertions with:

```python
def test_expression_prompt_prefers_a_suitable_change_and_keeps_only_as_fallback():
    rules = build_rules()

    assert "优先选择一个与上一句不同、又符合当前语义的已标注表情" in rules
    assert "即使相邻台词的情绪接近" in rules
    assert "实在没有其他合适候选时，才保持上一表情" in rules
    assert "不要为了变化而换成明显不合语境的表情" in rules
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_direction_feedback_rules.py::test_expression_prompt_prefers_a_suitable_change_and_keeps_only_as_fallback -q`

Expected: FAIL because the old prompt prioritizes continuity and does not contain the new change-first contract.

- [x] **Step 3: Update the face-selection policy**

Revise only the `## 表情 face` paragraph in `prompt.py` so it states:

```text
角色每次开口都重新选择 face。默认动作是优先选择一个与上一句不同、又符合当前语义的已标注表情。
即使相邻台词的情绪接近，只要另一个可用表情同样贴合语气、态度或反应，也优先换表情；表情较少的角色同样执行这条规则。
只有同一句拆开的连续气口，或实在没有其他合适候选时，才保持上一表情。
不要为了变化而换成明显不合语境的表情，也不要按编号机械轮换。
```

Keep the surrounding resource-semantic and unlabeled-ID safety rules unchanged.

- [x] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_direction_feedback_rules.py::test_expression_prompt_prefers_a_suitable_change_and_keeps_only_as_fallback tests/test_direction_feedback_rules.py::test_expression_prompt_treats_usage_context_as_guidance_not_trigger tests/test_direction_feedback_rules.py::test_custom_expression_table_overrides_official_common_face_numbers -q`

Expected: `3 passed`.

- [x] **Step 5: Run the prompt contract suite and inspect the diff**

Run: `python -m pytest tests/test_balanced_direction_prompt.py tests/test_direction_feedback_rules.py -q`

Expected: all tests pass.

Run: `git diff --check -- prompt.py tests/test_direction_feedback_rules.py`

Expected: exit code 0 with no whitespace errors.
