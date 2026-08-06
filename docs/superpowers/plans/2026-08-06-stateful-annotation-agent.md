# Stateful Annotation Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fixed, context-poor screenplay annotation batches with a scene-aware, checkpointed Agent that preserves verified state and relevant story events across thousands of lines without increasing each model request with total script length.

**Architecture:** Add focused modules for stable annotation identities and semantic chunks, structured model protocol validation, persistent memory/checkpoints, event retrieval, orchestration, and final consistency review. Keep `annotate.py` as the compatible entry point and reuse its resource filtering, proposals, deterministic supplements, density normalization, rendering, and Provider abstraction.

**Tech Stack:** Python 3.9+ standard library, existing OpenAI/Anthropic-compatible `llm.Provider`, JSON Schema structured output, pytest, existing `JobManager` and browser runtime tests.

## Global Constraints

- Do not alter, add, delete, or rewrite screenplay dialogue text.
- Do not modify AA executables, configuration, AssetBundles, workspace files, or timestamps.
- Do not use a provider's hidden chat session as business state; all durable state must be local, versioned JSON.
- Do not add a vector database, external retrieval service, or agent framework in the first version.
- Normal target chunks contain 20-40 dialogue items; the hard limit is 60.
- Each target source item must appear exactly once in a validated model response.
- A failed chunk must never partially update annotations, memory, or progress.
- `annotate_script(options, provider_instance=None)` and its existing return keys remain compatible.
- Existing resource allowlists, proposals, deterministic supplements, density normalization, rendering, draft review, and AA compilation remain authoritative.
- Preserve unrelated dirty-worktree changes and stage only files owned by the current task.

---

## File Map

- Create `annotation_chunks.py`: stable annotation IDs, deterministic scene detection, natural chunk boundaries, retry subdivision, context windows.
- Create `annotation_protocol.py`: Agent response schemas, exact target coverage checks, source fingerprint checks, state/event structural validation.
- Create `annotation_memory.py`: versioned state models, event index and retrieval, context assembly, atomic checkpoint persistence and cache keys.
- Create `annotation_agent.py`: planning, per-chunk request orchestration, retries, transactional application, cancellation/progress, final review.
- Modify `annotate.py`: parse stable identities, expose reusable application helpers, select Agent or legacy path, preserve public result contract.
- Modify `webui.py`: pass checkpoint/progress/cancellation inputs and report meaningful annotation phases.
- Modify `js/app.js`: display live `Job.detail` during annotation polling without changing the workflow layout.
- Modify `prepare_release.py`: include the four new runtime modules in release output.
- Create focused tests: `test_annotation_chunks.py`, `test_annotation_protocol.py`, `test_annotation_memory.py`, `test_annotation_agent.py`.
- Extend existing integration/UI tests only where the public entry point or progress behavior changes.

Each new test file must define the small fixtures used by its snippets (`make_items`, `complete_response`, `run_agent_fixture`, fake Providers, and checkpoint readers) directly above the first test that needs them. These helpers construct only the exact plain dictionaries required by the public interfaces listed for that task; they must not depend on helpers from another test module.

---

### Task 1: Stable Target Identities and Natural Chunks

**Files:**
- Create: `annotation_chunks.py`
- Modify: `annotate.py:522`
- Test: `tests/test_annotation_chunks.py`
- Test: `tests/test_source_id_flow.py`

**Interfaces:**
- Produces: `assign_annotation_ids(items: list[dict]) -> list[dict]`
- Produces: `build_scene_map(items: list[dict], usage_chain: list[dict] | None = None) -> list[dict]`
- Produces: `build_chunks(items: list[dict], scenes: list[dict], target=30, soft_limit=40, hard_limit=60) -> list[dict]`
- Produces: `subdivide_chunk(chunk: dict, maximum: int) -> list[dict]`
- Produces: `context_indices(dialogue_indices: list[int], chunk: dict, before=15, after=10) -> tuple[list[int], list[int]]`
- A target ID is `src-<1-based physical line>-<split_index>-<12 hex chars>` where the suffix is SHA-256 over normalized speaker and text. It is reproducible and does not reuse draft UUIDs.

- [ ] **Step 1: Write failing identity tests**

```python
from annotation_chunks import assign_annotation_ids


def test_annotation_ids_are_stable_and_distinguish_split_segments():
    original = [
        {"kind": "line", "line_no": 7, "split_index": 0, "who": "凯伊", "text": "前半。"},
        {"kind": "line", "line_no": 7, "split_index": 1, "who": "凯伊", "text": "后半。"},
    ]
    first = assign_annotation_ids([dict(item) for item in original])
    second = assign_annotation_ids([dict(item) for item in original])
    assert [item["annotation_id"] for item in first] == [item["annotation_id"] for item in second]
    assert first[0]["annotation_id"] != first[1]["annotation_id"]
    assert first[0]["text_fingerprint"] != first[1]["text_fingerprint"]
```

