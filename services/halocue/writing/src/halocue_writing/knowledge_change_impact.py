"""Read-only, ID-based comparison with the last completed scene review.

This is a dependency report, not semantic contradiction detection or a release
Gate. No draft is assembled and no model or formal write is triggered by reads.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .errors import NotFound
from .repository import sha256_text

if TYPE_CHECKING:
    from .service import WritingService

SCHEMA = "knowledge-change-impact/1.0"
FIELD_LABELS = {
    "name": "名称",
    "canonical_name": "标准名称",
    "aliases": "别名",
    "role": "故事职责",
    "voice_anchors": "声音锚点",
    "knowledge_boundary": "知情边界",
    "ooc_constraints": "OOC 红线",
    "relationships": "人物关系",
    "ba_profile": "人物主档",
    "summary": "本作定义与限制",
    "kind": "类型",
    "participants": "关联人物",
    "participant_character_ids": "人物关联",
    "related_world_ids": "关联设定",
    "source": "来源",
    "source_refs": "来源依据",
    "source_type": "来源类型",
    "trust_status": "采用状态",
    "confidence_status": "可信状态",
    "status": "归档状态",
    "scope": "采用范围",
    "profile_format": "资料格式",
    "import_metadata": "导入记录",
    "source_hash": "来源指纹",
    "extractor_version": "提取版本",
}


def _usable(kind: str, content: dict) -> bool:
    field = "trust_status" if kind == "character_card" else "confidence_status"
    default = "confirmed" if kind == "character_card" else "open"
    return (
        bool(content)
        and content.get("status", "active") != "archived"
        and content.get(field, default) == "confirmed"
    )


def _changed_fields(before: dict, after: dict) -> list[dict]:
    # Older world snapshots omit optional ID arrays; a no-op editor save may
    # materialize them as []. That representation change is not new knowledge.
    optional_lists = {"participant_character_ids", "related_world_ids"}

    def value(content: dict, key: str):
        return content.get(key) or [] if key in optional_lists else content.get(key)

    keys = sorted(set(before) | set(after))
    return [
        {"key": key, "label": FIELD_LABELS.get(key, "其他资料字段")}
        for key in keys
        if value(before, key) != value(after, key)
    ]


def build_knowledge_change_impact(service: WritingService, work_id: str) -> dict[str, Any]:
    with service.repo.connect() as connection:
        # Pin one consistent database read version for the whole projection.
        connection.execute("BEGIN")
        work = connection.execute("SELECT id,version FROM works WHERE id=?", (work_id,)).fetchone()
        if not work:
            raise NotFound("work", work_id)
        revisions: dict[str, tuple[dict, dict]] = {}

        def revision(revision_id: str) -> tuple[dict, dict]:
            if revision_id not in revisions:
                row = connection.execute(
                    "SELECT r.*,a.scope_id,a.kind FROM revisions r JOIN artifacts a ON a.id=r.artifact_id WHERE r.id=? AND a.work_id=?",
                    (revision_id, work_id),
                ).fetchone()
                if not row:
                    raise ValueError("revision is not owned by this work")
                text = service.repo.read_text(row["content_uri"])
                if sha256_text(text) != row["content_hash"]:
                    raise ValueError("revision content hash mismatch")
                content = json.loads(text)
                if not isinstance(content, dict):
                    raise ValueError("revision is not an object")
                revisions[revision_id] = (dict(row), content)
            return revisions[revision_id]

        current: dict[tuple[str, str], dict] = {}
        brief_names: list[str] = []
        for artifact in connection.execute(
            "SELECT kind,scope_id,current_revision_id FROM artifacts WHERE work_id=? AND kind IN ('character_card','world_bible','brief')",
            (work_id,),
        ).fetchall():
            rid = artifact["current_revision_id"]
            if not rid:
                continue
            _, content = revision(rid)
            if artifact["kind"] == "brief":
                brief_names = content.get("characters", [])
            elif artifact["kind"] == "character_card":
                current[("character_card", artifact["scope_id"])] = {
                    "content": content,
                    "revision_id": rid,
                }
            else:
                for item in content.get("entities", []):
                    current[("world_card", item["id"])] = {"content": item, "revision_id": rid}

        # A gate proves this run reached the end of review (including a blocked result).
        latest_gates: dict[str, dict] = {}
        for row in connection.execute(
            "SELECT * FROM gates WHERE work_id=? AND kind='scene.review' ORDER BY created_at DESC,id DESC",
            (work_id,),
        ).fetchall():
            latest_gates.setdefault(row["scope_id"], dict(row))
        scene_rows = connection.execute(
            """SELECT s.*,c.title AS chapter_title FROM scenes s JOIN chapters c ON c.id=s.chapter_id
               LEFT JOIN volumes v ON v.id=c.volume_id WHERE s.work_id=?
               ORDER BY COALESCE(v.stable_order_key,''),c.stable_order_key,s.stable_order_key,s.id""",
            (work_id,),
        ).fetchall()
        result = []
        for scene in scene_rows:
            contract = json.loads(scene["contract_json"] or "{}")
            selection = contract.get("context_selection") or {"mode": "legacy"}
            explicit = selection.get("mode") == "explicit"
            if explicit:
                selected = {
                    ("character_card", key) for key in selection.get("character_card_ids", [])
                }
                # Rules and timeline are not cards; keep them outside this report's scope.
                selected.update(
                    ("world_card", key)
                    for key in selection.get("world_item_ids", [])
                    if ("world_card", key) in current
                )
            else:
                selected = {
                    key
                    for key, item in current.items()
                    if _usable(key[0], item["content"])
                    and (key[0] == "world_card" or item["content"].get("name") in brief_names)
                }
            baseline: dict[str, Any] = {
                "status": "missing",
                "run_id": None,
                "checked_at": None,
                "gate_status": None,
                "manuscript_matches": None,
                "contract_matches": None,
            }
            previous: dict[tuple[str, str], dict] = {}
            gate = latest_gates.get(scene["id"])
            if gate:
                baseline.update(
                    status="unavailable", checked_at=gate["created_at"], gate_status=gate["status"]
                )
                try:
                    gate_snapshot = json.loads(gate["result_json"])
                    run_id = gate_snapshot["agent_run_id"]
                    run = connection.execute(
                        "SELECT * FROM agent_runs WHERE id=? AND work_id=? AND scope_id=? AND status='succeeded'",
                        (run_id, work_id, scene["id"]),
                    ).fetchone()
                    if not run:
                        raise ValueError("completed review run not found")
                    text = service.repo.read_text(run["input_snapshot_uri"])
                    if sha256_text(text) != run["input_digest"]:
                        raise ValueError("review input hash mismatch")
                    snap = json.loads(text)
                    if (
                        not isinstance(snap, dict)
                        or snap.get("schema_version") != "scene-review-input/1.0"
                        or snap.get("scene_id") != scene["id"]
                        or snap.get("revision_id") != gate_snapshot.get("revision_id")
                    ):
                        raise ValueError("review snapshot identity mismatch")
                    for card in snap["runtime_character_cards"]:
                        row, content = revision(card["source_revision_id"])
                        if row["kind"] != "character_card":
                            raise ValueError("invalid card revision")
                        previous[("character_card", row["scope_id"])] = {
                            "content": content,
                            "revision_id": row["id"],
                        }
                    world = snap.get("world_bible") or {}
                    if not isinstance(world, dict):
                        raise ValueError("invalid world snapshot")
                    for item in world.get("entities", []):
                        previous[("world_card", item["id"])] = {
                            "content": item,
                            "revision_id": None,
                        }
                    baseline.update(
                        status="ready",
                        run_id=run_id,
                        manuscript_matches=snap["revision_id"] == scene["current_revision_id"],
                        contract_matches=snap["scene_contract"] == contract,
                    )
                except (OSError, UnicodeError, ValueError, TypeError, KeyError):
                    # Never invent a clean baseline or silently substitute an older review.
                    previous = {}
            dependencies = []
            for key in sorted(selected | previous.keys()):
                kind, target_id = key
                now = current.get(key, {})
                before = previous.get(key, {})
                now_content, old_content = now.get("content", {}), before.get("content", {})
                usable = key in selected and _usable(kind, now_content)
                fields = _changed_fields(old_content, now_content) if before and now else []
                if baseline["status"] != "ready":
                    status = (
                        "not_reviewed"
                        if baseline["status"] == "missing"
                        else "baseline_unavailable"
                    )
                elif key not in selected:
                    status = "removed"
                elif not usable:
                    status = "unavailable"
                elif not before:
                    status = "added"
                else:
                    status = "changed" if fields else "unchanged"
                dependencies.append(
                    {
                        "kind": kind,
                        "target_id": target_id,
                        "name": now_content.get("name")
                        or old_content.get("name")
                        or "资料已不可用",
                        "status": status,
                        "fields": fields,
                        "selected": key in selected,
                        "available": usable,
                        "basis": "explicit_selection"
                        if explicit and key in selected
                        else "legacy_selection"
                        if key in selected
                        else "last_review",
                        "before_revision_id": before.get("revision_id"),
                        "current_revision_id": now.get("revision_id"),
                    }
                )
            reasons = []
            if baseline["status"] == "ready":
                if not baseline["manuscript_matches"]:
                    reasons.append("manuscript_changed")
                if not baseline["contract_matches"]:
                    reasons.append("scene_contract_changed")
            changed = sum(
                item["status"] in {"changed", "added", "removed", "unavailable"}
                for item in dependencies
            )
            status = (
                "not_reviewed"
                if baseline["status"] == "missing"
                else "baseline_unavailable"
                if baseline["status"] == "unavailable"
                else "needs_review"
                if changed or reasons
                else "unchanged"
            )
            result.append(
                {
                    "scene_id": scene["id"],
                    "scene_title": scene["title"],
                    "chapter_id": scene["chapter_id"],
                    "chapter_title": scene["chapter_title"],
                    "has_manuscript": bool(scene["current_revision_id"]),
                    "selection_mode": "explicit" if explicit else "legacy",
                    "status": status,
                    "baseline": baseline,
                    "reasons": reasons,
                    "changed_count": changed,
                    "dependencies": dependencies,
                }
            )
        return {
            "schema_version": SCHEMA,
            "work_id": work_id,
            "work_version": work["version"],
            "scope": "character_and_world_cards",
            "read_only": True,
            "scenes": result,
            "summary": {
                status: sum(row["status"] == status for row in result)
                for status in ("needs_review", "not_reviewed", "baseline_unavailable", "unchanged")
            },
        }
