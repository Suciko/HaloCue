from __future__ import annotations

import json

from .errors import DomainError
from .repository import canonical_json


MEMORY_KINDS = {
    "episode_memory",
    "scene_state_snapshot",
    "open_thread",
    "decision_record",
}
MEMORY_OPERATIONS = {"create", "update", "retire"}
MEMORY_CONFIDENCE = {"confirmed", "inferred", "open", "conflict", "retired"}
MEMORY_SCOPES = {"work", "chapter", "scene", "character"}


def validate_provider_knowledge_suggestions(
    value: dict,
    *,
    scene_id: str,
    scene_block_ids: set[str],
) -> list[dict]:
    """Validate optional formal-knowledge suggestions from memory extraction.

    They are deliberately narrower than memory items: the first product slice
    only permits new WorkCanon facts backed by the pinned scene revision. The
    caller still has to persist each item as a Proposal before it can become a
    formal Revision.
    """

    if not isinstance(value, dict):
        raise DomainError("provider_output_invalid", "模型返回的资料建议不是对象。", status=502)
    raw_items = value.get("knowledge_suggestions", [])
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, list) or len(raw_items) > 12:
        raise DomainError(
            "provider_output_invalid",
            "作品事实建议必须是最多 12 条的数组。",
            status=502,
            details={"field": "knowledge_suggestions"},
        )
    suggestions = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or any(
            key in raw for key in ("id", "fact_id", "artifact_id", "revision_id")
        ):
            raise DomainError(
                "provider_output_invalid",
                "作品事实建议包含不允许由模型分配的系统字段。",
                status=502,
                details={"index": index},
            )
        kind = str(raw.get("kind") or "canon_fact").strip()
        text = str(raw.get("text") or "").strip()
        scope = str(raw.get("scope") or "work").strip()
        confidence = str(raw.get("confidence_status") or "open").strip()
        block_ids = [
            str(item).strip()
            for item in raw.get("source_block_ids", [])
            if str(item).strip()
        ] if isinstance(raw.get("source_block_ids"), list) else []
        unknown = sorted(set(block_ids).difference(scene_block_ids))
        if kind != "canon_fact":
            raise DomainError(
                "provider_output_invalid",
                "后台资料维护目前只允许提出作品事实候选。",
                status=502,
                details={"index": index, "kind": kind},
            )
        if not text or len(text) > 4000:
            raise DomainError(
                "provider_output_invalid",
                "作品事实建议需要具体且长度受限的内容。",
                status=502,
                details={"index": index, "field": "text"},
            )
        if scope not in {"work", "chapter", "scene"}:
            raise DomainError(
                "provider_output_invalid",
                "作品事实建议的作用域无效。",
                status=502,
                details={"index": index, "scope": scope},
            )
        if confidence not in {"open", "inferred"}:
            raise DomainError(
                "provider_output_invalid",
                "后台资料建议不能由模型标记为已确认。",
                status=502,
                details={"index": index, "confidence_status": confidence},
            )
        if not block_ids or unknown:
            raise DomainError(
                "provider_output_invalid",
                "每条作品事实建议必须引用当前场景中存在的正文块。",
                status=502,
                details={"index": index, "scene_id": scene_id, "unknown_block_ids": unknown},
            )
        suggestions.append({
            "kind": "canon_fact",
            "text": text,
            "scope": scope,
            "confidence_status": confidence,
            "source_block_ids": list(dict.fromkeys(block_ids))[:80],
        })
    return suggestions


def validate_provider_memory_bundle(value: dict, *, scene_id: str) -> dict:
    if not isinstance(value, dict):
        raise DomainError("provider_output_invalid", "模型返回的长期记忆候选不是对象。", status=502)
    raw_items = value.get("items")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 24:
        raise DomainError(
            "provider_output_invalid",
            "长期记忆候选必须包含 1 到 24 条记录。",
            status=502,
            details={"field": "items"},
        )
    items = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or any(key in raw for key in ("id", "memory_id", "artifact_id", "revision_id")):
            raise DomainError(
                "provider_output_invalid",
                "长期记忆候选包含不允许由模型分配的系统字段。",
                status=502,
                details={"index": index},
            )
        kind = str(raw.get("kind") or "").strip()
        operation = str(raw.get("operation") or "create").strip()
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        scope_type = str(raw.get("scope_type") or "scene").strip()
        scope_id = str(raw.get("scope_id") or scene_id).strip()
        confidence = str(raw.get("confidence_status") or "open").strip()
        target_memory_id = str(raw.get("target_memory_id") or "").strip() or None
        if kind not in MEMORY_KINDS:
            raise DomainError("provider_output_invalid", "长期记忆类型无效。", status=502, details={"index": index, "kind": kind})
        if operation not in MEMORY_OPERATIONS:
            raise DomainError("provider_output_invalid", "长期记忆操作无效。", status=502, details={"index": index, "operation": operation})
        if operation == "create" and target_memory_id:
            raise DomainError("provider_output_invalid", "新建记忆不能指定已有 ID。", status=502, details={"index": index})
        if operation != "create" and not target_memory_id:
            raise DomainError("provider_output_invalid", "更新或回收记忆必须指定已有记忆。", status=502, details={"index": index})
        if scope_type not in MEMORY_SCOPES or not scope_id:
            raise DomainError("provider_output_invalid", "长期记忆作用域无效。", status=502, details={"index": index})
        if confidence not in MEMORY_CONFIDENCE:
            raise DomainError("provider_output_invalid", "长期记忆可信状态无效。", status=502, details={"index": index})
        if not title or not summary or len(title) > 160 or len(summary) > 4000:
            raise DomainError("provider_output_invalid", "长期记忆需要简短标题和具体摘要。", status=502, details={"index": index})
        details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
        if len(canonical_json(details)) > 16000:
            raise DomainError("provider_output_invalid", "长期记忆详情过长。", status=502, details={"index": index})
        source_block_ids = [
            str(item).strip() for item in raw.get("source_block_ids", [])
            if str(item).strip()
        ] if isinstance(raw.get("source_block_ids"), list) else []
        items.append({
            "kind": kind,
            "operation": operation,
            "target_memory_id": target_memory_id,
            "title": title,
            "summary": summary,
            "details": details,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "confidence_status": confidence,
            "source_block_ids": list(dict.fromkeys(source_block_ids))[:80],
        })
    return {
        "schema_version": "memory-bundle/1.0",
        "summary": str(value.get("summary") or "").strip()[:1600],
        "items": items,
    }


