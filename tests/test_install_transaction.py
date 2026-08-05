# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from build_bundle import BuildBundleManager
from draft_store import DraftStore
from install_manager import (
    InstallManager,
    AACorruptBundleError,
    AAInstallTargetExistsError,
    AARunningError,
    compose_install_project_name,
)


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
    )

    return {
        "store": store,
        "bundle_mgr": bundle_mgr,
        "install_mgr": install_mgr,
        "aa_data_dir": aa_data_dir,
    }


def test_corrupted_bundle_refuses_install(temp_environment, monkeypatch):
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

    # 允许跳过真实 AA 运行检查
    monkeypatch.setattr("install_manager.assert_aa_closed", lambda: None)

    with pytest.raises(AACorruptBundleError):
        install_mgr.install_build(token=token, build_id=build_id)


def test_aa_running_refuses_install(temp_environment, monkeypatch):
    env = temp_environment
    store = env["store"]
    bundle_mgr = env["bundle_mgr"]
    install_mgr = env["install_mgr"]

    token = "install-token-2"
    sample_text = "## 场景1\n旁白: 第一句\n"

    store.create_draft(token=token, text=sample_text, project="Install测试2")
    build_id = bundle_mgr.create_compile_snapshot(token=token, expected_draft_version=1)
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)

    # 模拟 AA 运行抛出异常
    def mock_assert_aa_closed():
        raise AARunningError("AA is running")

    monkeypatch.setattr("install_manager.assert_aa_closed", mock_assert_aa_closed)

    with pytest.raises(AARunningError):
        install_mgr.install_build(token=token, build_id=build_id)


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
    temp_environment, monkeypatch
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
    monkeypatch.setattr("install_manager.assert_aa_closed", lambda: None)

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


def test_renamed_install_refuses_an_existing_target(
    temp_environment, monkeypatch
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
    monkeypatch.setattr("install_manager.assert_aa_closed", lambda: None)

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
