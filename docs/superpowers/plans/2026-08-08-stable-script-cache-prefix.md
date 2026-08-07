# Stable Script Cache Prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve exact source-script text in each annotation run's stable prompt prefix so chunk-specific memory cannot invalidate it.

**Architecture:** `annotate_script()` reads the source once and constructs a stable cached system segment from existing rules/resources plus the unmodified source. `run_annotation_agent()` continues to send memory and chunk windows separately as volatile system and user content. Provider adapters retain their current stable-before-volatile ordering.

**Tech Stack:** Python 3, pytest, Anthropic Messages API, OpenAI-compatible Chat Completions API.

## Global Constraints

- Never summarize, normalize, reorder, or redact the source script before placing it in the stable prompt prefix.
- Keep all dynamic state after the stable prefix.
- Do not log script text, credentials, or reasoning text.
- Preserve existing annotation protocol, checkpoints, and chunk recovery behavior.

---

### Task 1: Define and test the stable source segment

**Files:**
- Modify: `annotate.py`
- Test: `tests/test_annotation_agent.py`

**Interfaces:**
- Produces: `build_annotation_static_system(static_rules: str, source_text: str) -> str`
- Consumes: exact `Path.read_text(encoding="utf-8")` content.

- [ ] **Step 1: Write the failing tests**

```python
def test_annotation_static_system_keeps_exact_source_after_rules():
    source = "甲: 原文\n\n乙: 不改写\n"
    static = annotate.build_annotation_static_system("RULES", source)
    assert static.startswith("RULES")
    assert static.endswith(source)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$env:PYTHONPATH=(Get-Location).Path; pytest tests/test_annotation_agent.py::test_annotation_static_system_keeps_exact_source_after_rules -q`

Expected: FAIL because `build_annotation_static_system` is not defined.

- [ ] **Step 3: Implement the minimal helper**

```python
def build_annotation_static_system(static_rules, source_text):
    return f"{static_rules}\n\nSOURCE_SCRIPT\n{source_text}"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `$env:PYTHONPATH=(Get-Location).Path; pytest tests/test_annotation_agent.py::test_annotation_static_system_keeps_exact_source_after_rules -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add annotate.py tests/test_annotation_agent.py
git commit -m "feat: stabilize source script cache prefix"
```

### Task 2: Integrate the stable segment into Agent calls

**Files:**
- Modify: `annotate.py`
- Test: `tests/test_annotation_agent.py`

**Interfaces:**
- Consumes: `build_annotation_static_system()`.
- Produces: Agent calls whose static argument is identical across scene chunks while volatile/user arguments remain per-chunk.

- [ ] **Step 1: Write the failing test**

```python
def test_agent_uses_same_source_prefixed_static_prompt_for_all_chunks(tmp_path):
    provider = RecordingProvider()
    result = annotate.annotate_script(agent_options(tmp_path), provider_instance=provider)
    assert len(provider.static_prompts) >= 2
    assert len(set(provider.static_prompts)) == 1
    assert "SOURCE_SCRIPT" in provider.static_prompts[0]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$env:PYTHONPATH=(Get-Location).Path; pytest tests/test_annotation_agent.py::test_agent_uses_same_source_prefixed_static_prompt_for_all_chunks -q`

Expected: FAIL because the source text is not part of the Agent static prompt.

- [ ] **Step 3: Pass the source-prefixed static system to the Agent**

```python
source_text = Path(script_path).read_text(encoding="utf-8")
static_system = build_annotation_static_system(static, source_text)
run_annotation_agent(..., static_system=static_system, ...)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `$env:PYTHONPATH=(Get-Location).Path; pytest tests/test_annotation_agent.py::test_agent_uses_same_source_prefixed_static_prompt_for_all_chunks -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add annotate.py tests/test_annotation_agent.py
git commit -m "feat: cache original script across annotation chunks"
```

### Task 3: Regression verification and controlled runtime measurement

**Files:**
- Modify: `docs/superpowers/specs/2026-08-07-single-block-latency-performance-debt.md`
- Test: `tests/test_annotation_memory.py`, `tests/test_annotation_agent.py`, `tests/test_llm_profile_provider.py`

**Interfaces:**
- Consumes: provider usage reports already exposed by `run_annotation_agent()`.
- Produces: a documented before/after measurement with cache values marked unknown when the provider omits usage.

- [ ] **Step 1: Run targeted regressions**

Run: `$env:PYTHONPATH=(Get-Location).Path; pytest tests/test_annotation_memory.py tests/test_annotation_agent.py tests/test_llm_profile_provider.py -q`

Expected: PASS.

- [ ] **Step 2: Run the full suite**

Run: `$env:PYTHONPATH=(Get-Location).Path; pytest -q`

Expected: PASS.

- [ ] **Step 3: Run one bounded real-provider comparison**

Use a short fixed fixture and one completion per variant. Record only input tokens, cached tokens, uncached tokens, output tokens, elapsed time, and finish reason. Do not record prompts, script text, API keys, or reasoning deltas.

- [ ] **Step 4: Commit documentation and verified implementation**

```powershell
git add docs/superpowers/specs/2026-08-08-stable-script-cache-prefix-design.md docs/superpowers/plans/2026-08-08-stable-script-cache-prefix.md docs/superpowers/specs/2026-08-07-single-block-latency-performance-debt.md
git commit -m "docs: record stable script cache prefix results"
```
