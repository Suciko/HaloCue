"""Versioned memory, retrieval and checkpoints for the annotation Agent."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from annotation_chunks import context_indices


SCHEMA_VERSION = 2
STORY_TYPES = {"auto", "main", "event", "bond"}
TRANSIENT_BGFX = {"集中线", "闪白", "闪电", "传送", "BG_FocusLine", "BG_Flash", "BG_Flash_Sound", "BG_Teleport"}


def _story_type(value: Any) -> str:
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in STORY_TYPES else "auto"


def initial_memory(story_summary: str = "", story_type: str = "auto") -> Dict[str, Any]:
    normalized_story_type = _story_type(story_type)
    return {
        "schema_version": SCHEMA_VERSION,
        "story": {
            "summary": str(story_summary or ""), "type": normalized_story_type,
            "relationships": {}, "open_threads": [],
        },
        "scene": {
            "id": "", "location": "", "time": "", "purpose": "", "mood": "", "summary": "",
            "scene_type": normalized_story_type if normalized_story_type != "auto" else "other",
        },
        "direction": {
            "background": None, "place": None, "bgfx": None,
            "visible_characters": [], "positions": {}, "last_faces": {},
            "recent_emoticons": [], "recent_actions": [], "recent_sounds": [],
            "focus": {"kind": "speaker", "character": ""},
            "relation_distance": "normal", "emotion_phase": "", "continuity": {},
        },
        "events": [],
        "progress": {"completed_chunks": [], "completed_target_ids": [], "next_scene_id": ""},
    }


def _bounded_strings(values: Any, limit: int = 12) -> List[str]:
    if not isinstance(values, list):
        return []
    return [str(value)[:160] for value in values if str(value or "").strip()][-limit:]


def apply_state_delta(memory: Mapping[str, Any], delta: Mapping[str, Any], *, cast: Mapping[str, Any], constraints: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a validated copy with persistent direction updates applied."""
    updated = copy.deepcopy(dict(memory))
    direction = updated.setdefault("direction", {})
    delta = dict(delta or {})
    background = str(delta.get("background") or "").strip()
    if background and background in set(constraints.get("ok_bg") or []):
        direction["background"] = background
    place = str(delta.get("place") or "").strip()
    if place:
        direction["place"] = place[:80]
    bgfx = str(delta.get("bgfx") or "").strip()
    if bgfx:
        direction["bgfx"] = None if bgfx in TRANSIENT_BGFX else bgfx[:80]

    valid_people = set(cast)
    if "visible_characters" in delta:
        direction["visible_characters"] = [
            name for name in _bounded_strings(delta.get("visible_characters"), 8)
            if name in valid_people
        ]
    positions = delta.get("positions")
    if isinstance(positions, dict):
        direction["positions"] = {
            name: int(value) for name, value in positions.items()
            if name in valid_people and isinstance(value, int) and 1 <= value <= 5
        }
    faces = delta.get("last_faces")
    if isinstance(faces, dict):
        current = dict(direction.get("last_faces") or {})
        for name, face in faces.items():
            character = cast.get(name) if isinstance(cast, dict) else None
            ident = character.get("id") if isinstance(character, dict) else None
            allowed = (constraints.get("faces_by_id") or {}).get(ident, set())
            if name in valid_people and str(face) in set(allowed or []):
                current[name] = str(face)
        direction["last_faces"] = current
    for source, target in (
        ("recent_emoticons", "recent_emoticons"),
        ("recent_actions", "recent_actions"),
        ("recent_sounds", "recent_sounds"),
    ):
        if source in delta:
            direction[target] = _bounded_strings(delta.get(source), 12)
    if "open_threads" in delta:
        updated.setdefault("story", {})["open_threads"] = _bounded_strings(delta.get("open_threads"), 20)
    return updated


def complete_scene(memory: Mapping[str, Any], scene: Mapping[str, Any], summary: str) -> Dict[str, Any]:
    updated = copy.deepcopy(dict(memory))
    previous_scene_type = str((updated.get("scene") or {}).get("scene_type") or "other")
    updated["scene"] = {
        "id": str(scene.get("scene_id") or ""),
        "location": str(scene.get("location") or ""),
        "time": str(scene.get("time") or ""),
        "purpose": str(scene.get("purpose") or ""),
        "mood": str(scene.get("mood") or ""),
        "summary": str(summary or "")[:1200],
        "scene_type": str(scene.get("scene_type") or previous_scene_type)[:32],
    }
    return updated


def _line_record(label: str, item: Mapping[str, Any], index: int = 0, *, compact: bool = False) -> str:
    marker = str(index) if compact and index else str(item.get("annotation_id"))
    suffix = "" if compact else f" | fingerprint={item.get('text_fingerprint')}"
    return f"[{label} {marker}] {item.get('who')}: {item.get('text')}{suffix}"


