# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - 身份模型 (draft_identity.py)
管理卡片的全局身份元数据 (identity.json)
持久化字段：card_id, source_id, origin, parent_id, order_key, text_fingerprint, review_state
派生状态（不持久化）：edit_state, validation_state
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def compute_text_fingerprint(text: str) -> str:
    """计算文本规范化后的 sha1 指纹。"""
    normalized = text.strip().encode("utf-8")
    return hashlib.sha1(normalized).hexdigest()


def create_source_map(text_or_lines: Any) -> Dict[int, Dict[str, Any]]:
    """生成包含 {line_no: {"source_id": uuid, "split_index": 0}} 的 source_map 数据结构。"""
    if isinstance(text_or_lines, str):
        lines = text_or_lines.splitlines()
    else:
        lines = list(text_or_lines)

    source_map = {}
    for idx, _ in enumerate(lines, 1):
        source_map[idx] = {
            "source_id": str(uuid.uuid4()),
            "split_index": 0,
        }
    return source_map


def generate_order_key(index: int, total: int = 0) -> str:
    """生成字典序排序键 (LexoRank 类字符串)。"""
    return f"a{index:05d}"


@dataclass
class CardIdentity:
    card_id: str
    source_id: Optional[str] = None
    origin: str = "source"  # source | ai | postprocessor | manual | imported
    parent_id: Optional[str] = None
    order_key: str = "a00000"
    text_fingerprint: str = ""
    review_state: str = "pending"  # pending | approved

    def to_dict(self) -> Dict[str, Any]:
        """仅序列化持久化字段，派生字段绝不持久化。"""
        return {
            "card_id": self.card_id,
            "source_id": self.source_id,
            "origin": self.origin,
            "parent_id": self.parent_id,
            "order_key": self.order_key,
            "text_fingerprint": self.text_fingerprint,
            "review_state": self.review_state,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CardIdentity":
        return cls(
            card_id=d["card_id"],
            source_id=d.get("source_id"),
            origin=d.get("origin", "source"),
            parent_id=d.get("parent_id"),
            order_key=d.get("order_key", "a00000"),
            text_fingerprint=d.get("text_fingerprint", ""),
            review_state=d.get("review_state", "pending"),
        )

    def derive_edit_state(self, current_text: str) -> str:
        """派生编辑状态：unchanged | modified"""
        current_fp = compute_text_fingerprint(current_text)
        if current_fp == self.text_fingerprint:
            return "unchanged"
        return "modified"


def assign_identity(
    nodes: List[Any],
    source_map: Optional[Dict[int, Dict[str, Any]]] = None,
    origin_override: str = "source",
) -> List[CardIdentity]:
    """为节点分配新的或关联的身份标识。"""
    identities = []
    source_map = source_map or {}

    for idx, node in enumerate(nodes, 1):
        line_no = getattr(node, "line_no", idx)
        raw_text = getattr(node, "raw", "")

        # 判断 source_id
        source_id = None
        origin = origin_override

        if line_no in source_map:
            source_id = source_map[line_no].get("source_id")

        card_id = str(uuid.uuid4())
        order_key = generate_order_key(idx, len(nodes))
        fp = compute_text_fingerprint(raw_text)

        identities.append(
            CardIdentity(
                card_id=card_id,
                source_id=source_id,
                origin=origin,
                parent_id=None,
                order_key=order_key,
                text_fingerprint=fp,
                review_state="pending",
            )
        )

    return identities