- [ ] **Step 2: Run the identity test and verify it fails**

Run: `python -m pytest tests/test_annotation_chunks.py::test_annotation_ids_are_stable_and_distinguish_split_segments -v`

Expected: FAIL because `annotation_chunks` does not exist.

- [ ] **Step 3: Implement stable IDs and preserve physical line numbers during parsing**

```python
# annotation_chunks.py
import hashlib


def _fingerprint(who, text):
    value = f"{str(who).strip()}\n{str(text).strip()}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def assign_annotation_ids(items):
    for ordinal, item in enumerate(items, 1):
        if item.get("kind") != "line":
            continue
        line_no = int(item.get("line_no") or ordinal)
        split_index = int(item.get("split_index") or 0)
        fingerprint = _fingerprint(item.get("who"), item.get("text"))
        item["text_fingerprint"] = fingerprint
        item["annotation_id"] = f"src-{line_no}-{split_index}-{fingerprint[:12]}"
    return items
```

Change `parse_lines()` to enumerate physical lines and attach `line_no` and `split_index=0` to dialogue items. Keep `dialogue_pacing.split_strong_dialogue_items()` responsible for incrementing split indexes.

- [ ] **Step 4: Add failing scene and chunk boundary tests**

```python
from annotation_chunks import build_chunks, build_scene_map, context_indices


def test_explicit_separator_closes_scene_and_chunk():
    items = make_items([
        ("旁白", "商店街入口。"),
        ("凯伊", "走吧。"),
        None,
        ("旁白", "游戏中心里。"),
        ("老师", "到了。"),
    ], separator_index=2)
    scenes = build_scene_map(items)
    chunks = build_chunks(items, scenes, target=20, soft_limit=40, hard_limit=60)
    assert [scene["target_indices"] for scene in scenes] == [[0, 1], [3, 4]]
    assert [chunk["target_indices"] for chunk in chunks] == [[0, 1], [3, 4]]


def test_chunk_uses_bounded_past_and_future_windows():
    dialogue = list(range(100))
    past, future = context_indices(dialogue, {"target_indices": list(range(30, 60))})
    assert past == list(range(15, 30))
    assert future == list(range(60, 70))
```

- [ ] **Step 5: Run the boundary tests and verify they fail**

Run: `python -m pytest tests/test_annotation_chunks.py -v`

Expected: identity test passes; scene/chunk tests FAIL because boundary functions are missing.

- [ ] **Step 6: Implement deterministic scene and semantic chunk construction**

Implement explicit boundary priority in this order: `---`/scene headings, `usage_chain` line ranges, narration that clearly changes location/time, then nearest completed dialogue turn before limits. A chunk may extend from 40 to at most 60 target lines to close a turn. `subdivide_chunk()` must preserve scene ID and return contiguous target sets of at most the requested maximum.

- [ ] **Step 7: Run focused and source identity tests**

Run: `python -m pytest tests/test_annotation_chunks.py tests/test_source_id_flow.py -v`

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```powershell
git add -- annotation_chunks.py annotate.py tests/test_annotation_chunks.py tests/test_source_id_flow.py
git commit -m "feat: add scene-aware annotation chunks"
```

---

### Task 2: Strict Agent Response Protocol

**Files:**
- Create: `annotation_protocol.py`
- Create: `tests/test_annotation_protocol.py`
- Modify: `annotate.py:445`

**Interfaces:**
- Produces: `build_chunk_schema(target_ids: list[str]) -> dict`
- Produces: `validate_chunk_response(response: object, targets: list[dict]) -> dict`
- Produces: `ChunkProtocolError(code: str, detail: str, retryable: bool = True)`
- Validated output is `{"lines_by_id": dict[str, dict], "state_delta": dict, "memory_events": list[dict]}`.
- Consumes existing `filter_annotation_row()` later; this task validates identity and structure, not resource semantics.

- [ ] **Step 1: Write exact-coverage failure tests**

```python
import pytest
from annotation_protocol import ChunkProtocolError, validate_chunk_response


TARGETS = [
    {"annotation_id": "src-1-0-a", "text_fingerprint": "fp-a"},
    {"annotation_id": "src-2-0-b", "text_fingerprint": "fp-b"},
]


@pytest.mark.parametrize("lines,code", [
    ([{"source_id": "src-1-0-a", "text_fingerprint": "fp-a"}], "missing_target"),
    ([
        {"source_id": "src-1-0-a", "text_fingerprint": "fp-a"},
        {"source_id": "src-1-0-a", "text_fingerprint": "fp-a"},
    ], "duplicate_target"),
    ([
        {"source_id": "src-1-0-a", "text_fingerprint": "fp-a"},
        {"source_id": "future", "text_fingerprint": "fp-b"},
    ], "unknown_target"),
])
def test_response_requires_exact_target_coverage(lines, code):
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response({"lines": lines, "state_delta": {}, "memory_events": []}, TARGETS)
    assert exc.value.code == code
```

