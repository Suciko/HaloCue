# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore, RevisionConflictError


@pytest.fixture
def temp_draft_dir(tmp_path):
    return DraftStore(base_dir=str(tmp_path / "drafts"))


def test_card_update_cas_and_versions(temp_draft_dir):
    store = temp_draft_dir
    token = "crud-token-1"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card_id = draft["identities"][1]["card_id"]

    # 错误 CAS 版本
    with pytest.raises(RevisionConflictError):
        store.update_card_content(
            token=token,
            card_id=card_id,
            patch={"text": "修改文本"},
            expected_draft_version=999,
        )

    # 正确 CAS 版本
    res = store.update_card_content(
        token=token,
        card_id=card_id,
        patch={"text": "修改文本"},
        expected_draft_version=1,
    )
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 2
    assert "修改文本" in res["edited_text"]


def test_card_insert_and_delete(temp_draft_dir):
    store = temp_draft_dir
    token = "crud-token-2"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card1_id = draft["identities"][1]["card_id"]

    # 插入卡片
    res = store.insert_card(
        token=token,
        after_card_id=card1_id,
        kind="line",
        payload={"who": "爱丽丝", "text": "第二句"},
        origin="manual",
        expected_draft_version=1,
    )
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 2
    assert len(res["identities"]) == 3
    assert "爱丽丝: 第二句" in res["edited_text"]

    new_card_id = res["identities"][2]["card_id"]

    # 删除卡片
    res_del = store.delete_card(
        token=token,
        card_id=new_card_id,
        expected_draft_version=2,
    )
    assert res_del["session"]["draft_version"] == 3
    assert res_del["session"]["content_revision"] == 3
    assert len(res_del["identities"]) == 2
    assert "爱丽丝: 第二句" not in res_del["edited_text"]


def test_directive_change_resets_downstream_reviews(temp_draft_dir):
    store = temp_draft_dir
    token = "crud-token-3"
    sample_text = "@bg BG_Room\n凯伊: 第一句\n凯伊: 第二句\n"

    draft = store.create_draft(token=token, text=sample_text)
    bg_card_id = draft["identities"][0]["card_id"]
    line1_card_id = draft["identities"][1]["card_id"]

    # 先把 line1 设为 approved
    store.update_card_review(token=token, card_id=line1_card_id, review_state="approved", expected_draft_version=1)
    d = store.load_draft(token)
    assert d["identities"][1]["review_state"] == "approved"

    # 修改 @bg 指令，应该触发连锁重置，后续卡片 review_state 重置为 pending
    res = store.update_card_content(
        token=token,
        card_id=bg_card_id,
        patch={"cmd": "bg", "arg": "BG_Beach"},
        expected_draft_version=2,
    )
    # 检查 line1 的 review_state 被重置为 pending
    target_card = [c for c in res["identities"] if c["card_id"] == line1_card_id][0]
    assert target_card["review_state"] == "pending"
