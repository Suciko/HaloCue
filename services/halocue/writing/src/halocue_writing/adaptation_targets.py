"""One target/base identity shared by adaptation generation, leases and adoption."""

import json

from .errors import DomainError


def resolve_target(connection, work_id, adaptation_chapter):
    dependency = json.loads(adaptation_chapter["dependency_json"] or "{}")
    association = dependency.get("scene_target") or {}
    scene_id = association.get("scene_id")
    if scene_id:
        scene = connection.execute(
            "SELECT id,chapter_id,current_revision_id FROM scenes WHERE id=? AND work_id=?",
            (scene_id, work_id),
        ).fetchone()
        if not scene:
            raise DomainError(
                "adaptation_target_missing",
                "已关联场景不存在，不能自动另建场景覆盖原关联。",
                status=409,
            )
        return {
            "scene_id": scene["id"],
            "chapter_id": scene["chapter_id"],
            "base_revision_id": scene["current_revision_id"],
            "mode": "replace",
        }
    chapter_id = dependency.get("target_chapter_id")
    chapter = connection.execute(
        "SELECT id FROM chapters WHERE work_id=?"
        + (" AND id=?" if chapter_id else " ORDER BY stable_order_key,id LIMIT 1"),
        (work_id, chapter_id) if chapter_id else (work_id,),
    ).fetchone()
    if not chapter:
        raise DomainError(
            "adaptation_target_missing", "请先创建或重新选择放置改编场景的章节。", status=409
        )
    legacy = connection.execute(
        "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='adaptation_manuscript' AND scope_type='adaptation_chapter' AND scope_id=?",
        (work_id, adaptation_chapter["id"]),
    ).fetchone()
    return {
        "scene_id": None,
        "chapter_id": chapter["id"],
        "base_revision_id": legacy["current_revision_id"] if legacy else None,
        "mode": "create",
    }
