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
from install_manager import InstallManager


def test_project_install_record_created_after_install(
    tmp_path, monkeypatch, seed_draft_resources
):
    store_dir = tmp_path / "drafts"
    aa_data_dir = tmp_path / "aa_data"
    aa_data_dir.mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "projects").mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "saves").mkdir(parents=True, exist_ok=True)
    (aa_data_dir / "overrides").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AA_DATA", str(aa_data_dir))

    record_file = tmp_path / "project_install_record.json"

    store = DraftStore(base_dir=str(store_dir))
    bundle_mgr = BuildBundleManager(store=store)
    install_mgr = InstallManager(store=store, aa_data_dir=str(aa_data_dir), record_path=str(record_file))

    token = "install-rec-token"
    sample_text = "## 场景1\n旁白: 第一句\n"

    store.create_draft(token=token, text=sample_text, project="记录测试工程")
    seed_draft_resources(store, token)
    build_id = bundle_mgr.create_compile_snapshot(token=token, expected_draft_version=1)
    bundle_info = bundle_mgr.execute_build_worker(token=token, build_id=build_id)

    # 绕过 AA 客户端退出断言
    monkeypatch.setattr("install_manager.assert_aa_closed", lambda: None)

    res = install_mgr.install_build(token=token, build_id=build_id)
    assert res["ok"] is True
    assert record_file.is_file()

    records = json.loads(record_file.read_text(encoding="utf-8"))
    assert isinstance(records, dict)
    assert "记录测试工程" in records
    assert records["记录测试工程"]["installed_build_id"] == build_id
    assert records["记录测试工程"]["source_draft_token"] == token