- [ ] **Step 2: Run coverage tests and verify failure**

Run: `python -m pytest tests/test_annotation_protocol.py -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement schema and exact identity validation**

The schema must require all existing annotation fields plus `source_id` and `text_fingerprint`. Use a string enum of target IDs for `source_id`, set top-level `additionalProperties` to `False`, and require `lines`, `state_delta`, and `memory_events`.

`validate_chunk_response()` must reject, in order: non-object response, non-array lines, duplicate IDs, unknown IDs, missing IDs, and fingerprint mismatch. It must return rows keyed by source ID only after the complete set passes.

- [ ] **Step 4: Add state/event validation tests**

```python
def test_state_and_events_must_use_whitelisted_shape():
    response = complete_response(TARGETS)
    response["state_delta"] = {"api_key": "secret"}
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response(response, TARGETS)
    assert exc.value.code == "invalid_state_delta"


def test_event_requires_visible_source_evidence():
    response = complete_response(TARGETS)
    response["memory_events"] = [{
        "kind": "callback", "participants": ["凯伊"], "keywords": ["称呼"],
        "summary": "发生了称呼变化", "source_ids": ["not-visible"],
        "evidence": "证据", "importance": 0.8, "status": "open",
    }]
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response(response, TARGETS)
    assert exc.value.code == "invalid_event_source"
```

- [ ] **Step 5: Implement state and event structural allowlists**

Allow only `background`, `place`, `bgfx`, `visible_characters`, `positions`, `last_faces`, `recent_emoticons`, `recent_actions`, `recent_sounds`, and `open_threads` inside `state_delta`. Require each event to contain `kind`, `participants`, `keywords`, `summary`, `source_ids`, `evidence`, `importance`, and `status`; source IDs must be visible in targets or supplied past/future context IDs.

- [ ] **Step 6: Replace the static annotation Schema builder without changing the legacy path**

Keep the existing `SCHEMA` for legacy tests and compatibility. Import `build_chunk_schema` for Agent requests only. Do not change `annotation_rows()` behavior in this task.

- [ ] **Step 7: Run protocol and legacy JSON tests**

Run: `python -m pytest tests/test_annotation_protocol.py tests/test_llm_json.py tests/test_annotate_main.py -v`

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```powershell
git add -- annotation_protocol.py annotate.py tests/test_annotation_protocol.py
git commit -m "feat: validate complete annotation chunks"
```

---

### Task 3: Structured Direction State and Bounded Context

**Files:**
- Create: `annotation_memory.py`
- Create: `tests/test_annotation_memory.py`
- Modify: `annotate.py:343`

**Interfaces:**
- Produces: `initial_memory(story_summary: str = "") -> dict`
- Produces: `apply_state_delta(memory: dict, delta: dict, *, cast: dict, constraints: dict) -> dict`
- Produces: `complete_scene(memory: dict, scene: dict, summary: str) -> dict`
- Produces: `assemble_chunk_context(items, chunk, memory, events, usage_chain, *, before=15, after=10, max_events=8) -> tuple[str, str]`
- State updates return a new dictionary; callers never mutate a committed checkpoint in place.

- [ ] **Step 1: Write failing state lifecycle tests**

```python
from annotation_memory import apply_state_delta, initial_memory


def test_state_delta_preserves_background_and_rejects_unknown_character():
    memory = initial_memory("约会故事")
    updated = apply_state_delta(
        memory,
        {"background": "BG_Street", "visible_characters": ["凯伊"],
         "last_faces": {"不存在": "03"}},
        cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints={"ok_bg": {"BG_Street"}, "faces_by_id": {"kei": {"03"}}},
    )
    assert updated["direction"]["background"] == "BG_Street"
    assert updated["direction"]["visible_characters"] == ["凯伊"]
    assert "不存在" not in updated["direction"]["last_faces"]


def test_transient_effect_is_not_persisted_as_background_state():
    memory = initial_memory()
    updated = apply_state_delta(
        memory, {"bgfx": "集中线"}, cast={}, constraints={"ok_bg": set(), "faces_by_id": {}}
    )
    assert updated["direction"]["bgfx"] is None
```

- [ ] **Step 2: Run lifecycle tests and verify failure**

Run: `python -m pytest tests/test_annotation_memory.py -v`

Expected: FAIL because `annotation_memory` does not exist.

- [ ] **Step 3: Implement versioned memory defaults and validated state merge**

Use plain JSON-compatible dictionaries with `schema_version=1`, `story`, `scene`, `direction`, `events`, and `progress`. Preserve weather-like background effects, but treat focus line, flashes and one-shot effects as transient using the same resolution rules as `normalize_bgfx_lifetime()`.

- [ ] **Step 4: Write bounded context tests**

```python
def test_context_marks_target_past_and_future_and_limits_events():
    volatile, user = assemble_chunk_context(
        items=make_80_items(),
        chunk={"scene_id": "scene-1", "target_indices": list(range(30, 50))},
        memory=memory_with_background("BG_Street"),
        events=make_events(12),
        usage_chain=[], before=15, after=10, max_events=8,
    )
    assert "CURRENT_DIRECTION_STATE" in volatile
    assert "BG_Street" in volatile
    assert user.count("[TARGET ") == 20
    assert user.count("[PAST_CONTEXT ") == 15
    assert user.count("[FUTURE_CONTEXT ") == 10
    assert volatile.count('"event-') == 8
    assert "不得标注 FUTURE_CONTEXT" in user
