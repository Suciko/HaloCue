import base64
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.ba_character_card_import import MAX_CHARACTER_CARD_BYTES, parse_import_payload
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


def formal_card(name="天童凯伊", aliases=None):
    sequences = []
    for index, source_id in enumerate(("1001", "1002", "1003", "1004"), start=1):
        sequences.append(
            {
                "source_id": source_id,
                "source_title": f"剧情 {index}",
                "context": "活动室内确认异常设备。",
                "function": "校准跨轮承接。",
                "sample_form": "scene_dialogue",
                "evidence_status": "local_exact",
                "turns": [
                    {"speaker": "爱丽丝", "line": f"第 {index} 次确认开始。"},
                    {"speaker": name, "line": "先检查日志，不要急着下结论。"},
                    {"speaker": "爱丽丝", "line": "明白，先看记录。"},
                ],
            }
        )
    return {
        "name": name,
        "canonical_name": name,
        "aliases": list(aliases or []),
        "core": {"identity": "游戏开发部的另一重人格", "role": "负责谨慎判断"},
        "personality": {"baseline": "克制、谨慎，先核对再行动"},
        "speech": {
            "baseline": "句子完整，判断落到当前行动。",
            "voice_examples": [
                {
                    "line": "先确认日志。",
                    "source_id": "1001",
                    "source_title": "剧情 1",
                    "state": "冷静",
                    "relation": "对爱丽丝",
                    "function": "给出下一步",
                    "evidence_status": "local_exact",
                },
                {
                    "line": "这还不能证明什么。",
                    "source_id": "1002",
                    "source_title": "剧情 2",
                    "state": "警惕",
                    "relation": "对爱丽丝",
                    "function": "阻止过早结论",
                    "evidence_status": "local_variant",
                },
            ],
            "voice_sequences": sequences,
        },
        "emotions": {"calm": "先压住情绪，检查事实"},
        "relations": {"爱丽丝": {"kind": "同伴", "summary": "会提醒她不要急着行动"}},
        "ooc": {"red_lines": ["不会无依据地替别人解释动机"]},
        "extension": {"must_survive": [1, 2, 3]},
    }


def encoded_payload(card, **extra):
    raw = json.dumps(card, ensure_ascii=False).encode("utf-8")
    return {
        "filename": f"{card.get('name', '人物')}.json",
        "content_base64": base64.b64encode(raw).decode("ascii"),
        **extra,
    }


def character_artifacts(work):
    return [item for item in work["artifacts"] if item["kind"] == "character_card"]


def request(url, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_formal_ba_card_import_is_lossless_and_restart_safe(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物卡导入"})
    mother_card = formal_card()

    result = service.import_character_card(
        work["id"],
        encoded_payload(mother_card, expected_version=work["version"], source_label="用户导入正式卡"),
    )

    assert result["import_mode"] == "created"
    assert result["validation_report"]["status"] == "PASS"
    assert result["validation_report"]["production_ready"] is True
    assert result["validation_report"]["open_humanness_ready"] is True
    assert result["validation_report"]["controlled_rewrite_ready"] is True

    restarted = WritingService(tmp_path).get_work(work["id"])
    artifact = character_artifacts(restarted)[0]
    content = artifact["current_revision"]["content"]
    assert content["ba_profile"] == mother_card
    assert content["ba_profile"]["extension"]["must_survive"] == [1, 2, 3]
    assert content["validation_report"]["status"] == "PASS"
    assert content["profile_format"] == "ba-character-card/full/1.0"
    assert content["source_hash"] == result["source_hash"]
    assert (tmp_path / content["raw_import_uri"]).is_file()
    assert (tmp_path / content["cleaned_import_uri"]).is_file()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"filename": "坏卡.json", "content_base64": base64.b64encode(b"{").decode("ascii")}, "invalid_character_card_json"),
        ({"filename": "数组.json", "content_base64": base64.b64encode(b"[]").decode("ascii")}, "invalid_character_card_root"),
        ({"filename": "错误.txt", "content_base64": base64.b64encode(b"{}").decode("ascii")}, "invalid_character_card_file"),
    ],
)
def test_invalid_character_card_file_shapes_are_rejected(payload, code):
    with pytest.raises(DomainError) as error:
        parse_import_payload(payload)
    assert error.value.code == code


