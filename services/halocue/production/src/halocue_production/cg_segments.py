from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .errors import ProductionError
from .models import new_id


_BACKGROUND_KEY = re.compile(r"^[^\x00-\x1f]{1,160}$")
_STAGE_COMMANDS = {"bg", "enter", "exit", "move", "stage", "auto", "camera", "camera_hold", "fx", "hl"}


def load(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionError("cg_segments_corrupted", "CG 段落数据无法读取", status=500) from exc
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ProductionError("cg_segments_corrupted", "CG 段落数据格式无效", status=500)
    return [dict(item) for item in value]


def save(path: Path, segments: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def create(
    *, start_card_id: str, end_card_id: str, background_key: str, label: str
) -> dict[str, Any]:
    background = background_key.strip()
    if not _BACKGROUND_KEY.fullmatch(background):
        raise ProductionError("invalid_cg_background_key", "CG 背景标识不能为空且不能包含控制字符")
    return {
        "segment_id": new_id("cg"),
        "start_card_id": start_card_id.strip(),
        "end_card_id": end_card_id.strip(),
        "background_key": background,
        "label": label.strip()[:80] or background,
        "display_mode": "named_slot_zero",
    }


def validate(
    *, segments: list[dict[str, Any]], cards: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Validate author-selected CG spans independently from the legacy compiler."""
    positions = {str(card.get("card_id") or ""): index for index, card in enumerate(cards)}
    issues: list[dict[str, Any]] = []
    membership: dict[str, dict[str, Any]] = {}
    occupied: set[str] = set()
    for segment in segments:
        segment_id = str(segment.get("segment_id") or "")
        start = str(segment.get("start_card_id") or "")
        end = str(segment.get("end_card_id") or "")
        background = str(segment.get("background_key") or "").strip()
        if not segment_id or start not in positions or end not in positions:
            issues.append(_issue("cg.range_invalid", start or None, "CG 段落的起止卡片已不存在，请重新设置范围"))
            continue
        if positions[start] > positions[end]:
            issues.append(_issue("cg.range_invalid", start, "CG 段落的结束卡片必须位于开始卡片之后"))
            continue
        if not _BACKGROUND_KEY.fullmatch(background):
            issues.append(_issue("cg.background_required", start, "CG 段落必须指定当前任务已登记的背景"))
            continue
        range_cards = cards[positions[start] : positions[end] + 1]
        if not any(card.get("kind") == "line" for card in range_cards):
            issues.append(_issue("cg.dialogue_required", start, "CG 段落内至少需要一条台词"))
            continue
        if any(str(card.get("card_id") or "") in occupied for card in range_cards):
            issues.append(_issue("cg.range_overlap", start, "CG 段落不能与其他 CG 段落重叠"))
            continue
        blocked = next(
            (
                card
                for card in range_cards
                if card.get("kind") == "dir"
                and str((card.get("current") or {}).get("cmd") or "").casefold() in _STAGE_COMMANDS
            ),
            None,
        )
        if blocked:
            issues.append(_issue("cg.stage_command_forbidden", str(blocked.get("card_id") or start), "CG 段落内不能切换背景、立绘、镜头或舞台指令"))
            continue
        for card in range_cards:
            card_id = str(card.get("card_id") or "")
            occupied.add(card_id)
            membership[card_id] = {
                "segment_id": segment_id,
                "label": str(segment.get("label") or background),
                "background_key": background,
                "start_card_id": start,
                "end_card_id": end,
                "display_mode": "named_slot_zero",
            }
    return issues, membership


def transform_for_compile(
    *, text: str, identities: list[dict[str, Any]], segments: list[dict[str, Any]]
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Emit CG as a background switch plus named dialogue with no portraits."""
    cards = [
        {"card_id": identity.get("card_id"), "kind": node.kind, "current": node.fields, "raw": node.raw}
        for node, identity in zip(_nodes(text), identities)
    ]
    issues, membership = validate(segments=segments, cards=cards)
    if issues:
        raise ProductionError("cg_segment_invalid", "CG 段落尚未通过编译前检查", status=409, details={"issues": issues})

    aliases: dict[str, dict[str, Any]] = {}
    out: list[str] = []
    active_segment: dict[str, Any] | None = None
    visible_background = "BG_Black"
    resume_background = "BG_Black"

    for card in cards:
        card_id = str(card.get("card_id") or "")
        segment = membership.get(card_id)
        if active_segment and (not segment or segment["segment_id"] != active_segment["segment_id"]):
            out.append(f"@bg {resume_background}\n")
            active_segment = None
        if not segment:
            fields = card.get("current") if isinstance(card.get("current"), dict) else {}
            if card.get("kind") == "dir" and str(fields.get("cmd") or "").casefold() == "bg":
                visible_background = str(fields.get("arg") or "").strip() or visible_background
            out.append(str(card.get("raw") or ""))
            continue
        if not active_segment:
            active_segment = segment
            resume_background = visible_background
            out.append(f"@camera -\n@bg {segment['background_key']}\n")
        if card.get("kind") != "line":
            # An embedded popup would make this a foreground-image scene rather than CG.
            fields = card.get("current") if isinstance(card.get("current"), dict) else {}
            if card.get("kind") == "dir" and str(fields.get("cmd") or "").casefold() == "popup":
                continue
            out.append(str(card.get("raw") or ""))
            continue
        fields = card.get("current") if isinstance(card.get("current"), dict) else {}
        speaker = str(fields.get("who") or "").strip()
        alias = "__halocue_cg_" + hashlib.sha1(speaker.encode("utf-8")).hexdigest()[:12]
        aliases[alias] = {"id": speaker, "name": speaker, "portrait": False, "narrator": False}
        out.append(f"{alias}: {str(fields.get('text') or '').strip()}\n")
    if active_segment:
        out.append(f"@bg {resume_background}\n")
    return "".join(out), aliases


def _nodes(text: str) -> list[Any]:
    from document import normalize_draft_nodes, parse_document_lossless

    return normalize_draft_nodes(parse_document_lossless(text))


def _issue(code: str, card_id: str | None, message: str) -> dict[str, Any]:
    return {"code": code, "severity": "error", "card_id": card_id, "message": message}