```

- [ ] **Step 5: Implement context assembly**

Reuse `build_batch_context()` and `build_face_usage_summary()` internally where useful, but add complete current direction state and recent sound/effect history. Put stable rules/resources in the existing static system string; put memory and events in the volatile system string; put marked source lines in the user string.

- [ ] **Step 6: Run memory and direction regression tests**

Run: `python -m pytest tests/test_annotation_memory.py tests/test_direction_feedback_rules.py tests/test_balanced_direction_prompt.py -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- annotation_memory.py annotate.py tests/test_annotation_memory.py tests/test_direction_feedback_rules.py
git commit -m "feat: carry annotation direction state"
```

---

### Task 4: Atomic Checkpoints and Cache Invalidation

**Files:**
- Modify: `annotation_memory.py`
- Modify: `tests/test_annotation_memory.py`

**Interfaces:**
- Produces: `build_run_fingerprint(script_text, cast, resources, prompt_version, schema_version, chunk_version, model_config) -> dict`
- Produces: `AnnotationCheckpointStore(root: str | Path)`
- `AnnotationCheckpointStore.load(run_key: str) -> dict | None`
- `AnnotationCheckpointStore.commit(run_key: str, state: dict) -> Path`
- `AnnotationCheckpointStore.resume_plan(saved: dict, current: dict, scenes: list[dict]) -> dict`
- Checkpoint file: `<root>/<run_key>/checkpoint.json`; writes use `.tmp` plus `os.replace`.

- [ ] **Step 1: Write atomic save and recovery tests**

```python
from annotation_memory import AnnotationCheckpointStore


def test_checkpoint_round_trip_and_no_temporary_file(tmp_path):
    store = AnnotationCheckpointStore(tmp_path)
    state = {"schema_version": 1, "progress": {"completed_chunks": ["chunk-1"]}}
    path = store.commit("run-a", state)
    assert store.load("run-a") == state
    assert path.name == "checkpoint.json"
    assert not list(tmp_path.rglob("*.tmp"))


def test_corrupt_checkpoint_is_ignored_without_deleting_it(tmp_path):
    path = tmp_path / "run-a" / "checkpoint.json"
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")
    store = AnnotationCheckpointStore(tmp_path)
    assert store.load("run-a") is None
    assert path.exists()
```

- [ ] **Step 2: Run checkpoint tests and verify failure**

Run: `python -m pytest tests/test_annotation_memory.py -k checkpoint -v`

Expected: FAIL because checkpoint methods are missing.

- [ ] **Step 3: Implement canonical fingerprints and atomic persistence**

Canonicalize JSON with sorted keys and compact separators. Never persist API keys, authorization headers, provider config dictionaries, or absolute source paths. Store only provider name, model, and semantic settings such as maximum output tokens.

- [ ] **Step 4: Write invalidation range tests**

```python
def test_middle_scene_edit_reuses_prefix_and_invalidates_following_state():
    saved = saved_fingerprints(scene_hashes=["a", "old-b", "c"])
    current = saved_fingerprints(scene_hashes=["a", "new-b", "c"])
    plan = store.resume_plan(saved, current, scenes=three_scenes())
    assert plan["reuse_scene_ids"] == ["scene-1"]
    assert plan["restart_scene_id"] == "scene-2"
    assert plan["reuse_after_restart"] is False


def test_prompt_change_invalidates_chunks_but_keeps_compatible_scene_map():
    plan = store.resume_plan(saved_run(prompt="v1"), current_run(prompt="v2"), three_scenes())
    assert plan["reuse_scene_map"] is True
    assert plan["reuse_chunk_results"] is False
