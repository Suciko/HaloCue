from __future__ import annotations

import io
import wave
import zipfile

import pytest
from PIL import Image

from halocue_production.errors import ProductionError
from halocue_production.service import ProductionService


class FakeVisionProvider:
    name = "fake-vision"
    model = "vision-contract-test"

    def __init__(self) -> None:
        self.calls = 0
        self.stats = {"calls": 0, "in": 0, "out": 0}

    def complete_json_vision(self, system, images, user, schema):
        self.calls += 1
        self.stats["calls"] = self.calls
        return {
            "title": "雨夜走廊",
            "summary": "蓝绿色走廊，画面中没有人物。",
            "tags": ["室内", "雨夜", "走廊"],
            "scene_type": "室内",
            "time_of_day": "夜晚",
            "mood": "安静",
            "expression_suggestions": [
                {"face_id": "03", "label": "微笑"},
                {"face_id": "not-validated", "label": "未知"},
            ],
        }


def image_bytes(color: str = "#214f66") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (32, 18), color).save(stream, format="PNG")
    return stream.getvalue()


def wav_bytes() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        output.writeframes(b"\0" * 2205)
    return stream.getvalue()


def spine_zip_bytes() -> bytes:
    avatar = io.BytesIO()
    texture = io.BytesIO()
    Image.new("RGBA", (8, 8), "#8aa5b8").save(avatar, format="PNG")
    Image.new("RGBA", (16, 16), "#526d88").save(texture, format="PNG")
    stream = io.BytesIO()
    stem = "CH0335_noweapon_spr"
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(f"{stem}.skel", b"\x00spine\x004.2.33\x00")
        archive.writestr(
            f"{stem}.atlas",
            f"{stem}.png\nsize:16,16\nformat:RGBA8888\n03_smile\nbounds:0,0,1,1\n",
        )
        archive.writestr(f"{stem}.png", texture.getvalue())
        archive.writestr(f"{stem}-avatar.png", avatar.getvalue())
    return stream.getvalue()


def test_image_recognition_is_a_proposal_until_explicit_registration(settings, monkeypatch):
    service = ProductionService(settings)
    provider = FakeVisionProvider()
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    monkeypatch.setattr(
        service.direction_model_settings,
        "public",
        lambda: {"model": {"configured": True, "provider": provider.name, "model": provider.model}},
    )

    upload = service.upload_asset(filename="rain-hall.png", content=image_bytes())
    payload = {"kind": "background", "upload_token": upload["upload_token"]}
    validation = service.validate_custom_asset(payload)
    proposal = service.recognize_custom_asset(payload)

    assert validation["validation"]["ok"] is True
    assert proposal["recognition"]["state"] == "proposal"
    assert proposal["recognition"]["evidence"] == {
        "scope": "uploaded_image", "image_count": 1, "spine_animation_rendered": False
    }
    assert service.list_custom_assets()["items"] == []

    registered = service.register_custom_asset({
        **payload,
        "accept_recognition": True,
        "recognition_digest": proposal["recognition"]["digest"],
    })
    assert registered["asset"]["name"] == "雨夜走廊"
    assert registered["asset"]["tags"] == ["室内", "雨夜", "走廊"]
    assert "private_source" not in registered["asset"]
    assert "source_relative" not in registered["asset"]
    assert service.custom_asset_preview(registered["asset"]["asset_id"]).path.is_file()

    cached = service.recognize_custom_asset(payload)
    assert cached["idempotent"] is True
    assert provider.calls == 1
    service.jobs.close()


def test_spine_recognition_only_uses_validated_faces_and_never_claims_render(settings, monkeypatch):
    service = ProductionService(settings)
    provider = FakeVisionProvider()
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    monkeypatch.setattr(
        service.direction_model_settings,
        "public",
        lambda: {"model": {"configured": True, "provider": provider.name, "model": provider.model}},
    )
    upload = service.upload_asset(filename="student.zip", content=spine_zip_bytes())
    proposal = service.recognize_custom_asset({
        "kind": "character", "upload_token": upload["upload_token"], "identifier": "1516544"
    })["recognition"]

    assert proposal["candidate"]["expression_suggestions"] == [{"face_id": "03", "label": "微笑"}]
    assert proposal["evidence"]["scope"] == "avatar_and_texture_preview"
    assert proposal["evidence"]["spine_animation_rendered"] is False
    service.jobs.close()


