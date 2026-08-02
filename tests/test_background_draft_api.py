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


def test_resolve_background_request_same_card_id(temp_draft_store):
    store = temp_draft_store
    token = "bg-resolve-token-1"
    sample_text = (
        "## 场景1\n"
        "# 待生成自定义背景：雨夜车站\n"
        "凯伊: 你好！\n"
    )

    draft = store.create_draft(token=token, text=sample_text)
    bg_card_id = draft["identities"][1]["card_id"]

    # 1. 解决背景请求为 BG_RainyStation
    res = store.resolve_background_request(
        token=token,
        card_id=bg_card_id,
        bg_name="BG_RainyStation",
        expected_draft_version=1,
    )

    # 2. 断言卡片总量依然为 3，card_id 维持不变
    identities = res["identities"]
    assert len(identities) == 3
    assert identities[1]["card_id"] == bg_card_id

    # 3. 文本已被替换为 @bg BG_RainyStation
    assert "@bg BG_RainyStation" in res["edited_text"]
    assert "待生成自定义背景" not in res["edited_text"]

    # 4. 诊断列表中原 bg.request_unresolved 消失
    assert not any(d["code"] == "bg.request_unresolved" for d in res["diagnostics"])

    # 5. 双版本 +1
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 2
