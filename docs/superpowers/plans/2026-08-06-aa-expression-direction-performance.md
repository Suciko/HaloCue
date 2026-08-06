# AA 演出语义、资源与性能优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不减少资源能力或演出质量的前提下，补齐多轴 Spine 表情语义、喜剧演出密度、无台词 `wait`、登场渐变状态和批次性能优化。

**Architecture:** 保留现有素材库渲染/缓存/视觉标注链路，增加可选的多轴语义并通过 `rich/basic/unknown` 能力等级兼容官方与自定义角色。剧情模型负责语义选择，程序负责完整 allowlist、状态机、确定性兜底、后处理和失败回退；请求层只压缩重复上下文。

**Tech Stack:** Python 3、SQLite、现有 JSON Schema 结构化 LLM 接口、pytest；不新增运行时依赖。

## Global Constraints

- 资源库保存完整合法资源和完整语义；只压缩每次请求中与当前镜头无关的重复上下文。
- 官方角色没有视觉标注时必须可生成；自定义 Spine 的视觉标注失败不能阻塞剧本生成。
- 新字段全部可选并兼容旧记录，人工修正优先于 AI 原值。
- 不用关键词表取代模型对反讽和混合情绪的理解。
- 登场渐变与首句同节点，不增加独立空文本或额外 1–1.5 秒停顿。
- 显式 `wait` 只用于独立无台词反应，不叠加 AA 气泡/动作默认停顿。
- 不并行具有共享角色状态的场景。
- 每项实现先写失败测试，再写最小实现，再运行相关测试并单独提交。

---

### Task 1: 扩展 Spine 视觉标注 Schema 与兼容持久化

**Files:**
- Modify: `spine_face_labeler.py` (`_EDITABLE_FACE_FIELDS`, `VISION_SCHEMA`, validation, persistence, record conversion)
- Modify: `assetdb.py` (`face_visual_label` migration/schema version only if required by chosen JSON storage)
- Test: `tests/test_spine_face_labeler.py`

**Interfaces:**
- Consumes: existing visual label items containing `face_id`, `primary_emotion`, `usage_hint_cn`, `confidence`; legacy `description_cn` remains accepted.
- Produces: optional `emotion_family`, `intensity`, `expression_class`, `beat_fit`, `hold_policy`, `special_tags`, `avoid_when_cn`, `semantic_level` in AI/manual/effective records; old rows remain readable.

- [ ] **Step 1: Write failing tests** for a rich item round-trip, optional-field omission, invalid enum/intensity rejection, manual override precedence, and legacy two-field records receiving `semantic_level="basic"`.
- [ ] **Step 2: Run focused tests** with `pytest tests/test_spine_face_labeler.py -q`; confirm the new fields are rejected or absent.
- [ ] **Step 3: Implement minimal compatibility layer**: validate optional fields, persist them in a JSON sidecar compatible with existing columns, expose them through `_visual_label_record`, and derive `semantic_level` without fabricating missing semantics.
- [ ] **Step 4: Run focused tests** and the existing asset-label tests; verify old fixtures and manual optimistic locking still pass.
- [ ] **Step 5: Commit** with `feat: support layered Spine face semantics`.

### Task 2: Preserve full resource allowlists while adding official/basic fallback

**Files:**
- Modify: `asset_catalog.py` (`_face_capabilities`, source priority, semantic metadata merge)
- Modify: `annotate.py` (`face_allowlist`, `_allowed_face_records`, `annotation_constraints`, `build_static`)
- Modify: `prompt.py` (`build_resources` compact semantic formatting)
- Test: `tests/test_annotation_constraints.py`, `tests/test_asset_catalog.py`, `tests/test_semantic_face_allowlist.py`, `tests/test_model_asset_constraints.py`

**Interfaces:**
- Consumes: face evidence sources `aa_verified`, `aap_observed`, `vision:*`, `spine_semantic`, `atlas_candidate`, and optional rich fields from Task 1.
- Produces: each face record carries complete legality plus `semantic_level`; `rich` metadata is preferred, official named faces become `basic`, pure-number faces remain `unknown` and are legal-but-not-suggested.

