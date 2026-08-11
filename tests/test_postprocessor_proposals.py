# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from annotate import normalize_emoticon_density, build_postprocessor_proposals


def test_postprocessor_emoticon_density_generates_proposals():
    # 构造高密度气泡台词行
    items = [
        {"kind": "line", "who": "凯伊", "text": "第一句", "emo": "惊讶", "card_id": "c-1"},
        {"kind": "line", "who": "凯伊", "text": "第二句", "emo": "惊讶", "card_id": "c-2"},
        {"kind": "line", "who": "凯伊", "text": "第三句", "emo": "惊讶", "card_id": "c-3"},
    ]

    # normalize 稀释连续气泡
    proposals = build_postprocessor_proposals(items, rule="emoticon_density")
    assert isinstance(proposals, list)


def test_continuity_density_drop_generates_a_reviewable_proposal():
    items = [{
        "kind": "line", "who": "凯伊", "text": "第二句", "card_id": "c-2",
        "_direction_drops": [{
            "field": "emo", "value": "惊叹", "reason": "unsupported_transient_repeat",
        }],
    }]

    proposals = build_postprocessor_proposals(items, rule="continuity_density")

    assert len(proposals) == 1
    assert proposals[0]["field"] == "emo"
    assert proposals[0]["before"] == "惊叹"
    assert proposals[0]["after"] is None
    assert proposals[0]["rule"] == "unsupported_transient_repeat"
