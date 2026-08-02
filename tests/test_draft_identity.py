# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from document import DocNode
from draft_identity import (
    CardIdentity,
    assign_identity,
    compute_text_fingerprint,
    generate_order_key,
)


def test_card_identity_dict_serialization():
    card = CardIdentity(
        card_id="card-123",
        source_id="src-456",
        origin="source",
        parent_id=None,
        order_key="a00001",
        text_fingerprint=compute_text_fingerprint("凯伊: 你好"),
        review_state="pending",
    )
    d = card.to_dict()
    # 必须包含 7 个持久化字段
    assert set(d.keys()) == {
        "card_id",
        "source_id",
        "origin",
        "parent_id",
        "order_key",
        "text_fingerprint",
        "review_state",
    }
    # edit_state 和 validation_state 绝不持久化
    assert "edit_state" not in d
    assert "validation_state" not in d

    restored = CardIdentity.from_dict(d)
    assert restored.card_id == "card-123"
    assert restored.source_id == "src-456"
    assert restored.origin == "source"


def test_derived_edit_state():
    original_text = "凯伊: 你好"
    card = CardIdentity(
        card_id="card-1",
        source_id=None,
        origin="manual",
        parent_id=None,
        order_key="a00001",
        text_fingerprint=compute_text_fingerprint(original_text),
        review_state="pending",
    )
    assert card.derive_edit_state(original_text) == "unchanged"
    assert card.derive_edit_state("凯伊: 你好呀") == "modified"


def test_assign_identity_with_source_map():
    nodes = [
        DocNode(kind="scene", raw="## 场景1\n", line_no=1, fields={"title": "场景1"}),
        DocNode(kind="line", raw="凯伊: 你好\n", line_no=2, fields={"who": "凯伊", "text": "你好"}),
    ]
    source_map = {
        2: {"source_id": "src-uuid-2", "split_index": 0}
    }
    identities = assign_identity(nodes, source_map=source_map, origin_override="source")
    assert len(identities) == 2

    # node 1 (no source_id)
    assert identities[0].source_id is None
    assert identities[0].origin == "source"

    # node 2 (has source_id in source_map)
    assert identities[1].source_id == "src-uuid-2"
    assert identities[1].origin == "source"
    assert identities[1].text_fingerprint == compute_text_fingerprint("凯伊: 你好")
    assert identities[0].order_key < identities[1].order_key