- [ ] **Step 1: Write failing tests** proving official named faces enter the prompt without vision rows, unknown numbered faces remain legal but are not described as guessed semantics, and rich metadata is not flattened away.
- [ ] **Step 2: Run focused tests** and capture current failures.
- [ ] **Step 3: Implement source-aware merge** with explicit priority `manual > rich vision > legacy vision > official basic > parsed parts > unknown`; retain compatibility `semantic_cn` for old consumers.
- [ ] **Step 4: Implement prompt grouping** so the current character's complete basic set is present while rich candidates are structured and concise.
- [ ] **Step 5: Run focused tests plus `tests/test_face_evidence.py` and commit** `feat: add official basic face fallback`.

### Task 3: Upgrade direction prompts and deterministic演出 supplements

**Files:**
- Modify: `prompt.py` (`WAIT_POLICY`, `DIMENSIONS`, few-shot examples, action/emoticon rules)
- Modify: `direction_rules.py` (density and duplicate handling)
- Modify: `annotate.py` or the existing supplement module where high-confidence punctuation/semantic supplements are applied
- Test: `tests/test_balanced_direction_prompt.py`, `tests/test_direction_feedback_rules.py`, add targeted tests under `tests/`

**Interfaces:**
- Consumes: line text, previous direction state, face metadata from Task 2, scene tone/state.
- Produces: prompts that permit high-frequency comedy reactions; deterministic supplements for `Surprise`, `Steam`, `Dot`, and `jump` only when confidence is high; post-processing downgrades/replaces before deletion.

- [ ] **Step 1: Write failing tests** for `！？` → Surprise candidate, sustained complaint → Steam, forceful short rebuttal → jump, `总、总之！` → embarrassment/panic preference, and valid `Steam+hophop` retention.
- [ ] **Step 2: Run focused direction tests** and confirm current density rules remove these cases.
- [ ] **Step 3: Rewrite prompt policy** to remove “10 lines max 2–3 bubbles” and blanket adjacency bans; specify family/intensity/hold decision order and comedy/peak exceptions.
- [ ] **Step 4: Change post-processing** so semantic continuity can retain adjacent strong layers, while ordinary duplicates are merged or downgraded.
- [ ] **Step 5: Run prompt and direction suites and commit** `feat: improve semantic direction density`.

### Task 4: Add independent no-dialogue beat/wait protocol and compiler support

**Files:**
- Modify: `annotation_protocol.py` (optional `beats` schema and validation)
- Modify: `annotation_agent.py` (carry validated beats through checkpoint/result)
- Modify: `annotate.py` (apply beats to source items and preserve them through rendering)
- Modify: `document.py` and/or `script2aap.py` (compile empty-text reaction nodes with explicit wait without duplicate implicit waits)
- Test: `tests/test_model_asset_constraints.py`, `tests/test_annotation_protocol.py`, `tests/test_script_commands.py`, add beat/compiler tests

**Interfaces:**
- Consumes: `beats[]` records `{anchor_id, position, who, face, emo, act, wait_ms}`.
- Produces: validated independent empty-text nodes; ordinary line schema remains one-response-per-line; `wait_ms` is explicit and bounded.

- [ ] **Step 1: Write failing tests** for valid after-line beats, rejection of unknown anchors/illegal face IDs/negative or excessive waits, checkpoint round-trip, and output containing one empty-text node with `#wait;2500`.
- [ ] **Step 2: Run focused protocol/compiler tests** and confirm `wait` is currently unavailable in the agent schema.
- [ ] **Step 3: Implement schema and validation** with bounded milliseconds, source anchor validation, complete face/emoticon/action legality checks, and default empty arrays for old responses.
- [ ] **Step 4: Implement compilation** so explicit waits override rather than add to automatic bubble/action pauses; do not add a wait for appearance fades.
- [ ] **Step 5: Run protocol, document, and script tests and commit** `feat: support dialogue-free reaction beats`.

### Task 5: Implement appearance fade state without an extra pause

**Files:**
- Modify: `annotate.py` or the direction-state preparation module that owns visible-character history
- Modify: `script2aap.py` where `appear` is emitted, only if compiler semantics require a non-pausing flag/normalization
- Test: `tests/test_script_commands.py`, `tests/test_direction_feedback_rules.py`, add state-transition tests

**Interfaces:**
- Consumes: scene boundaries, visible character sets, effective dialogue count, and current positions.
- Produces: fade on current-scene first appearance, cross-scene reappearance, or reappearance after 8 effective dialogue lines; multi-person slot position; single-person centered position; no standalone wait.

