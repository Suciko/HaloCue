"""Work-owned editor targets for proposal-only card assistance.

The editor is an input snapshot, not authority to change identity, provenance or
trust. Stable IDs and base revisions are checked again before proposing.
"""

from __future__ import annotations

import json
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any

from .errors import DomainError

if TYPE_CHECKING:
    from .service import WritingService

SCHEMA = "card-assistance/1.0"
FIELDS = {
    "character_card": {
        "role",
        "voice_anchors",
        "knowledge_boundary",
        "ooc_constraints",
        "relationships",
    },
    "world_card": {
        "summary",
        "aliases",
        "participants",
        "participant_character_ids",
        "related_world_ids",
    },
}


def resolve_card_assistance(
    service: WritingService, connection: Connection, work_id: str, value: object
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
        raise DomainError("validation_error", "资料助手上下文格式无效。")
    kind = value.get("kind")
    fields = value.get("allowed_fields")
    if (
        not isinstance(kind, str)
        or kind not in FIELDS
        or not isinstance(fields, list)
        or not fields
        or any(not isinstance(key, str) or key not in FIELDS[kind] for key in fields)
    ):
        raise DomainError("validation_error", "请选择允许调整的资料字段。")
    target_id = value.get("target_id")
    base = value.get("base_revision_id")
    if not isinstance(target_id, str) or not target_id or not isinstance(base, str) or not base:
        raise DomainError("validation_error", "定向调整需要已保存的卡片和基准修订。")
    artifact_kind = "character_card" if kind == "character_card" else "world_bible"
    scope_id = target_id if kind == "character_card" else work_id
    row = connection.execute(
        "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind=? AND scope_id=?",
        (work_id, artifact_kind, scope_id),
    ).fetchone()
    if not row or not row["current_revision_id"]:
        raise DomainError(
            "card_assistance_target_missing", "目标卡片不属于当前作品或已不存在。", status=409
        )
    if row["current_revision_id"] != base:
        raise DomainError(
            "card_assistance_stale", "资料已有新修订，请回到卡片核对后重新发起调整。", status=409
        )
    content = service._revision_content(connection, base)
    if kind == "world_card":
        content = next(
            (item for item in content.get("entities", []) if item.get("id") == target_id), None
        )
    if not content or content.get("status") == "archived":
        raise DomainError("card_assistance_target_missing", "目标卡片已归档或不存在。", status=409)
    draft = value.get("draft", {})
    draft_fields = {
        "name",
        "canonical_name",
        "role",
        "voice",
        "boundary",
        "ooc",
        "relationships",
        "source",
        "source_type",
        "trust_status",
        "kind",
        "aliases",
        "summary",
        "confidence_status",
        "participants",
        "related_world_ids",
        "world_character_card_ids",
    }
    if not isinstance(draft, dict) or any(key not in draft_fields for key in draft):
        raise DomainError("validation_error", "卡片讨论草稿字段无效。")
    if len(json.dumps(draft, ensure_ascii=False)) > 60000 or any(
        not isinstance(item, str)
        and not (isinstance(item, list) and all(isinstance(v, str) for v in item))
        for item in draft.values()
    ):
        raise DomainError("validation_error", "卡片讨论草稿过长或格式无效。")
    context = {
        "schema_version": SCHEMA,
        "kind": kind,
        "target_id": target_id,
        "base_revision_id": base,
        "allowed_fields": list(dict.fromkeys(fields)),
        "name": content.get("name", ""),
        "draft": draft,
        "boundary": "draft_is_unconfirmed; existing_identity_sources_and_trust_are_read_only; proposal_only",
    }
    return context, content
