# Annotation Request Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Record enough request-level, redacted telemetry to explain cache misses and reasoning-only responses without storing prompts, script text, raw reasoning, or secrets.

**Architecture:** The OpenAI-compatible provider creates one bounded telemetry record per request from usage and stream phase counters. The annotation agent attaches scene/chunk/retry metadata and returns an aggregate plus bounded recent records. Existing prompt construction, stable cache prefix, retry limits, and checkpoint payloads remain unchanged; the web layer exposes only the numeric/status telemetry needed by the current progress UI.

**Tech Stack:** Python stdlib, existing provider/annotation agent/job APIs, pytest, existing browser harness.

## Global Constraints

- Never store or expose prompt text, source script, API keys, or raw `reasoning_content`.
- Cache hit rate is `cache_read / (cache_read + cache_miss)` and excludes output tokens.
- Keep the current `annotation_max_tokens` budget and source-context policy unchanged until telemetry proves a budget or prefix problem.
- Preserve checkpoint/resume behavior and the existing one-retry empty-response recovery.

### Task 1: Provider Request Records

**Files:**
- Modify: `llm.py` (`Provider` stats and `OpenAIProvider` completion paths)
- Test: `tests/test_llm_profile_provider.py`

**Interfaces:**
- Produces `Provider.stats["request_records"]`, a bounded list of records containing request index, input/cached/missed/output tokens, reasoning/content character counts, elapsed/first-phase timings, and finish reason.
- Produces no prompt or response text in records.

- [ ] Write a failing test for a streamed request with usage details and reasoning/content deltas; assert one redacted record and correct cache fields.
- [ ] Run `pytest tests/test_llm_profile_provider.py::test_openai_stream_request_record_captures_redacted_usage -q` and verify failure because request records do not exist.
- [ ] Implement a small record helper and append one record on every completed or empty-response stream, preserving existing aggregate stats.
- [ ] Run the targeted test and the existing provider tests; verify all pass.

### Task 2: Agent Chunk Attribution

**Files:**
- Modify: `annotation_agent.py`
- Test: `tests/test_annotation_agent.py`

**Interfaces:**
- Adds `scene_id`, `chunk_id`, `request_index`, `retry_count`, and `subdivision_count` to copied request records.
- Returns `metrics.request_records` with a bounded list and aggregate counts; no checkpoint schema expansion is required.

- [ ] Write a failing agent test using a fake provider record and assert chunk/retry attribution plus no prompt fields.
- [ ] Run the targeted test and verify failure.
- [ ] Copy provider records at request boundaries, attach current chunk metadata, and cap retained records to prevent unbounded memory growth.
- [ ] Run annotation-agent tests and verify existing retry/checkpoint assertions remain unchanged.

### Task 3: Web/UI Presentation

**Files:**
- Modify: `webui.py`, `js/app.js`
- Test: `tests/test_web_draft_endpoints.py`, `tests/test_ui_runtime_behavior.py`

**Interfaces:**
- Draft result exposes existing aggregate metrics plus `request_records` with only redacted numeric/status fields.
- Completion text shows separate input cache hit rate and output token count; active progress keeps raw reasoning hidden.

- [ ] Add endpoint/UI regression tests for the new fields and labels.
- [ ] Run tests to verify failure.
- [ ] Thread metrics through the existing job result without introducing a new endpoint or persistence store.
- [ ] Run endpoint and UI tests, then capture one browser snapshot of the completion summary.

### Task 4: Verification and Commit

**Files:**
- Modify: `docs/superpowers/specs/2026-08-08-stable-script-cache-prefix-design.md` only if telemetry findings require a documented correction.

- [ ] Run `python -m py_compile llm.py annotation_agent.py webui.py` and `git diff --check`.
- [ ] Run `pytest -q` and require the complete suite to finish with zero failures.
- [ ] Review the diff for secrets, prompt text, source text, and raw reasoning leakage.
- [ ] Commit the implementation and tests with a focused message.