def test_character_card_file_size_limit_is_enforced():
    payload = {
        "filename": "过大.json",
        "content_base64": base64.b64encode(b"x" * (MAX_CHARACTER_CARD_BYTES + 1)).decode("ascii"),
    }
    with pytest.raises(DomainError) as error:
        parse_import_payload(payload)
    assert error.value.code == "character_card_file_too_large"
    assert error.value.status == 413


@pytest.mark.parametrize(
    "mutate, expected_code",
    [
        (lambda card: card.pop("core"), "required_field"),
        (lambda card: card["speech"]["voice_examples"][0].update(source_id="剧情一"), "invalid_source_id"),
        (lambda card: card["speech"]["voice_sequences"][0].update(turns=card["speech"]["voice_sequences"][0]["turns"][:2]), "invalid_turn_count"),
    ],
)
def test_structural_failures_do_not_create_artifacts(tmp_path, mutate, expected_code):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "失败不写入"})
    card = formal_card()
    mutate(card)
    preview = service.validate_character_card_import(work["id"], encoded_payload(card))
    assert preview["validation_report"]["status"] == "FAIL"
    assert any(item["code"] == expected_code for item in preview["validation_report"]["errors"])

    with pytest.raises(DomainError) as error:
        service.import_character_card(work["id"], encoded_payload(card, expected_version=work["version"]))
    assert error.value.code == "character_card_validation_failed"
    loaded = service.get_work(work["id"])
    assert loaded["version"] == work["version"]
    assert character_artifacts(loaded) == []


def test_semantic_warning_does_not_block_normal_import(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "警告可导入"})
    card = formal_card()
    card["core"]["identity"] = "她总是能看穿所有隐藏动机。"

    result = service.import_character_card(work["id"], encoded_payload(card, expected_version=work["version"]))

    assert result["validation_report"]["status"] == "PASS"
    assert {warning["code"] for warning in result["validation_report"]["warnings"]} >= {"absolute_claim", "mind_reading"}
    assert len(character_artifacts(result["work"])) == 1


def test_unique_name_or_alias_match_updates_stable_card_id(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "稳定身份"})
    first = service.import_character_card(work["id"], encoded_payload(formal_card(), expected_version=work["version"]))
    updated_card = formal_card(name="凯伊", aliases=["天童凯伊"])
    updated_card["core"]["role"] = "更新后的角色职责"

    second = service.import_character_card(
        work["id"], encoded_payload(updated_card, expected_version=first["work"]["version"])
    )

    assert second["import_mode"] == "updated"
    assert second["card_id"] == first["card_id"]
    artifact = character_artifacts(second["work"])[0]
    assert artifact["current_revision"]["ordinal"] == 2
    assert artifact["current_revision"]["content"]["ba_profile"]["core"]["role"] == "更新后的角色职责"


def test_ambiguous_identity_match_fails_without_writing(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "身份冲突"})
    first = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "name": "凯伊 A",
            "aliases": ["天童凯伊"],
            "source_refs": ["用户确认"],
        },
    )
    second = service.save_character_card(
        work["id"],
        {
            "expected_version": first["work"]["version"],
            "name": "凯伊 B",
            "aliases": ["天童凯伊"],
            "source_refs": ["用户确认"],
        },
    )
    before = service.get_work(work["id"])

    with pytest.raises(DomainError) as error:
        service.import_character_card(
            work["id"], encoded_payload(formal_card(), expected_version=second["work"]["version"])
        )

    assert error.value.code == "character_card_identity_conflict"
    after = service.get_work(work["id"])
    assert after["version"] == before["version"]
    assert [len(item["revisions"]) for item in character_artifacts(after)] == [1, 1]


def test_character_card_import_http_contract(tmp_path):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, created = request(base + "/api/v1/works", "POST", {"title": "HTTP 人物卡"})
        assert status == 201
        work = created["data"]
        payload = encoded_payload(formal_card(), expected_version=work["version"])

        status, preview = request(base + f"/api/v1/works/{work['id']}/character-cards:validate", "POST", payload)
        assert status == 200
        assert preview["ok"] is True
        assert preview["data"]["can_import"] is True

        status, imported = request(base + f"/api/v1/works/{work['id']}/character-cards:import", "POST", payload)
        assert status == 200
        assert imported["data"]["import_mode"] == "created"
        assert imported["data"]["validation_report"]["status"] == "PASS"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
