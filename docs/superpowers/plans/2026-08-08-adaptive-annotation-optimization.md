# Adaptive Annotation Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce annotation reasoning waste, empty-output loss, and avoidable cache misses without treating one model/script run as a universal chunk-size optimum.

**Architecture:** Keep the original script and rules as a stable request prefix. Replace the verbose model response with a compact indexed wire format that is expanded and validated locally, use model maximum output as the request capacity, preserve context-window metadata separately, retry reasoning-only empty responses once at a lower effort, and adapt chunk tiers only inside the current run.

**Tech Stack:** Python 3.12, stdlib HTTP/SSE, pytest, vanilla JavaScript, HTML/CSS.

## Global Constraints

- Existing checkpoints remain readable; a protocol version change creates a new run fingerprint instead of mutating old results.
- New model profiles default to thinking enabled at balanced effort.
- Unknown providers receive no guessed reasoning parameter.
- Request `max_tokens` follows the configured model maximum output.
- Chunk adaptation is run-local and never persists a universal best line count.
- No API keys, original screenplay text, or reasoning text enter request metrics.
- All production changes follow red-green-refactor.

---

### Task 1: Compact Indexed Annotation Protocol

**Files:**
- Modify: `annotation_protocol.py`
- Modify: `annotation_memory.py`
- Modify: `annotation_agent.py`
- Test: `tests/test_annotation_protocol.py`
- Test: `tests/test_annotation_memory.py`
- Test: `tests/test_annotation_agent.py`

**Interfaces:**
- Produces: `build_compact_chunk_schema(target_count: int) -> dict`
- Produces: `expand_compact_chunk_response(response, targets) -> dict`
- Consumes: existing `validate_chunk_response(...)` after expansion.

- [ ] Write failing tests proving the wire schema uses integer `i`, omits source hashes/default-empty fields, and rejects duplicate, missing, and out-of-range indices.
- [ ] Run the focused protocol and prompt tests and confirm failures are caused by the missing compact interfaces.
- [ ] Implement compact schema construction and deterministic expansion to the existing complete row protocol.
- [ ] Change TARGET rendering to use stable per-block indices and instruct the model not to restate rules, hashes, candidates, or empty fields.
- [ ] Route Agent responses through expansion and then the existing validator; bump the annotation protocol/fingerprint version.
- [ ] Run protocol, memory, Agent, constraints, and checkpoint tests.
- [ ] Commit the compact protocol independently.

### Task 2: Model Output and Context Capacity

**Files:**
- Modify: `model_capabilities.py`
- Modify: `model_profiles.py`
- Modify: `model_router.py`
- Modify: `llm.py`
- Modify: `webui.py`
- Test: `tests/test_model_capabilities.py`
- Test: `tests/test_model_profiles.py`
- Test: `tests/test_llm_profile_provider.py`
- Test: `tests/test_web_model_profiles.py`

**Interfaces:**
- Produces persisted `context_window_tokens`, `context_window_source`, and `recommended_context_window_tokens` model fields.
- Produces provider config where `annotation_max_tokens == max_tokens` for automatic profiles.
- Consumes remote `context_length` from normalized model records.

- [ ] Write failing tests for remote/catalog context-window resolution and automatic request capacity following model maximum output.
- [ ] Verify the tests fail against the current 16K/32K/64K automatic budget table.
- [ ] Persist context-window capability independently of maximum output and expose both through workbench APIs.
- [ ] Remove mode-derived automatic Agent budgets while preserving explicit legacy/manual compatibility only when deliberately configured.
- [ ] Make OpenAI/Anthropic annotation calls use the resolved model output capacity.
- [ ] Run capability, profile, router, provider, and web API tests.
- [ ] Commit capacity semantics independently.

### Task 3: Reasoning-Only Empty Response Recovery and Request Diagnostics

