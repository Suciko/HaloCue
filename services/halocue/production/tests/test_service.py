from __future__ import annotations

import json
import hashlib
import os
import time
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

import halocue_production.legacy_adapter as legacy_adapter_module
from halocue_production.errors import ProductionError
from halocue_production.config import Settings
from halocue_production.service import ProductionService
from halocue_production.jobs import JobCancelled, JobRecord, JobRegistry
from halocue_production.model_settings import DirectionModelSettings


SCRIPT = """# 第一章
## 场景 01
爱丽丝: 前方发现了新的副本入口！
凯伊: ……先别进去。
"""


def configured_resource_settings(settings, tmp_path):
    index = tmp_path / "resources.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1, "BG_RainyStation": 2, "BG_Classroom": 3, "BG_CS_Abydos_06": 4},
                "sounds": ["SE_DoorOpen_01", "SE_Confirm_01"],
                "characters": [
                    {
                        "identifier": "alice-school",
                        "name": "爱丽丝",
                        "club": "游戏开发部",
                        "spine": "characters/alice",
                        "faces": [
                            {"id": "00", "label": "", "raw": ""},
                            {"id": "01", "label": "", "raw": ""},
                        ],
                    }
                ],
                "enums": {"emoticon": {}, "action": {}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return Settings(
        project_root=settings.project_root,
        data_dir=settings.data_dir,
        legacy_root=settings.legacy_root,
        resource_index=index,
        aa_data=None,
        host="127.0.0.1",
        port=0,
    )


def test_new_run_freezes_portrait_layout_metadata(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    source = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    source["characters"][0]["aliases"] = ["天童爱丽丝"]
    configured.resource_index.write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )
    service = ProductionService(configured)

    created = service.create_run({
        "project": "站位元数据快照",
        "source": {"kind": "inline", "text": "爱丽丝: 测试。\n"},
    })
    token = created["run"]["draft_token"]
    frozen_path = configured.data_dir / "drafts" / token / "resources.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))

    assert frozen["portrait_layout_catalog"]["version"] == 1
    assert frozen["characters"][0]["portrait_layout"]["confidence"] == (
        "coarse_name_consensus"
    )

    source["characters"][0]["portrait_layout"] = {"face_direction": "left"}
    configured.resource_index.write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )
    assert json.loads(frozen_path.read_text(encoding="utf-8")) == frozen
    service.jobs.close()


def test_execute_compile_keeps_snapshot_index_and_enables_snapshot_layout(
    settings, tmp_path, monkeypatch,
):
    service = ProductionService(settings)
    build_bundle = service.adapter._modules["build_bundle"]
    captured = {}
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "project").mkdir(parents=True)

    def compile_probe(options, **_kwargs):
        captured.update(options)
        return {}

    class ManagerProbe:
        def __init__(self, *, store):
            self.store = store

        def execute_build_worker(self, token, build_id):
            build_bundle.compile_script({"index": "snapshot/resources.json"})
            return {"build_id": build_id, "bundle_dir": str(bundle_dir)}

    monkeypatch.setattr(build_bundle, "compile_script", compile_probe)
    monkeypatch.setattr(build_bundle, "BuildBundleManager", ManagerProbe)

    service.adapter.execute_compile("draft-test", "build-test")

    assert captured["index"] == "snapshot/resources.json"
    assert captured["portrait_layout_mode"] == "snapshot_only"
    service.jobs.close()


