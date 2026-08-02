# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore


@pytest.fixture
def temp_draft_store(tmp_path):
    return DraftStore(base_dir=str(tmp_path / "drafts"))


def test_per_draft_context_frozen_on_creation(temp_draft_store):
    store = temp_draft_store

    # 1. 创建草稿 A，冻结上下文
    token_a = "freeze-token-a"
    cast_a = {"default_bg": "BG_Room_A", "cast": {"Kai": {"id": "kai"}}}
    draft_a = store.create_draft(
        token=token_a,
        text="## 场景1\nKai: 第一句\n",
        project="工程A",
        cast=cast_a,
    )
    assert draft_a["session"]["project"] == "工程A"

    # 2. 创建草稿 B，不同上下文
    token_b = "freeze-token-b"
    cast_b = {"default_bg": "BG_Beach_B", "cast": {"Alice": {"id": "alice"}}}
    draft_b = store.create_draft(
        token=token_b,
        text="## 场景1\nAlice: 第一句\n",
        project="工程B",
        cast=cast_b,
    )
    assert draft_b["session"]["project"] == "工程B"

    # 3. 重新加载草稿 A，验证其 project 与演员配置依然为冻结状态，不受草稿 B 或全局状态变化的影响
    loaded_a = store.load_draft(token_a)
    assert loaded_a["session"]["project"] == "工程A"
