"""Shared resource guards for model-generated screenplay annotations."""

from __future__ import annotations

import re


FX_PARTS = frozenset({"通讯", "黑屏剪影", "特写"})
RESOURCE_FIELDS = ("face", "emo", "act", "fx", "se", "bg")
CONTINUITY_RESOURCE_FIELDS = ("face", "emo", "act", "fx", "bgfx")


def is_face_allowed(allow, face):
    """Reject guesses when no verified face allowlist is available."""
    return bool(allow) and face in allow


def is_fx_allowed(value):
    """Accept documented, non-duplicated character-effect bit names only."""
    parts = [part.strip() for part in re.split(r"[+＋、,，/]", str(value)) if part.strip()]
    return bool(parts) and len(parts) == len(set(parts)) and set(parts) <= FX_PARTS


def filter_annotation_row(row, item, character, constraints, *, include_details=False):
    """Return legal model fields and exact reasons for every rejected field."""
    clean, dropped, rejected_details = {}, [], []
    who = item["who"]
    portrait = character.get("portrait") and not character.get("narrator")
    for field in ("face", "emo", "act", "fx"):
        value = row.get(field)
        if not value:
            continue
        if not portrait:
            msg = f"{who}无立绘，不能使用 {field}"
            dropped.append(msg)
            rejected_details.append({"field": field, "value": value, "reason": msg})
            continue
        if field == "face":
            character_id = character.get("id")
            allowed = constraints["faces_by_id"].get(character_id, set())
            evidence_by_id = constraints.get("face_evidence_by_id")
            evidence_level = (
                evidence_by_id.get(character_id, {}).get(value, "unknown")
                if evidence_by_id is not None else "visual_confirmed"
            )
            if (
                is_face_allowed(allowed, value)
                and evidence_level in {"visual_confirmed", "asset_semantic"}
            ):
                clean[field] = value
            elif is_face_allowed(allowed, value):
                evidence_text = (
                    "只有上下文证据"
                    if evidence_level == "context_inferred"
                    else "缺少可审阅的视觉或资产语义证据"
                )
                msg = f"{who} 的表情 {value} {evidence_text}，需要人工审阅"
                dropped.append(msg)
                rejected_details.append({
                    "code": "face_inferred_only",
                    "field": field,
                    "value": value,
                    "reason": msg,
                    "character": who,
                    "character_id": character_id,
                    "outfit_key": character.get("outfit_key", ""),
                    "spine_signature": character.get("spine_signature", ""),
                    "face_id": value,
                    "evidence_level": evidence_level,
                })
            else:
                msg = f"{who} 没有已验证表情 {value}"
                dropped.append(msg)
                rejected_details.append({"field": field, "value": value, "reason": msg})
        elif field == "emo":
            if value in constraints["ok_emo"]:
                clean[field] = constraints["sym2cn"].get(value, value)
            else:
                msg = f"未知气泡 {value}"
                dropped.append(msg)
                rejected_details.append({"field": field, "value": value, "reason": msg})
        elif field == "act":
            if value in constraints["ok_act"]:
                clean[field] = value
            else:
                msg = f"未知动作 {value}"
                dropped.append(msg)
                rejected_details.append({"field": field, "value": value, "reason": msg})
        elif field == "fx" and is_fx_allowed(value):
            clean[field] = value
        else:
            msg = f"未知效果 {value}"
            dropped.append(msg)
            rejected_details.append({"field": field, "value": value, "reason": msg})
    for field, message in (("se", "未知音效"), ("bg", "未知背景")):
        value = row.get(field)
        if not value:
            continue
        if value in constraints[f"ok_{field}"]:
            clean[field] = value
        else:
            msg = f"{message} {value}"
            dropped.append(msg)
            rejected_details.append({"field": field, "value": value, "reason": msg})
    bg_request = str(row.get("bg_request") or "").strip()
    if bg_request:
        confirmed_bg = set(constraints.get("confirmed_bg") or set())
        if clean.get("bg") and clean["bg"] in confirmed_bg:
            dropped.append("已确认背景不再生成背景请求")
        else:
            clean.pop("bg", None)
            clean["bg_request"] = bg_request[:320]
    shot = row.get("shot")
    if shot:
        if shot in constraints["ok_shot"]:
            clean["shot"] = shot
        else:
            msg = f"射击目标‘{shot}’不是可显示角色"
            dropped.append(msg)
            rejected_details.append({"field": "shot", "value": shot, "reason": msg})
    if include_details:
        return clean, dropped, rejected_details
    return clean, dropped


def project_effective_annotation_row(row, item, character, constraints):
    """Return the legal, authored-precedence row used by state and rendering."""
    clean, dropped, rejected_details = filter_annotation_row(
        row, item, character, constraints, include_details=True,
    )
    effective = dict(row)
    for field in RESOURCE_FIELDS:
        effective[field] = clean.get(field, "")
    bgfx = str(row.get("bgfx") or "")
    effective["bgfx"] = bgfx if bgfx in set(constraints.get("ok_bgfx") or ()) else ""
    explicit = set(item.get("_explicit_direction_fields") or ())
    for field in RESOURCE_FIELDS:
        if field in explicit:
            effective[field] = item.get(field, "")

    for direction_field in ("direction", "direction_intent"):
        direction = effective.get(direction_field)
        if not isinstance(direction, dict):
            continue
        direction = dict(direction)
        continuity = dict(direction.get("continuity") or {})
        for field in CONTINUITY_RESOURCE_FIELDS:
            if continuity.get(field) in {"start", "escalate"} and not effective.get(field):
                continuity[field] = "none"
        if continuity or "continuity" in direction:
            direction["continuity"] = continuity
        effective[direction_field] = direction
    return effective, clean, dropped, rejected_details
