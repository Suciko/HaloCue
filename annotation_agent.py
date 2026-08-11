"""Transactional orchestration for scene-aware screenplay annotation."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from director_state import SCENE_FUNCTIONS, SCENE_TYPES, apply_continuity

from annotation_chunks import (
    RunChunkController, assign_annotation_ids, build_chunks, build_scene_map,
    estimate_initial_chunk_limits, subdivide_chunk,
)
from annotation_memory import (
    AnnotationCheckpointStore,
    apply_state_delta,
    assemble_chunk_context,
    build_story_plan,
    complete_scene,
    initial_memory,
    merge_memory_events,
    retrieve_events,
)
from annotation_protocol import (
    ChunkProtocolError, build_chunk_schema, build_compact_chunk_schema,
    expand_compact_chunk_response, validate_chunk_response,
    validate_review_patches,
)
from annotation_safety import project_effective_annotation_row
from annotation_telemetry import (
    ReasoningTelemetryWriter, RequestTelemetryWriter, build_request_prompt_hashes,
)
from llm import EmptyModelResponseError, OutputCapacityError, RequestDeadlineError, StructuredOutputError


_CAPACITY_PROTOCOL_CODES = {"missing_target"}


def _classify_chunk_error(exc: Exception) -> str:
    if isinstance(exc, OutputCapacityError):
        return "capacity"
    if isinstance(exc, ChunkProtocolError) and exc.code in _CAPACITY_PROTOCOL_CODES:
        return "capacity"
    if isinstance(exc, (ChunkProtocolError, StructuredOutputError, EmptyModelResponseError)):
        return "protocol"
    return "fatal"


def _is_request_deadline(exc: Exception) -> bool:
    return isinstance(exc, RequestDeadlineError)


def _chunk_error_code(exc: Exception) -> str:
    return str(getattr(exc, "code", "structured_output") or "structured_output")


def _chunk_error_detail(exc: Exception) -> str:
    return str(getattr(exc, "detail", "") or str(exc))


@contextmanager
def _temporary_reasoning_mode(provider: Any, mode: Optional[str]):
    if not mode:
        yield
        return
    override = getattr(provider, "temporary_reasoning_mode", None)
    if callable(override):
        with override(mode):
            yield
        return
    config = getattr(provider, "cfg", None)
    if not isinstance(config, dict):
        yield
        return
    previous = config.get("reasoning_mode")
    config["reasoning_mode"] = mode
    try:
        yield
    finally:
        if previous is None:
            config.pop("reasoning_mode", None)
        else:
            config["reasoning_mode"] = previous


def estimate_chunk_output_budget(
    target_lines: int, *, compact: bool, reasoning_mode: Optional[str], maximum: Optional[int],
) -> int:
    """Bound model output to the actual wire shape instead of always requesting 16K."""
    mode = str(reasoning_mode or "balanced").strip().lower()
    multiplier = 0.8 if mode == "speed" else 1.8 if mode in {"deep", "high", "xhigh", "max"} else 1.0
    per_line = 75 if compact else 200
    estimate = int((1500 + max(1, int(target_lines)) * per_line) * multiplier)
    cap = max(1, int(maximum or estimate))
    return max(1, min(cap, max(1200, estimate)))


@contextmanager
def _temporary_output_budget(provider: Any, maximum: int):
    override = getattr(provider, "temporary_output_budget", None)
    if callable(override):
        with override(maximum):
            yield
        return
    yield


class AnnotationAgentError(RuntimeError):
    def __init__(self, stage: str, scene_id: str, chunk_id: str, detail: str):
        super().__init__(f"{stage} {scene_id}/{chunk_id}: {detail}")
        self.stage = stage
        self.scene_id = scene_id
        self.chunk_id = chunk_id
        self.detail = detail


def _emit(progress: Optional[Callable[..., None]], phase: str, current: int, total: int, detail: str) -> None:
    if progress:
        progress(phase, current, total, detail)


def _run_key(fingerprint: Mapping[str, Any]) -> str:
    value = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _checkpoint(
    memory: Mapping[str, Any], fingerprint: Mapping[str, Any], plan: Mapping[str, Any],
    rows: Mapping[str, Any], beats: Sequence[Mapping[str, Any]], *,
    director_plan: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": 2, "fingerprint": dict(fingerprint), "story_plan": dict(plan),
        "director_plan": copy.deepcopy(dict(director_plan)),
        "memory": copy.deepcopy(dict(memory)), "rows_by_id": copy.deepcopy(dict(rows)),
        "beats": copy.deepcopy(list(beats)),
    }


def _merge_director_rows(
    memory: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
    speakers_by_id: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(memory))
    state = updated.setdefault("direction", {})
    continuity = dict(state.get("continuity") or {})
    for row in rows:
        director = row.get("direction") if isinstance(row, Mapping) else None
        intent = row.get("direction_intent") if isinstance(row, Mapping) else None
        source_id = str(row.get("source_id") or "")
        speaker = str((speakers_by_id or {}).get(source_id) or "")
        if speaker and row.get("face"):
            state.setdefault("last_faces", {})[speaker] = str(row["face"])[:32]
        for field, state_field in (
            ("emo", "recent_emoticons"),
            ("act", "recent_actions"),
            ("se", "recent_sounds"),
        ):
            value = str(row.get(field) or "")
            if value:
                recent = list(state.get(state_field) or [])
                state[state_field] = (recent + [value[:160]])[-12:]
        for field in ("background", "place", "bgfx"):
            row_field = "bg" if field == "background" else field
            value = str(row.get(row_field) or "")
            if value:
                state[field] = value[:160]
        if not isinstance(director, Mapping) or not isinstance(intent, Mapping) or not intent:
            continue
        focus = dict(state.get("focus") or {})
        if "focus_kind" in intent:
            focus["kind"] = str(director.get("focus_kind") or "speaker")[:32]
        if "focus_character" in intent:
            focus["character"] = str(director.get("focus_character") or "")[:160]
        state["focus"] = focus
        if "relation_distance" in intent:
            state["relation_distance"] = str(director.get("relation_distance") or "normal")[:32]
        if "emotion_phase" in intent:
            state["emotion_phase"] = str(director.get("emotion_phase") or "")[:160]
        if "scene_type" in intent:
            scene_type = str(director.get("scene_type") or "other")[:32]
            if scene_type != "other":
                updated.setdefault("scene", {})["scene_type"] = scene_type
        if "scene_function" in intent:
            updated.setdefault("scene", {})["scene_function"] = str(
                director.get("scene_function") or "dialogue"
            )[:32]
        if "subtext" in intent:
            state["subtext"] = str(director.get("subtext") or "")[:160]
        if "reaction_target" in intent:
            state["reaction_target"] = str(director.get("reaction_target") or "")[:160]
        if "visible_characters" in intent:
            state["shot_visible_characters"] = list(
                director.get("visible_characters") or []
            )[:8]
        commands = dict(intent.get("continuity") or {})
        values = {name: str(row.get(name) or "")[:160] for name in commands}
        changes = apply_continuity(continuity, values, commands)
        for name, command in commands.items():
            if command != "none" and name in changes:
                continuity[name] = changes[name]
    state["continuity"] = continuity
    return updated


def _effective_director_rows(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    targets: Sequence[Mapping[str, Any]],
    cast: Mapping[str, Any],
    constraints: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    """Project model rows to the values that can actually reach the script."""
    effective_rows = []
    for item in targets:
        source_id = str(item.get("annotation_id") or "")
        row = rows_by_id.get(source_id)
        if not isinstance(row, Mapping):
            continue
        character = cast.get(item.get("who")) if isinstance(cast, Mapping) else None
        if not isinstance(character, Mapping):
            continue
        effective, _clean, _dropped, _details = project_effective_annotation_row(
            row, item, character, constraints,
        )
        effective_rows.append(effective)
    return effective_rows


def _visible_items(items: Sequence[Mapping[str, Any]], chunk: Mapping[str, Any], before: int, after: int) -> List[Mapping[str, Any]]:
    dialogue = [i for i, item in enumerate(items) if item.get("kind") == "line"]
    targets = list(chunk.get("target_indices") or [])
    if not targets:
        return []
    positions = {index: pos for pos, index in enumerate(dialogue)}
    first = positions[targets[0]]
    last = positions[targets[-1]]
    indices = dialogue[max(0, first - before):last + 1 + after]
    return [items[index] for index in indices]


def _next_subdivision_limit(size: int) -> Optional[int]:
    for limit in (50, 30, 20, 10, 5):
        if size > limit:
            return limit
    return None


def annotation_mode_limits(mode: str) -> tuple[int, int, int]:
    mode = str(mode or "balanced").strip().lower()
    if mode == "speed":
        return 50, 60, 72
    if mode in {"deep", "high"}:
        return 16, 20, 24
    return 20, 24, 30


def run_annotation_agent(
    items: List[Dict[str, Any]], *, provider: Any, static_system: str,
    cast: Mapping[str, Any], constraints: Mapping[str, Any],
    usage_chain: Sequence[Mapping[str, Any]], checkpoint_store: AnnotationCheckpointStore,
    run_fingerprint: Mapping[str, Any], progress: Optional[Callable[..., None]] = None,
    model_activity: Optional[Callable[[Mapping[str, Any]], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None, target: Optional[int] = None,
    soft_limit: Optional[int] = None, hard_limit: Optional[int] = None,
    before: int = 15, after: int = 10,
    reasoning_mode: Optional[str] = None, annotation_max_tokens: Optional[int] = None,
    context_window_tokens: Optional[int] = None,
    story_type: str = "auto",
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    stats_before = dict(getattr(provider, "stats", {}) or {})
    request_count = 0
    retries = 0
    subdivisions = 0
    assign_annotation_ids(items)
    _emit(progress, "planning", 0, 1, "正在分析场景")
    scenes = build_scene_map(items, usage_chain)
    story_plan = build_story_plan(items, scenes, usage_chain)
    normalized_story_type = str(story_type or "auto").strip().lower()
    if normalized_story_type not in {"auto", "main", "event", "bond"}:
        normalized_story_type = "auto"

    def planned_scene_type(scene):
        value = str(scene.get("scene_type") or "").strip().lower()
        if value in SCENE_TYPES and value != "other":
            return value
        return normalized_story_type if normalized_story_type != "auto" else "other"

    def planned_scene_function(scene):
        value = str(scene.get("scene_function") or "").strip().lower()
        return value if value in SCENE_FUNCTIONS else "dialogue"

    director_plan = {
        "story_type": normalized_story_type,
        "director_version": str(run_fingerprint.get("director_version") or ""),
        "scenes": [{
            "scene_id": str(scene.get("scene_id") or "")[:160],
            "scene_type": planned_scene_type(scene),
            "scene_function": planned_scene_function(scene),
        } for scene in story_plan["scenes"][:200]],
    }
    dialogue_items = [item for item in items if item.get("kind") == "line"]
    task_profile = {
        "target_lines": len(dialogue_items),
        "speaker_count": len({str(item.get("who") or "") for item in dialogue_items if item.get("who")}),
        "resource_complexity": min(
            10,
            len(cast or {}) + len(constraints.get("ok_bg") or set()) // 4 + len(usage_chain or []),
        ),
        "context_window_tokens": context_window_tokens,
        "annotation_max_tokens": annotation_max_tokens,
        "estimated_prompt_tokens": max(
            1_000,
            sum(len(str(item.get("who") or "")) + len(str(item.get("text") or "")) for item in items) // 3
            + len(json.dumps(story_plan, ensure_ascii=False)) // 3,
        ),
    }
    estimated_limits = estimate_initial_chunk_limits(task_profile)
    if target is not None or soft_limit is not None or hard_limit is not None:
        estimated_limits = type(estimated_limits)(
            int(target if target is not None else estimated_limits.target),
            int(soft_limit if soft_limit is not None else estimated_limits.soft_limit),
            int(hard_limit if hard_limit is not None else estimated_limits.hard_limit),
        )
    controller = RunChunkController(
        target=estimated_limits.target,
        soft_limit=estimated_limits.soft_limit,
        hard_limit=estimated_limits.hard_limit,
    )
    chunks = build_chunks(
        items, scenes, target=estimated_limits.target,
        soft_limit=estimated_limits.soft_limit, hard_limit=estimated_limits.hard_limit,
    )
    run_key = _run_key(run_fingerprint)
    telemetry_root = (
        checkpoint_store.root.parent / "annotation-telemetry"
        if checkpoint_store.root.name == "annotation-checkpoints"
        else checkpoint_store.root / "annotation-telemetry"
    )
    reasoning_writer = ReasoningTelemetryWriter(telemetry_root, run_key)
    request_writer = RequestTelemetryWriter(telemetry_root, run_key)
    saved = checkpoint_store.load(run_key)
    saved_schema_version = saved.get("schema_version") if isinstance(saved, Mapping) else None
    if (
        saved and isinstance(saved_schema_version, int) and not isinstance(saved_schema_version, bool)
        and saved_schema_version >= 2
        and saved.get("fingerprint") == dict(run_fingerprint)
    ):
        memory = copy.deepcopy(saved.get("memory") or initial_memory(story_plan["summary"], normalized_story_type))
        rows_by_id = copy.deepcopy(saved.get("rows_by_id") or {})
        beats = copy.deepcopy(saved.get("beats") or [])
        completed = set((memory.get("progress") or {}).get("completed_chunks") or [])
        resumed_chunks = len(completed)
    else:
        memory = initial_memory(story_plan["summary"], normalized_story_type)
        rows_by_id = {}
        beats = []
        completed = set()
        resumed_chunks = 0

    completed_target_ids = set(
        str(value)
        for value in (memory.get("progress") or {}).get("completed_target_ids") or []
    )
    request_telemetry: List[Dict[str, Any]] = []
    base_chunk_targets = [
        {str(items[index].get("annotation_id") or "") for index in chunk["target_indices"]}
        for chunk in chunks
    ]

    def user_progress(include_current: bool = True) -> tuple[int, int]:
        total = len(base_chunk_targets)
        finished = sum(1 for target_ids in base_chunk_targets if target_ids <= completed_target_ids)
        current = min(total, finished + (1 if include_current and finished < total else 0))
        return current, total

    if resumed_chunks:
        current, total = user_progress(include_current=False)
        _emit(progress, "resumed", current, total, "已从检查点继续")

    queue = deque(chunks)
    completed_this_run = 0
    diagnostics: List[Dict[str, Any]] = [{
        "code": "chunk_initial_limits", "level": "info",
        "target": estimated_limits.target, "soft_limit": estimated_limits.soft_limit,
        "hard_limit": estimated_limits.hard_limit, "task_profile": task_profile,
    }]
    chunk_adaptations: List[Dict[str, Any]] = []
    safe_target_limit: Optional[int] = None
    prepared_scenes: set[str] = set()

    def emit_model_activity(
        payload: Mapping[str, Any], *, scene_id: str, chunk_id: str,
        current: int, total: int,
        request_index: int, retry_count: int, subdivision_count: int,
    ) -> None:
        if not model_activity:
            return
        event = dict(payload)
        event.update({
            "scene_id": scene_id,
            "chunk_id": chunk_id,
            "chunk_current": current,
            "chunk_total": total,
            "request_index": request_index,
            "retry_count": retry_count,
            "subdivision_count": subdivision_count,
        })
        model_activity(event)

    def complete_chunk(
        call_user: str, schema: Mapping[str, Any], *, scene_id: str, chunk_id: str,
        current: int, total: int, retry_count: int, subdivision_count: int,
    ) -> Mapping[str, Any]:
        request_index = request_count

        def activity_callback(payload: Mapping[str, Any]) -> None:
            emit_model_activity(
                payload,
                scene_id=scene_id,
                chunk_id=chunk_id,
                current=current,
                total=total,
                request_index=request_index,
                retry_count=retry_count,
                subdivision_count=subdivision_count,
            )

        stream_method = getattr(provider, "complete_json_stream", None)
        if callable(stream_method):
            return stream_method(
                static_system,
                volatile,
                call_user,
                schema,
                on_activity=activity_callback,
            )
        started_ms = int(time.time() * 1000)
        emit_model_activity(
            {
                "state": "waiting",
                "model": str(getattr(provider, "model", "") or ""),
                "request_started_at_ms": started_ms,
                "elapsed_ms": 0,
                "first_delta_ms": None,
                "received_chars": 0,
                "finish_reason": "",
            },
            scene_id=scene_id,
            chunk_id=chunk_id,
            current=current,
            total=total,
            request_index=request_index,
            retry_count=retry_count,
            subdivision_count=subdivision_count,
        )
        response = provider.complete_json(static_system, volatile, call_user, schema)
        emit_model_activity(
            {
                "state": "completed",
                "model": str(getattr(provider, "model", "") or ""),
                "request_started_at_ms": started_ms,
                "elapsed_ms": max(0, int(time.time() * 1000) - started_ms),
                "first_delta_ms": None,
                "received_chars": 0,
                "finish_reason": str(getattr(provider, "_last_finish_reason", "unknown") or "unknown"),
            },
            scene_id=scene_id,
            chunk_id=chunk_id,
            current=current,
            total=total,
            request_index=request_index,
            retry_count=retry_count,
            subdivision_count=subdivision_count,
        )
        return response

    def lower_reasoning_for_empty_retry(exc: EmptyModelResponseError) -> Optional[str]:
        if (
            str(getattr(exc, "finish_reason", "") or "").lower() != "stop"
            or int(getattr(exc, "reasoning_chars", 0) or 0) <= 0
            or int(getattr(exc, "content_chars", 0) or 0) != 0
        ):
            return None
        config = getattr(provider, "cfg", None)
        if not isinstance(config, dict):
            return None
        current_mode = str(config.get("reasoning_mode") or "").strip().lower()
        return {"deep": "balanced", "high": "balanced", "balanced": "low", "medium": "low", "low": "speed"}.get(current_mode)

    def build_metrics() -> Dict[str, Any]:
        stats = getattr(provider, "stats", {}) or {}

        def token_delta(key):
            if key not in stats:
                return None
            return max(0, int(stats.get(key) or 0) - int(stats_before.get(key) or 0))

        cache_reports = token_delta("cache_reports")
        cache_read = token_delta("cache_read")
        cache_miss = token_delta("cache_miss")
        cache_reported = bool(cache_reports)
        cache_total = (cache_read or 0) + (cache_miss or 0)
        records = [dict(record) for record in request_telemetry[-50:]]

        def record_sum(key):
            values = [record.get(key) for record in records]
            if not any(value is not None for value in values):
                return None
            return sum(int(value or 0) for value in values)

        return {
            "requests": request_count,
            "retries": retries,
            "subdivisions": subdivisions,
            "input_tokens": token_delta("in"),
            "output_tokens": token_delta("out"),
            "cache_read_tokens": cache_read if cache_reported else None,
            "uncached_input_tokens": cache_miss if cache_reported else None,
            "cache_hit_rate": (
                cache_read / cache_total
                if cache_reported and cache_total
                else (0.0 if cache_reported else None)
            ),
            "cache_reported": cache_reported,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
            "actual_model": str(getattr(provider, "model", "") or ""),
            "request_records": records,
            "reasoning_tokens": record_sum("reasoning_tokens"),
            "reasoning_chars": record_sum("reasoning_chars"),
            "content_chars": record_sum("content_chars"),
            "initial_chunk_limits": {
                "target": estimated_limits.target,
                "soft_limit": estimated_limits.soft_limit,
                "hard_limit": estimated_limits.hard_limit,
            },
            "chunk_adaptations": list(chunk_adaptations),
        }

    def capture_request_records(
        previous_records: Sequence[Mapping[str, Any]],
        previous_reasoning_records: Sequence[Mapping[str, Any]], *, scene_id: str, chunk_id: str,
        current_retry_count: int, current_subdivision_count: int, agent_request_index: int,
        prompt_hashes: Mapping[str, Any],
    ) -> None:
        records = list(getattr(provider, "request_records", []) or [])
        reasoning_records = list(getattr(provider, "reasoning_records", []) or [])
        def new_since(previous, current):
            previous_indices = {
                int(record["request_index"])
                for record in previous
                if isinstance(record, Mapping) and record.get("request_index") is not None
            }
            indexed = [
                record for record in current
                if isinstance(record, Mapping) and record.get("request_index") is not None
            ]
            if indexed:
                return [record for record in indexed if int(record["request_index"]) not in previous_indices]
            offset = len(previous)
            return current[offset:] if len(current) >= offset else current

        new_records = new_since(previous_records, records)
        if not new_records:
            new_records = [{"request_index": agent_request_index, "telemetry_source": "agent"}]
        for record in new_records:
            safe = dict(record)
            safe.update({
                "scene_id": scene_id,
                "chunk_id": chunk_id,
                "agent_request_index": agent_request_index,
                "retry_count": current_retry_count,
                "subdivision_count": current_subdivision_count,
                **dict(prompt_hashes),
                "adaptation_reason": controller.last_reason,
            })
            request_telemetry.append(safe)
            request_writer.write(safe)
        if len(request_telemetry) > 50:
            del request_telemetry[:-50]
        for record in new_since(previous_reasoning_records, reasoning_records):
            reasoning_writer.write({
                **dict(record),
                "scene_id": scene_id,
                "chunk_id": chunk_id,
                "agent_request_index": agent_request_index,
                "retry_count": current_retry_count,
                "subdivision_count": current_subdivision_count,
            })

    def observe_chunk(result: Dict[str, Any], *, scene_id: str, chunk_id: str) -> None:
        before_limits = controller.next_limits()
        after_limits = controller.observe(result)
        if after_limits == before_limits:
            return
        adaptation = {
            "scene_id": scene_id, "chunk_id": chunk_id,
            "reason": controller.last_reason,
            "previous": {
                "target": before_limits.target, "soft_limit": before_limits.soft_limit,
                "hard_limit": before_limits.hard_limit,
            },
            "next": {
                "target": after_limits.target, "soft_limit": after_limits.soft_limit,
                "hard_limit": after_limits.hard_limit,
            },
        }
        chunk_adaptations.append(adaptation)
        diagnostics.append({"code": "chunk_adapted", "level": "info", **adaptation})

    def success_ratio() -> Optional[float]:
        record = (getattr(provider, "request_records", []) or [])[-1:]
        if not record:
            return None
        current = record[0]
        reasoning = current.get("reasoning_chars")
        content = current.get("content_chars")
        if reasoning is None or content is None:
            return None
        return float(reasoning or 0) / max(1, float(content or 0))

    while queue:
        chunk = queue.popleft()
        scene_id = str(chunk.get("scene_id") or "")
        if scene_id not in prepared_scenes:
            same_scene = [chunk]
            while queue and str(queue[0].get("scene_id") or "") == scene_id:
                same_scene.append(queue.popleft())
            scene = next((entry for entry in scenes if str(entry.get("scene_id")) == scene_id), None)
            if scene and controller.next_limits() != estimated_limits:
                remaining_indices = [
                    index for part in same_scene for index in part.get("target_indices") or []
                    if str(items[index].get("annotation_id") or "") not in completed_target_ids
                ]
                if remaining_indices:
                    rebuilt_scene = dict(scene)
                    rebuilt_scene["target_indices"] = remaining_indices
                    limits = controller.next_limits()
                    same_scene = build_chunks(
                        items, [rebuilt_scene], target=limits.target,
                        soft_limit=limits.soft_limit, hard_limit=limits.hard_limit,
                    )
            for part in reversed(same_scene):
                queue.appendleft(part)
            prepared_scenes.add(scene_id)
            chunk = queue.popleft()
        chunk_id = str(chunk["chunk_id"])
        if chunk_id in completed and all(
            str(items[index].get("annotation_id") or "") in completed_target_ids
            for index in chunk.get("target_indices") or []
        ):
            continue
        pending_indices = [
            index for index in chunk["target_indices"]
            if str(items[index].get("annotation_id") or "") not in completed_target_ids
        ]
        if not pending_indices:
            completed.add(chunk_id)
            continue
        if len(pending_indices) != len(chunk["target_indices"]):
            chunk = dict(chunk)
            chunk["target_indices"] = pending_indices
            chunk["target_ids"] = [items[index].get("annotation_id") for index in pending_indices]
            chunk["start_line"] = items[pending_indices[0]].get("line_no")
            chunk["end_line"] = items[pending_indices[-1]].get("line_no")
        if cancelled and cancelled():
            current, total = user_progress(include_current=False)
            _emit(progress, "cancelled", current, total, "标注已暂停，可继续")
            return {
                "items": items, "rows_by_id": rows_by_id, "memory": memory,
                "beats": beats,
                "metrics": build_metrics(),
                "diagnostics": diagnostics, "completed_chunks": len(completed),
                "resumed_chunks": resumed_chunks, "cancelled": True,
            }
        if safe_target_limit and len(pending_indices) > safe_target_limit:
            parts = subdivide_chunk(chunk, safe_target_limit)
            for part in reversed(parts):
                queue.appendleft(part)
            subdivisions += 1
            _emit(progress, "recovery", 0, len(base_chunk_targets),
                  f"已学习安全上限，先切分到 {safe_target_limit} 行再请求")
            if model_activity:
                emit_model_activity(
                    {
                        "state": "subdividing",
                        "reason": "learned_safe_limit",
                        "next_chunk_lines": safe_target_limit,
                    },
                    scene_id=str(chunk["scene_id"]),
                    chunk_id=chunk_id,
                    current=current,
                    total=total,
                    request_index=request_count,
                    retry_count=retries,
                    subdivision_count=subdivisions,
                )
            continue
        targets = [items[index] for index in chunk["target_indices"]]
        current_scene = next(
            (entry for entry in story_plan["scenes"] if str(entry.get("scene_id") or "") == scene_id),
            None,
        )
        if current_scene and str((memory.get("scene") or {}).get("id") or "") != scene_id:
            scene_context = dict(current_scene)
            scene_context["scene_type"] = planned_scene_type(current_scene)
            scene_context["scene_function"] = planned_scene_function(current_scene)
            memory = complete_scene(
                memory, scene_context,
                str(current_scene.get("evidence") or current_scene.get("opening_text") or ""),
            )
        relevant_events = retrieve_events(memory.get("events") or [], targets, chunk["scene_id"], limit=8)
        volatile, user = assemble_chunk_context(
            items, chunk, memory, relevant_events, usage_chain,
            before=before, after=after, max_events=8,
            compact=bool(getattr(provider, "supports_compact_annotation", False)),
            story_type=normalized_story_type,
        )
        compact_protocol = bool(getattr(provider, "supports_compact_annotation", False))
        schema = (
            build_compact_chunk_schema(len(targets))
            if compact_protocol
            else build_chunk_schema([str(item["annotation_id"]) for item in targets])
        )
        current, total = user_progress()
        _emit(progress, "annotating", current, total,
              f"正在标注第 {current}/{total} 个场景块")
        validated = None
        last_error = None
        protocol_attempts = 0
        empty_retry_attempted = False
        empty_retry_mode = None
        while True:
            call_user = user
            if protocol_attempts:
                call_user += (
                    f"\n\n上次响应无效：{_chunk_error_code(last_error)} - {_chunk_error_detail(last_error)}。"
                    "请修正内容，保持相同 TARGET，并且只返回 TARGET。"
                )
            if empty_retry_attempted:
                call_user += "\n\n上一次模型只输出了思考而没有正文。不要继续分析或复述规则，立即返回最终 JSON。"
            previous_records = list(getattr(provider, "request_records", []) or [])
            previous_reasoning_records = list(getattr(provider, "reasoning_records", []) or [])
            prompt_hashes = build_request_prompt_hashes(
                static_system, volatile, call_user, schema, len(targets),
            )
            try:
                request_count += 1
                output_budget = estimate_chunk_output_budget(
                    len(targets), compact=compact_protocol,
                    reasoning_mode=empty_retry_mode or reasoning_mode,
                    maximum=annotation_max_tokens,
                )
                with _temporary_reasoning_mode(provider, empty_retry_mode):
                    with _temporary_output_budget(provider, output_budget):
                        response = complete_chunk(
                            call_user,
                            schema,
                            scene_id=str(chunk["scene_id"]),
                            chunk_id=chunk_id,
                            current=current,
                            total=total,
                            retry_count=retries,
                            subdivision_count=subdivisions,
                        )
                visible = _visible_items(items, chunk, before, after)
                if compact_protocol:
                    response = expand_compact_chunk_response(response, targets)
                validated = validate_chunk_response(
                    response, targets,
                    visible_ids=[item["annotation_id"] for item in visible],
                    cast=cast, constraints=constraints,
                )
                if current_scene:
                    for validated_row in validated["lines_by_id"].values():
                        direction = validated_row.get("direction")
                        intent = validated_row.get("direction_intent")
                        if not isinstance(direction, dict) or not isinstance(intent, Mapping):
                            continue
                        if "scene_type" not in intent:
                            direction["scene_type"] = planned_scene_type(current_scene)
                        if "scene_function" not in intent:
                            direction["scene_function"] = planned_scene_function(current_scene)
                break
            except Exception as exc:
                kind = _classify_chunk_error(exc)
                last_error = exc
                if _is_request_deadline(exc):
                    observe_chunk({"success": False, "reason": "deadline"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    diagnostics.append({
                        "code": "request_deadline", "level": "warning",
                        "scene_id": str(chunk["scene_id"]), "chunk_id": chunk_id,
                        "detail": str(exc), "completed_chunks": len(completed),
                    })
                    _emit(progress, "timed_out", current, total, "当前场景块达到时间上限，已保留之前完成的内容")
                    if model_activity:
                        emit_model_activity(
                            {"state": "timed_out", "reason": "request_deadline"},
                            scene_id=str(chunk["scene_id"]), chunk_id=chunk_id,
                            current=current, total=total, request_index=request_count,
                            retry_count=retries, subdivision_count=subdivisions,
                        )
                    return {
                        "items": items, "rows_by_id": rows_by_id, "memory": memory,
                        "beats": beats, "metrics": build_metrics(),
                        "diagnostics": diagnostics,
                        "completed_chunks": len(completed), "resumed_chunks": resumed_chunks,
                        "cancelled": False, "timed_out": True,
                    }
                if kind == "capacity":
                    observe_chunk({"success": False, "reason": "capacity"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    break
                if isinstance(exc, EmptyModelResponseError) and empty_retry_attempted:
                    raise AnnotationAgentError(
                        "model_call", str(chunk["scene_id"]), chunk_id, str(exc)
                    ) from exc
                if isinstance(exc, EmptyModelResponseError):
                    observe_chunk({"success": False, "reason": "empty_response"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    empty_retry_mode = lower_reasoning_for_empty_retry(exc)
                    if empty_retry_mode:
                        empty_retry_attempted = True
                        retries += 1
                        continue
                if kind == "protocol" and protocol_attempts == 0:
                    observe_chunk({"success": False, "reason": "protocol"}, scene_id=str(chunk["scene_id"]), chunk_id=chunk_id)
                    protocol_attempts += 1
                    retries += 1
                    if model_activity:
                        emit_model_activity(
                            {
                                "state": "retrying",
                                "reason": _chunk_error_code(exc),
                            },
                            scene_id=str(chunk["scene_id"]),
                            chunk_id=chunk_id,
                            current=current,
                            total=total,
                            request_index=request_count,
                            retry_count=retries,
                            subdivision_count=subdivisions,
                        )
                    continue
                if kind == "protocol":
                    raise AnnotationAgentError(
                        "structured_output",
                        str(chunk["scene_id"]),
                        chunk_id,
                        f"{_chunk_error_code(exc)}: {_chunk_error_detail(exc)}",
                    ) from exc
                raise AnnotationAgentError(
                    "model_call", str(chunk["scene_id"]), chunk_id, str(exc)
                ) from exc
            finally:
                capture_request_records(
                    previous_records,
                    previous_reasoning_records,
                    scene_id=str(chunk["scene_id"]),
                    chunk_id=chunk_id,
                    current_retry_count=retries,
                    current_subdivision_count=subdivisions,
                    agent_request_index=request_count,
                    prompt_hashes=prompt_hashes,
                )
        if validated is None:
            subdivision = _next_subdivision_limit(len(targets))
            if subdivision is not None:
                _emit(
                    progress,
                    "recovery",
                    current,
                    total,
                    f"当前场景块输出过长，正在自动缩小到 {subdivision} 行后重试",
                )
                parts = subdivide_chunk(chunk, subdivision)
                for part in parts:
                    part["_capacity_candidate"] = True
                for part in reversed(parts):
                    queue.appendleft(part)
                diagnostics.append({
                    "code": "chunk_subdivided", "level": "warning", "chunk_id": chunk_id,
                    "maximum": subdivision,
                    "reason": getattr(last_error, "code", "structured_output"),
                })
                subdivisions += 1
                if model_activity:
                    emit_model_activity(
                        {
                            "state": "subdividing",
                            "reason": _chunk_error_code(last_error),
                            "next_chunk_lines": subdivision,
                        },
                        scene_id=str(chunk["scene_id"]),
                        chunk_id=chunk_id,
                        current=current,
                        total=total,
                        request_index=request_count,
                        retry_count=retries,
                        subdivision_count=subdivisions,
                    )
                continue
            raise AnnotationAgentError("structured_output", str(chunk["scene_id"]), chunk_id, str(last_error))

        observe_chunk(
            {"success": True, "reasoning_content_ratio": success_ratio()},
            scene_id=str(chunk["scene_id"]), chunk_id=chunk_id,
        )

        next_rows = copy.deepcopy(rows_by_id)
        next_rows.update(validated["lines_by_id"])
        next_beats = copy.deepcopy(beats)
        next_beats.extend(validated["beats"])
        next_memory = apply_state_delta(memory, validated["state_delta"], cast=cast, constraints=constraints)
        next_memory = _merge_director_rows(
            next_memory,
            _effective_director_rows(
                validated["lines_by_id"], targets, cast, constraints,
            ),
            {
                str(item.get("annotation_id") or ""): str(item.get("who") or "")
                for item in targets
            },
        )
        diagnostics.extend(validated.get("diagnostics") or [])
        visible = _visible_items(items, chunk, before, after)
        next_memory["events"] = merge_memory_events(next_memory.get("events") or [], validated["memory_events"], visible)
        next_progress = next_memory.setdefault("progress", {})
        next_progress.setdefault("completed_chunks", []).append(chunk_id)
        target_ids = [str(item["annotation_id"]) for item in targets]
        next_progress["completed_target_ids"] = list(dict.fromkeys(
            list(next_progress.get("completed_target_ids") or []) + target_ids
        ))
        checkpoint_store.commit(run_key, _checkpoint(
            next_memory, run_fingerprint, story_plan, next_rows, next_beats,
            director_plan=director_plan,
        ))
        rows_by_id = next_rows
        beats = next_beats
        memory = next_memory
        completed.add(chunk_id)
        completed_target_ids.update(target_ids)
        completed_this_run += 1
        if chunk.get("_capacity_candidate"):
            safe_target_limit = len(targets)

    return {
        "items": items, "rows_by_id": rows_by_id, "memory": memory,
        "beats": beats,
        "metrics": build_metrics(),
        "diagnostics": diagnostics, "completed_chunks": len(completed),
        "resumed_chunks": resumed_chunks, "cancelled": False, "timed_out": False,
    }


def build_review_windows(items: Sequence[Mapping[str, Any]], scenes: Sequence[Mapping[str, Any]], events: Sequence[Mapping[str, Any]], chunk_size: int = 30) -> List[Dict[str, Any]]:
    windows = []
    for scene in scenes:
        indices = list(scene.get("target_indices") or [])
        for offset in range(chunk_size, len(indices), chunk_size):
            selected = indices[max(0, offset - 5):min(len(indices), offset + 5)]
            event_text = " ".join(str(event.get("summary") or "") for event in events if event.get("status") == "open")
            windows.append({
                "kind": "chunk_boundary", "scene_id": scene.get("scene_id"),
                "source_ids": [items[index].get("annotation_id") for index in selected],
                "context": event_text + "\n" + "\n".join(str(items[index].get("text") or "") for index in selected),
            })
    return windows


def apply_review_patches(items: List[Dict[str, Any]], patches: Sequence[Mapping[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    updated = copy.deepcopy(items)
    by_id = {str(item.get("annotation_id")): item for item in updated}
    diagnostics = []
    for patch in patches:
        item = by_id.get(str(patch.get("source_id")))
        field = str(patch.get("field") or "")
        if not item or field not in {"face", "emo", "act", "fx", "se", "bg", "bg_request", "place", "shake", "bgfx", "trans", "move", "shot"}:
            continue
        if item.get(field) != patch.get("before"):
            diagnostics.append({"code": "review_before_mismatch", "level": "warning", "source_id": patch.get("source_id"), "field": field})
            continue
        item[field] = patch.get("after")
    return updated, diagnostics
