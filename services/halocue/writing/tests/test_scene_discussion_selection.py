"""Scene discussion respects the author's explicit material scope."""
from halocue_writing.service import WritingService
from test_scene_conversation_harness import create_ready_scene


def test_scene_discussion_limits_explicit_materials(tmp_path):
    card_ids = ["alice-card"]
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    other = service.save_character_card(work_id, {
        "expected_version": work["version"], "card_id": "other-card",
        "name": "其他人物", "source_type": "custom", "trust_status": "confirmed",
        "source_refs": ["用户确认"],
    })
    world = service.save_world_bible(work_id, {
        "expected_version": other["work"]["version"], "title": "世界观", "source_type": "custom",
        "entities": [
            {"id": key, "name": key, "kind": "place", "source": "用户确认", "confidence_status": "confirmed"}
            for key in ("room", "unselected-room")
        ],
    })
    first = service.create_reference_file(work_id, {
        "expected_version": world["work"]["version"], "title": "本场资料",
        "source_label": "用户导入", "content": "本场资料", "trust_status": "confirmed",
    })
    second = service.create_reference_file(work_id, {
        "expected_version": first["work"]["version"], "title": "其他资料",
        "source_label": "用户导入", "content": "不应传给模型", "trust_status": "confirmed",
    })
    configured = service.configure_scene_context(work_id, scene_id, {
        "expected_version": second["work"]["version"], "character_card_ids": card_ids,
        "world_item_ids": ["room"], "reference_file_ids": [first["reference_file_id"]],
    })
    with service.repo.connect() as connection:
        context = service._scene_conversation_context(connection, work_id, {
            "task_scope": {"surface": "scene", "scene_id": scene_id},
        })
    materials = context["confirmed_materials"]
    assert [item["scope_id"] for item in materials if item["kind"] == "character_card"] == card_ids
    assert [item["id"] for item in next(item["content"] for item in materials if item["kind"] == "world_bible")["entities"]] == ["room"]
    assert [item["id"] for item in context["confirmed_references"]] == [first["reference_file_id"]]
    assert not any(item["scope_id"] == "other-card" for item in context["source_revisions"])
    # Filtering is read-only; unrelated cards remain in the work.
    assert len([item for item in service.get_work(work_id)["artifacts"] if item["kind"] == "character_card"]) == 2
    assert service.get_work(work_id)["version"] == configured["work"]["version"]