```

- [ ] **Step 5: Implement conservative invalidation rules**

Use the first changed scene as the restart point. Never reuse later state after a changed scene, even when later scene text hashes match. Cast changes restart at the first scene containing an affected speaker. Resource changes restart at the first scene using an affected capability when exact affected keys are known; otherwise restart the first scene. Prompt/Schema changes invalidate model chunk results but may retain a structurally compatible scene map.

- [ ] **Step 6: Run checkpoint tests**

Run: `python -m pytest tests/test_annotation_memory.py -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- annotation_memory.py tests/test_annotation_memory.py
git commit -m "feat: checkpoint annotation agent state"
```

---

### Task 5: Story Planning and Evidence-Backed Event Retrieval

**Files:**
- Modify: `annotation_memory.py`
- Create: `tests/test_annotation_planning.py`
- Modify: `prompt.py`

**Interfaces:**
- Produces: `build_story_plan(items: list[dict], scenes: list[dict], usage_chain: list[dict]) -> dict`
- Produces: `merge_memory_events(existing: list[dict], candidates: list[dict], visible_items: list[dict]) -> list[dict]`
- Produces: `retrieve_events(events: list[dict], items: list[dict], scene_id: str, limit=8) -> list[dict]`
- `build_story_plan()` consumes confirmed `usage_chain` first and uses deterministic scene facts for missing fields. It does not make a second full-text model call in version 1; chunk responses accumulate semantic events with exact evidence.

- [ ] **Step 1: Write plan construction tests**

```python
from annotation_memory import build_story_plan


def test_confirmed_usage_chain_names_scene_and_preserves_evidence():
    plan = build_story_plan(items(), scenes(), [{
        "segment": "转场", "location": "夜间天台", "start": "第21行", "end": "第40行",
        "evidence": "夜色中的天台。", "needs": [],
    }])
    assert plan["scenes"][1]["location"] == "夜间天台"
    assert plan["scenes"][1]["evidence"] == "夜色中的天台。"


def test_no_usage_chain_produces_deterministic_story_summary():
    plan = build_story_plan(items(), scenes(), [])
    assert plan["summary"]
    assert set(plan["speakers"]) == {"凯伊", "老师", "旁白"}
```

- [ ] **Step 2: Run planning tests and verify failure**

Run: `python -m pytest tests/test_annotation_planning.py -v`

Expected: FAIL because planning functions are missing.

- [ ] **Step 3: Implement deterministic plan construction**

Map `usage_chain` segments to scenes using parsed line references and overlapping evidence. For unmapped scenes, derive a compact summary from headings, the first narration, speakers, and first/last dialogue; never invent relationship claims.

- [ ] **Step 4: Write event merge and retrieval tests**

```python
def test_event_without_exact_evidence_is_dropped():
    visible = [{"annotation_id": "src-4", "text": "才不是凯伊酱好吗！"}]
    candidates = [event(source_ids=["src-4"], evidence="不存在的台词")]
    assert merge_memory_events([], candidates, visible) == []


def test_open_name_callback_beats_unrelated_recent_event():
    selected = retrieve_events(
        [name_event(status="open", importance=.9), unrelated_recent_event(importance=.95)],
        [{"who": "老师", "text": "凯伊酱老师？"}], "scene-3", limit=1,
    )
    assert selected[0]["kind"] == "relationship_callback"
```

- [ ] **Step 5: Implement evidence checks, deduplication and structured retrieval**

Score participant overlap, exact keyword occurrence, same/adjacent scene, open status, and importance. Deduplicate on normalized `kind + participants + keywords + evidence source IDs`. Keep all accepted events in the checkpoint but inject only the top eight into a request.

- [ ] **Step 6: Extend prompt rules for memory discipline**

Add concise rules stating that `memory_events` are only for cross-window facts, require quoted evidence, cannot turn speculation into fact, and must not store ordinary face/action changes. Add a prompt contract test asserting these phrases are present.

- [ ] **Step 7: Run planning and prompt tests**

Run: `python -m pytest tests/test_annotation_planning.py tests/test_balanced_direction_prompt.py -v`

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```powershell
git add -- annotation_memory.py prompt.py tests/test_annotation_planning.py tests/test_balanced_direction_prompt.py
git commit -m "feat: retrieve evidence-backed story memory"
```

---

### Task 6: Transactional Annotation Agent Orchestration

**Files:**
- Create: `annotation_agent.py`
- Create: `tests/test_annotation_agent.py`
- Modify: `annotate.py:659`
- Modify: `llm.json.example`

**Interfaces:**
- Produces: `run_annotation_agent(items, *, provider, static_system, cast, constraints, usage_chain, checkpoint_store, run_fingerprint, progress=None, cancelled=None) -> dict`
- Produces: `AnnotationAgentError(stage: str, scene_id: str, chunk_id: str, detail: str)`
- Progress callback: `progress(phase: str, current: int, total: int, detail: str) -> None`
- Cancellation callback: `cancelled() -> bool`; cancellation occurs only between Provider calls and before checkpoint commit.
- Returns `{"items": list[dict], "memory": dict, "diagnostics": list[dict], "completed_chunks": int, "resumed_chunks": int}`.

- [ ] **Step 1: Write a happy-path multi-chunk test**

```python
def test_agent_carries_state_and_event_into_next_chunk(tmp_path):
    provider = RecordingProvider([
        response_for_chunk(0, background="BG_Street", event=name_callback()),
        response_for_chunk(1),
    ])
    result = run_agent_fixture(tmp_path, provider, line_count=70)
    assert provider.calls == 2
    assert "BG_Street" in provider.requests[1]["volatile"]
    assert "凯伊酱" in provider.requests[1]["volatile"]
    assert result["completed_chunks"] == 2
