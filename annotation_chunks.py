"""Stable source identities and scene-aware annotation chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s+|场景\s*[:：]?|地点\s*[:：]?)")


@dataclass(frozen=True)
class ChunkLimits:
    target: int
    soft_limit: int
    hard_limit: int


def estimate_initial_chunk_limits(task_profile: Dict[str, Any]) -> ChunkLimits:
    """Estimate a starting tier for one run; never persists the result."""
    target_lines = max(1, int(task_profile.get("target_lines") or 1))
    speakers = max(1, int(task_profile.get("speaker_count") or 1))
    resources = max(1, int(task_profile.get("resource_complexity") or 1))
    context = int(task_profile.get("context_window_tokens") or 0)
    output_capacity = int(task_profile.get("annotation_max_tokens") or 0)
    prompt_tokens = int(task_profile.get("estimated_prompt_tokens") or 0)
    target = 50
    if speakers >= 10 or resources >= 8:
        target -= 10
    elif speakers >= 6 or resources >= 5:
        target -= 5
    if context and context < 64_000:
        target -= 10
    elif context and context < 256_000:
        target -= 5
    if output_capacity and output_capacity < 8_000:
        target -= 10
    elif output_capacity and output_capacity < 32_000:
        target -= 5
    if context and prompt_tokens and prompt_tokens * 5 > context:
        target -= 10
    elif prompt_tokens > 50_000:
        target -= 5
    if target_lines < target:
        target = max(5, target_lines)
    target = max(10, min(50, target))
    return ChunkLimits(
        target=target,
        soft_limit=min(60, target + 5),
        hard_limit=min(60, target + 10),
    )


class RunChunkController:
    """Learn only within the current run, with two-success hysteresis."""

    def __init__(self, *, target: int, soft_limit: int, hard_limit: int):
        self._limits = ChunkLimits(int(target), int(soft_limit), int(hard_limit))
        self._successes = 0
        self.last_reason = "initial"

    def next_limits(self) -> ChunkLimits:
        return self._limits

    def confirm_capacity(self, target: int) -> ChunkLimits:
        """Keep the largest full subdivision that has actually succeeded."""
        confirmed = max(1, int(target))
        if confirmed <= self._limits.target:
            return self._limits
        hard_limit = max(confirmed, self._limits.hard_limit)
        self._limits = ChunkLimits(
            confirmed,
            min(hard_limit, max(confirmed, self._limits.soft_limit)),
            hard_limit,
        )
        self._successes = 0
        self.last_reason = "confirmed_capacity"
        return self._limits

    def observe(self, result: Dict[str, Any]) -> ChunkLimits:
        if not result.get("success"):
            self._successes = 0
            reason = str(result.get("reason") or "failure")
            if reason in {"capacity", "deadline"}:
                target = max(5, self._limits.target // 2)
                self._limits = ChunkLimits(
                    target,
                    min(self._limits.soft_limit, target + 4),
                    min(self._limits.hard_limit, target + 8),
                )
            self.last_reason = reason
            return self._limits
        ratio_value = result.get("reasoning_content_ratio")
        if ratio_value is None:
            self._successes = 0
            self.last_reason = "insufficient_telemetry"
            return self._limits
        ratio = float(ratio_value)
        if ratio > 6:
            # A large reasoning/content ratio is a model-effort signal, not
            # evidence that the request exceeded context or output capacity.
            # Keep the chunk size stable; capacity failures are handled above.
            self._successes = 0
            self.last_reason = "high_reasoning_ratio"
            return self._limits
        self._successes += 1
        if self._successes >= 2 and self._limits.target < self._limits.hard_limit:
            self._successes = 0
            target = min(self._limits.hard_limit, self._limits.target + 5)
            self._limits = ChunkLimits(target, min(self._limits.hard_limit, target + 5), self._limits.hard_limit)
            self.last_reason = "two_efficient_successes"
        else:
            self.last_reason = "efficient_success"
        return self._limits


def _fingerprint(who: Any, text: Any) -> str:
    value = f"{str(who or '').strip()}\n{str(text or '').strip()}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def assign_annotation_ids(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach reproducible identity fields to every dialogue item in place."""
    for ordinal, item in enumerate(items, 1):
        if item.get("kind") != "line":
            continue
        line_no = int(item.get("line_no") or ordinal)
        split_index = int(item.get("split_index") or 0)
        fingerprint = _fingerprint(item.get("who"), item.get("text"))
        item["line_no"] = line_no
        item["split_index"] = split_index
        item["text_fingerprint"] = fingerprint
        item["annotation_id"] = f"src-{line_no}-{split_index}-{fingerprint[:12]}"
    return items


