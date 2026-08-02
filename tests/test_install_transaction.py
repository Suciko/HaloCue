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
from install_manager import InstallManager, AACorruptBundleError, AARunningError


@pytest.fixture
def temp_environment(tmp_path):
    store_dir = tmp_path / "drafts"
    aa_data_dir = tmp_path / "aa_data"
    aa_data_dir.mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "projects").mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "saves").mkdir(parents=True, exist_ok=True)

    store = DraftStore(base_dir=str(store_dir))
    bundle_mgr = BuildBundleManager(store=store)
    install_mgr = InstallManager(store=store, aa_data_dir=str(aa_data_dir))

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
