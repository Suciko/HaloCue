"""Transactional orchestration for scene-aware screenplay annotation."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import deque
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from annotation_chunks import assign_annotation_ids, build_chunks, build_scene_map, subdivide_chunk
from annotation_memory import (
    AnnotationCheckpointStore,
    apply_state_delta,
    assemble_chunk_context,
    build_story_plan,
    initial_memory,
    merge_memory_events,
    retrieve_events,
)
from annotation_protocol import (
    ChunkProtocolError, build_chunk_schema, validate_chunk_response,
    validate_review_patches,
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


def _checkpoint(memory: Mapping[str, Any], fingerprint: Mapping[str, Any], plan: Mapping[str, Any], rows: Mapping[str, Any], beats: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": 1, "fingerprint": dict(fingerprint), "story_plan": dict(plan),
        "memory": copy.deepcopy(dict(memory)), "rows_by_id": copy.deepcopy(dict(rows)),
        "beats": copy.deepcopy(list(beats)),
    }


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
    cancelled: Optional[Callable[[], bool]] = None, target: int = 50,
    soft_limit: int = 50, hard_limit: int = 60, before: int = 15, after: int = 10,
    reasoning_mode: Optional[str] = None, annotation_max_tokens: Optional[int] = None,
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
    if reasoning_mode:
        mode_target, mode_soft, mode_hard = annotation_mode_limits(reasoning_mode)
        target, soft_limit, hard_limit = mode_target, mode_soft, mode_hard
    chunks = build_chunks(items, scenes, target=target, soft_limit=soft_limit, hard_limit=hard_limit)
    run_key = _run_key(run_fingerprint)
    saved = checkpoint_store.load(run_key)
    if saved and saved.get("fingerprint") == dict(run_fingerprint):
        memory = copy.deepcopy(saved.get("memory") or initial_memory(story_plan["summary"]))
        rows_by_id = copy.deepcopy(saved.get("rows_by_id") or {})
        beats = copy.deepcopy(saved.get("beats") or [])
        completed = set((memory.get("progress") or {}).get("completed_chunks") or [])
        resumed_chunks = len(completed)
    else:
        memory = initial_memory(story_plan["summary"])
        rows_by_id = {}
        beats = []
        completed = set()
        resumed_chunks = 0

    completed_target_ids = set(
        str(value)
        for value in (memory.get("progress") or {}).get("completed_target_ids") or []
    )
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
    diagnostics: List[Dict[str, Any]] = []
    safe_target_limit: Optional[int] = None

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
        }

    while queue:
        chunk = queue.popleft()
        chunk_id = str(chunk["chunk_id"])
        if chunk_id in completed:
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
        relevant_events = retrieve_events(memory.get("events") or [], targets, chunk["scene_id"], limit=8)
        volatile, user = assemble_chunk_context(
            items, chunk, memory, relevant_events, usage_chain,
            before=before, after=after, max_events=8,
        )
        schema = build_chunk_schema([str(item["annotation_id"]) for item in targets])
        current, total = user_progress()
        _emit(progress, "annotating", current, total,
              f"正在标注第 {current}/{total} 个场景块")
        validated = None
        last_error = None
        protocol_attempts = 0
        while True:
            call_user = user
            if protocol_attempts:
                call_user += (
                    f"\n\n上次响应无效：{_chunk_error_code(last_error)} - {_chunk_error_detail(last_error)}。"
                    "请修正内容，保持相同 TARGET，并且只返回 TARGET。"
                )
            try:
                request_count += 1
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
                validated = validate_chunk_response(
                    response, targets,
                    visible_ids=[item["annotation_id"] for item in visible],
                    cast=cast, constraints=constraints,
                )
                break
            except Exception as exc:
                kind = _classify_chunk_error(exc)
                last_error = exc
                if _is_request_deadline(exc):
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
                    break
                if kind == "protocol" and protocol_attempts == 0:
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

        next_rows = copy.deepcopy(rows_by_id)
        next_rows.update(validated["lines_by_id"])
        next_beats = copy.deepcopy(beats)
        next_beats.extend(validated["beats"])
        next_memory = apply_state_delta(memory, validated["state_delta"], cast=cast, constraints=constraints)
        visible = _visible_items(items, chunk, before, after)
        next_memory["events"] = merge_memory_events(next_memory.get("events") or [], validated["memory_events"], visible)
        next_progress = next_memory.setdefault("progress", {})
        next_progress.setdefault("completed_chunks", []).append(chunk_id)
        target_ids = [str(item["annotation_id"]) for item in targets]
        next_progress["completed_target_ids"] = list(dict.fromkeys(
            list(next_progress.get("completed_target_ids") or []) + target_ids
        ))
        checkpoint_store.commit(run_key, _checkpoint(next_memory, run_fingerprint, story_plan, next_rows, next_beats))
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
