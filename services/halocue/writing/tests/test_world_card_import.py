import base64
import json

import pytest

from halocue_writing.ba_world_card_import import MAX_WORLD_CARD_BYTES, parse_import_payload
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


def world_document(name="夏莱"):
    return {
        "title": "BA 世界观资料",
        "source_type": "official_reference",
        "entities": [
            {
                "id": "world-schale",
                "name": name,
                "kind": "organization",
                "summary": "本作采用的组织入口。",
                "aliases": ["SCHALE"],
                "source": "official-corpus://schale",
                "source_type": "official_reference",
                "confidence_status": "open",
                "scope": "work",
                "participants": [],
                "related_world_ids": [],
            },
            {
                "id": "world-kivotos",
                "name": "基沃托斯",
                "kind": "place",
                "summary": "故事发生的学园都市。",
                "source": "official-corpus://kivotos",
                "source_type": "official_reference",
                "confidence_status": "confirmed",
                "scope": "work",
                "participants": [],
                "related_world_ids": ["world-schale"],
            },
        ],
        "rules": [{"id": "rule-halo", "text": "学生光环是本作采用的世界规则入口。", "category": "technology", "source": "用户确认", "confidence_status": "open"}],
        "timeline": [],
    }


def encoded(document, **extra):
    raw = json.dumps(document, ensure_ascii=False).encode("utf-8")
    return {"filename": "ba-world.json", "content_base64": base64.b64encode(raw).decode("ascii"), **extra}


def world_artifacts(work):
    return [item for item in work["artifacts"] if item["kind"] == "world_bible"]


def test_world_document_import_preserves_source_and_files(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观导入"})
    result = service.import_world_card(work["id"], encoded(world_document(), expected_version=work["version"], source_label="BA 资料包"))
    assert result["import_mode"] == "created"
    assert result["validation_report"]["status"] == "PASS"
    artifact = world_artifacts(result["work"])[0]
    content = artifact["current_revision"]["content"]
    assert content["import_metadata"]["profile_format"] == "ba-world-card/full/1.0"
    assert (tmp_path / content["import_metadata"]["raw_import_uri"]).is_file()
    assert len(content["entities"]) == 2
    assert content["entities"][0]["confidence_status"] == "open"


def test_world_document_import_updates_stable_entity_without_duplicate(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观身份"})
    first = service.import_world_card(work["id"], encoded(world_document(), expected_version=work["version"]))
    document = world_document()
    document["entities"][0]["id"] = ""
    document["entities"][0]["summary"] = "更新后的本作定义。"
    document["entities"][1]["related_world_ids"] = []
    second = service.import_world_card(work["id"], encoded(document, expected_version=first["work"]["version"]))
    assert second["import_mode"] == "updated"
    entities = world_artifacts(second["work"])[0]["current_revision"]["content"]["entities"]
    assert len(entities) == 2
    assert next(item for item in entities if item["name"] == "夏莱")["id"] == "world-schale"
    assert next(item for item in entities if item["name"] == "夏莱")["summary"] == "更新后的本作定义。"


def test_world_import_validation_failure_does_not_write(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观失败"})
    broken = world_document()
    broken["entities"][0].pop("source")
    preview = service.validate_world_card_import(work["id"], encoded(broken))
    assert preview["can_import"] is False
    assert any(item["code"] == "required_field" for item in preview["validation_report"]["errors"])
    with pytest.raises(DomainError) as error:
        service.import_world_card(work["id"], encoded(broken, expected_version=work["version"]))
    assert error.value.code == "world_card_validation_failed"
    assert world_artifacts(service.get_work(work["id"])) == []


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"filename": "bad.txt", "content_base64": "e30="}, "invalid_world_card_file"),
        ({"filename": "bad.json", "content_base64": "W10="}, "invalid_world_card_root"),
        ({"filename": "bad.json", "content_base64": "eA=="}, "invalid_world_card_json"),
    ],
)
def test_world_import_file_shape_errors(payload, code):
    with pytest.raises(DomainError) as error:
        parse_import_payload(payload)
    assert error.value.code == code


def test_world_import_file_size_limit():
    payload = {"filename": "large.json", "content_base64": base64.b64encode(b"x" * (MAX_WORLD_CARD_BYTES + 1)).decode("ascii")}
    with pytest.raises(DomainError) as error:
        parse_import_payload(payload)
    assert error.value.code == "world_card_file_too_large"
