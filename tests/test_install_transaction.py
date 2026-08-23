# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
import install_manager as install_manager_module
from build_bundle import BuildBundleManager, calc_file_sha256
from draft_store import AnnotationIncompleteError, DraftStore
from install_manager import (
    InstallManager,
    AACorruptBundleError,
    AAInstallTargetExistsError,
    AAQualityGateError,
    AARunningError,
    _merge_install_manifests,
    _bundle_custom_backgrounds,
    _repair_install_assets,
    compose_install_project_name,
)


def _rehash_bundle_file(bundle_dir, path):
    files_path = bundle_dir / "files.json"
    files = json.loads(files_path.read_text(encoding="utf-8"))
    relative = path.relative_to(bundle_dir).as_posix()
    entry = next(item for item in files if item["path"] == relative)
    entry["size"] = path.stat().st_size
    entry["sha256"] = calc_file_sha256(path)
    files_path.write_text(json.dumps(files, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def temp_environment(tmp_path):
    store_dir = tmp_path / "drafts"
    aa_data_dir = tmp_path / "aa_data"
    aa_data_dir.mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "projects").mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "saves").mkdir(parents=True, exist_ok=True)

    store = DraftStore(base_dir=str(store_dir))
    bundle_mgr = BuildBundleManager(store=store)
    install_mgr = InstallManager(
        store=store,
        aa_data_dir=str(aa_data_dir),
        record_path=str(tmp_path / "project_install_record.json"),
        running_probe=lambda: False,
    )

    return {
        "store": store,
        "bundle_mgr": bundle_mgr,
        "install_mgr": install_mgr,
        "aa_data_dir": aa_data_dir,
    }


def test_corrupted_bundle_refuses_install(temp_environment):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]

    token = "install-token-1"
    sample_text = "## 场景1\n旁白: 第一句\n"

    store.create_draft(token=token, text=sample_text, project="Install测试")
    build_id = bundle_mgr.create_compile_snapshot(token=token, expected_draft_version=1)
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    bundle_dir = Path(bundle_info["bundle_dir"])

    # 篡改 bundle 文件内容导致 files.json sha256 校验失败
    build_json = bundle_dir / "build.json"
    build_json.write_text("tampered content", encoding="utf-8")

    with pytest.raises(AACorruptBundleError):
        install_mgr.install_build(token=token, build_id=build_id)


def test_install_rechecks_annotation_completion(temp_environment, monkeypatch):
    env = temp_environment
    store = env["store"]
    token = "partial-install"
    store.create_draft(
        token=token,
        text="旁白: 部分结果\n",
        annotation_status={
            "status": "partial", "completed_targets": 1,
            "total_targets": 2, "pending_targets": 1,
        },
    )
    monkeypatch.setattr(
        env["install_mgr"], "find_bundle_dir",
        lambda *_args: (_ for _ in ()).throw(AssertionError("不应读取构建包")),
    )

    with pytest.raises(AnnotationIncompleteError):
        env["install_mgr"].install_build(token=token, build_id="stale-build")


def test_partial_annotation_install_requires_explicit_review_override(
    temp_environment,
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    token = "partial-install-approved"
    created = store.create_draft(
        token=token,
        text="旁白: 已保留的部分结果\n",
        project="部分结果安装",
        cast={"cast": {"旁白": {"narrator": True}}},
        annotation_status={
            "status": "partial", "completed_targets": 0,
            "total_targets": 8, "pending_targets": 8,
        },
    )
    with pytest.raises(AnnotationIncompleteError):
        install_mgr.install_build(token=token, build_id="stale-build")

    reviewed = store.batch_approve_reviews(
        token=token,
        card_ids=None,
        expected_draft_version=created["session"]["draft_version"],
    )
    assert reviewed["session"]["annotation_override_accepted"] is True
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=reviewed["session"]["draft_version"],
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)

    with pytest.raises(AnnotationIncompleteError):
        install_mgr.install_build(token=token, build_id=build_id)
    result = install_mgr.install_build(
        token=token,
        build_id=build_id,
        allow_incomplete_annotation=True,
    )
    assert result["ok"] is True
    assert result["install_audit"]["annotation_incomplete_override"] is True
    assert result["install_audit"]["annotation_status"]["pending_targets"] == 8


