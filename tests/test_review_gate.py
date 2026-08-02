# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore, ReviewPendingError


@pytest.fixture
def temp_draft_dir(tmp_path):
    return DraftStore(base_dir=str(tmp_path / "drafts"))


def test_review_ready_gate_blocking(temp_draft_dir):
    store = temp_draft_dir
    token = "gate-token-1"
    sample_text = (
        "## 场景1\n"
        "# 待生成自定义背景：雨夜车站\n"
        "凯伊: 你好！\n"
    )

    draft = store.create_draft(token=token, text=sample_text)
    # 存在 unresolved background_request 诊断 (blocking error) 与 pending 卡片
    with pytest.raises(ReviewPendingError) as exc_info:
        store.assert_review_ready(token=token)

    assert "review_pending" in str(exc_info.value) or exc_info.value.code == "review_pending"


def test_batch_approve_single_transaction(temp_draft_dir):
    store = temp_draft_dir
    token = "gate-token-2"
    sample_text = "## 场景1\n凯伊: 第一句\n凯伊: 第二句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card1_id = draft["identities"][1]["card_id"]
    card2_id = draft["identities"][2]["card_id"]

    # 批量批准 card1 和 card2，传入 expected_draft_version=1
    res = store.batch_approve_reviews(
        token=token,
        card_ids=[card1_id, card2_id],
        expected_draft_version=1,
    )
    # 结果：draft_version 仅增加 1 变为 2
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 1

    # 断言卡片状态均已为 approved
    c1 = [c for c in res["identities"] if c["card_id"] == card1_id][0]
    c2 = [c for c in res["identities"] if c["card_id"] == card2_id][0]
    assert c1["review_state"] == "approved"
    assert c2["review_state"] == "approved"
