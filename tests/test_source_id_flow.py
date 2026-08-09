# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_identity import create_source_map
from dialogue_pacing import split_strong_dialogue_items


def test_create_source_map():
    text = "## 场景1\n凯伊: 第一句\n凯伊: 第二句\n"
    s_map = create_source_map(text)
    assert 1 in s_map or "1" in s_map
    assert 2 in s_map or "2" in s_map
    assert 3 in s_map or "3" in s_map
    # 每个条目包含 source_id 和 split_index
    item2 = s_map[2] if 2 in s_map else s_map["2"]
    assert "source_id" in item2
    assert item2["split_index"] == 0


def test_split_strong_dialogue_items_inherits_source_id():
    cast = {"凯伊": {"id": "kei"}}
    # 构造一条长台词，能触发 split_strong_dialogue_items
    long_line = "——" + "这就来把这长句子分成两段吧！" * 4 + "——" + "第二段在这里继续说话！" * 4
    items = [
        {
            "kind": "line",
            "who": "凯伊",
            "text": long_line,
            "raw": f"凯伊: {long_line}",
            "source_id": "src-test-uuid-100",
            "split_index": 0,
        }
    ]
    split_items = split_strong_dialogue_items(items, cast, threshold=20)
    assert len(split_items) == 2
    assert split_items[0]["source_id"] == "src-test-uuid-100"
    assert split_items[0]["split_index"] == 0
    assert split_items[1]["source_id"] == "src-test-uuid-100"
    assert split_items[1]["split_index"] == 1