```

- [ ] **Step 2: Run the Agent test and verify failure**

Run: `python -m pytest tests/test_annotation_agent.py::test_agent_carries_state_and_event_into_next_chunk -v`

Expected: FAIL because `annotation_agent` does not exist.

- [ ] **Step 3: Implement per-chunk orchestration and transactional application**

For each chunk: assemble context, build the target-specific Schema, call `provider.complete_json`, validate exact coverage, filter each annotation row through existing resource constraints, apply rows to a deep copy of current items, merge validated state/events into a copied memory state, then atomically commit the checkpoint. Publish copied state to the live run only after the commit succeeds.

- [ ] **Step 4: Write retry subdivision tests**

```python
def test_truncated_chunk_retries_then_subdivides_without_partial_commit(tmp_path):
    provider = ProviderThatOmitsLastLineUntilMaximum(10)
    result = run_agent_fixture(tmp_path, provider, line_count=25)
    assert provider.request_sizes == [25, 25, 20, 5]
    assert all(item.get("agent_applied") for item in result["items"] if item["kind"] == "line")
    assert result["memory"]["progress"]["completed_target_ids"] == target_ids(result["items"])


def test_failed_minimum_chunk_keeps_previous_checkpoint(tmp_path):
    provider = ProviderThatFailsAfterFirstChunk()
    with pytest.raises(AnnotationAgentError):
        run_agent_fixture(tmp_path, provider, line_count=50)
    saved = checkpoint(tmp_path)
    assert saved["progress"]["completed_chunks"] == ["scene-1-chunk-1"]
```

- [ ] **Step 5: Implement correction retry, subdivision and failure diagnostics**

Retry the same chunk once with a compact correction message naming missing/duplicate IDs. On a second structural failure or detected truncation, subdivide to the next maximum size in `20, 10, 5`; do not retry Provider/auth/network errors that are classified non-retryable by `LLMError`. Preserve the last successful checkpoint on terminal failure.

- [ ] **Step 6: Write resume and cancellation tests**

```python
def test_resume_skips_completed_provider_calls(tmp_path):
    run_agent_fixture(tmp_path, RecordingProvider.two_chunks(), line_count=70)
    resumed = RecordingProvider.one_chunk()
    result = run_agent_fixture(tmp_path, resumed, line_count=90)
    assert resumed.calls == 1
    assert result["resumed_chunks"] == 2


def test_cancellation_stops_before_next_call_and_keeps_checkpoint(tmp_path):
    cancelled = CancelAfterCalls(1)
    result = run_agent_fixture(tmp_path, RecordingProvider.many(), line_count=90, cancelled=cancelled)
    assert result["cancelled"] is True
    assert checkpoint(tmp_path)["progress"]["completed_chunks"] == ["scene-1-chunk-1"]
```

- [ ] **Step 7: Integrate the Agent into `annotate_script()`**

Add `agent_enabled` defaulting to `True`, `checkpoint_dir`, `progress`, and `cancelled` options. Keep `agent_enabled=False` as an internal regression switch. Convert validated Agent rows into the same proposals, dropped diagnostics and final `items` used by existing supplements/normalizers/rendering. Preserve return keys and add non-breaking `agent` metadata.

Set new defaults in `llm.json.example`: `agent_enabled: true`, `agent_target_lines: 30`, `agent_soft_limit: 40`, `agent_hard_limit: 60`, `agent_context_before: 15`, `agent_context_after: 10`.

- [ ] **Step 8: Run Agent and entry-point tests**

Run: `python -m pytest tests/test_annotation_agent.py tests/test_annotate_main.py tests/test_annotation_constraints.py tests/test_direction_feedback_rules.py -v`

Expected: PASS.

- [ ] **Step 9: Commit Task 6**

```powershell
git add -- annotation_agent.py annotate.py llm.json.example tests/test_annotation_agent.py tests/test_annotate_main.py
git commit -m "feat: orchestrate stateful screenplay annotation"
```

---

### Task 7: Deterministic and Semantic Consistency Review

**Files:**
- Modify: `annotation_agent.py`
- Modify: `annotation_protocol.py`
- Modify: `tests/test_annotation_agent.py`
- Modify: `performance_rules.py`

**Interfaces:**
- Produces: `build_review_windows(items, scenes, events) -> list[dict]`
- Produces: `validate_review_patches(response, items, constraints) -> list[dict]`
- Produces: `apply_review_patches(items, patches) -> tuple[list[dict], list[dict]]`
- Review patches contain `source_id`, `field`, `before`, `after`, `reason`, and `evidence_source_ids`.

- [ ] **Step 1: Write boundary review tests**

```python
def test_review_windows_include_adjacent_chunk_boundaries_and_open_events():
    windows = build_review_windows(items(), scenes(), [name_callback(status="open")])
    assert any(window["kind"] == "chunk_boundary" for window in windows)
    assert any("凯伊酱" in window["context"] for window in windows)