def test_partial_annotation_override_flag_without_review_is_not_enough(
    temp_environment,
):
    env = temp_environment
    token = "partial-install-unreviewed"
    env["store"].create_draft(
        token=token,
        text="旁白: 未审查结果\n",
        project="未审查部分结果",
        annotation_status={
            "status": "partial", "completed_targets": 0,
            "total_targets": 8, "pending_targets": 8,
        },
    )
    with pytest.raises(AnnotationIncompleteError):
        env["install_mgr"].install_build(
            token=token,
            build_id="stale-build",
            allow_incomplete_annotation=True,
        )


def test_aa_running_refuses_install(temp_environment):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]

    token = "install-token-2"
    sample_text = "## 场景1\n旁白: 第一句\n"

    store.create_draft(token=token, text=sample_text, project="Install测试2")
    build_id = bundle_mgr.create_compile_snapshot(token=token, expected_draft_version=1)
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)

    install_mgr.running_probe = lambda: True

    with pytest.raises(AARunningError):
        install_mgr.install_build(token=token, build_id=build_id)


def test_unresolved_high_quality_issue_refuses_install_before_touching_aa(
    temp_environment,
):
    env = temp_environment
    token = "quality-gate-install"
    project = "演出质量未通过"
    env["store"].create_draft(
        token=token, text="旁白: 检查\n", project=project,
    )
    build_id = env["bundle_mgr"].create_compile_snapshot(token, 1)
    result = env["bundle_mgr"].execute_build_worker(token, build_id)
    bundle_dir = Path(result["bundle_dir"])
    validation_file = bundle_dir / "validation.json"
    validation_file.write_text(json.dumps({
        "valid": False,
        "diagnostics": [],
        "quality": {"issues": [{
            "code": "compiled_exit_still_visible", "severity": "critical",
        }]},
        "blocking_issues": [],
    }, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, validation_file)

    with pytest.raises(AAQualityGateError) as caught:
        env["install_mgr"].install_build(token=token, build_id=build_id)

    assert caught.value.code == "staging_quality_failed"
    assert caught.value.issues[0]["code"] == "compiled_exit_still_visible"
    assert not (env["aa_data_dir"] / "projects" / f"{project}.aap").exists()


def test_deterministic_duplicate_camera_issue_does_not_block_install(temp_environment):
    env = temp_environment
    token = "quality-dedup-install"
    project = "重复镜头可安装"
    env["store"].create_draft(token=token, text="旁白: 检查\n", project=project)
    build_id = env["bundle_mgr"].create_compile_snapshot(token, 1)
    result = env["bundle_mgr"].execute_build_worker(token, build_id)
    bundle_dir = Path(result["bundle_dir"])
    validation_file = bundle_dir / "validation.json"
    validation_file.write_text(json.dumps({
        "valid": True,
        "diagnostics": [],
        "quality": {"issues": [{
            "code": "compiled_redundant_camera_declaration",
            "severity": "high",
        }]},
        "blocking_issues": [],
    }, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, validation_file)

    decision = InstallManager.assert_quality_ready(bundle_dir)

    assert decision["resolved_issues"]
    assert decision["resolved_issues"][0]["resolution"] == "deterministic"


def test_quality_warning_can_be_overridden_without_allowing_hard_error(temp_environment):
    env = temp_environment
    token = "quality-warning-override"
    project = "质量提示保留"
    env["store"].create_draft(token=token, text="旁白: 检查\n", project=project)
    build_id = env["bundle_mgr"].create_compile_snapshot(token, 1)
    result = env["bundle_mgr"].execute_build_worker(token, build_id)
    bundle_dir = Path(result["bundle_dir"])
    validation_file = bundle_dir / "validation.json"
    validation_file.write_text(json.dumps({
        "valid": True,
        "diagnostics": [],
        "quality": {"issues": [{
            "code": "unclassified_quality_warning",
            "severity": "high",
        }]},
        "blocking_issues": [],
    }, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, validation_file)

    with pytest.raises(AAQualityGateError):
        InstallManager.assert_quality_ready(bundle_dir)
    decision = InstallManager.assert_quality_ready(
        bundle_dir, allow_quality_warnings=True
    )

    assert decision["warnings_overridden"] is True


def test_mixed_quality_report_does_not_offer_a_bypass_for_hard_errors(
    temp_environment,
):
    env = temp_environment
    token = "quality-mixed-override"
    env["store"].create_draft(token=token, text="旁白: 检查\n", project="混合质量问题")
    build_id = env["bundle_mgr"].create_compile_snapshot(token, 1)
    result = env["bundle_mgr"].execute_build_worker(token, build_id)
    bundle_dir = Path(result["bundle_dir"])
    validation_file = bundle_dir / "validation.json"
    validation_file.write_text(json.dumps({
        "valid": False,
        "diagnostics": [],
        "quality": {"issues": [
            {"code": "unclassified_quality_warning", "severity": "high"},
            {"code": "compiled_exit_still_visible", "severity": "critical"},
        ]},
        "blocking_issues": [],
    }, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, validation_file)

    with pytest.raises(AAQualityGateError) as caught:
        InstallManager.assert_quality_ready(bundle_dir)
    assert caught.value.override_allowed is False


@pytest.mark.parametrize(
    ("category", "story_name", "expected"),
    [
        ("", "第一幕-第一章", "第一幕-第一章"),
        ("大故事", "第一幕-第一章", "大故事-第一幕-第一章"),
    ],
)
def test_install_project_name_uses_an_optional_single_category(
    category, story_name, expected
):
    assert compose_install_project_name(category, story_name) == expected


def test_install_project_name_rejects_nested_category_names():
    with pytest.raises(ValueError, match="一级分类"):
        compose_install_project_name("大故事-第一幕", "第一章")


def test_renamed_install_rewrites_aap_and_copies_story_assets(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "renamed-install"

    store.create_draft(
        token=token,
        text="## 场景1\n旁白: 第一句\n",
        project="第一幕-第一章",
    )
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    source_project = aa_data / "projects" / "第一幕-第一章"
    source_save = aa_data / "saves" / "第一幕-第一章"
    source_project.mkdir(parents=True)
    source_save.mkdir(parents=True)
    (source_project / "custom-project.asset").write_text("project", encoding="utf-8")
    (source_save / "custom-save.asset").write_text("save", encoding="utf-8")
    result = install_mgr.install_build(
        token=token,
        build_id=build_id,
        category="大故事",
        story_name="第一幕-第一章",
    )

    target = "大故事-第一幕-第一章"
    aap_path = aa_data / "projects" / f"{target}.aap"
    assert json.loads(aap_path.read_text(encoding="utf-8"))["ProjectName"] == target
    assert (aa_data / "projects" / target / "custom-project.asset").is_file()
    assert (aa_data / "saves" / target / "custom-save.asset").is_file()
    for root in (aa_data / "projects", aa_data / "saves"):
        delta = json.loads(
            (root / target / "manifest_delta.json").read_text(encoding="utf-8")
        )
        assert delta["add"][0]["name"] == target
    assert result == {
        "ok": True,
        "project": target,
        "source_project": "第一幕-第一章",
        "installed_build_id": build_id,
        "aap_path": str(aap_path),
        "project_dir": str(aa_data / "projects" / target),
        "save_dir": str(aa_data / "saves" / target),
    }


def test_same_name_install_preserves_registered_story_assets(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "preserve-story-assets"
    project_name = "已有素材项目"

    store.create_draft(token=token, text="旁白: 测试\n", project=project_name)
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)

    character = {
        "Identifier": "custom-kei",
        "Name": "凯伊（约会服）",
        "Nickname": "",
        "CharacterReference": None,
        "OriginalIdentifier": None,
        "SpinePortraitPath": r"characters\custom-kei\date",
        "SmallPortraitPath": r"characters\custom-kei\date-avatar.png",
    }
    manifest = {
        "CharacterOverrides": [character],
        "VoiceOverrides": [r"voices\missing.ogg"],
        "PopupOverrides": [],
        "SoundOverrides": [],
        "BgOverrides": [r"bgs\river.png", r"bgs\missing.png"],
        "BgmOverrides": [],
    }
    for scope in ("projects", "saves"):
        target = aa_data / scope / project_name
        (target / "bgs").mkdir(parents=True)
        (target / "bgs" / "river.png").write_bytes(b"background")
        character_dir = target / "characters" / "custom-kei"
        character_dir.mkdir(parents=True)
        for suffix in (".skel", ".atlas", ".png"):
            (character_dir / f"date{suffix}").write_bytes(suffix.encode("ascii"))
        (character_dir / "date-avatar.png").write_bytes(b"avatar")
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

    install_mgr.install_build(token=token, build_id=build_id)

    for scope in ("projects", "saves"):
        target = aa_data / scope / project_name
        installed = json.loads(
            (target / "manifest.json").read_text(encoding="utf-8")
        )
        assert installed["BgOverrides"] == [r"bgs\river.png"]
        assert installed["VoiceOverrides"] == []
        assert installed["CharacterOverrides"] == [character]
        assert (target / "bgs" / "river.png").read_bytes() == b"background"
        assert (target / "characters" / "custom-kei" / "date.skel").is_file()


def test_install_manifest_uses_bundle_display_name_with_registered_spine_paths():
    registered = {
        "CharacterOverrides": [{
            "Identifier": "626652156",
            "Name": "凯伊（约会服）",
            "Nickname": "约会短篇",
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": r"characters\626652156\Kei_Date_Outfit",
            "SmallPortraitPath": r"characters\626652156\Kei_Date_Outfit-avatar.png",
        }],
    }
    bundle = {
        "CharacterOverrides": [{
            "Identifier": "626652156",
            "Name": "凯伊",
            "Nickname": "",
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": None,
            "SmallPortraitPath": None,
        }],
    }

    merged = _merge_install_manifests(registered, bundle)

    character = merged["CharacterOverrides"][0]
    assert character["Name"] == "凯伊"
    assert character["Nickname"] == "约会短篇"
    assert character["SpinePortraitPath"] == r"characters\626652156\Kei_Date_Outfit"
    assert character["SmallPortraitPath"] == (
        r"characters\626652156\Kei_Date_Outfit-avatar.png"
    )


def test_bundle_spine_index_does_not_hide_missing_manifest_registration(tmp_path):
    projects_dir = tmp_path / "projects"
    source = projects_dir / "registered-source"
    project_dir = tmp_path / "target-project"
    save_dir = tmp_path / "target-save"
    bundle_project_dir = tmp_path / "bundle-project"
    for directory in (source, project_dir, save_dir, bundle_project_dir):
        directory.mkdir(parents=True)

    identifier = "custom-character"
    stem = "Date_Outfit"
    source_character = source / "characters" / identifier
    source_character.mkdir(parents=True)
    for suffix in (".skel", ".atlas", ".png"):
        (source_character / f"{stem}{suffix}").write_bytes(suffix.encode("ascii"))
    (source_character / f"{stem}-avatar.png").write_bytes(b"avatar")
    row = {
        "Identifier": identifier,
        "Name": "测试角色",
        "Nickname": "",
        "CharacterReference": None,
        "OriginalIdentifier": None,
        "SpinePortraitPath": rf"characters\{identifier}\{stem}",
        "SmallPortraitPath": rf"characters\{identifier}\{stem}-avatar.png",
    }
    manifest = {
        "CharacterOverrides": [row],
        "VoiceOverrides": [], "PopupOverrides": [], "SoundOverrides": [],
        "BgOverrides": [], "BgmOverrides": [],
    }
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    placeholder = {
        "Identifier": identifier,
        "Name": "测试角色",
        "Nickname": "",
        "CharacterReference": None,
        "OriginalIdentifier": None,
        "SpinePortraitPath": None,
        "SmallPortraitPath": None,
    }
    empty_manifest = {
        "CharacterOverrides": [placeholder],
        "VoiceOverrides": [], "PopupOverrides": [], "SoundOverrides": [],
        "BgOverrides": [], "BgmOverrides": [],
    }
    for directory in (project_dir, save_dir):
        (directory / "manifest.json").write_text(json.dumps(empty_manifest), encoding="utf-8")

    (bundle_project_dir / "aa_resources.json").write_text(
        json.dumps({"characters": [{"identifier": identifier, "spine":
            rf"characters\{identifier}\{stem}"}]}), encoding="utf-8"
    )
    (tmp_path / "story.aap").write_text(json.dumps({
        "nodes": {"$values": [{"Scripts": {"$values": [{
            "characters": {"$values": [{"name": identifier}]}
        }]}}]}
    }), encoding="utf-8")

    repaired = _repair_install_assets(
        projects_dir=projects_dir,
        project_dir=project_dir,
        save_dir=save_dir,
        bundle_project_dir=bundle_project_dir,
        aap_path=tmp_path / "story.aap",
        manifest=empty_manifest,
    )

    assert repaired["CharacterOverrides"] == [row]
    assert (project_dir / "characters" / identifier / f"{stem}.skel").is_file()
    assert (save_dir / "characters" / identifier / f"{stem}.atlas").is_file()


def test_install_repairs_empty_character_paths_from_matching_physical_variant(tmp_path):
    projects_dir = tmp_path / "projects"
    project_dir = projects_dir / "story"
    save_dir = tmp_path / "saves" / "story"
    bundle_project_dir = tmp_path / "bundle-project"
    for directory in (project_dir, save_dir, bundle_project_dir):
        directory.mkdir(parents=True)

    identifier = "custom-character"
    stem = "Date_Outfit"
    for root in (project_dir, save_dir):
        character_dir = root / "characters" / identifier
        character_dir.mkdir(parents=True)
        for suffix in (".skel", ".atlas", ".png"):
            (character_dir / f"{stem}{suffix}").write_bytes(suffix.encode("ascii"))
        (character_dir / f"{stem}-avatar.png").write_bytes(b"avatar")

    placeholder = {
        "Identifier": identifier,
        "Name": "测试角色",
        "Nickname": "",
        "CharacterReference": None,
        "OriginalIdentifier": None,
        "SpinePortraitPath": None,
        "SmallPortraitPath": None,
    }
    manifest = {
        "CharacterOverrides": [placeholder],
        "VoiceOverrides": [], "PopupOverrides": [], "SoundOverrides": [],
        "BgOverrides": [], "BgmOverrides": [],
    }
    (bundle_project_dir / "aa_resources.json").write_text(
        json.dumps({
            "characters": [{
                "identifier": identifier,
                "name": "测试角色",
                "spine": "",
                "face_capabilities": [{
                    "spine": rf"characters\{identifier}\{stem}",
                    "spine_signature": "variant-signature",
                    "outfit_key": stem,
                    "faces": [],
                }],
            }],
        }),
        encoding="utf-8",
    )
    (tmp_path / "story.aap").write_text(json.dumps({
        "nodes": {"$values": [{"Scripts": {"$values": [{
            "characters": {"$values": [{"name": identifier}]}
        }]}}]}
    }), encoding="utf-8")

    repaired = _repair_install_assets(
        projects_dir=projects_dir,
        project_dir=project_dir,
        save_dir=save_dir,
        bundle_project_dir=bundle_project_dir,
        aap_path=tmp_path / "story.aap",
        manifest=manifest,
    )

    assert repaired["CharacterOverrides"] == [{
        **placeholder,
        "SpinePortraitPath": rf"characters\{identifier}\{stem}",
        "SmallPortraitPath": rf"characters\{identifier}\{stem}-avatar.png",
    }]


def test_install_repairs_referenced_orphan_background_and_external_character(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "repair-referenced-assets"
    project_name = "待修复项目"

    store.create_draft(token=token, text="旁白: 测试\n", project=project_name)
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    bundle_dir = Path(bundle_info["bundle_dir"])
    aap_path = bundle_dir / f"{project_name}.aap"
    aap = json.loads(aap_path.read_text(encoding="utf-8"))
    script = next(
        script
        for node in aap["nodes"]["$values"]
        for script in node.get("Scripts", {}).get("$values", [])
    )
    script["bgName"] = 123456789
    script["bgFriendlyName"] = "river"
    script["characters"]["$values"][0]["name"] = "external-kei"
    script["characters"]["$values"][0]["faceId"] = "00"
    aap_path.write_text(json.dumps(aap, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, aap_path)

    for scope in ("projects", "saves"):
        target = aa_data / scope / project_name
        (target / "bgs").mkdir(parents=True)
        (target / "bgs" / "orphan.png").write_bytes(b"orphan-background")

    source_name = "素材来源"
    character = {
        "Identifier": "external-kei",
        "Name": "凯伊",
        "Nickname": "",
        "CharacterReference": None,
        "OriginalIdentifier": None,
        "SpinePortraitPath": r"characters\external-kei\date",
        "SmallPortraitPath": r"characters\external-kei\date-avatar.png",
    }
    source_manifest = {
        "CharacterOverrides": [character],
        "VoiceOverrides": [],
        "PopupOverrides": [],
        "SoundOverrides": [],
        "BgOverrides": [r"bgs\river.png"],
        "BgmOverrides": [],
    }
    for scope in ("projects", "saves"):
        source = aa_data / scope / source_name
        (source / "bgs").mkdir(parents=True)
        (source / "bgs" / "river.png").write_bytes(b"river-background")
        character_dir = source / "characters" / "external-kei"
        character_dir.mkdir(parents=True)
        for suffix in (".skel", ".atlas", ".png"):
            (character_dir / f"date{suffix}").write_bytes(suffix.encode("ascii"))
        (character_dir / "date-avatar.png").write_bytes(b"avatar")
        (source / "manifest.json").write_text(
            json.dumps(source_manifest, ensure_ascii=False), encoding="utf-8"
        )

    install_mgr.install_build(token=token, build_id=build_id)

    for scope in ("projects", "saves"):
        target = aa_data / scope / project_name
        installed = json.loads(
            (target / "manifest.json").read_text(encoding="utf-8")
        )
        assert set(installed["BgOverrides"]) == {
            r"bgs\orphan.png",
            r"bgs\river.png",
        }
        assert character in installed["CharacterOverrides"]
        assert (target / "bgs" / "river.png").read_bytes() == b"river-background"
        assert (target / "characters" / "external-kei" / "date.skel").is_file()


def test_unresolved_character_rolls_back_the_existing_install(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "unresolved-character"
    project_name = "不能损坏"

    store.create_draft(token=token, text="旁白: 测试\n", project=project_name)
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    bundle_dir = Path(bundle_info["bundle_dir"])
    bundle_aap = bundle_dir / f"{project_name}.aap"
    aap = json.loads(bundle_aap.read_text(encoding="utf-8"))
    script = next(
        script
        for node in aap["nodes"]["$values"]
        for script in node.get("Scripts", {}).get("$values", [])
    )
    script["characters"]["$values"][0]["name"] = "missing-character"
    bundle_aap.write_text(json.dumps(aap, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, bundle_aap)

    project_dir = aa_data / "projects" / project_name
    save_dir = aa_data / "saves" / project_name
    project_dir.mkdir(parents=True)
    save_dir.mkdir(parents=True)
    manifest = {
        "CharacterOverrides": [],
        "VoiceOverrides": [],
        "PopupOverrides": [],
        "SoundOverrides": [],
        "BgOverrides": [r"bgs\keep.png"],
        "BgmOverrides": [],
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
    for target in (project_dir, save_dir):
        (target / "manifest.json").write_bytes(manifest_bytes)
    installed_aap = aa_data / "projects" / f"{project_name}.aap"
    installed_aap.write_bytes(b"existing-aap")
    with pytest.raises(AACorruptBundleError, match="missing-character"):
        install_mgr.install_build(token=token, build_id=build_id)

    assert installed_aap.read_bytes() == b"existing-aap"
    assert (project_dir / "manifest.json").read_bytes() == manifest_bytes
    assert (save_dir / "manifest.json").read_bytes() == manifest_bytes


def test_missing_custom_background_rolls_back_the_existing_install(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "missing-custom-background"
    project_name = "背景不能损坏"
    background_name = "missing-custom-bg"

    store.create_draft(token=token, text="旁白: 测试\n", project=project_name)
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    bundle_dir = Path(bundle_info["bundle_dir"])
    bundle_aap = bundle_dir / f"{project_name}.aap"
    aap = json.loads(bundle_aap.read_text(encoding="utf-8"))
    script = next(
        script
        for node in aap["nodes"]["$values"]
        for script in node.get("Scripts", {}).get("$values", [])
    )
    script["bgName"] = 987654321
    script["bgFriendlyName"] = background_name
    bundle_aap.write_text(json.dumps(aap, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, bundle_aap)

    index_path = bundle_dir / "project" / "aa_resources.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.setdefault("bg", {})[background_name] = 987654321
    index.setdefault("bg_label", {})[background_name] = {"label": "缺失背景"}
    index.setdefault("custom_asset_keys", {})["backgrounds"] = [background_name]
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    _rehash_bundle_file(bundle_dir, index_path)

    project_dir = aa_data / "projects" / project_name
    save_dir = aa_data / "saves" / project_name
    project_dir.mkdir(parents=True)
    save_dir.mkdir(parents=True)
    manifest_bytes = json.dumps({
        "CharacterOverrides": [],
        "VoiceOverrides": [],
        "PopupOverrides": [],
        "SoundOverrides": [],
        "BgOverrides": [],
        "BgmOverrides": [],
    }).encode("utf-8")
    for target in (project_dir, save_dir):
        (target / "manifest.json").write_bytes(manifest_bytes)
    installed_aap = aa_data / "projects" / f"{project_name}.aap"
    installed_aap.write_bytes(b"existing-aap")

    with pytest.raises(AACorruptBundleError, match=background_name):
        install_mgr.install_build(token=token, build_id=build_id)

    assert installed_aap.read_bytes() == b"existing-aap"
    assert (project_dir / "manifest.json").read_bytes() == manifest_bytes
    assert (save_dir / "manifest.json").read_bytes() == manifest_bytes


def test_labeled_official_background_is_not_classified_as_custom(tmp_path):
    bundle_project = tmp_path / "bundle-project"
    bundle_project.mkdir()
    (bundle_project / "aa_resources.json").write_text(
        json.dumps({
            "bg": {"BG_Black": 1047754314},
            "bg_label": {"BG_Black": {"label": "黑屏"}},
            "custom_asset_keys": {"backgrounds": []},
        }),
        encoding="utf-8",
    )

    assert _bundle_custom_backgrounds(bundle_project) == set()


def test_legacy_bundle_compares_labels_with_official_catalog(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    bundle_project = tmp_path / "bundle-project"
    runtime_root.mkdir()
    bundle_project.mkdir()
    (runtime_root / "aa_resources.json").write_text(
        json.dumps({"bg": {"BG_Black": 1047754314}}), encoding="utf-8"
    )
    (bundle_project / "aa_resources.json").write_text(
        json.dumps({
            "bg": {"BG_Black": 1047754314, "chapter-night": 987654321},
            "bg_label": {
                "BG_Black": {"label": "黑屏"},
                "chapter-night": {"label": "章节夜景"},
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(install_manager_module, "HERE", runtime_root)

    assert _bundle_custom_backgrounds(bundle_project) == {"chapter-night"}


def test_orphan_character_uses_the_registration_matching_its_existing_files(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "matching-orphan-character"
    project_name = "孤立角色项目"
    identifier = "variant-kei"

    store.create_draft(token=token, text="旁白: 测试\n", project=project_name)
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)

    def write_character(root, contents, display_name):
        character_dir = root / "characters" / identifier
        character_dir.mkdir(parents=True)
        for suffix in (".skel", ".atlas", ".png"):
            (character_dir / f"date{suffix}").write_bytes(contents + suffix.encode())
        (character_dir / "date-avatar.png").write_bytes(contents + b"avatar")
        row = {
            "Identifier": identifier,
            "Name": display_name,
            "Nickname": "",
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": rf"characters\{identifier}\date",
            "SmallPortraitPath": rf"characters\{identifier}\date-avatar.png",
        }
        manifest = {
            "CharacterOverrides": [row],
            "VoiceOverrides": [],
            "PopupOverrides": [],
            "SoundOverrides": [],
            "BgOverrides": [],
            "BgmOverrides": [],
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        return row

    write_character(aa_data / "projects" / "错误来源", b"wrong", "错误来源")
    expected = write_character(
        aa_data / "projects" / "匹配来源", b"matching", "匹配来源"
    )
    for scope in ("projects", "saves"):
        target = aa_data / scope / project_name / "characters" / identifier
        target.mkdir(parents=True)
        for suffix in (".skel", ".atlas", ".png"):
            (target / f"date{suffix}").write_bytes(b"matching" + suffix.encode())
        (target / "date-avatar.png").write_bytes(b"matchingavatar")

    install_mgr.install_build(token=token, build_id=build_id)

    for scope in ("projects", "saves"):
        manifest = json.loads(
            (aa_data / scope / project_name / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert expected in manifest["CharacterOverrides"]


def test_renamed_install_refuses_an_existing_target(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]
    aa_data = env["aa_data_dir"]
    token = "install-conflict"
    store.create_draft(token=token, text="旁白: 测试\n", project="第一章")
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    existing = aa_data / "projects" / "大故事-第一章"
    existing.mkdir(parents=True)
    marker = existing / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(AAInstallTargetExistsError):
        install_mgr.install_build(
            token=token,
            build_id=build_id,
            category="大故事",
            story_name="第一章",
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_install_options_do_not_guess_categories_from_hyphenated_project_names(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    aa_data = env["aa_data_dir"]
    token = "install-options"
    store.create_draft(
        token=token, text="旁白: 测试\n", project="第一幕-第一章"
    )
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    for name in ("大故事-序章.aap", "另一个-第一章.aap", "单独项目.aap"):
        (aa_data / "projects" / name).write_text("{}", encoding="utf-8")
    source_aap = aa_data / "projects" / "第一幕-第一章.aap"
    source_aap.write_text("{}", encoding="utf-8")
    (aa_data / "projects" / "第一幕-第一章").mkdir()
    (aa_data / "saves" / "第一幕-第一章").mkdir()

    result = env["install_mgr"].install_options(token=token, build_id=build_id)

    assert result == {
        "ok": True,
        "source_project": "第一幕-第一章",
        "default_category": "",
        "default_story_name": "第一幕-第一章",
        "categories": [],
        "existing_install": {
            "project": "第一幕-第一章",
            "aap_path": str(source_aap),
            "project_dir": str(aa_data / "projects" / "第一幕-第一章"),
            "save_dir": str(aa_data / "saves" / "第一幕-第一章"),
        },
    }


def test_install_options_offer_only_categories_recorded_by_this_tool(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    token = "recorded-install-options"
    store.create_draft(token=token, text="旁白: 测试\n", project="第一幕-第一章")
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    env["install_mgr"].record_path.write_text(
        json.dumps(
            {
                "大故事-序章": {"project": "大故事-序章", "category": "大故事"},
                "第一幕-第一章": {"project": "第一幕-第一章", "category": ""},
                "旧记录": {"project": "旧记录"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = env["install_mgr"].install_options(token=token, build_id=build_id)

    assert result["categories"] == ["大故事"]


def test_install_options_restore_the_last_renamed_install_location(
    temp_environment
):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    aa_data = env["aa_data_dir"]
    token = "renamed-install-options"
    store.create_draft(token=token, text="旁白: 测试\n", project="第一章")
    build_id = bundle_mgr.create_compile_snapshot(
        token=token, expected_draft_version=1
    )
    bundle_mgr.execute_build_worker(token=token, build_id=build_id)
    session_file = store.get_draft_path(token) / "session.json"
    session = json.loads(session_file.read_text(encoding="utf-8"))
    session.update({
        "last_installed_build_id": build_id,
        "last_installed_project": "大故事-第一章",
    })
    session_file.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    target_aap = aa_data / "projects" / "大故事-第一章.aap"
    target_aap.write_text("{}", encoding="utf-8")

    result = env["install_mgr"].install_options(token=token, build_id=build_id)

    assert result["existing_install"]["project"] == "大故事-第一章"
    assert result["existing_install"]["aap_path"] == str(target_aap)