**Files:**
- Modify: `llm.py`
- Modify: `annotation_agent.py`
- Modify: `annotation_telemetry.py`
- Test: `tests/test_llm_profile_provider.py`
- Test: `tests/test_annotation_agent.py`
- Test: `tests/test_annotation_telemetry.py`

**Interfaces:**
- Produces `Provider.temporary_reasoning_mode(mode)` context manager.
- Produces request records with prefix/dynamic/schema hashes and target count.
- Consumes `EmptyModelResponseError` metadata: finish reason, reasoning chars/tokens, content chars.

- [ ] Write failing tests for exactly one lower-effort retry after `stop + reasoning + empty content` and no effort change for unrelated protocol errors.
- [ ] Write failing telemetry tests proving hashes are stable/sanitized and per-request cache fields remain intact.
- [ ] Attach structured metadata to empty-response exceptions and implement scoped effort override without mutating saved model settings.
- [ ] On the one allowed empty retry, lower deep to balanced, balanced to low, and low to speed only when the model capability supports it; append a direct-final-answer repair instruction.
- [ ] Record stable prefix, dynamic tail, schema hashes, target count, and retry reason on every completed request.
- [ ] Run provider, Agent, telemetry, and checkpoint tests.
- [ ] Commit recovery and diagnostics independently.

### Task 4: Run-Local Adaptive Chunk Tiers

**Files:**
- Modify: `annotation_chunks.py`
- Modify: `annotation_agent.py`
- Modify: `annotate.py`
- Test: `tests/test_annotation_chunks.py`
- Test: `tests/test_annotation_agent_scale.py`
- Test: `tests/test_annotate_main.py`

**Interfaces:**
- Produces `estimate_initial_chunk_limits(task_profile) -> ChunkLimits`.
- Produces `RunChunkController.observe(record) -> ChunkDecision`.
- Consumes context-window/output capacity, scene/role/resource complexity, target count, elapsed time, finish reason, reasoning/content ratio, and retry outcome.

- [ ] Write failing tests for different initial tiers across small/simple, long/multi-character, and constrained-context tasks.
- [ ] Write failing tests proving two successful low-ratio requests are required before growth, while capacity/empty/deadline failures shrink immediately.
- [ ] Implement bounded chunk tiers and hysteresis; do not persist learned limits beyond the current Agent call.
- [ ] Apply decisions only at future scene/chunk boundaries, preserving completed IDs and checkpoint compatibility.
- [ ] Record the initial estimate and each adaptation reason in diagnostics.
- [ ] Run chunk, scale, Agent, annotation main, and checkpoint tests.
- [ ] Commit adaptive chunking independently.

### Task 5: Discrete Reasoning Slider and End-to-End Verification

**Files:**
- Modify: `ui.html`
- Modify: `css/layout.css`
- Modify: `js/model.js`
- Modify: `js/app.js`
- Test: `tests/test_ui_model_workbench.py`
- Test: `tests/test_model_profiles.py`

**Interfaces:**
- Consumes existing normalized values `speed`, `low`, `balanced`, `deep`, and `provider_default`.
- Produces an accessible segmented range control whose value is submitted as `reasoning_mode`.

- [ ] Write failing DOM/helper tests for the four discrete labels, balanced default, capability-filtered speed option, and persisted value.
- [ ] Replace the select with an accessible fixed-track slider/segmented control and keep a synchronized text label and hint.
- [ ] Verify keyboard arrows, click/drag, unknown-provider fallback, narrow layout, and no text overlap.
- [ ] Run all model workbench/UI tests, then the complete pytest suite and `git diff --check`.
- [ ] Restart the local server and verify the model editor in the in-app browser at desktop and narrow viewports.
- [ ] Generate V3 from `多人物多场景测试_测试列车大冒险`, verify five selected backgrounds remain, and compare V3 against V2 for wall time, uncached input, reasoning, content, requests, retries, and subdivisions.
- [ ] Commit the UI and verification-compatible changes.