def test_review_patch_cannot_change_dialogue_or_unseen_line():
    response = {"patches": [
        {"source_id": "src-2", "field": "text", "before": "原文", "after": "改写", "reason": "润色", "evidence_source_ids": ["src-2"]},
        {"source_id": "unknown", "field": "face", "before": "01", "after": "03", "reason": "调整", "evidence_source_ids": ["src-2"]},
    ]}
    assert validate_review_patches(response, items(), constraints()) == []
```

- [ ] **Step 2: Run review tests and verify failure**

Run: `python -m pytest tests/test_annotation_agent.py -k review -v`

Expected: FAIL because review functions are missing.

- [ ] **Step 3: Implement deterministic review windows and patch protocol**

Always run deterministic coverage, resource, density, background lifetime and repeated-sound checks. Build model review windows only around chunk boundaries, scene transitions and open-event callbacks; do not resend the whole script. Allow patches only for existing annotation fields, require `before` to match current state, and pass `after` through the same resource constraints.

- [ ] **Step 4: Add semantic review failure degradation test**

```python
def test_semantic_review_failure_keeps_validated_chunk_output(tmp_path):
    provider = ProviderWithFailingReview(valid_chunk_responses())
    result = run_agent_fixture(tmp_path, provider, line_count=70)
    assert result["completed_chunks"] == 2
    assert any(d["code"] == "semantic_review_failed" for d in result["diagnostics"])
    assert rendered_dialogue_count(result["items"]) == 70
```

- [ ] **Step 5: Implement optional semantic review and proposal audit**

Run semantic review only after all chunks succeed. A failed review adds a warning and leaves chunk output intact. Applied review patches create `applied_pending` proposals with `origin="model_review"`; rejected patches create `suggested_fix` diagnostics and do not alter items.

- [ ] **Step 6: Run review and performance tests**

Run: `python -m pytest tests/test_annotation_agent.py tests/test_balanced_direction_rules.py tests/test_direction_feedback_rules.py -v`

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```powershell
git add -- annotation_agent.py annotation_protocol.py performance_rules.py tests/test_annotation_agent.py
git commit -m "feat: review cross-chunk direction consistency"
```

---

### Task 8: Web Progress, Resume Integration, and Release Packaging

**Files:**
- Modify: `webui.py:2657`
- Modify: `js/app.js:1590`
- Modify: `prepare_release.py:19`
- Modify: `tests/test_web_draft_endpoints.py`
- Modify: `tests/test_ui_runtime_behavior.py`
- Modify: `tests/test_ui_runtime_transitions.py`
- Modify: `tests/test_prepare_release_entry.py`

**Interfaces:**
- `annotate_draft_worker(payload, job=None)` passes `job.update_progress` and `job.is_cancel_requested` into `annotate_script()`.
- Checkpoint root is `out/annotation-checkpoints`; the run key derives from safe content/config fingerprints, not a Job ID or absolute path.
- `Job.detail` uses one of: `正在分析场景`, `正在标注第 N/M 个场景`, `正在检查全文一致性`, `已从检查点继续`, `标注已暂停，可继续`.

- [ ] **Step 1: Write worker progress and cancellation tests**

```python
def test_annotation_worker_forwards_job_callbacks(tmp_path, monkeypatch):
    captured = {}
    class ANN:
        @staticmethod
        def annotate_script(options, provider_instance=None):
            captured.update(options)
            options["progress"]("annotating", 1, 3, "正在标注第 1/3 个场景")
            return {"text": "凯伊: 好。\n", "proposals": [], "diagnostics": []}
    job = FakeJob()
    result = webui.annotate_draft_worker(valid_payload(tmp_path), job=job)
    assert callable(captured["cancelled"])
    assert job.details[-1] == "正在标注第 1/3 个场景"
    assert result["draft_token"]
