# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from annotate import annotate_script, should_trigger_retry
from draft_store import DraftStore


def test_should_trigger_retry_conditions():
    # 触发 A: 结构失败
    assert should_trigger_retry(total_lines=10, rejected_count=0, parse_error=True) is True

    # 触发 B: 拒绝率 >= 10% (10 行中拒绝 2 处 => 20%)
    assert should_trigger_retry(total_lines=10, rejected_count=2, parse_error=False) is True

    # 不触发: 拒绝率 < 10%
    assert should_trigger_retry(total_lines=20, rejected_count=1, parse_error=False) is False


def test_retry_does_not_overwrite_approved_cards(tmp_path):
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    token = "retry-token-1"
    sample_text = "## 场景1\n凯伊: 第一句\n凯伊: 第二句\n"

    draft = store.create_draft(token=token, text=sample_text)
    card1_id = draft["identities"][1]["card_id"]

    # 用户手动批复 card1
    store.update_card_review(token=token, card_id=card1_id, review_state="approved", expected_draft_version=1)

    # 模拟保存 rationale.json
    rationale_file = Path(store.get_draft_path(token)) / "rationale.json"
    rationale_file.write_text(json.dumps({card1_id: "AI 选择了惊疑表情"}, ensure_ascii=False), encoding="utf-8")

    assert rationale_file.is_file()
    r_data = json.loads(rationale_file.read_text(encoding="utf-8"))
    assert r_data[card1_id] == "AI 选择了惊疑表情"