def test_rejected_recognition_is_recorded_but_does_not_change_manual_labels(settings, monkeypatch):
    service = ProductionService(settings)
    provider = FakeVisionProvider()
    monkeypatch.setattr(service.direction_models, "provider", lambda: provider)
    monkeypatch.setattr(
        service.direction_model_settings,
        "public",
        lambda: {"model": {"configured": True, "provider": provider.name, "model": provider.model}},
    )
    upload = service.upload_asset(filename="manual-label.png", content=image_bytes("#725a75"))
    payload = {"kind": "cg", "upload_token": upload["upload_token"]}
    recognition = service.recognize_custom_asset(payload)["recognition"]
    registered = service.register_custom_asset({
        **payload,
        "display_name": "手工命名插图",
        "labels": {"tags": ["手工标签"]},
        "accept_recognition": False,
        "recognition_digest": recognition["digest"],
    })["asset"]

    assert registered["name"] == "手工命名插图"
    assert registered["tags"] == ["手工标签"]
    assert registered["recognition"]["state"] == "proposal"
    assert registered["recognition_accepted"] is False
    service.jobs.close()


def test_recognition_requires_a_model_and_does_not_fake_audio_support(settings):
    service = ProductionService(settings)
    image = service.upload_asset(filename="manual.png", content=image_bytes())
    with pytest.raises(ProductionError) as missing:
        service.recognize_custom_asset({"kind": "background", "upload_token": image["upload_token"]})
    assert missing.value.code == "asset_recognition_not_configured"

    sound = service.upload_asset(filename="click.wav", content=wav_bytes())
    with pytest.raises(ProductionError) as unsupported:
        service.recognize_custom_asset({"kind": "sound", "upload_token": sound["upload_token"]})
    assert unsupported.value.code == "asset_recognition_media_unsupported"
    service.jobs.close()


def test_library_is_durable_deduplicated_and_attaches_a_task_local_copy(settings):
    service = ProductionService(settings)
    upload = service.upload_asset(filename="shared.png", content=image_bytes("#445566"))
    registered = service.register_custom_asset({
        "kind": "background", "upload_token": upload["upload_token"],
        "display_name": "共享背景", "labels": {"place": "活动室"},
    })
    duplicate_upload = service.upload_asset(filename="shared-again.png", content=image_bytes("#445566"))
    duplicate = service.register_custom_asset({
        "kind": "background", "upload_token": duplicate_upload["upload_token"]
    })
    assert duplicate["idempotent"] is True
    assert duplicate["asset"]["asset_id"] == registered["asset"]["asset_id"]

    created = service.create_run({
        "project": "复用素材", "source": {"kind": "inline", "text": "旁白: 测试\n"}
    })
    attached = service.attach_custom_asset(
        created["run"]["run_id"],
        registered["asset"]["asset_id"],
        {"expected_draft_version": created["draft"]["draft_version"]},
    )
    assert attached["draft"]["draft_version"] == created["draft"]["draft_version"] + 1
    assert attached["asset"]["library_asset_id"] == registered["asset"]["asset_id"]
    assert service.task_assets(created["run"]["run_id"])["items"][0]["library_asset_id"] == registered["asset"]["asset_id"]
    service.jobs.close()

    restarted = ProductionService(settings)
    assert restarted.list_custom_assets()["items"][0]["asset_id"] == registered["asset"]["asset_id"]
    assert restarted.custom_asset_preview(registered["asset"]["asset_id"]).path.is_file()
    restarted.jobs.close()


def test_registered_asset_metadata_can_be_corrected_without_changing_source(settings):
    service = ProductionService(settings)
    assert "edit_metadata" in service.capabilities()["custom_assets"]["flow"]
    upload = service.upload_asset(filename="corridor.png", content=image_bytes("#334455"))
    original = service.register_custom_asset({
        "kind": "background",
        "upload_token": upload["upload_token"],
        "display_name": "旧名称",
        "labels": {
            "tags": ["旧标签"],
            "scene_type": "AI 旧场景",
            "time_of_day": "AI 旧时间",
        },
    })["asset"]

    updated = service.update_custom_asset(original["asset_id"], {
        "expected_metadata_version": original["metadata_version"],
        "name": "雨夜长廊",
        "nickname": "第二章备用",
        "tags": ["室内", "雨夜", "室内"],
        "labels": {"place": "教学楼", "time": "夜晚", "mood": "安静"},
    })["asset"]

    assert updated["metadata_version"] == 2
    assert updated["name"] == "雨夜长廊"
    assert updated["tags"] == ["室内", "雨夜"]
    assert updated["sha256"] == original["sha256"]
    assert updated["key"] == original["key"]
    assert "scene_type" not in updated["labels"]
    assert "time_of_day" not in updated["labels"]
    assert service.list_custom_assets(query="教学楼")["items"][0]["asset_id"] == original["asset_id"]
    assert service.list_custom_assets(query="雨夜")["items"][0]["asset_id"] == original["asset_id"]

    with pytest.raises(ProductionError) as conflict:
        service.update_custom_asset(original["asset_id"], {
            "expected_metadata_version": 1,
            "name": "过期修改",
            "tags": [],
            "labels": {},
        })
    assert conflict.value.code == "custom_asset_metadata_conflict"
    assert service.custom_asset_detail(original["asset_id"])["asset"]["name"] == "雨夜长廊"
    service.jobs.close()
