# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from build_bundle import BuildBundleManager, CompileInputStaleError
from draft_store import DraftStore


@pytest.fixture
def temp_draft_store(tmp_path):
    store_dir = tmp_path / "drafts"
    return DraftStore(base_dir=str(store_dir))


def test_build_bundle_structure_and_atomic_seal(temp_draft_store, tmp_path):
    store = temp_draft_store
    token = "bundle-token-1"
    sample_text = "## 场景1\n旁白: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text, project="Bundle测试项目")
    manager = BuildBundleManager(store=store)

    # 锁定快照
    build_id = manager.create_compile_snapshot(token=token, expected_draft_version=1)
    assert build_id.startswith("build-") or len(build_id) > 5

    # 模拟 Worker 编译产出 Bundle
    bundle_info = manager.execute_build_worker(token=token, build_id=build_id)
    bundle_dir = Path(bundle_info["bundle_dir"])

    # 1. 验证包含 bundle.complete 标记
    assert (bundle_dir / "bundle.complete").is_file()

    # 2. 验证 files.json 包含全文件 hash 清单
    assert (bundle_dir / "files.json").is_file()
    files_manifest = json.loads((bundle_dir / "files.json").read_text(encoding="utf-8"))
    assert isinstance(files_manifest, list)
    assert any(item["path"] == "build.json" for item in files_manifest)

    # 3. 验证 manifest_delta.json 存在
    assert (bundle_dir / "project" / "manifest_delta.json").is_file()


def test_stale_compile_snapshot_raises_409(temp_draft_store):
    store = temp_draft_store
    token = "bundle-token-2"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    store.create_draft(token=token, text=sample_text)
    manager = BuildBundleManager(store=store)

    # 传入过期的 expected_draft_version (例如 999) 抛出 CompileInputStaleError
    with pytest.raises(CompileInputStaleError):
        manager.create_compile_snapshot(token=token, expected_draft_version=999)
