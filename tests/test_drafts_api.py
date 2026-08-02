# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore
from jobs import global_job_manager


def test_draft_detail_and_counts_api(tmp_path):
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    token = "draft-detail-test"
    sample_text = (
        "## 场景1\n"
        "# 待生成自定义背景：雨夜车站\n"
        "未绑定角色: 你好\n"
    )
    draft = store.create_draft(token=token, text=sample_text, project="测试细节项目")

    # 手动从 store 获取渲染并计算派生状态
    loaded = store.load_draft(token)
    assert loaded["session"]["draft_token"] == token

    # 派生 counts 检查
    diagnostics = loaded["diagnostics"]
    blocking_errors = sum(1 for d in diagnostics if d.get("severity") == "error")
    # 背景请求与未绑定角色均为 error
    assert blocking_errors >= 2


def test_list_drafts(tmp_path):
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    store.create_draft(token="token-1", text="## 场景1\n", project="项目1")
    store.create_draft(token="token-2", text="## 场景2\n", project="项目2")

    draft_dirs = [d for d in (tmp_path / "drafts").iterdir() if d.is_dir()]
    assert len(draft_dirs) == 2


def test_jobs_api():
    def sample_fn(job):
        return "result_data"

    job_id = global_job_manager.submit(sample_fn, label="api_test")
    info = global_job_manager.get(job_id)
    assert info is not None
    assert info["job_id"] == job_id
