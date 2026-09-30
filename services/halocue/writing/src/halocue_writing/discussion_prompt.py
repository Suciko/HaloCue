"""Lossless, deterministic layout for discussion context (not a response cache).

Stable scope and confirmed material precede frequently changing context. Every
call still includes the supplied current revision, retrieval and conversation;
no payload or token usage is reused locally and list order remains meaningful.
"""

from __future__ import annotations

import json
from typing import Any


def _ordered(value: Any, first: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        keys = [key for key in first if key in value]
        keys.extend(sorted(key for key in value if key not in keys))
        return {key: _ordered(value[key]) for key in keys}
    if isinstance(value, list):
        return [_ordered(item) for item in value]
    return value


def discussion_context_json(context: dict) -> str:
    """Reorder JSON keys only; retain all values, unknown fields and list order."""
    ordered = _ordered(
        context,
        (
            "work_id",
            "idea",
            "scene_conversation_context",
            "scene_memory_context",
            "task_contract",
            "document_skill",
            "conversation_summary",
            "attachments",
            "document_context",
            "tool_followup",
            "tool_results",
        ),
    )
    scene = context.get("scene_conversation_context")
    if isinstance(scene, dict):
        ordered["scene_conversation_context"] = _ordered(
            scene,
            (
                "schema_version",
                "scene",
                "write_boundary",
                "ba_skill",
                "confirmed_materials",
                "confirmed_references",
                "scene_asset_references",
                "current_manuscript",
                "source_revisions",
                "source_revision_ids",
            ),
        )
    return json.dumps(ordered, ensure_ascii=False)