def _is_boundary_item(item: Dict[str, Any]) -> bool:
    if item.get("kind") == "other":
        raw = str(item.get("raw") or "").strip()
        return (
            raw == "---"
            or bool(_HEADING_RE.match(raw))
            or bool(re.match(r"^@(bg|place)\b", raw, re.IGNORECASE))
        )
    return False


def _usage_chain_ranges(usage_chain: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    ranges = []
    for chain_index, entry in enumerate(usage_chain or []):
        if not isinstance(entry, dict):
            continue
        def line_value(value: Any) -> Optional[int]:
            match = re.search(r"\d+", str(value or ""))
            return int(match.group()) if match else None
        start = line_value(entry.get("start"))
        end = line_value(entry.get("end")) or start
        if start is None:
            continue
        ranges.append({
            **dict(entry), "_chain_index": chain_index,
            "start_line": start, "end_line": max(start, end or start),
        })
    ranges.sort(key=lambda row: (row["start_line"], row["end_line"], row["_chain_index"]))
    return ranges


def build_scene_map(items: List[Dict[str, Any]], usage_chain: Optional[Sequence[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Build scenes from explicit separators/headings and confirmed line ranges."""
    assign_annotation_ids(items)
    ranges = _usage_chain_ranges(usage_chain)
    groups: List[List[int]] = []
    current: List[int] = []
    previous_scene_key = None
    for index, item in enumerate(items):
        if _is_boundary_item(item):
            if current:
                groups.append(current)
                current = []
            previous_scene_key = None
            continue
        if item.get("kind") != "line":
            continue
        line_no = int(item.get("line_no") or index + 1)
        matching = next((r for r in ranges if r["start_line"] <= line_no <= r["end_line"]), None)
        scene_key = matching["_chain_index"] if matching else None
        if current and scene_key != previous_scene_key and (scene_key is not None or previous_scene_key is not None):
            groups.append(current)
            current = []
        current.append(index)
        previous_scene_key = scene_key
    if current:
        groups.append(current)

    scenes = []
    for scene_number, indices in enumerate(groups, 1):
        first = items[indices[0]]
        line_numbers = [int(items[i].get("line_no") or i + 1) for i in indices]
        matching = next((
            r for r in ranges
            if r["start_line"] <= line_numbers[0] <= r["end_line"]
        ), None)
        scenes.append({
            "scene_id": f"scene-{scene_number}",
            "scene_index": scene_number,
            "target_indices": indices,
            "start_line": min(line_numbers),
            "end_line": max(line_numbers),
            "location": str(matching.get("location") or "") if matching else "",
            "segment": str(matching.get("segment") or "") if matching else "",
            "time": str(matching.get("time") or "") if matching else "",
            "scene_type": str(matching.get("scene_type") or "other") if matching else "other",
            "scene_function": str(matching.get("scene_function") or "dialogue") if matching else "dialogue",
            "purpose": str(matching.get("reason") or "") if matching else "",
            "evidence": str(matching.get("evidence") or "") if matching else "",
            "usage_chain_index": matching.get("_chain_index") if matching else None,
            "speakers": sorted({str(items[i].get("who") or "") for i in indices if items[i].get("who")}),
            "opening_text": str(first.get("text") or ""),
        })
    return scenes


def _natural_cut(indices: Sequence[int], items: Sequence[Dict[str, Any]], start: int, limit: int) -> int:
    end = min(len(indices), start + limit)
    if end == len(indices):
        return end
    candidates = []
    for pos in range(start + 1, end + 1):
        item = items[indices[pos - 1]]
        text = str(item.get("text") or "")
        if item.get("who") == "旁白" or text.endswith(("。", "！", "？", "！", "？")):
            candidates.append(pos)
    return max(candidates) if candidates else end


def build_chunks(
    items: List[Dict[str, Any]],
    scenes: Sequence[Dict[str, Any]],
    target: int = 50,
    soft_limit: int = 50,
    hard_limit: int = 60,
) -> List[Dict[str, Any]]:
    """Split each scene at natural boundaries while respecting hard limits."""
    if not 1 <= target <= soft_limit <= hard_limit:
        raise ValueError("chunk limits must satisfy 1 <= target <= soft_limit <= hard_limit")
    chunks = []
    for scene in scenes:
        indices = list(scene.get("target_indices") or [])
        start = 0
        chunk_number = 1
        while start < len(indices):
            remaining = len(indices) - start
            if remaining <= hard_limit:
                end = len(indices)
            else:
                preferred = min(soft_limit, max(target, remaining - hard_limit))
                end = _natural_cut(indices, items, start, preferred)
                if end - start < target and remaining > target:
                    end = _natural_cut(indices, items, start, min(target, hard_limit))
                if end <= start:
                    end = min(len(indices), start + target)
            chunk_id = f"{scene['scene_id']}-chunk-{chunk_number}"
            chunks.append({
                "chunk_id": chunk_id,
                "scene_id": scene["scene_id"],
                "chunk_index": chunk_number,
                "target_indices": indices[start:end],
                "target_ids": [items[i].get("annotation_id") for i in indices[start:end]],
                "target_lines": [items[i].get("line_no") for i in indices[start:end]],
                "start_line": items[indices[start]].get("line_no"),
                "end_line": items[indices[end - 1]].get("line_no"),
            })
            start = end
            chunk_number += 1
    return chunks


def subdivide_chunk(chunk: Dict[str, Any], maximum: int) -> List[Dict[str, Any]]:
    if maximum < 1:
        raise ValueError("maximum must be positive")
    indices = list(chunk.get("target_indices") or [])
    result = []
    for offset in range(0, len(indices), maximum):
        target_indices = indices[offset:offset + maximum]
        part = dict(chunk)
        part["chunk_id"] = f"{chunk.get('chunk_id', 'chunk')}-part-{len(result) + 1}"
        part["target_indices"] = target_indices
        target_ids = list(chunk.get("target_ids") or [])
        part["target_ids"] = target_ids[offset:offset + maximum] or target_ids_for_indices(target_indices)
        target_lines = list(chunk.get("target_lines") or [])
        part_lines = target_lines[offset:offset + maximum]
        if part_lines:
            part["target_lines"] = part_lines
            part["start_line"] = part_lines[0]
            part["end_line"] = part_lines[-1]
        result.append(part)
    return result


def target_ids_for_indices(indices: Iterable[int]) -> List[str]:
    return [str(index) for index in indices]


def context_indices(dialogue_indices: Sequence[int], chunk: Dict[str, Any], before: int = 15, after: int = 10) -> Tuple[List[int], List[int]]:
    ordered = list(dialogue_indices)
    targets = list(chunk.get("target_indices") or [])
    if not targets:
        return [], []
    positions = {index: pos for pos, index in enumerate(ordered)}
    first = positions.get(targets[0], 0)
    last = positions.get(targets[-1], first)
    past = ordered[max(0, first - before):first]
    future = ordered[last + 1:last + 1 + after]
    return past, future