- [ ] **Step 1: Write failing transition tests** for all three triggers, the 8-line threshold, short <8-line cuts, single-person centering, and multi-person normal slots.
- [ ] **Step 2: Run focused transition tests** and inspect current `appear` output and implicit timing.
- [ ] **Step 3: Implement a small explicit appearance state helper** with scene reset and per-character off-screen counters; attach fade to the first spoken node.
- [ ] **Step 4: Normalize compiler output** to ensure appearance flags do not create a separate empty node or explicit wait.
- [ ] **Step 5: Run script/direction suites and commit** `feat: make appearance fades stateful and non-blocking`.

### Task 6: Increase batch size while preserving scene/state boundaries and fallback

**Files:**
- Modify: `annotation_chunks.py` (natural chunk sizing defaults/constraints)
- Modify: `annotation_agent.py` (fallback subdivision and diagnostics)
- Modify: `annotate.py` (config defaults and short state/context payload)
- Modify: `aa_config.json` or example config only if defaults are stored there
- Test: `tests/test_annotation_chunks.py`, `tests/test_annotation_agent.py`, `tests/test_annotation_agent_scale.py`, add token/diagnostic assertions

**Interfaces:**
- Consumes: scenes, usage chain, checkpoint memory, complete static prompt, provider limits.
- Produces: target 40–50, soft 50, hard 60 default; automatic fallback `50 → 30 → 20` (then existing smaller subdivisions if still required); per-run request/token/time diagnostics.

- [ ] **Step 1: Write failing tests** for a 241-line scene producing approximately 5–6 primary chunks, scene boundaries never crossed, shared state remaining serial, and fallback diagnostics after a structured-output failure.
- [ ] **Step 2: Run chunk/agent scale tests** and record current 20/24/30 behavior.
- [ ] **Step 3: Raise defaults conservatively** and make fallback limits explicit without changing checkpoint identity semantics.
- [ ] **Step 4: Add compact state diagnostics** for request count, retries, token fields when provider exposes them, and elapsed time; keep unknown metrics nullable rather than guessed.
- [ ] **Step 5: Run chunk/agent suites and commit** `perf: batch scene annotation without quality loss`.

### Task 7: End-to-end regression, metrics, and documentation

**Files:**
- Modify: `tests/` with a fixture based on the “本日行程全部作废” examples
- Modify: `README.md` or `docs/commands.md` for official/basic/rich behavior and beat syntax
- Modify: `diagnostics.py` only if metric rendering needs a shared helper

**Interfaces:**
- Consumes: all outputs from Tasks 1–6.
- Produces: one reproducible regression fixture and a report comparing request count, token usage, elapsed time, legal-resource rate, direction density, and wait count.

- [ ] **Step 1: Add regression fixtures** covering Surprise, Steam, Dot, jump, hophop, the “总、总之！” embarrassment case, an official unlabelled character, a visually-labelled custom Spine, an appearance re-entry, and a 2500ms beat.
- [ ] **Step 2: Run the complete relevant test selection**: `pytest tests/test_spine_face_labeler.py tests/test_face_evidence.py tests/test_annotation_constraints.py tests/test_direction_feedback_rules.py tests/test_annotation_protocol.py tests/test_script_commands.py tests/test_annotation_chunks.py tests/test_annotation_agent.py tests/test_annotation_agent_scale.py -q`.
- [ ] **Step 3: Run the end-to-end fixture twice** with old and new batch settings; assert quality invariants and report performance deltas.
- [ ] **Step 4: Update user-facing docs** with the concise resource capability explanation and beat syntax.
- [ ] **Step 5: Commit** `test: cover AA direction and performance regression`.

## Self-Review Checklist

- [ ] Every design requirement has an implementation task: semantic axes (Task 1), official/custom fallback (Task 2), expressive direction (Task 3), beats/wait (Task 4), appearance state (Task 5), performance (Task 6), metrics and regression (Task 7).
- [ ] No task requires rich visual labels for official characters.
- [ ] No task removes full local allowlists or existing custom Spine rendering/caching.
- [ ] `beats` is optional so old responses remain valid.
- [ ] Appearance fade has no implicit explicit wait path.
- [ ] Token reduction is measured, not assumed.