def assemble_chunk_context(
    items: Sequence[Mapping[str, Any]], chunk: Mapping[str, Any], memory: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]], usage_chain: Sequence[Mapping[str, Any]], *,
    before: int = 15, after: int = 10, max_events: int = 8, compact: bool = False,
    story_type: str = "auto",
) -> Tuple[str, str]:
    dialogue = [i for i, item in enumerate(items) if item.get("kind") == "line"]
    past, future = context_indices(dialogue, dict(chunk), before=before, after=after)
    targets = list(chunk.get("target_indices") or [])
    selected = list(events)[:max_events]
    direction = memory.get("direction") or {}
    scene = memory.get("scene") or {}
    focus = direction.get("focus") if isinstance(direction.get("focus"), Mapping) else {}
    continuity = direction.get("continuity") if isinstance(direction.get("continuity"), Mapping) else {}
    normalized_story_type = _story_type(story_type)
    director_context = {
        "story_type": normalized_story_type,
        "scene_type": str(scene.get("scene_type") or (
            normalized_story_type if normalized_story_type != "auto" else "other"
        ))[:32],
        "focus": {
            "kind": str(focus.get("kind") or "speaker")[:32],
            "character": str(focus.get("character") or "")[:160],
        },
        "relation_distance": str(direction.get("relation_distance") or "normal")[:32],
        "emotion_phase": str(direction.get("emotion_phase") or "")[:160],
        "continuity": {
            name: str(continuity.get(name) or "")[:160]
            for name in ("face", "emo", "act", "fx", "bgfx")
            if name in continuity
        },
        "visible_characters": _bounded_strings(direction.get("visible_characters"), 8),
    }
    positions = direction.get("positions") if isinstance(direction.get("positions"), Mapping) else {}
    direction_snapshot = {
        "background": str(direction.get("background") or "")[:160],
        "place": str(direction.get("place") or "")[:80],
        "bgfx": str(direction.get("bgfx") or "")[:80],
        "visible_characters": _bounded_strings(direction.get("visible_characters"), 8),
        "positions": {
            str(name)[:160]: value for name, value in positions.items()
            if isinstance(value, int)
        },
        **director_context,
    }
    volatile_parts = [
        "CURRENT_STORY_MEMORY\n" + json.dumps(memory.get("story") or {}, ensure_ascii=False, separators=(",", ":")),
        "CURRENT_SCENE_MEMORY\n" + json.dumps(memory.get("scene") or {}, ensure_ascii=False, separators=(",", ":")),
        "CURRENT_DIRECTION_STATE\n" + json.dumps(direction_snapshot, ensure_ascii=False, separators=(",", ":")),
        "DIRECTOR_CONTEXT\n" + json.dumps(director_context, ensure_ascii=False, separators=(",", ":")),
    ]
    if usage_chain:
        volatile_parts.append("CONFIRMED_USAGE_CHAIN\n" + json.dumps(list(usage_chain)[:80], ensure_ascii=False, separators=(",", ":"))[:16000])
    volatile_parts.append("RELEVANT_MEMORY_EVENTS\n" + json.dumps(selected, ensure_ascii=False, separators=(",", ":")))
    body = [
        "Update continuity across lines from DIRECTOR_CONTEXT; do not reset direction state for each line.",
        "只为 TARGET 行输出标注；PAST_CONTEXT 和 FUTURE_CONTEXT 只用于理解，不得标注 FUTURE_CONTEXT。",
        ("响应协议：只返回一个 JSON 对象；lines 使用从 1 开始的 i 对应 TARGET 顺序，只填写有值的演出字段；"
         "不复述规则、哈希、原文或候选比较；每行只做一次决策，完成语义判断后立即返回 JSON。"
         if compact else
         "响应协议：只返回一个 JSON 对象，顶层必须有 lines、state_delta、memory_events；可选 beats 只表达独立无台词反应；lines 必须恰好覆盖每个 TARGET，"
         "每项必须复制对应 TARGET 的 source_id 和 text_fingerprint，并只填写演出字段；不要使用旧版 i/speaker/wait 格式。"),
    ]
    body.extend(_line_record("PAST_CONTEXT", items[index], compact=compact) for index in past)
    body.extend(_line_record("TARGET", items[index], position + 1, compact=compact) for position, index in enumerate(targets))
    body.extend(_line_record("FUTURE_CONTEXT", items[index], compact=compact) for index in future)
    return "\n\n".join(volatile_parts), "\n".join(body)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: Any) -> str:
    text = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_run_fingerprint(
    script_text: str, cast: Mapping[str, Any], resources: Mapping[str, Any],
    prompt_version: str, schema_version: int, chunk_version: str,
    model_config: Mapping[str, Any], scene_hashes: Optional[Sequence[str]] = None,
    *, story_type: str = "auto", director_version: str = "",
) -> Dict[str, Any]:
    safe_model = {
        "provider": str(model_config.get("provider") or ""),
        "model": str(model_config.get("model") or ""),
        "max_tokens": int(model_config.get("max_tokens") or 0),
        "annotation_max_tokens": int(model_config.get("annotation_max_tokens") or 0),
        "reasoning_mode": str(model_config.get("reasoning_mode") or ""),
        "reasoning_wire_protocol": str(model_config.get("reasoning_wire_protocol") or ""),
    }
    return {
        "script_sha256": _sha(script_text), "cast_sha256": _sha(cast),
        "resources_sha256": _sha(resources), "prompt_version": str(prompt_version),
        "schema_version": int(schema_version), "chunk_version": str(chunk_version),
        "story_type": _story_type(story_type), "director_version": str(director_version or ""),
        "model": safe_model, "scene_hashes": list(scene_hashes or []),
    }