def test_new_run_freezes_visual_face_labels_from_aa_database(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir()
    (legacy_root / "aa_assets.db").touch()
    configured = replace(configured, legacy_root=legacy_root)
    service = ProductionService(configured)
    calls = []

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()

    def merge(resources, actual_connection, *, scope):
        calls.append((actual_connection, scope))
        merged = dict(resources)
        merged["face_capabilities"] = {
            "alice-school": [{
                "spine_signature": "sig-alice",
                "outfit_key": "alice",
                "faces": [{
                    "id": "01",
                    "semantic_cn": "认真专注｜解释关键线索时保持镇定",
                    "sources": ["vision:model"],
                    "semantic_level": "rich",
                }],
            }],
        }
        return merged

    monkeypatch.setattr(service.adapter._modules["assetdb"], "connect", lambda _path: connection)
    monkeypatch.setattr(
        service.adapter._modules["asset_catalog"], "merge_model_constraints", merge
    )

    created = service.create_run(
        {"project": "表情标签冻结", "source": {"kind": "inline", "text": "爱丽丝: 测试\n"}}
    )
    resources = service.adapter._draft_resources(created["run"]["draft_token"])

    assert resources["face_capabilities"]["alice-school"][0]["faces"][0]["id"] == "01"
    assert calls and calls[0][0] is connection
    assert calls[0][1].endswith(created["run"]["draft_token"])
    assert connection.closed is True
    service.jobs.close()


def test_task_asset_registration_is_isolated_and_updates_frozen_resources(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "素材登记", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    image = tmp_path / "自定义背景.png"
    Image.new("RGB", (16, 9), "#24745d").save(image)

    uploaded = service.upload_asset(filename=image.name, content=image.read_bytes())
    assert "path" not in uploaded
    validation = service.validate_task_asset(
        created["run"]["run_id"], {"kind": "background", "upload_token": uploaded["upload_token"]}
    )
    assert validation["validation"]["ok"] is True
    assert "source" not in validation["validation"]

    registered = service.register_task_asset(
        created["run"]["run_id"],
        {
            "kind": "background", "upload_token": uploaded["upload_token"],
            "labels": {"label": "夜间走廊"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    assert registered["status"] == "registered"
    assert registered["asset"]["key"] == "自定义背景"
    assert "private_source" not in registered["asset"]
    assert service.adapter.draft_resource_contains(
        str(created["run"]["draft_token"]), "backgrounds", "自定义背景"
    )
    assets = service.task_assets(created["run"]["run_id"])
    assert assets["items"][0]["name"] == "自定义背景"
    preview = service.run_resource_preview(created["run"]["run_id"], "backgrounds", "自定义背景")
    assert preview.path.is_file()
    service.jobs.close()


def test_task_asset_registration_requires_current_draft_version(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "素材版本", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    image = tmp_path / "版本.png"
    Image.new("RGB", (8, 8), "#ffffff").save(image)
    uploaded = service.upload_asset(filename=image.name, content=image.read_bytes())
    with pytest.raises(ProductionError) as error:
        service.register_task_asset(
            created["run"]["run_id"],
            {"kind": "background", "upload_token": uploaded["upload_token"], "expected_draft_version": 999},
        )
    assert error.value.code == "revision_conflict"
    service.jobs.close()


def test_task_cg_background_is_frozen_previewable_and_injected_as_bg_override(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "自定义 CG", "source": {"kind": "inline", "text": "旁白: 测试。\n"}}
    )
    image = tmp_path / "rainy-promise.png"
    Image.new("RGB", (32, 18), "#4b6389").save(image)
    uploaded = service.upload_asset(filename=image.name, content=image.read_bytes())
    validated = service.validate_task_asset(
        created["run"]["run_id"],
        {"kind": "background", "upload_token": uploaded["upload_token"]},
    )
    assert validated["validation"]["ok"] is True
    assert validated["validation"]["kind"] == "background"

    registered = service.register_task_asset(
        created["run"]["run_id"],
        {
            "kind": "background",
            "upload_token": uploaded["upload_token"],
            "labels": {"label": "雨夜的约定"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    key = registered["asset"]["key"]
    assert key == "rainy-promise"
    catalog = service.list_run_resources(created["run"]["run_id"], "backgrounds")
    imported = next(item for item in catalog["items"] if item["key"] == key)
    assert imported == {
        "key": key,
        "name": "雨夜的约定",
        "source": "task_import",
        "asset_id": registered["asset"]["asset_id"],
        "preview_available": True,
    }
    preview = service.run_resource_preview(created["run"]["run_id"], "backgrounds", key)
    assert preview.path.is_file()

    card_id = registered["draft"]["cards"][0]["card_id"]
    segmented = service.create_cg_segment(
        created["run"]["run_id"],
        {
            "start_card_id": card_id,
            "end_card_id": card_id,
            "background_key": key,
            "label": "雨夜的约定",
            "expected_draft_version": registered["draft"]["draft_version"],
        },
    )
    with pytest.raises(ProductionError) as in_use:
        service.remove_task_asset(
            created["run"]["run_id"],
            registered["asset"]["asset_id"],
            {"expected_draft_version": segmented["draft"]["draft_version"]},
        )
    assert in_use.value.code == "asset_in_use"

    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "project").mkdir(parents=True)
    service.adapter._inject_task_assets_into_bundle(
        token=str(created["run"]["draft_token"]), bundle_dir=bundle_dir
    )
    manifest = json.loads((bundle_dir / "project" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["BgOverrides"] == ["bgs\\rainy-promise.png"]
    assert (bundle_dir / "project" / "bgs" / "rainy-promise.png").is_file()
    service.jobs.close()


def test_task_asset_can_only_be_removed_when_unused(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "素材移除", "source": {"kind": "inline", "text": "# 待生成自定义背景：夜间走廊\n旁白: 测试\n"}}
    )
    image = tmp_path / "夜间走廊.png"
    Image.new("RGB", (16, 9), "#24745d").save(image)
    uploaded = service.upload_asset(filename=image.name, content=image.read_bytes())
    registered = service.register_task_asset(
        created["run"]["run_id"],
        {
            "kind": "background", "upload_token": uploaded["upload_token"],
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    asset = registered["asset"]
    token = str(created["run"]["draft_token"])
    asset_dir = configured.data_dir / "drafts" / token / "custom-assets" / asset["asset_id"]
    assert asset_dir.is_dir()

    request_card = next(card for card in registered["draft"]["cards"] if card["kind"] == "background_request")
    resolved = service.resolve_background_request(
        created["run"]["run_id"],
        request_card["card_id"],
        {
            "action": "select", "background_key": asset["key"],
            "expected_draft_version": registered["draft"]["draft_version"],
        },
    )
    with pytest.raises(ProductionError) as in_use:
        service.remove_task_asset(
            created["run"]["run_id"], asset["asset_id"],
            {"expected_draft_version": resolved["draft"]["draft_version"]},
        )
    assert in_use.value.code == "asset_in_use"

    # A separate unreferenced import can be removed without touching the earlier asset.
    unused_image = tmp_path / "备用背景.png"
    Image.new("RGB", (16, 9), "#6d89a8").save(unused_image)
    unused_upload = service.upload_asset(filename=unused_image.name, content=unused_image.read_bytes())
    unused = service.register_task_asset(
        created["run"]["run_id"],
        {
            "kind": "background", "upload_token": unused_upload["upload_token"],
            "expected_draft_version": resolved["draft"]["draft_version"],
        },
    )
    removed = service.remove_task_asset(
        created["run"]["run_id"], unused["asset"]["asset_id"],
        {"expected_draft_version": unused["draft"]["draft_version"]},
    )
    assert removed["draft"]["draft_version"] == unused["draft"]["draft_version"] + 1
    assert not service.adapter.draft_resource_contains(token, "backgrounds", unused["asset"]["key"])
    assert [item["asset_id"] for item in service.task_assets(created["run"]["run_id"])["items"]] == [asset["asset_id"]]
    assert not (configured.data_dir / "drafts" / token / "custom-assets" / unused["asset"]["asset_id"]).exists()
    service.jobs.close()


def test_create_run_persists_release_and_real_draft(settings):
    service = ProductionService(settings)
    result = service.create_run(
        {"project": "第一章", "source": {"kind": "inline", "text": SCRIPT}}
    )

    run = result["run"]
    draft = result["draft"]
    assert run["state"] == "waiting_for_review"
    assert run["source_summary"]["speakers"] == ["凯伊", "爱丽丝"]
    assert draft["counts"]["total"] == 4
    assert draft["counts"]["blocking_errors"] == 2
    assert (settings.data_dir / "releases" / run["release_id"] / "source.txt").read_text(
        encoding="utf-8"
    ) == SCRIPT
    assert (settings.data_dir / "drafts" / run["draft_token"] / "identity.json").is_file()
    service.jobs.close()


def test_writing_script_release_handoff_is_verified_persisted_and_idempotent(settings):
    service = ProductionService(settings)
    release_hash = hashlib.sha256(SCRIPT.encode("utf-8")).hexdigest()
    payload = {
        "project": "第一章 · v1",
        "source": {"kind": "inline", "text": SCRIPT},
        "script_release": {
            "schema_version": "1.0",
            "id": "release-000000000001",
            "work_id": "work-000000000001",
            "display_version": "v1",
            "content_hash": release_hash,
            "writing_pack_version": "ba-writing.productized/1.0.0",
        },
    }

    first = service.create_run(payload)
    origin = first["run"]["source_summary"]["upstream_release"]
    assert origin == {
        "kind": "halocue_writing",
        "schema_version": "1.0",
        "release_id": "release-000000000001",
        "display_version": "v1",
        "content_hash": release_hash,
        "work_id": "work-000000000001",
        "writing_pack_version": "ba-writing.productized/1.0.0",
    }
    assert first["handoff"]["idempotent"] is False
    assert first["run"]["release_id"] != origin["release_id"]

    second = service.create_run(payload)
    assert second["run"]["run_id"] == first["run"]["run_id"]
    assert second["handoff"]["idempotent"] is True
    assert len(service.repository.list_runs()) == 1
    assert len(list((settings.data_dir / "releases").glob("release-*"))) == 1
    service.jobs.close()


def test_writing_script_release_handoff_rejects_content_hash_mismatch(settings):
    service = ProductionService(settings)
    with pytest.raises(ProductionError) as error:
        service.create_run(
            {
                "project": "损坏的交接",
                "source": {"kind": "inline", "text": SCRIPT},
                "script_release": {
                    "id": "release-000000000001",
                    "display_version": "v1",
                    "content_hash": "0" * 64,
                },
            }
        )
    assert error.value.code == "script_release_hash_mismatch"
    assert service.repository.list_runs() == []
    assert list((settings.data_dir / "releases").iterdir()) == []
    service.jobs.close()


def test_task_preflight_summary_explains_frozen_draft_decisions(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {
            "project": "任务初审摘要",
            "source": {
                "kind": "inline",
                "text": "## 放学后的走廊\n# 待生成自定义背景：黄昏走廊\n爱丽丝: 我们到了。\n凯伊: 先观察一下。\n",
            },
        }
    )
    summary = service.task_preflight_summary(created["run"]["run_id"])
    assert summary["kind"] == "task_preflight_summary"
    assert summary["source"] == "frozen_draft"
    assert [(item["speaker"], item["count"]) for item in summary["speakers"]] == [("凯伊", 1), ("爱丽丝", 1)]
    assert all(item["mapping"]["kind"] == "unset" for item in summary["speakers"])
    assert summary["requests"][0]["kind"] == "background_request"
    assert summary["next_action"]["stage"] == "mapping"
    assert "未映射" in summary["next_action"]["label"]
    service.jobs.close()


def test_task_character_detail_uses_frozen_resources(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "冻结角色详情", "source": {"kind": "inline", "text": "爱丽丝: 测试。\n"}}
    )
    run_id = created["run"]["run_id"]
    detail = service.run_character_resource(run_id, "alice-school")
    assert detail["frozen"] is True
    assert detail["character"]["name"] == "爱丽丝"
    assert [face["id"] for face in detail["character"]["faces"]] == ["00", "01"]

    with pytest.raises(ProductionError) as missing:
        service.run_character_resource(run_id, "introduced-after-run")
    assert missing.value.code == "character_not_found"
    service.jobs.close()


def test_performance_preview_uses_current_draft_and_frozen_cast(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {
            "project": "草稿演出预览",
            "source": {"kind": "inline", "text": "@bg BG_Classroom\n爱丽丝: 我们到了。\n"},
        }
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "portrait", "id": "alice-school", "name": "爱丽丝"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    line = next(card for card in mapped["draft"]["cards"] if card["kind"] == "line")
    updated = service.update_card(
        run_id,
        line["card_id"],
        {
            "patch": {"face": "01", "fx": "特写"},
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    preview = service.performance_preview(run_id)
    assert preview["kind"] == "draft_performance_preview"
    assert preview["read_only"] is True
    assert preview["draft_version"] == updated["draft"]["draft_version"]
    frame = next(item for item in preview["frames"] if item["card_id"] == line["card_id"])
    assert frame["presentation"] == "dialogue"
    assert frame["background_key"] == "BG_Classroom"
    assert frame["background_preview_available"] is False
    assert frame["speaker"] == {"name": "爱丽丝", "mapping_kind": "portrait", "character_id": "alice-school"}
    assert {item["kind"]: item["value"] for item in frame["annotations"]} == {"表情": "01", "画面效果": "特写"}
    assert "private_source" not in json.dumps(preview, ensure_ascii=False)
    service.jobs.close()


def test_line_face_must_belong_to_mapped_frozen_character(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "台词演出", "source": {"kind": "inline", "text": "爱丽丝: 测试。\n"}}
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "portrait", "id": "alice-school", "name": "爱丽丝"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    line = next(card for card in mapped["draft"]["cards"] if card["kind"] == "line")
    updated = service.update_card(
        run_id,
        line["card_id"],
        {
            "patch": {"face": "01", "emo": "惊讶", "act": "挥手", "fx": "特写"},
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    current = next(card for card in updated["draft"]["cards"] if card["card_id"] == line["card_id"])["current"]
    assert current["face"] == "01"
    assert current["emo"] == "惊讶"

    with pytest.raises(ProductionError) as invalid_face:
        service.update_card(
            run_id,
            line["card_id"],
            {
                "patch": {"face": "not-a-frozen-face"},
                "expected_draft_version": updated["draft"]["draft_version"],
            },
        )
    assert invalid_face.value.code == "face_not_available_for_character"

    with pytest.raises(ProductionError) as changed_speaker:
        service.update_card(
            run_id,
            line["card_id"],
            {
                "patch": {"who": "旁白"},
                "expected_draft_version": updated["draft"]["draft_version"],
            },
        )
    assert changed_speaker.value.code == "face_requires_portrait_mapping"
    service.jobs.close()


def test_source_preflight_explains_structure_without_creating_persistent_work(settings):
    service = ProductionService(settings)
    result = service.preflight_source(
        {
            "source": {
                "kind": "inline",
                "text": "## 放学后的走廊\n爱丽丝: 我们到了。\n凯伊: 先观察一下。\n@wait\n@typo value\n",
            }
        }
    )
    assert result["kind"] == "static_preflight"
    assert result["format"]["label"] == "AA 指令混合格式"
    assert [(item["name"], item["count"]) for item in result["speakers"]] == [("凯伊", 1), ("爱丽丝", 1)]
    assert result["scenes"] == [{"title": "放学后的走廊", "line_no": 1}]
    assert {item["code"] for item in result["directives"]["issues"]} == {
        "missing_directive_argument", "unknown_directive"
    }
    assert not service.repository.list_runs()
    assert not list((settings.data_dir / "releases").glob("*"))
    service.jobs.close()


def test_cast_mapping_review_and_optimistic_version_gate(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "第一章", "source": {"kind": "inline", "text": SCRIPT}}
    )
    run_id = created["run"]["run_id"]
    version = created["draft"]["draft_version"]

    first = service.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": version,
        },
    )
    with pytest.raises(ProductionError) as stale:
        service.update_cast(
            run_id,
            {
                "speaker": "凯伊",
                "mapping": {"kind": "narrator"},
                "expected_draft_version": version,
            },
        )
    assert stale.value.code == "revision_conflict"

    second = service.update_cast(
        run_id,
        {
            "speaker": "凯伊",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": first["draft"]["draft_version"],
        },
    )
    assert second["draft"]["counts"]["blocking_errors"] == 0
    approved = service.approve_review(
        run_id,
        {
            "card_ids": None,
            "expected_draft_version": second["draft"]["draft_version"],
        },
    )
    assert approved["draft"]["review_ready"] is True
    assert approved["run"]["state"] == "ready_to_compile"
    service.jobs.close()


def test_editing_installed_draft_invalidates_previous_build_and_install_claim(settings):
    service = ProductionService(settings)
    created = service.create_run({"project": "已安装后修改", "source": {"kind": "inline", "text": SCRIPT}})
    run_id = created["run"]["run_id"]
    current = created["draft"]["draft_version"]
    for speaker in ("爱丽丝", "凯伊"):
        result = service.update_cast(run_id, {"speaker": speaker, "mapping": {"kind": "narrator"}, "expected_draft_version": current})
        current = result["draft"]["draft_version"]
    approved = service.approve_review(run_id, {"card_ids": None, "expected_draft_version": current})
    run = service._run(run_id)
    run.state = "installed"
    run.last_build_id = "build-old"
    run.last_installed_project = "已安装工程"
    service.repository.save_run(run)

    changed = service.update_cast(run_id, {"speaker": "爱丽丝", "mapping": {"kind": "voice", "display_name": "爱丽丝语音"}, "expected_draft_version": approved["draft"]["draft_version"]})
    assert changed["run"]["state"] == "waiting_for_review"
    assert changed["run"]["last_build_id"] is None
    assert changed["run"]["last_installed_project"] is None
    service.jobs.close()


def test_compile_reports_missing_configuration_after_review(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "第一章", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": 1,
        },
    )
    approved = service.approve_review(
        run_id,
        {
            "card_ids": None,
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    with pytest.raises(ProductionError) as error:
        service.compile(
            run_id,
            {"expected_draft_version": approved["draft"]["draft_version"]},
        )
    assert error.value.code == "compile_not_configured"
    service.jobs.close()


def test_ai_direction_mode_is_not_simulated_without_a_provider(settings):
    service = ProductionService(settings)
    with pytest.raises(ProductionError) as error:
        service.create_run(
            {
                "project": "不能伪造 AI",
                "generation_mode": "ai_direction",
                "source": {"kind": "inline", "text": "旁白: 测试\n"},
            }
        )
    assert error.value.code == "direction_generation_not_configured"
    assert (
        service.health()["capabilities"]["generation_modes"]["ai_direction"]["state"]
        == "not_configured"
    )
    service.jobs.close()


def test_ai_preflight_is_read_only_and_persists_a_safe_task_local_result(settings, monkeypatch):
    monkeypatch.setenv("HALOCUE_PREFLIGHT_KEY", "preflight-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "preflight-model",
            "api_key_env": "HALOCUE_PREFLIGHT_KEY",
        }
    )

    class FakeProvider:
        name = "fake"
        model = "preflight-model"

        def complete_json(self, _system, _volatile, _user, _schema):
            return {
                "potential_speakers": ["老师"],
                "scenes": [{
                    "start_line": 1, "end_line": 2, "location": "教室", "time": "放学后",
                    "background_need": "放学后的教室",
                }],
                "ambiguities": [{"line": 2, "message": "确认老师是否实际出场"}],
            }

    service.direction_models.provider = lambda: FakeProvider()
    created = service.create_run(
        {"project": "AI 初审只读", "source": {"kind": "inline", "text": "旁白: 开始\n爱丽丝: 老师来了\n"}}
    )
    before = created["draft"]
    status, accepted = service.start_ai_preflight(created["run"]["run_id"])
    assert status == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert job and job.state == "succeeded"
    result = service.ai_preflights(created["run"]["run_id"])
    assert result["read_only"] is True
    assert result["items"][0]["analysis"]["potential_speakers"] == ["老师"]
    assert result["items"][0]["source"] == {"kind": "frozen_source", "line_count": 2}
    assert "path" not in json.dumps(result, ensure_ascii=False)
    after = service.run_detail(created["run"]["run_id"])["draft"]
    assert after["draft_version"] == before["draft_version"]
    assert after["content_revision"] == before["content_revision"]
    run = service._run(created["run"]["run_id"])
    stored_draft = service.adapter.store.load_draft(str(run.draft_token))
    source_text = str(
        stored_draft.get("source_text") or stored_draft.get("edited_text") or ""
    )
    plan, reference = service.adapter._compatible_performance_plan(
        str(run.draft_token), source_text,
    )
    assert plan[0]["location"] == "教室"
    assert plan[0]["source"] == "ai_preflight"
    assert reference["scene_count"] == 1
    assert reference["preflight_id"] == result["items"][0]["preflight_id"]
    assert service.adapter._compatible_performance_plan(
        str(run.draft_token), source_text.replace("开始", "变化"),
    ) == ([], None)
    service.jobs.close()


def test_ai_preflight_does_not_expose_server_validation_fields_to_model(settings, monkeypatch):
    """The model must not be primed to echo internal line-count metadata."""
    monkeypatch.setenv("HALOCUE_PREFLIGHT_CONTEXT_KEY", "preflight-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "preflight-model",
            "api_key_env": "HALOCUE_PREFLIGHT_CONTEXT_KEY",
        }
    )

    captured: dict[str, str] = {}

    class CapturingProvider:
        name = "fake"
        model = "preflight-model"

        def complete_json(self, _system, volatile, _user, _schema):
            captured["volatile"] = volatile
            return {"potential_speakers": [], "scenes": [], "ambiguities": []}

    service.direction_models.provider = lambda: CapturingProvider()
    created = service.create_run(
        {"project": "AI 初审上下文", "source": {"kind": "inline", "text": "旁白: 开始\n"}}
    )
    _, accepted = service.start_ai_preflight(created["run"]["run_id"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert job and job.state == "succeeded"
    assert captured["volatile"] == ""
    service.jobs.close()


def test_ai_preflight_normalizes_missing_advisory_scene_fields(settings, monkeypatch):
    """A scene with only line bounds remains a usable read-only suggestion."""
    monkeypatch.setenv("HALOCUE_PREFLIGHT_PARTIAL_KEY", "preflight-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "preflight-model",
            "api_key_env": "HALOCUE_PREFLIGHT_PARTIAL_KEY",
        }
    )

    class PartialProvider:
        name = "fake"
        model = "preflight-model"

        def complete_json(self, _system, _volatile, _user, _schema):
            return {
                "potential_speakers": [],
                "scenes": [{"start_line": 1, "end_line": 1}],
                "ambiguities": [],
            }

    service.direction_models.provider = lambda: PartialProvider()
    created = service.create_run(
        {"project": "AI 初审可选场景字段", "source": {"kind": "inline", "text": "旁白: 开始\n"}}
    )
    _, accepted = service.start_ai_preflight(created["run"]["run_id"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert job and job.state == "succeeded"
    scene = service.ai_preflights(created["run"]["run_id"])["items"][0]["analysis"]["scenes"][0]
    assert scene["location"] == ""
    assert scene["time"] == ""
    assert scene["background_need"] == ""
    service.jobs.close()


def test_ai_preflight_malformed_model_output_fails_without_writing_a_result(settings, monkeypatch):
    monkeypatch.setenv("HALOCUE_PREFLIGHT_BAD_KEY", "preflight-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "preflight-model",
            "api_key_env": "HALOCUE_PREFLIGHT_BAD_KEY",
        }
    )

    class InvalidProvider:
        name = "fake"
        model = "invalid"

        def complete_json(self, _system, _volatile, _user, _schema):
            return {"potential_speakers": [], "scenes": [], "ambiguities": [], "extra": True}

    service.direction_models.provider = lambda: InvalidProvider()
    created = service.create_run(
        {"project": "AI 初审失败", "source": {"kind": "inline", "text": "旁白: 开始\n"}}
    )
    _, accepted = service.start_ai_preflight(created["run"]["run_id"])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert job and job.state == "failed"
    assert job.error["code"] == "ai_preflight_invalid_output"
    assert service.ai_preflights(created["run"]["run_id"])["items"] == []
    service.jobs.close()


def test_failed_ai_preflight_can_be_resubmitted_without_replacing_history(settings, monkeypatch):
    monkeypatch.setenv("HALOCUE_PREFLIGHT_RETRY_KEY", "preflight-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "preflight-model",
            "api_key_env": "HALOCUE_PREFLIGHT_RETRY_KEY",
        }
    )

    class InvalidProvider:
        name = "fake"
        model = "invalid"

        def complete_json(self, _system, _volatile, _user, _schema):
            return {"potential_speakers": [], "scenes": [], "ambiguities": [], "extra": True}

    class ValidProvider:
        name = "fake"
        model = "valid"

        def complete_json(self, _system, _volatile, _user, _schema):
            return {
                "potential_speakers": [],
                "scenes": [],
                "ambiguities": [],
            }

    service.direction_models.provider = lambda: InvalidProvider()
    created = service.create_run(
        {"project": "AI 初审重试", "source": {"kind": "inline", "text": "旁白: 开始\n"}}
    )
    _, accepted = service.start_ai_preflight(created["run"]["run_id"])
    original_id = accepted["job"]["job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        original = service.jobs.get(original_id)
        if original and original.state == "failed":
            break
        time.sleep(0.01)
    assert original and original.state == "failed"
    assert service.job_detail(original_id)["job"]["retryable"] is True
    assert "retry_context" not in service.job_detail(original_id)["job"]

    service.direction_models.provider = lambda: ValidProvider()
    retried = service.retry_job(original_id)
    retry_id = retried["job"]["job_id"]
    assert retried["retried_from"] == original_id
    assert retry_id != original_id
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        retry = service.jobs.get(retry_id)
        if retry and retry.state in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert retry and retry.state == "succeeded"
    assert service.jobs.get(original_id).state == "failed"
    assert len(service.ai_preflights(created["run"]["run_id"])["items"]) == 1
    service.jobs.close()


def test_direction_model_configuration_is_redacted_and_env_backed(settings, monkeypatch):
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(settings)
    saved = service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
            "max_tokens": 1024,
        }
    )
    assert saved["model"]["configured"] is True
    assert saved["model"]["secret_source"] == "environment"
    assert "api_key" not in saved["model"]
    assert "test-secret" not in json.dumps(saved)
    persisted = json.loads((settings.data_dir / "direction-model.json").read_text(encoding="utf-8"))
    assert "api_key" not in persisted
    service.jobs.close()


def test_direction_model_rejects_missing_secret_before_persisting(settings):
    service = ProductionService(settings)
    with pytest.raises(ProductionError) as error:
        service.configure_direction_model(
            {
                "provider": "openai",
                "base_url": "https://example.invalid/v1",
                "model": "test-model",
            }
        )
    assert error.value.code == "model_secret_required"
    assert not (settings.data_dir / "direction-model.json").exists()
    service.jobs.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_direction_model_dpapi_secret_round_trip_is_redacted(settings):
    store = DirectionModelSettings(settings.data_dir)
    saved = store.save(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key": "dpapi-placeholder-secret",
        }
    )
    assert saved["model"]["secret_source"] == "dpapi"
    assert "dpapi-placeholder-secret" not in json.dumps(saved)
    provider, private = store.provider_settings()
    assert provider == "openai"
    assert private["api_key"] == "dpapi-placeholder-secret"
    assert b"dpapi-placeholder-secret" not in (
        settings.data_dir / "secrets" / "direction-model.dpapi"
    ).read_bytes()


def test_ai_direction_run_requires_cast_mapping_before_background_job(settings, monkeypatch):
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
        }
    )
    created = service.create_run(
        {
            "project": "AI 演出门控",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "爱丽丝: 测试\n"},
        }
    )
    with pytest.raises(ProductionError) as error:
        service.generate_direction(
            created["run"]["run_id"],
            {"expected_draft_version": created["draft"]["draft_version"]},
        )
    assert error.value.code == "cast_mapping_required"
    service.jobs.close()


def test_ai_direction_background_job_writes_a_reviewable_draft(settings, tmp_path, monkeypatch):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
        }
    )

    class FakeProvider:
        name = "fake"
        model = "fake-direction"
        cfg = {
            "max_tokens": 4096,
            "annotation_max_tokens": 4096,
            "reasoning_mode": "balanced",
        }
        supports_compact_annotation = True
        stats = {"calls": 0, "in": 0, "out": 0}
        request_records = []
        reasoning_records = []

        def complete_json(self, _static, _volatile, _user, _schema):
            self.stats["calls"] += 1
            return {"lines": []}

        def report(self):
            return "fake"

    monkeypatch.setattr(service.direction_models, "provider", lambda: FakeProvider())
    original_annotate = service.adapter._modules["annotate"].annotate_script

    def annotate_with_proposal(*args, **kwargs):
        result = original_annotate(*args, **kwargs)
        result["proposals"] = [{
            "proposal_id": "prop-audit-test", "type": "applied_pending", "origin": "model",
            "rule": "llm_annotation", "card_id": "pre-write-card", "field": "face",
            "before": None, "after": "00", "state": "pending",
        }]
        return result

    monkeypatch.setattr(service.adapter._modules["annotate"], "annotate_script", annotate_with_proposal)
    created = service.create_run(
        {
            "project": "AI 演出后台任务",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 测试\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    status, accepted = service.generate_direction(
        created["run"]["run_id"],
        {
            "story_type": "main",
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    assert status == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = service.job_detail(accepted["job"]["job_id"])["job"]
        if job["state"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert job["state"] == "succeeded", json.dumps(job, ensure_ascii=False)
    assert job["result"]["model"] == "fake-direction"
    detail = service.run_detail(created["run"]["run_id"])
    assert detail["run"]["state"] == "waiting_for_review"
    assert detail["draft"]["draft_version"] == mapped["draft"]["draft_version"] + 1
    attempt = (
        configured.data_dir
        / "drafts"
        / created["run"]["draft_token"]
        / "direction-generations"
        / accepted["generation_id"]
    )
    assert (attempt / "source.txt").is_file()
    assert (attempt / "annotated.txt").is_file()
    assert (attempt / "result.json").is_file()
    assert (attempt / "proposals.json").is_file()
    audit = service.direction_proposals(created["run"]["run_id"])
    assert audit["read_only"] is True
    assert audit["total"] == 1
    proposal = audit["generations"][0]["proposals"][0]
    assert proposal["field"] == "face"
    assert proposal["after"] == "00"
    assert proposal["can_apply_safely"] is False
    assert "pre-write-card" not in json.dumps(audit, ensure_ascii=False)
    service.jobs.close()


def test_incomplete_direction_generation_keeps_checkpoint_audit_without_writing_draft(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "未完成演出不写回", "source": {"kind": "inline", "text": "旁白: 原文\n"}}
    )
    original = created["draft"]

    class Provider:
        name = "fake"
        model = "checkpoint-model"
        stats = {"in": 120, "out": 8}

    monkeypatch.setattr(
        service.adapter._modules["annotate"],
        "annotate_script",
        lambda *_args, **_kwargs: {
            "text": "旁白: 部分结果\n",
            "proposals": [],
            "diagnostics": [{"code": "request_deadline", "level": "warning", "detail": "timeout"}],
            "agent": {
                "pending_targets": 2,
                "metrics": {
                    "requests": 3,
                    "retries": 1,
                    "subdivisions": 1,
                    "cache_reported": True,
                    "cache_read_tokens": 90,
                    "uncached_input_tokens": 30,
                    "cache_write_tokens": 30,
                    "warm_cache_hit_rate": 0.75,
                    "failed_request_count": 1,
                    "uncached_input_tokens_per_completed_target": 12.5,
                },
            },
            "incomplete": True,
            "pending_targets": 2,
            "direction_change_count": 0,
        },
    )

    result = service.adapter.execute_direction_generation(
        token=created["run"]["draft_token"],
        generation_id="direction-incomplete-test",
        provider=Provider(),
        expected_draft_version=original["draft_version"],
        story_type="auto",
        layout_mode="ai",
    )

    current = service.adapter.draft_detail(created["run"]["draft_token"])
    attempt = configured.data_dir / "drafts" / created["run"]["draft_token"] / "direction-generations" / "direction-incomplete-test"
    assert result["status"] == "incomplete"
    assert result["pending_targets"] == 2
    assert current["draft_version"] == original["draft_version"]
    assert next(card for card in current["cards"] if card["kind"] == "line")["current"]["text"] == "原文"
    assert not (attempt / "annotated.txt").exists()
    audit = service.adapter.direction_proposals(created["run"]["draft_token"])
    assert audit["generations"][0]["status"] == "incomplete"
    assert audit["generations"][0]["metrics"]["requests"] == 3
    assert audit["generations"][0]["metrics"]["cache_write_tokens"] == 30
    assert audit["generations"][0]["metrics"]["warm_cache_hit_rate"] == 0.75
    assert audit["generations"][0]["metrics"]["failed_request_count"] == 1
    assert audit["generations"][0]["metrics"]["uncached_input_tokens_per_completed_target"] == 12.5
    assert audit["generations"][0]["diagnostics"][0]["code"] == "request_deadline"
    service.jobs.close()


def test_empty_direction_generation_is_audited_as_failure_without_writing_draft(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "空演出不伪装成功", "source": {"kind": "inline", "text": "旁白: 原文\n"}}
    )
    original = created["draft"]

    class Provider:
        name = "fake"
        model = "empty-model"
        stats = {}

    monkeypatch.setattr(
        service.adapter._modules["annotate"],
        "annotate_script",
        lambda options, **_kwargs: {
            "text": Path(options["script"]).read_text(encoding="utf-8"),
            "proposals": [],
            "diagnostics": [{"code": "no_effective_direction", "level": "warning"}],
            "agent": {"metrics": {"requests": 1, "retries": 0, "subdivisions": 0}},
            "pending_targets": 0,
            "direction_change_count": 0,
        },
    )

    with pytest.raises(ProductionError) as failure:
        service.adapter.execute_direction_generation(
            token=created["run"]["draft_token"],
            generation_id="direction-empty-test",
            provider=Provider(),
            expected_draft_version=original["draft_version"],
            story_type="auto",
            layout_mode="ai",
        )

    assert failure.value.code == "direction_generation_empty"
    current = service.adapter.draft_detail(created["run"]["draft_token"])
    assert current["draft_version"] == original["draft_version"]
    audit = service.adapter.direction_proposals(created["run"]["draft_token"])
    generation = audit["generations"][0]
    assert generation["status"] == "failed"
    assert generation["error"]["code"] == "direction_generation_empty"
    assert generation["metrics"]["requests"] == 1
    service.jobs.close()


def test_direction_failure_surfaces_persisted_sanitized_request_records(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "失败请求日志", "source": {"kind": "inline", "text": "旁白: 原文\n"}}
    )

    class Provider:
        name = "fake"
        model = "failure-model"
        stats = {}

    def fail_after_telemetry(options, **_kwargs):
        path = Path(options["checkpoint_dir"]) / "annotation-telemetry" / "run-test" / "requests.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "agent_request_index": 1,
            "chunk_id": "scene-1-chunk-1",
            "outcome": "failed",
            "error_code": "model_service_unavailable",
            "stable_prefix_hash": "safe-hash",
        }) + "\n", encoding="utf-8")
        raise RuntimeError("gateway failed")

    monkeypatch.setattr(
        service.adapter._modules["annotate"], "annotate_script", fail_after_telemetry,
    )
    with pytest.raises(ProductionError) as failure:
        service.adapter.execute_direction_generation(
            token=created["run"]["draft_token"],
            generation_id="direction-request-log-test",
            provider=Provider(),
            expected_draft_version=created["draft"]["draft_version"],
            story_type="auto",
            layout_mode="ai",
        )

    assert failure.value.details["request_log_files"]
    audit = service.adapter.direction_proposals(created["run"]["draft_token"])
    metrics = audit["generations"][0]["metrics"]
    assert metrics["failed_request_count"] == 1
    assert metrics["request_records"][0]["error_code"] == "model_service_unavailable"
    assert "prompt" not in json.dumps(metrics)
    service.jobs.close()


@pytest.mark.parametrize(
    ("requested_mode", "expected_mode"),
    [(None, "ai"), ("pure_ai", "pure_ai"), ("rules", "rules")],
)
def test_direction_layout_mode_is_forwarded_and_frozen(
    settings, tmp_path, monkeypatch, requested_mode, expected_mode,
):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
        }
    )

    class FakeProvider:
        name = "fake"
        model = "fake-direction"
        stats = {"calls": 0, "in": 0, "out": 0}

    captured = {}

    def annotate_probe(options, **_kwargs):
        captured.update(options)
        return {
            "text": Path(options["script"]).read_text(encoding="utf-8"),
            "proposals": [],
            "diagnostics": [],
            "story_type": options["story_type"],
            "agent": {},
            "direction_change_count": 1,
        }

    monkeypatch.setattr(service.direction_models, "provider", lambda: FakeProvider())
    monkeypatch.setattr(
        service.adapter._modules["annotate"], "annotate_script", annotate_probe,
    )
    created = service.create_run(
        {
            "project": f"站位模式-{expected_mode}",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 测试\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    payload = {"expected_draft_version": mapped["draft"]["draft_version"]}
    if requested_mode is not None:
        payload["layout_mode"] = requested_mode
    _, accepted = service.generate_direction(created["run"]["run_id"], payload)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = service.job_detail(accepted["job"]["job_id"])["job"]
        if job["state"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert job["state"] == "succeeded", json.dumps(job, ensure_ascii=False)
    assert captured["layout_mode"] == expected_mode

    token = created["run"]["draft_token"]
    cast = service.adapter.store.load_cast(token)
    assert cast["layout_mode"] == expected_mode
    detail = service.run_detail(created["run"]["run_id"])
    assert detail["run"]["source_summary"]["layout_mode"] == expected_mode
    assert job["result"]["layout_mode"] == expected_mode

    approved = service.approve_review(
        created["run"]["run_id"],
        {
            "card_ids": None,
            "expected_draft_version": detail["draft"]["draft_version"],
        },
    )
    manager = service.adapter._modules["build_bundle"].BuildBundleManager(
        store=service.adapter.store,
    )
    build_id = manager.create_compile_snapshot(
        token, approved["draft"]["draft_version"],
    )
    snapshot_cast = json.loads(
        (
            configured.data_dir
            / "drafts"
            / token
            / "builds"
            / ".tmp"
            / build_id
            / "input"
            / "cast.json"
        ).read_text(encoding="utf-8")
    )
    assert snapshot_cast["layout_mode"] == expected_mode
    service.jobs.close()


def test_direction_layout_mode_rejects_unknown_value(settings, monkeypatch):
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(settings)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
        }
    )
    created = service.create_run(
        {
            "project": "无效站位模式",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 测试\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )

    with pytest.raises(ProductionError) as error:
        service.generate_direction(
            created["run"]["run_id"],
            {
                "expected_draft_version": mapped["draft"]["draft_version"],
                "layout_mode": "random",
            },
        )
    assert error.value.code == "invalid_layout_mode"
    assert error.value.status == 400
    service.jobs.close()


def test_safe_ai_proposal_can_be_reverted_once_and_becomes_stale_after_content_change(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "AI 建议撤销", "source": {"kind": "inline", "text": "旁白: 原句\n"}}
    )
    run_id = created["run"]["run_id"]
    line = created["draft"]["cards"][0]
    applied = service.adapter.update_card(
        token=created["run"]["draft_token"],
        card_id=line["card_id"],
        patch={"emo": "惊讶"},
        expected_draft_version=created["draft"]["draft_version"],
    )
    attempt = service.adapter.store.get_draft_path(created["run"]["draft_token"]) / "direction-generations" / "direction-safe-test"
    attempt.mkdir(parents=True)
    (attempt / "result.json").write_text(json.dumps({"generation_id": "direction-safe-test", "model": "test", "draft_version": applied["draft_version"]}), encoding="utf-8")
    (attempt / "proposals.json").write_text(json.dumps([{
        "proposal_id": "prop-safe-test", "type": "applied_pending", "field": "emo",
        "before": None, "after": "惊讶", "state": "pending", "safe_card_id": line["card_id"],
        "based_on_content_revision": applied["content_revision"],
    }], ensure_ascii=False), encoding="utf-8")

    audit = service.direction_proposals(run_id)
    proposal = audit["generations"][0]["proposals"][0]
    assert proposal["can_apply_safely"] is True
    assert proposal["card_id"] == line["card_id"]
    reverted = service.decide_direction_proposal(
        run_id, "prop-safe-test", {"action": "reject", "expected_draft_version": applied["draft_version"]}
    )
    current = next(item for item in reverted["draft"]["cards"] if item["card_id"] == line["card_id"])["current"]
    assert not current.get("emo")
    assert reverted["draft"]["draft_version"] == applied["draft_version"] + 1
    decided = service.direction_proposals(run_id)["generations"][0]["proposals"][0]
    assert decided["state"] == "rejected"
    assert decided["can_apply_safely"] is False

    with pytest.raises(ProductionError) as repeated:
        service.decide_direction_proposal(
            run_id, "prop-safe-test", {"action": "reject", "expected_draft_version": reverted["draft"]["draft_version"]}
        )
    assert repeated.value.code == "proposal_already_decided"
    service.jobs.close()


def test_ai_direction_does_not_overwrite_user_edits_made_while_running(
    settings, tmp_path, monkeypatch
):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_TEST_MODEL_KEY",
        }
    )
    entered = threading.Event()
    release = threading.Event()

    class SlowProvider:
        name = "slow-fake"
        model = "slow-direction"
        cfg = {"max_tokens": 4096, "annotation_max_tokens": 4096}
        supports_compact_annotation = True
        stats = {"calls": 0}
        request_records = []
        reasoning_records = []

        def complete_json(self, _static, _volatile, _user, _schema):
            entered.set()
            release.wait(timeout=5)
            return {"lines": [], "state_delta": {}, "memory_events": []}

        def report(self):
            return "slow fake"

    monkeypatch.setattr(service.direction_models, "provider", lambda: SlowProvider())
    created = service.create_run(
        {
            "project": "并发修改保护",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 原文\n"},
        }
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    _, accepted = service.generate_direction(
        run_id, {"expected_draft_version": mapped["draft"]["draft_version"]}
    )
    assert entered.wait(timeout=5)
    line = next(card for card in mapped["draft"]["cards"] if card["kind"] == "line")
    edited = service.update_card(
        run_id,
        line["card_id"],
        {
            "patch": {"text": "用户运行中修改"},
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = service.job_detail(accepted["job"]["job_id"])["job"]
        if job["state"] in {"succeeded", "failed", "superseded"}:
            break
        time.sleep(0.02)
    assert job["state"] == "superseded"
    assert job["error"]["code"] == "job_superseded"
    detail = service.run_detail(run_id)
    current = next(card for card in detail["draft"]["cards"] if card["kind"] == "line")
    assert current["current"]["text"] == "用户运行中修改"
    assert detail["draft"]["draft_version"] == edited["draft"]["draft_version"]
    service.jobs.close()


def test_install_rejects_snapshot_that_has_not_finished_building(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "未完成构建", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    run_id = created["run"]["run_id"]
    run = service._run(run_id)
    run.state = "compiling"
    run.pending_build_id = "build-000000000001"
    service.repository.save_run(run)
    with pytest.raises(ProductionError) as error:
        service.install(run_id, {"build_id": "build-000000000001"})
    assert error.value.code == "build_not_installable"
    service.jobs.close()


def test_service_restores_persisted_runs(settings):
    first = ProductionService(settings)
    created = first.create_run(
        {"project": "恢复测试", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    first.jobs.close()

    restored = ProductionService(settings)
    detail = restored.run_detail(created["run"]["run_id"])
    assert detail["run"]["project"] == "恢复测试"
    assert detail["draft"]["counts"]["total"] == 1
    restored.jobs.close()


def test_service_marks_in_process_direction_job_interrupted_after_restart(settings):
    first = ProductionService(settings)
    created = first.create_run(
        {"project": "中断恢复", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    run = first._run(created["run"]["run_id"])
    run.state = "generating_direction"
    first.repository.save_run(run)
    first.jobs.close()

    restored = ProductionService(settings)
    detail = restored.run_detail(run.run_id)
    assert detail["run"]["state"] == "direction_interrupted"
    restored.jobs.close()


def test_job_registry_persists_completed_and_interrupted_jobs(tmp_path):
    jobs_dir = tmp_path / "jobs"
    first = JobRegistry(jobs_dir)
    completed = first.submit("test", lambda: {"value": 7})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = first.get(completed.job_id)
        if current and current.state == "succeeded":
            break
        time.sleep(0.01)
    assert current and current.result == {"value": 7}
    first.close()

    interrupted = JobRecord(
        "job-000000000001",
        "direction_generation",
        "running",
        "2026-08-14T00:00:00+00:00",
        "2026-08-14T00:00:01+00:00",
    )
    (jobs_dir / f"{interrupted.job_id}.json").write_text(
        json.dumps(interrupted.to_dict()), encoding="utf-8"
    )
    restored = JobRegistry(jobs_dir)
    assert restored.get(completed.job_id).state == "succeeded"
    recovered = restored.get(interrupted.job_id)
    assert recovered.state == "interrupted"
    assert recovered.error["code"] == "job_interrupted"
    assert restored.list()[0].job_id == interrupted.job_id
    restored.close()


def test_job_registry_persists_associated_run_identifier(tmp_path):
    jobs_dir = tmp_path / "jobs"
    first = JobRegistry(jobs_dir)
    completed = first.submit(
        "compile",
        lambda: {"build_id": "build-000000000000"},
        run_id="run-000000000001",
        retry_context={"expected_draft_version": 7},
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = first.get(completed.job_id)
        if current and current.state == "succeeded":
            break
        time.sleep(0.01)
    assert current and current.run_id == "run-000000000001"
    first.close()
    restored = JobRegistry(jobs_dir)
    assert restored.get(completed.job_id).run_id == "run-000000000001"
    assert restored.get(completed.job_id).retry_context == {"expected_draft_version": 7}
    restored.close()


def test_old_job_record_without_retry_context_remains_readable():
    restored = JobRecord.from_dict(
        {
            "job_id": "job-000000000001",
            "kind": "compile",
            "state": "failed",
            "created_at": "2026-08-14T00:00:00+00:00",
            "updated_at": "2026-08-14T00:00:01+00:00",
            "run_id": "run-000000000001",
        }
    )
    assert restored.retry_context == {}


def test_retry_rejects_old_compile_job_without_version_context(settings):
    service = ProductionService(settings)

    def fail():
        raise RuntimeError("compile failed")

    failed = service.jobs.submit("compile", fail, run_id="run-000000000001")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = service.jobs.get(failed.job_id)
        if current and current.state == "failed":
            break
        time.sleep(0.01)
    assert current and current.state == "failed"
    assert service.job_detail(failed.job_id)["job"]["retryable"] is False
    with pytest.raises(ProductionError) as error:
        service.retry_job(failed.job_id)
    assert error.value.code == "job_retry_unavailable"
    service.jobs.close()


def test_aa_workspace_configuration_persists_and_enables_capabilities(
    settings, tmp_path
):
    aa_data = tmp_path / "configured-aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    popup_dir = aa_data / "overrides" / "popups"
    popup_dir.mkdir()
    (popup_dir / "Event03_CH0070.png").write_bytes(b"test")

    first = ProductionService(settings)
    configured = first.configure_aa_workspace({"path": str(aa_data)})
    assert configured["aa_workspace"] == {
        "configured": True,
        "path": str(aa_data.resolve()),
        "valid": True,
    }
    assert configured["capabilities"]["install"]["state"] == "available"
    first.jobs.close()

    restored = ProductionService(settings)
    assert restored.settings.aa_data == aa_data.resolve()
    assert restored.aa_workspace_settings()["capabilities"]["install"]["state"] == "available"
    restored.jobs.close()


def test_invalid_aa_workspace_is_rejected(settings, tmp_path):
    incomplete = tmp_path / "incomplete-aa-data"
    (incomplete / "projects").mkdir(parents=True)
    service = ProductionService(settings)

    with pytest.raises(ProductionError) as error:
        service.configure_aa_workspace({"path": str(incomplete)})

    assert error.value.code == "invalid_aa_workspace"
    assert error.value.details["missing"] == ["saves", "overrides", "settings"]
    service.jobs.close()


def test_card_crud_updates_versions_order_and_review_state(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {
            "project": "卡片编辑",
            "source": {
                "kind": "inline",
                "text": "## 场景 1\n爱丽丝: 你好\n@wait 1\n",
            },
        }
    )
    run_id = created["run"]["run_id"]
    original = created["draft"]
    line_card = next(card for card in original["cards"] if card["kind"] == "line")
    scene_card = next(card for card in original["cards"] if card["kind"] == "scene")

    updated = service.update_card(
        run_id,
        line_card["card_id"],
        {
            "patch": {"text": "修改后的台词"},
            "expected_draft_version": original["draft_version"],
        },
    )
    assert updated["draft"]["draft_version"] == original["draft_version"] + 1
    assert updated["draft"]["content_revision"] == original["content_revision"] + 1
    changed = next(
        card for card in updated["draft"]["cards"] if card["card_id"] == line_card["card_id"]
    )
    assert changed["current"]["text"] == "修改后的台词"

    inserted = service.insert_card(
        run_id,
        {
            "after_card_id": line_card["card_id"],
            "kind": "line",
            "fields": {"who": "凯伊", "text": "新台词"},
            "expected_draft_version": updated["draft"]["draft_version"],
        },
    )
    manual = next(card for card in inserted["draft"]["cards"] if card["origin"] == "manual")
    assert manual["review_state"] == "pending"

    moved = service.move_card(
        run_id,
        {
            "card_id": manual["card_id"],
            "before_card_id": scene_card["card_id"],
            "expected_draft_version": inserted["draft"]["draft_version"],
        },
    )
    assert moved["draft"]["cards"][0]["card_id"] == manual["card_id"]

    deleted = service.delete_card(
        run_id,
        manual["card_id"],
        {"expected_draft_version": moved["draft"]["draft_version"]},
    )
    assert all(card["card_id"] != manual["card_id"] for card in deleted["draft"]["cards"])
    service.jobs.close()


def test_card_edit_rejects_stale_version_and_background_request_deletion(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {
            "project": "卡片保护",
            "source": {
                "kind": "inline",
                "text": "# 待生成自定义背景：雨夜车站\n旁白: 测试\n",
            },
        }
    )
    run_id = created["run"]["run_id"]
    draft = created["draft"]
    line_card = next(card for card in draft["cards"] if card["kind"] == "line")
    request_card = next(
        card for card in draft["cards"] if card["kind"] == "background_request"
    )

    changed = service.update_card(
        run_id,
        line_card["card_id"],
        {
            "patch": {"text": "第一次修改"},
            "expected_draft_version": draft["draft_version"],
        },
    )
    with pytest.raises(ProductionError) as stale:
        service.update_card(
            run_id,
            line_card["card_id"],
            {
                "patch": {"text": "过期修改"},
                "expected_draft_version": draft["draft_version"],
            },
        )
    assert stale.value.code == "revision_conflict"

    with pytest.raises(ProductionError) as protected:
        service.delete_card(
            run_id,
            request_card["card_id"],
            {"expected_draft_version": changed["draft"]["draft_version"]},
        )
    assert protected.value.code == "request_card_requires_resolution"
    service.jobs.close()


def test_structured_directive_edit_validates_input_and_resets_review(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "演出指令编辑", "source": {"kind": "inline", "text": "@wait 500\n@camera -\n"}}
    )
    run_id = created["run"]["run_id"]
    first, second = created["draft"]["cards"]
    approved = service.approve_review(
        run_id, {"card_ids": None, "expected_draft_version": created["draft"]["draft_version"]}
    )
    changed = service.update_card(
        run_id,
        first["card_id"],
        {"patch": {"cmd": "camera_hold", "arg": "-"}, "expected_draft_version": approved["draft"]["draft_version"]},
    )
    edited = next(card for card in changed["draft"]["cards"] if card["card_id"] == first["card_id"])
    later = next(card for card in changed["draft"]["cards"] if card["card_id"] == second["card_id"])
    assert edited["current"] == {"cmd": "camera_hold", "arg": "-"}
    assert edited["review_state"] == "pending"
    assert later["review_state"] == "pending"

    with pytest.raises(ProductionError) as bad_wait:
        service.update_card(
            run_id, first["card_id"],
            {"patch": {"cmd": "wait", "arg": "马上"}, "expected_draft_version": changed["draft"]["draft_version"]},
        )
    assert bad_wait.value.code == "directive_argument_invalid"
    with pytest.raises(ProductionError) as needs_picker:
        service.update_card(
            run_id, first["card_id"],
            {"patch": {"cmd": "bg", "arg": "BG_Black"}, "expected_draft_version": changed["draft"]["draft_version"]},
        )
    assert needs_picker.value.code == "directive_requires_resource_picker"
    service.jobs.close()


def test_real_compile_and_install_use_isolated_workspace(settings, tmp_path):
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    resource_settings = configured_resource_settings(settings, tmp_path)
    configured = Settings(
        project_root=settings.project_root,
        data_dir=settings.data_dir,
        legacy_root=settings.legacy_root,
        resource_index=resource_settings.resource_index,
        aa_data=aa_data,
        host="127.0.0.1",
        port=0,
    )
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "隔离构建测试", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": 1,
        },
    )
    approved = service.approve_review(
        run_id,
        {
            "card_ids": None,
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    token = approved["run"]["draft_token"]
    build_id = service.adapter.create_compile_snapshot(
        token, approved["draft"]["draft_version"]
    )
    built = service.adapter.execute_compile(token, build_id)
    assert built["build_id"] == build_id
    assert built["bundle_dir"].startswith(str(settings.data_dir / "drafts"))

    run = service._run(run_id)
    run.state = "compiled"
    run.last_build_id = build_id
    run.last_build_draft_version = approved["draft"]["draft_version"]
    service.repository.save_run(run)
    options = service.install_options(run_id)
    assert options["source_project"] == "隔离构建测试"
    assert options["existing_install"] is None
    assert "path" not in json.dumps(options)

    (aa_data / "projects" / "测试分类-重命名剧情.aap").write_text(
        "{}", encoding="utf-8"
    )
    checked = service.check_install(
        run_id,
        {"category": "测试分类", "story_name": "重命名剧情"},
    )
    assert checked["target"] == {
        "project": "测试分类-重命名剧情",
        "source_project": "隔离构建测试",
        "category": "测试分类",
        "story_name": "重命名剧情",
        "mode": "renamed_copy",
        "available": False,
        "conflict": True,
    }

    installed = service.adapter.install(
        token=token,
        build_id=build_id,
        category="测试分类",
        story_name="隔离构建测试",
    )
    assert Path(installed["aap_path"]).is_file()
    assert Path(installed["aap_path"]).is_relative_to(aa_data)
    service.jobs.close()


def test_resource_catalog_is_searchable_and_does_not_expose_paths(settings, tmp_path):
    service = ProductionService(configured_resource_settings(settings, tmp_path))
    backgrounds = service.list_resources("backgrounds", query="rain", limit=1)
    sounds = service.list_resources("sounds", query="confirm")
    characters = service.list_resources("characters", query="爱丽丝")

    assert backgrounds["items"][0]["key"] == "BG_RainyStation"
    assert backgrounds["items"][0]["preview_available"] is False
    assert sounds["items"][0]["key"] == "SE_Confirm_01"
    assert sounds["items"][0]["preview_available"] is False
    assert characters["items"][0]["face_count"] == 2
    assert characters["items"][0]["preview_available"] is False
    assert not any(
        "path" in item
        for result in (backgrounds, sounds, characters)
        for item in result["items"]
    )
    detail = service.character_resource("alice-school")["character"]
    assert detail["faces"] == [
        {"id": "00", "raw": "", "label": ""},
        {"id": "01", "raw": "", "label": ""},
    ]
    assert "path" not in detail
    service.jobs.close()


def test_character_name_baseline_controls_display_search_and_frozen_import(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    index["characters"][0]["name"] = "愛麗絲"
    configured.resource_index.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    baseline = tmp_path / "character-name-baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "characters": [
                    {
                        "identifier": "alice-school",
                        "name_zh_cn": "爱丽丝",
                        "name_ja_fandom": "天童爱丽丝",
                        "aliases": ["天童爱丽丝", "アリス"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    configured = Settings(
        project_root=configured.project_root,
        data_dir=configured.data_dir,
        legacy_root=configured.legacy_root,
        resource_index=configured.resource_index,
        aa_data=None,
        name_baseline=baseline,
        host="127.0.0.1",
        port=0,
    )
    service = ProductionService(configured)

    catalog = service.list_resources("characters", query="アリス")
    assert catalog["items"][0]["name"] == "爱丽丝"
    assert catalog["items"][0]["name_source"] == "zh_cn_official_or_curated"
    assert service.character_resource("alice-school")["character"]["source_name"] == "愛麗絲"

    created = service.create_run(
        {"project": "译名快照", "source": {"kind": "inline", "text": "老师: 测试。\n"}}
    )
    frozen = service.run_character_resource(created["run"]["run_id"], "alice-school")["character"]
    assert frozen["name"] == "爱丽丝"
    assert frozen["source_name"] == "愛麗絲"
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "老师",
            "mapping": {"kind": "portrait", "id": "alice-school", "name": "愛麗絲"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    assert mapped["draft"]["cast"]["cast"]["老师"]["name"] == "爱丽丝"
    service.jobs.close()


def test_popup_catalog_is_separate_from_cg_background_selection(settings, tmp_path):
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    popup_dir = aa_data / "overrides" / "popups"
    popup_dir.mkdir()
    (popup_dir / "Event03_CH0070.png").write_bytes(b"test")
    configured = configured_resource_settings(settings, tmp_path)
    configured = Settings(
        project_root=configured.project_root,
        data_dir=configured.data_dir,
        legacy_root=configured.legacy_root,
        resource_index=configured.resource_index,
        aa_data=aa_data,
        host="127.0.0.1",
        port=0,
    )
    service = ProductionService(configured)
    catalog = service.list_resources("cg", query="0070")
    assert catalog["items"] == [
        {
            "key": "Event03_CH0070",
            "name": "Event03_CH0070",
            "source": "aa_popup_override",
            "preview_available": True,
        }
    ]
    created = service.create_run(
        {"project": "冻结 CG", "source": {"kind": "inline", "text": "老师: 测试\n"}}
    )
    (popup_dir / "Late_Image.png").write_bytes(b"late")
    frozen_popups = service.list_run_resources(created["run"]["run_id"], "cg")
    assert [item["key"] for item in frozen_popups["items"]] == ["Event03_CH0070"]
    with pytest.raises(ProductionError) as missing:
        service.create_cg_segment(
            created["run"]["run_id"],
            {
                "start_card_id": created["draft"]["cards"][0]["card_id"],
                "end_card_id": created["draft"]["cards"][0]["card_id"],
                "background_key": "Event03_CH0070",
                "expected_draft_version": created["draft"]["draft_version"],
            },
        )
    assert missing.value.code == "cg_background_not_found"
    cg_catalog = service.list_run_resources(created["run"]["run_id"], "cg-backgrounds")
    assert [item["key"] for item in cg_catalog["items"]] == ["BG_CS_Abydos_06"]
    with pytest.raises(ProductionError) as ordinary_background:
        service.create_cg_segment(
            created["run"]["run_id"],
            {
                "start_card_id": created["draft"]["cards"][0]["card_id"],
                "end_card_id": created["draft"]["cards"][0]["card_id"],
                "background_key": "BG_Classroom",
                "expected_draft_version": created["draft"]["draft_version"],
            },
        )
    assert ordinary_background.value.code == "cg_background_not_found"
    service.jobs.close()


def test_cast_binding_uses_the_draft_frozen_character_catalog(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {
            "project": "冻结角色目录",
            "source": {"kind": "inline", "text": "爱丽丝: 测试\n"},
        }
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "portrait", "id": "alice-school"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    assert mapped["draft"]["cast"]["cast"]["爱丽丝"]["id"] == "alice-school"

    current_index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    current_index["characters"].append(
        {"identifier": "late-character", "name": "后来加入的角色"}
    )
    configured.resource_index.write_text(
        json.dumps(current_index, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ProductionError) as missing:
        service.update_cast(
            run_id,
            {
                "speaker": "爱丽丝",
                "mapping": {"kind": "portrait", "id": "late-character"},
                "expected_draft_version": mapped["draft"]["draft_version"],
            },
        )
    assert missing.value.code == "character_not_found"
    service.jobs.close()


def test_background_request_resolution_preserves_card_identity(settings, tmp_path):
    service = ProductionService(configured_resource_settings(settings, tmp_path))
    created = service.create_run(
        {
            "project": "背景处理",
            "source": {
                "kind": "inline",
                "text": "# 待生成自定义背景：雨夜车站\n旁白: 测试\n",
            },
        }
    )
    run_id = created["run"]["run_id"]
    request_card = next(
        card for card in created["draft"]["cards"] if card["kind"] == "background_request"
    )

    resolved = service.resolve_background_request(
        run_id,
        request_card["card_id"],
        {
            "action": "select",
            "background_key": "BG_RainyStation",
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    same_card = next(
        card
        for card in resolved["draft"]["cards"]
        if card["card_id"] == request_card["card_id"]
    )
    assert same_card["kind"] == "dir"
    assert same_card["current"] == {"cmd": "bg", "arg": "BG_RainyStation"}
    assert not any(
        issue["code"] == "bg.request_unresolved" for issue in same_card["issues"]
    )

    with pytest.raises(ProductionError) as missing:
        service.resolve_background_request(
            run_id,
            same_card["card_id"],
            {
                "action": "select",
                "background_key": "BG_NotIndexed",
                "expected_draft_version": resolved["draft"]["draft_version"],
            },
        )
    assert missing.value.code == "background_not_found"
    service.jobs.close()


def test_sound_directive_can_be_replaced_or_explicitly_removed(settings, tmp_path):
    service = ProductionService(configured_resource_settings(settings, tmp_path))
    created = service.create_run(
        {
            "project": "音效处理",
            "source": {"kind": "inline", "text": "@se 未登记音效\n旁白: 测试\n"},
        }
    )
    run_id = created["run"]["run_id"]
    sound_card = next(
        card
        for card in created["draft"]["cards"]
        if card["kind"] == "dir" and card["current"].get("cmd") == "se"
    )
    assert any(issue["code"] == "sound.unregistered" for issue in sound_card["issues"])

    selected = service.resolve_sound_request(
        run_id,
        sound_card["card_id"],
        {
            "action": "select",
            "sound_key": "SE_DoorOpen_01",
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    same_card = next(
        card
        for card in selected["draft"]["cards"]
        if card["card_id"] == sound_card["card_id"]
    )
    assert same_card["current"] == {"cmd": "se", "arg": "SE_DoorOpen_01"}
    assert not any(
        issue["code"] == "sound.unregistered" for issue in same_card["issues"]
    )

    removed = service.resolve_sound_request(
        run_id,
        sound_card["card_id"],
        {
            "action": "remove",
            "expected_draft_version": selected["draft"]["draft_version"],
        },
    )
    assert all(
        card["card_id"] != sound_card["card_id"] for card in removed["draft"]["cards"]
    )
    service.jobs.close()


def test_cg_segment_compiles_as_background_with_named_slot_zero_and_no_portraits(settings, tmp_path):
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    popup_dir = aa_data / "overrides" / "popups"
    popup_dir.mkdir()
    (popup_dir / "Event03_CH0070.png").write_bytes(b"test")
    configured = configured_resource_settings(settings, tmp_path)
    configured = Settings(
        project_root=configured.project_root,
        data_dir=configured.data_dir,
        legacy_root=configured.legacy_root,
        resource_index=configured.resource_index,
        aa_data=aa_data,
        host="127.0.0.1",
        port=0,
    )
    service = ProductionService(configured)
    created = service.create_run(
        {
            "project": "CG 段落",
            "source": {"kind": "inline", "text": "老师: 这里交给我。\n爱丽丝: 收到！\n"},
        }
    )
    run_id = created["run"]["run_id"]
    teacher = service.update_cast(
        run_id,
        {
            "speaker": "老师",
            "mapping": {"kind": "voice", "display_name": "老师"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "portrait", "id": "alice-school"},
            "expected_draft_version": teacher["draft"]["draft_version"],
        },
    )
    cards = mapped["draft"]["cards"]
    cg = service.create_cg_segment(
        run_id,
        {
            "start_card_id": cards[0]["card_id"],
            "end_card_id": cards[1]["card_id"],
            "background_key": "BG_CS_Abydos_06",
            "label": "老师与爱丽丝",
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    assert len(cg["draft"]["cg_segments"]) == 1
    assert all(card["cg"] for card in cg["draft"]["cards"])
    approved = service.approve_review(
        run_id,
        {"card_ids": None, "expected_draft_version": cg["draft"]["draft_version"]},
    )
    build_id = service.adapter.create_compile_snapshot(
        approved["run"]["draft_token"], approved["draft"]["draft_version"]
    )
    input_dir = configured.data_dir / "drafts" / approved["run"]["draft_token"] / "builds" / ".tmp" / build_id / "input"
    transformed = (input_dir / "edited.txt").read_text(encoding="utf-8")
    transformed_cast = json.loads((input_dir / "cast.json").read_text(encoding="utf-8"))["cast"]
    plan = json.loads((input_dir / "cg-plan.json").read_text(encoding="utf-8"))
    assert transformed.count("@camera -") == 1
    assert transformed.count("@bg BG_CS_Abydos_06") == 1
    assert "@popup" not in transformed
    assert "老师:" not in transformed and "爱丽丝:" not in transformed
    assert all(value["portrait"] is False and value["narrator"] is False for key, value in transformed_cast.items() if key.startswith("__halocue_cg_"))
    assert plan["mode"] == "named_slot_zero_no_portraits"
    service.jobs.close()


def test_cg_segment_rejects_portrait_stage_commands(settings, tmp_path):
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    popup_dir = aa_data / "overrides" / "popups"
    popup_dir.mkdir()
    (popup_dir / "Event03_CH0070.png").write_bytes(b"test")
    configured = configured_resource_settings(settings, tmp_path)
    configured = Settings(
        project_root=configured.project_root,
        data_dir=configured.data_dir,
        legacy_root=configured.legacy_root,
        resource_index=configured.resource_index,
        aa_data=aa_data,
        host="127.0.0.1",
        port=0,
    )
    service = ProductionService(configured)
    created = service.create_run(
        {
            "project": "CG 禁止舞台指令",
            "source": {"kind": "inline", "text": "@camera 爱丽丝\n爱丽丝: 不应该出现骨骼。\n"},
        }
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "爱丽丝",
            "mapping": {"kind": "portrait", "id": "alice-school"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    cards = mapped["draft"]["cards"]
    with pytest.raises(ProductionError) as error:
        service.create_cg_segment(
            run_id,
            {
                "start_card_id": cards[0]["card_id"],
                "end_card_id": cards[1]["card_id"],
                "background_key": "BG_CS_Abydos_06",
                "expected_draft_version": mapped["draft"]["draft_version"],
            },
        )
    assert error.value.code == "cg_segment_invalid"
    assert error.value.details["issues"][0]["code"] == "cg.stage_command_forbidden"
    service.jobs.close()


def test_file_upload_source_keeps_safe_provenance(settings):
    service = ProductionService(settings)
    created = service.create_run(
        {
            "project": "文件导入",
            "source": {
                "kind": "file_upload",
                "filename": "..\\第一章.md",
                "text": "## 场景 01\n旁白: 测试\n",
            },
        }
    )
    assert created["run"]["source_summary"]["source_kind"] == "file_upload"
    assert created["run"]["source_summary"]["source_filename"] == "第一章.md"
    release = json.loads(
        (settings.data_dir / "releases" / created["run"]["release_id"] / "release.json").read_text(
            encoding="utf-8"
        )
    )
    assert release["source_kind"] == "file_upload"
    assert ".." not in json.dumps(created, ensure_ascii=False)
    service.jobs.close()


def test_file_upload_source_rejects_unsupported_suffix(settings):
    service = ProductionService(settings)
    with pytest.raises(ProductionError) as error:
        service.create_run(
            {
                "project": "错误文件",
                "source": {"kind": "file_upload", "filename": "script.docx", "text": "旁白: 测试\n"},
            }
        )
    assert error.value.code == "source_file_type_unsupported"
    service.jobs.close()


def test_aa_environment_can_inspect_and_adopt_data_workspace(settings, tmp_path):
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    service = ProductionService(settings)
    inspected = service.inspect_aa_environment({"selection": str(aa_data)})
    assert inspected["environment"]["workspace"]["valid"] is True
    assert inspected["adopted"] is False
    adopted = service.inspect_aa_environment({"selection": str(aa_data), "adopt": True})
    assert adopted["adopted"] is True
    assert adopted["aa_workspace"]["valid"] is True
    assert adopted["capabilities"]["install"]["state"] == "available"
    service.jobs.close()


def test_job_registry_cancels_queued_and_signals_running_jobs(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    started = threading.Event()
    release = threading.Event()

    def blocking_job():
        started.set()
        release.wait(timeout=3)
        return {"ok": True}

    running = registry.submit("blocking", blocking_job)
    assert started.wait(timeout=2)
    queued = registry.submit("queued", lambda: {"ok": True})
    assert registry.cancel(queued.job_id) is True
    assert registry.get(queued.job_id).state == "cancelled"
    assert registry.cancel(running.job_id) is True
    assert registry.get(running.job_id).state == "cancelling"
    release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if registry.get(running.job_id).state == "cancelled":
            break
        time.sleep(0.01)
    assert registry.get(running.job_id).state == "cancelled"
    registry.close()


def test_job_stop_callback_interrupts_an_active_provider_handle(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    started = threading.Event()
    interrupted = threading.Event()

    def blocking_job(control):
        remove = control.add_stop_callback(interrupted.set)
        started.set()
        try:
            control.wait_for_stop(timeout=3)
        finally:
            remove()
        return {"ok": True}

    job = registry.submit("blocking", blocking_job, cooperative=True)
    assert started.wait(timeout=2)
    assert registry.pause(job.job_id) is True
    assert interrupted.wait(timeout=0.5)
    registry.close()


def test_duplicate_direction_submission_reuses_the_active_job(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_SINGLE_FLIGHT_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_SINGLE_FLIGHT_KEY",
        }
    )
    service.direction_models.provider = lambda: object()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def slow_generation(**kwargs):
        calls.append(kwargs["generation_id"])
        entered.set()
        release.wait(timeout=5)
        return {
            "generation_id": kwargs["generation_id"],
            "draft_version": kwargs["expected_draft_version"] + 1,
        }

    monkeypatch.setattr(service.adapter, "execute_direction_generation", slow_generation)
    created = service.create_run(
        {
            "project": "演出任务单飞",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 测试\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )

    try:
        _, first = service.generate_direction(
            created["run"]["run_id"],
            {"expected_draft_version": mapped["draft"]["draft_version"]},
        )
        assert entered.wait(timeout=2)
        _, duplicate = service.generate_direction(
            created["run"]["run_id"],
            {"expected_draft_version": mapped["draft"]["draft_version"]},
        )
    finally:
        release.set()

    assert duplicate["job"]["job_id"] == first["job"]["job_id"]
    assert duplicate["generation_id"] == first["generation_id"]
    assert duplicate["deduplicated"] is True
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if service.jobs.get(first["job"]["job_id"]).state == "succeeded":
            break
        time.sleep(0.01)
    assert calls == [first["generation_id"]]
    service.jobs.close()


def test_late_compile_result_cannot_publish_a_stale_build(settings, monkeypatch):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "旧编译结果隔离", "source": {"kind": "inline", "text": "旁白: 原文\n"}}
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    approved = service.approve_review(
        run_id,
        {
            "card_ids": None,
            "expected_draft_version": mapped["draft"]["draft_version"],
        },
    )
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        service.adapter,
        "create_compile_snapshot",
        lambda _token, _version: "build-000000000001",
    )

    def slow_compile(_token, build_id):
        entered.set()
        release.wait(timeout=5)
        return {"build_id": build_id, "bundle_dir": "isolated"}

    monkeypatch.setattr(service.adapter, "execute_compile", slow_compile)
    _, accepted = service.compile(
        run_id,
        {"expected_draft_version": approved["draft"]["draft_version"]},
    )
    assert entered.wait(timeout=2)
    line = next(card for card in approved["draft"]["cards"] if card["kind"] == "line")
    changed = service.update_card(
        run_id,
        line["card_id"],
        {
            "patch": {"text": "用户的新版本"},
            "expected_draft_version": approved["draft"]["draft_version"],
        },
    )
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state not in {"queued", "running"}:
            break
        time.sleep(0.01)

    detail = service.run_detail(run_id)
    assert job.state == "superseded"
    assert detail["run"]["state"] == "waiting_for_review"
    assert detail["run"]["pending_build_id"] is None
    assert detail["run"]["last_build_id"] is None
    assert detail["draft"]["draft_version"] == changed["draft"]["draft_version"]
    service.jobs.close()


def test_install_rejects_a_build_from_an_older_draft(settings, monkeypatch):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "旧构建禁止安装", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    current_version = created["draft"]["draft_version"]
    run = service._run(created["run"]["run_id"])
    run.state = "compiled"
    run.last_build_id = "build-000000000001"
    run.last_build_draft_version = current_version - 1
    service.repository.save_run(run)
    called = []
    monkeypatch.setattr(service.adapter, "install", lambda **kwargs: called.append(kwargs))

    with pytest.raises(ProductionError) as error:
        service.install(run.run_id, {"build_id": run.last_build_id})

    assert error.value.code == "build_stale"
    assert called == []
    service.jobs.close()


def test_job_registry_cooperatively_cancels_a_running_job(tmp_path):
    registry = JobRegistry(tmp_path / "jobs")
    started = threading.Event()

    def work(control):
        started.set()
        assert control.wait_for_stop(timeout=2)
        raise JobCancelled("用户结束任务")

    job = registry.submit("direction_generation", work, cooperative=True)
    assert started.wait(timeout=2)
    assert registry.cancel(job.job_id) is True
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if registry.get(job.job_id).state == "cancelled":
            break
        time.sleep(0.01)
    assert registry.get(job.job_id).state == "cancelled"
    registry.close()


def test_empty_direction_failure_is_retryable_but_not_presented_as_checkpoint_resume():
    public = ProductionService._job_public(
        JobRecord(
            job_id="job-000000000001",
            kind="direction_generation",
            state="failed",
            created_at="2026-09-04T00:00:00+00:00",
            updated_at="2026-09-04T00:00:01+00:00",
            run_id="run-000000000001",
            retry_context={"expected_draft_version": 2, "generation_id": "direction-empty"},
            error={"code": "direction_generation_empty", "message": "没有有效演出修改"},
        ).to_dict()
    )

    assert public["retryable"] is True
    assert public["resumable"] is False
    assert public["retry_label"] == "重新生成"
    assert public["next_action"]["stage"] == "generation"


def test_direction_job_can_pause_and_resume_the_same_generation(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_RESUME_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_RESUME_MODEL_KEY",
        }
    )
    service.direction_models.provider = lambda: object()
    entered = threading.Event()
    calls = []

    def resumable_generation(**kwargs):
        calls.append(
            {
                "generation_id": kwargs["generation_id"],
                "resume": kwargs["resume"],
            }
        )
        if len(calls) == 1:
            entered.set()
            while not kwargs["cancelled"]():
                time.sleep(0.005)
            return {
                "generation_id": kwargs["generation_id"],
                "cancelled": True,
                "pending_targets": 3,
                "agent": {"metrics": {"requests": 1}},
            }
        return {
            "generation_id": kwargs["generation_id"],
            "draft_version": kwargs["expected_draft_version"] + 1,
            "pending_targets": 0,
            "agent": {"metrics": {"requests": 1}},
        }

    monkeypatch.setattr(
        service.adapter, "execute_direction_generation", resumable_generation
    )
    created = service.create_run(
        {
            "project": "演出暂停恢复",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 测试\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    _, accepted = service.generate_direction(
        created["run"]["run_id"],
        {"expected_draft_version": mapped["draft"]["draft_version"]},
    )
    assert entered.wait(timeout=2)
    paused = service.pause_job(accepted["job"]["job_id"])
    assert paused["job"]["state"] in {"pausing", "paused"}

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        first_job = service.jobs.get(accepted["job"]["job_id"])
        if first_job and first_job.state == "paused":
            break
        time.sleep(0.01)
    assert first_job.state == "paused"
    assert service.run_detail(created["run"]["run_id"])["run"]["state"] == "direction_paused"

    resumed = service.retry_job(first_job.job_id)
    second_id = resumed["job"]["job_id"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        second_job = service.jobs.get(second_id)
        if second_job and second_job.state == "succeeded":
            break
        time.sleep(0.01)
    assert second_job.state == "succeeded"
    assert calls == [
        {"generation_id": accepted["generation_id"], "resume": False},
        {"generation_id": accepted["generation_id"], "resume": True},
    ]
    assert second_job.resumed_from_job_id == first_job.job_id
    service.jobs.close()


def test_direction_job_cancel_wins_over_a_recoverable_pending_checkpoint(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_CANCEL_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_CANCEL_MODEL_KEY",
        }
    )
    service.direction_models.provider = lambda: object()
    entered = threading.Event()

    def cancellable_generation(**kwargs):
        entered.set()
        while not kwargs["cancelled"]():
            time.sleep(0.005)
        return {
            "generation_id": kwargs["generation_id"],
            "cancelled": True,
            "incomplete": True,
            "pending_targets": 3,
            "agent": {"metrics": {"requests": 1}},
        }

    monkeypatch.setattr(
        service.adapter, "execute_direction_generation", cancellable_generation
    )
    created = service.create_run(
        {
            "project": "演出明确结束",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 测试\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    _, accepted = service.generate_direction(
        created["run"]["run_id"],
        {"expected_draft_version": mapped["draft"]["draft_version"]},
    )
    assert entered.wait(timeout=2)
    service.cancel_job(accepted["job"]["job_id"])

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state in {"cancelled", "paused"}:
            break
        time.sleep(0.01)

    assert job.state == "cancelled"
    assert job.progress["phase"] == "cancelled"
    assert "结束" in job.progress["detail"]
    assert service.run_detail(created["run"]["run_id"])["run"]["state"] == "direction_cancelled"
    service.jobs.close()


@pytest.mark.parametrize(
    ("control_method", "expected_job_state", "expected_run_state"),
    [
        ("cancel_job", "cancelled", "direction_cancelled"),
        ("pause_job", "paused", "direction_paused"),
    ],
)
def test_last_inflight_direction_result_cannot_write_after_stop(
    settings,
    tmp_path,
    monkeypatch,
    control_method,
    expected_job_state,
    expected_run_state,
):
    configured = configured_resource_settings(settings, tmp_path)
    monkeypatch.setenv("HALOCUE_FENCE_MODEL_KEY", "test-secret")
    service = ProductionService(configured)
    service.configure_direction_model(
        {
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key_env": "HALOCUE_FENCE_MODEL_KEY",
        }
    )

    class Provider:
        name = "blocking"
        model = "blocking-model"
        stats = {"calls": 1, "in": 10, "out": 10}

    service.direction_models.provider = Provider
    entered = threading.Event()
    release = threading.Event()

    def blocking_annotation(_options, provider_instance=None):
        assert provider_instance is not None
        entered.set()
        assert release.wait(timeout=5)
        return {
            "text": "旁白: 迟到结果\n",
            "story_type": "auto",
            "proposals": [
                {
                    "proposal_id": "prop-late-result",
                    "type": "applied_pending",
                    "origin": "model",
                    "rule": "llm_annotation",
                    "card_id": "late-card",
                    "field": "face",
                    "before": None,
                    "after": "00",
                    "state": "pending",
                }
            ],
            "direction_change_count": 1,
            "pending_targets": 0,
            "agent": {"metrics": {"requests": 1}},
            "diagnostics": [],
        }

    monkeypatch.setattr(
        service.adapter._modules["annotate"],
        "annotate_script",
        blocking_annotation,
    )
    created = service.create_run(
        {
            "project": f"最终请求{control_method}",
            "generation_mode": "ai_direction",
            "source": {"kind": "inline", "text": "旁白: 原文\n"},
        }
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    baseline_version = mapped["draft"]["draft_version"]
    _, accepted = service.generate_direction(
        created["run"]["run_id"],
        {"expected_draft_version": baseline_version},
    )
    assert entered.wait(timeout=2)

    getattr(service, control_method)(accepted["job"]["job_id"])
    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = service.jobs.get(accepted["job"]["job_id"])
        if job and job.state == expected_job_state:
            break
        time.sleep(0.01)

    detail = service.run_detail(created["run"]["run_id"])
    assert job.state == expected_job_state
    assert detail["run"]["state"] == expected_run_state
    assert detail["draft"]["draft_version"] == baseline_version
    assert detail["draft"]["cards"][0]["current"]["text"] == "原文"
    service.jobs.close()


def test_direction_commit_rolls_back_when_proposal_audit_write_fails(
    settings, tmp_path, monkeypatch,
):
    configured = configured_resource_settings(settings, tmp_path)
    service = ProductionService(configured)
    created = service.create_run(
        {"project": "提交事务回滚", "source": {"kind": "inline", "text": "旁白: 原文\n"}}
    )
    mapped = service.update_cast(
        created["run"]["run_id"],
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )

    class Provider:
        name = "fake"
        model = "fake"
        stats = {}

    monkeypatch.setattr(
        service.adapter._modules["annotate"],
        "annotate_script",
        lambda *_args, **_kwargs: {
            "text": "旁白: 迟到结果\n",
            "proposals": [{
                "proposal_id": "prop-rollback",
                "type": "applied_pending",
                "field": "face",
                "before": None,
                "after": "00",
            }],
            "direction_change_count": 1,
            "pending_targets": 0,
            "agent": {"metrics": {}},
            "diagnostics": [],
        },
    )
    staged = service.adapter.execute_direction_generation(
        token=created["run"]["draft_token"],
        generation_id="direction-rollback-test",
        provider=Provider(),
        expected_draft_version=mapped["draft"]["draft_version"],
        story_type="auto",
        layout_mode="pure_ai",
    )
    original_writer = legacy_adapter_module._write_json_atomic

    def failing_writer(path, value):
        if path.name == "proposals.json":
            raise OSError("injected proposal audit failure")
        return original_writer(path, value)

    monkeypatch.setattr(legacy_adapter_module, "_write_json_atomic", failing_writer)
    with pytest.raises(OSError, match="injected proposal audit failure"):
        service.adapter.commit_direction_generation(staged)

    detail = service.adapter.draft_detail(created["run"]["draft_token"])
    assert detail["draft_version"] == mapped["draft"]["draft_version"]
    assert detail["cards"][0]["current"]["text"] == "原文"
    assert service.adapter.store.load_cast(created["run"]["draft_token"]).get(
        "layout_mode"
    ) != "pure_ai"
    service.jobs.close()


def test_warning_diagnostics_block_every_review_gate(settings, monkeypatch):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "校验门一致", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    original = service.adapter.draft_detail(created["run"]["draft_token"])
    warning_detail = {
        **original,
        "review_ready": False,
        "counts": {
            **original["counts"],
            "pending": 0,
            "blocking_errors": 0,
            "unresolved_issues": 1,
        },
    }
    monkeypatch.setattr(service.adapter, "draft_detail", lambda _token: warning_detail)

    validation = service.validate(created["run"]["run_id"])
    gates = service.run_detail(created["run"]["run_id"])["gates"]

    assert validation["review_ready"] is False
    assert validation["blockers"] == [{"code": "unresolved_issues", "count": 1}]
    assert gates["preflight"] == {
        "passed": False,
        "blockers": ["unresolved_issues"],
    }
    assert "unresolved_issues" in gates["compile"]["blockers"]
    service.jobs.close()


@pytest.mark.parametrize(
    ("operation", "adapter_operation"),
    [("install_options", "install_options"), ("check_install", "check_install_target")],
)
def test_install_preflight_rejects_a_build_from_an_older_draft(
    settings, monkeypatch, operation, adapter_operation,
):
    service = ProductionService(settings)
    created = service.create_run(
        {"project": "旧构建禁止预检", "source": {"kind": "inline", "text": "旁白: 测试\n"}}
    )
    run = service._run(created["run"]["run_id"])
    run.state = "compiled"
    run.last_build_id = "build-000000000001"
    run.last_build_draft_version = created["draft"]["draft_version"] - 1
    service.repository.save_run(run)
    called = []
    monkeypatch.setattr(
        service.adapter,
        adapter_operation,
        lambda **kwargs: called.append(kwargs) or {"ok": True},
    )

    with pytest.raises(ProductionError) as error:
        if operation == "install_options":
            service.install_options(run.run_id, run.last_build_id)
        else:
            service.check_install(
                run.run_id,
                {
                    "build_id": run.last_build_id,
                    "category": "测试",
                    "story_name": "测试",
                },
            )

    assert error.value.code == "build_stale"
    assert called == []
    service.jobs.close()
