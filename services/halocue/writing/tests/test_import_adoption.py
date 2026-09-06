from __future__ import annotations

import base64
import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


def _aap_payload() -> dict:
    source = {
        "ProjectName": "导入的 AA 工程",
        "nodes": {
            "$values": [
                {
                    "NodeName": "场景一",
                    "Scripts": {
                        "$values": [
                            {"text": "开场旁白", "isDialogScript": False, "speakerSlotNum": 0, "characters": {"$values": [{}]}},
                            {"text": "我们到了。", "isDialogScript": True, "speakerSlotNum": 0, "characters": {"$values": [{"name": "爱丽丝"}]}},
                        ]
                    },
                },
                {
                    "NodeName": "场景二",
                    "Scripts": {
                        "$values": [
                            {"text": "门后传来声音。", "isDialogScript": False, "speakerSlotNum": 0, "characters": {"$values": [{}]}},
                        ]
                    },
                },
            ]
        },
    }
    raw = json.dumps(source, ensure_ascii=False).encode("utf-8")
    return {"filename": "导入工程.aap", "content_base64": base64.b64encode(raw).decode("ascii")}


def _story_payload() -> dict:
    raw = "第一章 夜行\n场景一 校舍\n爱丽丝：听见了吗？\n灯光在走廊尽头闪烁。\n第二章 清晨\n旁白：雨停了。".encode("utf-8")
    return {"filename": "旧稿.txt", "content_base64": base64.b64encode(raw).decode("ascii")}


def test_aap_adoption_creates_formal_work_scenes_and_revisions(tmp_path):
    service = WritingService(tmp_path)
    staged = service.stage_aap_import({**_aap_payload(), "confirm": True, "idempotency_key": "aap-acceptance"})
    assert staged["status"] == "staged_draft"
    with pytest.raises(DomainError) as error:
        service.adopt_aap_import({"import_id": staged["import_id"]})
    assert error.value.code == "aap_confirmation_required"

    adopted = service.adopt_aap_import({"import_id": staged["import_id"], "confirm": True})
    assert adopted["status"] == "adopted"
    assert adopted["source_type"] == "aap"
    assert len(adopted["revision_ids"]) == 2
    work = service.get_work(adopted["work_id"])
    assert len(work["chapters"]) == 1
    scenes = work["chapters"][0]["scenes"]
    assert [scene["title"] for scene in scenes] == ["场景一", "场景二"]
    scripts = [item for item in work["artifacts"] if item["kind"] == "scene_script"]
    assert len(scripts) == 2
    assert all(item["current_revision"]["provenance"]["import_id"] == staged["import_id"] for item in scripts)
    assert any(
        "爱丽丝：我们到了。" in item["current_revision"]["content"]["text"]
        for item in scripts
    )


def test_import_adoption_is_idempotent_and_does_not_create_second_work(tmp_path):
    service = WritingService(tmp_path)
    staged = service.stage_story_import({**_story_payload(), "confirm": True, "idempotency_key": "story-acceptance"})
    first = service.adopt_story_import({"import_id": staged["import_id"], "confirm": True, "title": "我的导入剧本"})
    replay = service.adopt_story_import({"import_id": staged["import_id"], "confirm": True, "title": "被忽略的重放标题"})
    assert replay["idempotent_replay"] is True
    assert replay["work_id"] == first["work_id"]
    assert len(service.list_works()) == 1
    work = service.get_work(first["work_id"])
    assert len(work["chapters"]) == 2
    assert all(scene.get("current_revision_id") for chapter in work["chapters"] for scene in chapter["scenes"])