def validate_provider_chapter_memory_bundle(
    value: dict,
    *,
    chapter_id: str,
    scene_block_ids: dict[str, set[str]],
) -> dict:
    """Validate a chapter sweep and keep every claim tied to pinned scene blocks."""
    bundle = validate_provider_memory_bundle(value, scene_id=chapter_id)
    raw_items = value.get("items") if isinstance(value, dict) else []
    validated = []
    for index, (item, raw) in enumerate(zip(bundle["items"], raw_items)):
        raw_refs = raw.get("source_refs") if isinstance(raw, dict) else None
        if not isinstance(raw_refs, list) or not raw_refs:
            raise DomainError(
                "provider_output_invalid",
                "章节记忆清扫的每条候选都必须引用至少一个场景修订。",
                status=502,
                details={"index": index, "field": "source_refs"},
            )
        refs = []
        seen = set()
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, dict):
                raise DomainError(
                    "provider_output_invalid", "章节记忆清扫包含无效来源引用。",
                    status=502, details={"index": index},
                )
            scene_id = str(raw_ref.get("scene_id") or "").strip()
            if scene_id not in scene_block_ids:
                raise DomainError(
                    "provider_output_invalid", "章节记忆清扫引用了章节外的场景。",
                    status=502, details={"index": index, "scene_id": scene_id},
                )
            block_ids = [
                str(block_id).strip()
                for block_id in raw_ref.get("source_block_ids", [])
                if str(block_id).strip()
            ] if isinstance(raw_ref.get("source_block_ids"), list) else []
            unknown = sorted(set(block_ids).difference(scene_block_ids[scene_id]))
            if unknown:
                raise DomainError(
                    "provider_output_invalid", "章节记忆清扫引用了不存在的正文块。",
                    status=502,
                    details={"index": index, "scene_id": scene_id, "block_ids": unknown},
                )
            if scene_id not in seen:
                refs.append({"scene_id": scene_id, "source_block_ids": list(dict.fromkeys(block_ids))[:80]})
                seen.add(scene_id)
        validated.append({**item, "source_refs": refs})
    return {**bundle, "items": validated}


def memory_projection_rows(connection, work_id: str, *, include_archived: bool = True) -> list[dict]:
    where = "WHERE work_id=?" if include_archived else "WHERE work_id=? AND lifecycle_status='active'"
    rows = connection.execute(
        f"""SELECT id,work_id,kind,scope_type,scope_id,content,source_revision_id,
                   confidence_status,version,created_by,artifact_id,current_revision_id,
                   source_refs_json,lifecycle_status,created_at,last_verified_at,updated_at
            FROM memories {where} ORDER BY updated_at DESC,created_at DESC""",
        (work_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["content"] = json.loads(item.get("content") or "{}")
        except json.JSONDecodeError:
            item["content"] = {"summary": str(item.get("content") or "")}
        try:
            item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
        except json.JSONDecodeError:
            item["source_refs"] = []
        result.append(item)
    return result


def relevant_memories(
    connection,
    work_id: str,
    *,
    chapter_id: str,
    scene_ids: list[str],
    character_ids: list[str],
) -> list[dict]:
    allowed = {
        ("work", work_id),
        ("chapter", chapter_id),
        *(("scene", item) for item in scene_ids),
        *(("character", item) for item in character_ids),
    }
    return [
        item for item in memory_projection_rows(connection, work_id, include_archived=False)
        if item["confidence_status"] == "confirmed"
        and item["lifecycle_status"] == "active"
        and (item["scope_type"], item["scope_id"]) in allowed
    ]