class AnnotationCheckpointStore:
    def __init__(self, root: Any):
        self.root = Path(root)
        self.last_error = ""

    @staticmethod
    def run_key(fingerprint: Mapping[str, Any]) -> str:
        return _sha(fingerprint)[:24]

    def _path(self, run_key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(run_key))[:80]
        return self.root / safe / "checkpoint.json"

    def load(self, run_key: str) -> Optional[Dict[str, Any]]:
        path = self._path(run_key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            self.last_error = str(exc)
            return None
        return value if isinstance(value, dict) else None

    def commit(self, run_key: str, state: Mapping[str, Any]) -> Path:
        path = self._path(run_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
        return path

    def resume_plan(self, saved: Mapping[str, Any], current: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        saved_fp = saved.get("fingerprint", saved)
        current_fp = current.get("fingerprint", current)
        scene_ids = [str(scene.get("scene_id") or "") for scene in scenes]
        old_hashes = list(saved_fp.get("scene_hashes") or [])
        new_hashes = list(current_fp.get("scene_hashes") or [])
        first_changed = next((i for i, pair in enumerate(zip(old_hashes, new_hashes)) if pair[0] != pair[1]), min(len(old_hashes), len(new_hashes)))
        structural = all(saved_fp.get(key) == current_fp.get(key) for key in (
            "prompt_version", "schema_version", "chunk_version", "director_version",
            "story_type", "model",
        ))
        exact = saved_fp == current_fp
        restart = scene_ids[first_changed] if first_changed < len(scene_ids) else None
        return {
            "reuse_scene_ids": scene_ids[:first_changed], "restart_scene_id": restart,
            "reuse_after_restart": False, "reuse_scene_map": saved_fp.get("schema_version") == current_fp.get("schema_version"),
            "reuse_chunk_results": exact and structural,
        }


def build_story_plan(items: Sequence[Mapping[str, Any]], scenes: Sequence[Mapping[str, Any]], usage_chain: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    speakers = sorted({str(item.get("who") or "") for item in items if item.get("kind") == "line" and item.get("who")})
    planned = []
    chain = [entry for entry in usage_chain or [] if isinstance(entry, dict)]
    for index, scene in enumerate(scenes):
        entry = chain[index] if index < len(chain) else {}
        planned.append({
            **dict(scene), "segment": str(entry.get("segment") or scene.get("segment") or f"场景 {index + 1}"),
            "location": str(entry.get("location") or scene.get("location") or ""),
            "evidence": str(entry.get("evidence") or scene.get("opening_text") or ""),
            "purpose": str(entry.get("reason") or ""),
        })
    summary = f"共 {len(planned)} 个场景；出场：{'、'.join(speakers)}。"
    return {"summary": summary, "speakers": speakers, "scenes": planned}


def merge_memory_events(existing: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]], visible_items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {str(item.get("annotation_id") or ""): str(item.get("text") or "") for item in visible_items}
    result = [dict(event) for event in existing]
    keys = {_event_key(event) for event in result}
    for candidate in candidates:
        source_ids = [str(value) for value in candidate.get("source_ids") or []]
        evidence = str(candidate.get("evidence") or "").strip()
        if not source_ids or any(source_id not in by_id for source_id in source_ids):
            continue
        source_text = " ".join(by_id[source_id] for source_id in source_ids)
        if evidence not in source_text and source_text not in evidence:
            continue
        event = dict(candidate)
        event.setdefault("id", f"event-{_sha(event)[:12]}")
        key = _event_key(event)
        if key not in keys:
            result.append(event)
            keys.add(key)
    return result


def _event_key(event: Mapping[str, Any]) -> str:
    return _sha({
        "kind": event.get("kind"), "participants": sorted(event.get("participants") or []),
        "keywords": sorted(event.get("keywords") or []), "source_ids": sorted(event.get("source_ids") or []),
    })


def retrieve_events(events: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]], scene_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    text = " ".join(str(item.get("text") or "") for item in items)
    speakers = {str(item.get("who") or "") for item in items}
    scored = []
    for event in events:
        keyword_hits = sum(1 for word in event.get("keywords") or [] if str(word) and str(word) in text)
        participant_hits = sum(1 for name in event.get("participants") or [] if str(name) in speakers)
        status_bonus = 3 if event.get("status") == "open" else 0
        scene_bonus = 1 if event.get("scene_id") == scene_id else 0
        score = keyword_hits * 5 + participant_hits * 2 + status_bonus + scene_bonus + float(event.get("importance") or 0)
        scored.append((score, str(event.get("id") or ""), dict(event)))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:max(0, limit)]]
