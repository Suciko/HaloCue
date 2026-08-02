# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore
from picker_token import register_file_token, resolve_file_token
from webui import get_draft_detail_data


def test_m1_real_annotated_sample_import_and_review(tmp_path):
    sample_file = HERE / "out" / "AA_Kei_Date_Semantic_20260730_v4.annotated.txt"
    if not sample_file.is_file():
        pytest.skip("Sample annotated file missing")

    # 1. 注册 file_token
    ft_token = register_file_token(str(sample_file))
    real_path = resolve_file_token(ft_token)
    assert real_path == str(sample_file.resolve())

    # 2. 导入为草稿
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    content = Path(real_path).read_text(encoding="utf-8")
    draft_token = "m1-sample-draft"

    draft = store.create_draft(token=draft_token, text=content, project="M1真实样例测试")
    assert draft["session"]["draft_token"] == draft_token

    # 3. 读取草稿卡片与诊断 Counts
    detail = get_draft_detail_data(draft_token, store=store)
    assert "cards" in detail
    assert "counts" in detail
    assert len(detail["cards"]) > 0
    assert detail["draft_version"] == 1
    assert detail["content_revision"] == 1
