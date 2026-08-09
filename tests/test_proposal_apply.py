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


def test_applied_pending_reject_restores_before(temp_draft_dir):
    store = temp_draft_dir
    token = "prop-token-1"
    sample_text = "## 场景1\n凯伊[惊疑]: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card_id = draft["identities"][1]["card_id"]

    # 构造并保存一个 applied_pending proposal (例如 LLM/后处理加了 [惊疑]，before 为 None)
    prop = {
        "proposal_id": "prop-101",
        "origin": "deterministic_postprocessor",
        "type": "applied_pending",
        "rule": "emoticon_density",
        "card_id": card_id,
        "field": "emo",
        "before": None,
        "after": "惊疑",
        "based_on_content_revision": 1,
        "expected_card_version": 1,
        "state": "pending",
    }
    store.add_proposals(token, [prop])

    # 拒绝 applied_pending 提案 -> 应恢复 before (即清空 emo)，双版本 +1
    res = store.handle_proposal(token=token, proposal_id="prop-101", action="reject", expected_draft_version=1)
    assert res["session"]["draft_version"] == 2
    assert res["session"]["content_revision"] == 2
    # 检查 edited_text 中 [惊疑] 已被移除
    assert "凯伊: 第一句" in res["edited_text"]


def test_suggested_fix_accept_and_reject(temp_draft_dir):
    store = temp_draft_dir
    token = "prop-token-2"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card_id = draft["identities"][1]["card_id"]

    prop = {
        "proposal_id": "prop-202",
        "origin": "model",
        "type": "suggested_fix",
        "rule": "face_out_of_range",
        "card_id": card_id,
        "field": "face",
        "before": None,
        "after": "01",
        "based_on_content_revision": 1,
        "expected_card_version": 1,
        "state": "pending",
    }
    store.add_proposals(token, [prop])

    # 拒绝 suggested_fix -> 文本保持不变，仅 draft_version +1
    res_rej = store.handle_proposal(token=token, proposal_id="prop-202", action="reject", expected_draft_version=1)
    assert res_rej["session"]["draft_version"] == 2
    assert res_rej["session"]["content_revision"] == 1
    assert "凯伊: 第一句" in res_rej["edited_text"]

    # 接受 suggested_fix -> 写入 after (即加 face (01))，双版本 +1
    prop_accept = dict(prop, proposal_id="prop-203", state="pending", based_on_content_revision=1)
    store.add_proposals(token, [prop_accept])

    res_acc = store.handle_proposal(token=token, proposal_id="prop-203", action="accept", expected_draft_version=2)
    assert res_acc["session"]["draft_version"] == 3
    assert res_acc["session"]["content_revision"] == 2
    assert "凯伊(01): 第一句" in res_acc["edited_text"]
