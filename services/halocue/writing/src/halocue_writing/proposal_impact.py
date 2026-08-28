from __future__ import annotations

from typing import Any

from .repository import canonical_json, sha256_text


KNOWLEDGE_TARGETS = {
    "character_card": {
        "artifact_kind": "character_card",
        "scope_type": "character",
        "label": "人物卡",
    },
    "world_card": {
        "artifact_kind": "world_bible",
        "scope_type": "work",
        "label": "世界观",
    },
    "world_rule": {
        "artifact_kind": "world_bible",
        "scope_type": "work",
        "label": "世界规则",
    },
    "canon_fact": {
        "artifact_kind": "work_canon",
        "scope_type": "work",
        "label": "作品事实",
    },
}


KNOWLEDGE_CONSUMERS = {
    "character_card": (
        ("scene_context", "后续场景上下文", "constraint_source"),
        ("ooc_review", "人物一致性检查", "review_rule"),
        ("release_review", "发布前全篇审查", "gate_input"),
    ),
    "world_card": (
        ("scene_context", "后续场景上下文", "world_rule_source"),
        ("continuity_review", "连续性检查", "review_rule"),
        ("release_review", "发布前全篇审查", "gate_input"),
    ),
    "world_rule": (
        ("scene_context", "后续场景上下文", "world_rule_source"),
        ("continuity_review", "连续性检查", "review_rule"),
        ("release_review", "发布前全篇审查", "gate_input"),
    ),
    "canon_fact": (
        ("scene_context", "后续场景上下文", "canon_source"),
        ("continuity_review", "连续性检查", "review_rule"),
        ("release_review", "发布前全篇审查", "gate_input"),
    ),
}


def build_knowledge_impact_preview(
    *,
    work_id: str,
    work_version: int,
    kind: str,
    operation: str,
    scope_id: str,
    title: str,
    base_revision_id: str | None,
    field_changes: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    affected_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = KNOWLEDGE_TARGETS[kind]
    normalized_changes = [
        {
            "key": str(item.get("key") or "").strip(),
            "label": str(item.get("field") or item.get("key") or "").strip(),
        }
        for item in field_changes
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    ]
    normalized_conflicts = [
        {
            "kind": str(item.get("kind") or "conflict").strip(),
            "label": str(item.get("label") or item.get("kind") or "存在冲突").strip(),
            "blocking": bool(item.get("blocking", True)),
            "resolution": str(item.get("resolution") or "review").strip(),
        }
        for item in conflicts
        if isinstance(item, dict)
    ]
    blocking_count = sum(1 for item in normalized_conflicts if item["blocking"])
    if blocking_count:
        conflict_status = "blocking"
    elif normalized_conflicts:
        conflict_status = "review"
    else:
        conflict_status = "clear"
    body = {
        "schema_version": "proposal-impact/1.0",
        "kind": kind,
        "operation": operation,
        "base_snapshot": {
            "work_version": work_version,
            "revision_id": base_revision_id,
        },
        "target": {
            **target,
            "scope_id": scope_id,
            "title": title,
        },
        "changes": normalized_changes,
        "affected_consumers": [
            {
                "id": consumer_id,
                "label": label,
                "scope_type": "work",
                "scope_id": work_id,
                "effect": effect,
            }
            for consumer_id, label, effect in KNOWLEDGE_CONSUMERS[kind]
        ],
        "affected_refs": [
            {
                "kind": str(item.get("kind") or "").strip(),
                "id": str(item.get("id") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "effect": str(item.get("effect") or "").strip(),
                "status": str(item.get("status") or "current").strip(),
            }
            for item in (affected_refs or [])
            if isinstance(item, dict)
            and str(item.get("kind") or "").strip()
            and str(item.get("id") or "").strip()
        ],
        "conflict_summary": {
            "status": conflict_status,
            "count": len(normalized_conflicts),
            "blocking_count": blocking_count,
            "items": normalized_conflicts,
        },
        "decision": {
            "requires_user_confirmation": True,
            "partial_accept_supported": operation == "update" and kind in {"character_card", "world_card", "world_rule", "canon_fact"},
        },
    }
    return {**body, "digest": sha256_text(canonical_json(body))}