```

- [ ] **Step 2: Run worker tests and verify failure**

Run: `python -m pytest tests/test_web_draft_endpoints.py -k annotation_worker_forwards -v`

Expected: FAIL because the worker does not accept a Job.

- [ ] **Step 3: Wire Job progress, cancellation, checkpoints and resume metadata**

Pass the active Job from the `/api/annotate` closure. Convert Agent phases to monotonically increasing progress: planning 0-10%, chunks 10-90%, review 90-98%, draft persistence 98-100%. If cancellation is observed, mark the Job cancelled and do not create a partial draft; keep the Agent checkpoint for a later identical request.

- [ ] **Step 4: Write UI polling detail test**

```javascript
const job = {state:'running', progress:42, detail:'正在标注第 2/6 个场景'};
// The poll callback receives job before the terminal response.
assert.equal(nodes.log.textContent.includes('正在标注第 2/6 个场景'), true);
```

Place the executable harness assertion in `tests/test_ui_runtime_behavior.py`; do not add a new panel or alter the workflow steps.

- [ ] **Step 5: Render live Job detail in the existing annotation status/log area**

Pass an `onProgress` callback to `Api.poll` if supported by the existing helper; otherwise update the helper so each successful poll snapshot can be observed while preserving existing terminal predicates and retry behavior. Deduplicate identical detail strings so polling does not flood the log.

- [ ] **Step 6: Add release packaging tests and module list**

Extend `prepare_release.CODE` with `annotation_chunks.py`, `annotation_protocol.py`, `annotation_memory.py`, and `annotation_agent.py`. Assert all four names are present in the release entry test.

- [ ] **Step 7: Run web, UI and release tests**

Run: `python -m pytest tests/test_web_draft_endpoints.py tests/test_jobmanager.py tests/test_ui_runtime_behavior.py tests/test_ui_runtime_transitions.py tests/test_prepare_release_entry.py -v`

Run: `node --check js/app.js`

Expected: all PASS; JavaScript syntax check exits 0.

- [ ] **Step 8: Commit Task 8**

```powershell
git add -- webui.py js/app.js prepare_release.py tests/test_web_draft_endpoints.py tests/test_ui_runtime_behavior.py tests/test_ui_runtime_transitions.py tests/test_prepare_release_entry.py
git commit -m "feat: expose resumable annotation progress"
```

---

### Task 9: Scale, Recovery, and Full Regression Verification

**Files:**
- Create: `tests/test_annotation_agent_scale.py`
- Modify: `README.md`
- Modify: `使用说明-从这里开始.md`
- Modify: `docs/commands.md`

**Interfaces:**
- Scale tests use a fake Provider and never call external APIs.
- User documentation describes behavior and recovery only; it does not expose internal memory tuning controls.

- [ ] **Step 1: Write the 240-line completeness test**

```python
def test_240_line_script_has_exactly_one_validated_result_per_target(tmp_path):
    provider = SizedFakeProvider()
    result = run_generated_script(tmp_path, provider, lines=240, scenes=4)
    ids = [item["annotation_id"] for item in result["items"] if item["kind"] == "line"]
    assert len(ids) == 240
    assert len(set(ids)) == 240
    assert set(result["memory"]["progress"]["completed_target_ids"]) == set(ids)
    assert max(provider.target_sizes) <= 60
```

- [ ] **Step 2: Write the 3000-line bounded-context and recovery test**

```python
def test_3000_line_context_is_bounded_and_resume_skips_prefix(tmp_path):
    first = InterruptingFakeProvider(after_calls=25)
    with pytest.raises(AnnotationAgentError):
        run_generated_script(tmp_path, first, lines=3000, scenes=50)
    resumed = SizedFakeProvider()
    result = run_generated_script(tmp_path, resumed, lines=3000, scenes=50)
    assert result["resumed_chunks"] == 25
    assert max(resumed.target_sizes) <= 60
    assert max(resumed.past_sizes) <= 15
    assert max(resumed.future_sizes) <= 10
    assert max(resumed.event_sizes) <= 8
```

- [ ] **Step 3: Run scale tests and resolve only demonstrated failures**

Run: `python -m pytest tests/test_annotation_agent_scale.py -v`

Expected: PASS without network access. Record runtime in the test output; keep the test data compact enough for the normal suite.

- [ ] **Step 4: Document the user-visible behavior**

Add concise documentation stating that long scripts are processed scene by scene, progress is checkpointed, restarting the same unchanged task resumes completed work, and the final draft still requires review. Do not promise reuse after changing model, cast, resources, or screenplay content.

- [ ] **Step 5: Run the full Python suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 6: Run JavaScript and release verification**

Run: `node --check js/app.js`

Run: `python prepare_release.py --check`

Expected: both exit 0; release safety check reports that publication is allowed.

- [ ] **Step 7: Inspect the final diff and confirm no unrelated files are staged**

Run: `git status --short`

Run: `git diff --check`

Run: `git diff --stat HEAD~8..HEAD`

Expected: no whitespace errors; the status may still show pre-existing user changes, but the Agent commits contain only files listed in this plan.

- [ ] **Step 8: Commit Task 9**

```powershell
git add -- tests/test_annotation_agent_scale.py README.md 使用说明-从这里开始.md docs/commands.md
git commit -m "test: verify long screenplay annotation recovery"
```

---

## Completion Gate

Before reporting completion, verify all of the following from fresh command output:

- `python -m pytest -q` passes.
- `node --check js/app.js` exits 0.
- `python prepare_release.py --check` exits 0.
- The 240-line test proves exact target coverage.
- The 3000-line test proves target, past, future, and event budgets remain bounded.
- A forced interruption resumes without repeating committed Provider calls.
- A middle-scene edit invalidates that scene and all dependent later state, never splicing stale state into new output.
- No API key, authorization header, absolute source path, or raw Provider config is present in checkpoints.
- Existing legacy mode, draft review, proposals, deterministic direction rules, and AA compilation tests remain passing.
