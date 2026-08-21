# -*- coding: utf-8 -*-
"""Shared, generator-safe expression semantics.

Visual models may describe a face freely in Chinese, but fields used for
filtering and ranking must stay within a small vocabulary. Legacy free-form
values remain in the source row for audit; this module exposes a normalized
effective view without pretending that an unknown term is a formal category.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json


CONTROLLED_BEAT_FIT = frozenset({
    "action", "agreement", "celebration", "climax", "comfort", "comedy",
    "conflict", "denial", "dialogue", "embarrassment", "exposition",
    "farewell", "greeting", "hesitation", "idle", "listening", "question",
    "reaction", "resolution", "reveal", "setback", "teasing", "tension",
    "transition",
})

CONTROLLED_DELIVERY_FIT = frozenset({
    "silent_reaction", "listening", "soft_speech", "normal_speech",
    "emphatic_speech", "shout",
})

CONTROLLED_USAGE_FREQUENCY = frozenset({
    "default", "common", "conditional", "rare",
})

CONTROLLED_SEMANTIC_TAGS = frozenset({
    "neutral", "curious", "focused", "serious", "assertive", "blank",
    "playful", "joyful", "embarrassed", "distressed", "angry", "sad",
    "surprised", "afraid", "resigned", "smug", "gentle", "determined",
})

_BEAT_ALIASES = {
    "react": "reaction", "response": "reaction", "positive_reaction": "reaction",
    "积极回应": "reaction", "回应": "reaction", "反应": "reaction",
    "normal_dialogue": "dialogue", "neutral_dialogue": "dialogue",
    "dialogue_neutral": "dialogue", "casual_chat": "dialogue", "casual": "dialogue",
    "daily": "dialogue", "normal": "dialogue", "日常对话": "dialogue",
    "日常闲聊": "dialogue", "日常交谈": "dialogue", "日常互动": "dialogue",
    "对话": "dialogue", "statement": "exposition", "explanation": "exposition",
    "punchline": "comedy", "comic_relief": "comedy", "humor": "comedy",
    "banter": "teasing", "tease": "teasing", "taunt": "teasing",
    "friendly_banter": "teasing", "调侃": "teasing", "被调侃": "teasing",
    "confrontation": "conflict", "argument": "conflict", "rebuttal": "conflict",
    "protest": "conflict", "threat": "conflict", "retort": "conflict",
    "listen": "listening", "attentive": "listening", "倾听": "listening",
    "questioning": "question", "inquiry": "question",
    "doubt": "hesitation", "thinking": "hesitation", "reflection": "hesitation",
    "revelation": "reveal", "discovery": "reveal", "twist": "reveal",
    "reassurance": "comfort", "warmth": "comfort", "bonding": "comfort",
    "intimacy": "comfort", "warm_moment": "comfort", "情感升温": "comfort",
    "crisis": "tension", "trouble": "tension", "warning": "tension",
    "turn": "transition", "setup": "transition",
    "victory": "celebration", "triumph": "celebration",
    "aftermath": "resolution", "relief": "resolution", "payoff": "resolution",
    "sadness": "setback", "resignation": "setback", "vulnerability": "setback",
    "fluster": "embarrassment", "flustered": "embarrassment",
    "awkward_moment": "embarrassment", "shock": "reaction",
    "standby": "idle", "climax_joy": "climax", "climax_positive": "climax",
    "情绪高潮": "climax", "欢快互动": "celebration",
}

_TERM_CN = {
    "flustered": "慌乱", "calm": "平静", "gentle": "温和", "smug": "得意",
    "shy": "害羞", "default": "常态", "cheerful": "开朗", "playful": "调皮",
    "troubled": "困扰", "serious": "严肃", "confident": "自信",
    "composed": "从容", "tsundere": "傲娇", "awkward": "尴尬",
    "friendly": "友好", "relaxed": "放松", "smile": "微笑", "sigh": "叹气",
    "happy": "开心", "pout": "闹别扭", "sulking": "生闷气", "focused": "专注",
    "laugh": "大笑", "speaking": "说话", "depressed": "低落",
    "teasing": "调侃", "curious": "好奇", "inquiry": "疑问", "warm": "温暖",
    "protest": "抗议", "attentive": "认真倾听", "panic": "慌张",
    "hesitant": "犹豫", "energetic": "元气",
}


def _strings(values: object) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _is_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def normalize_semantic_modes(value: object) -> list[dict]:
    """Normalize up to three alternate acting uses for one visible face."""
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for raw in value:
        if not isinstance(raw, Mapping):
            continue
        label = str(raw.get("label_cn") or "").strip()
        if not label:
            continue
        normalized = normalize_semantic_payload({
            "beat_fit": raw.get("beat_fit") or [],
            "delivery_fit": raw.get("delivery_fit") or [],
            "semantic_tags": raw.get("semantic_tags") or [],
        })
        intensity = raw.get("intensity")
        if isinstance(intensity, bool) or not isinstance(intensity, int) or not 0 <= intensity <= 3:
            intensity = 1
        mode = {
            "label_cn": label,
            "beat_fit": normalized.get("beat_fit") or [],
            "delivery_fit": normalized.get("delivery_fit") or [],
            "intensity": intensity,
            "semantic_tags": normalized.get("semantic_tags") or [],
            "avoid_when_cn": str(raw.get("avoid_when_cn") or "").strip(),
        }
        if mode not in result:
            result.append(mode)
        if len(result) == 3:
            break
    return result


def normalize_semantic_payload(payload: Mapping | None) -> dict:
    """Return a compatible payload with controlled beats and Chinese search terms."""
    source = dict(payload or {})
    has_terms = any(
        key in source for key in ("beat_fit", "special_tags", "search_terms_cn")
    )
    controlled: list[str] = []
    search_terms = _strings(source.get("search_terms_cn"))
    for value in _strings(source.get("beat_fit")):
        canonical = value if value in CONTROLLED_BEAT_FIT else _BEAT_ALIASES.get(value)
        if canonical:
            if canonical not in controlled:
                controlled.append(canonical)
        else:
            translated = _TERM_CN.get(value)
            if translated and translated not in search_terms:
                search_terms.append(translated)
            elif _is_chinese(value) and value not in search_terms:
                search_terms.append(value)
    for value in _strings(source.get("special_tags")):
        translated = _TERM_CN.get(value, value if _is_chinese(value) else "")
        if translated and translated not in search_terms:
            search_terms.append(translated)
    if has_terms:
        source["beat_fit"] = controlled
        source["search_terms_cn"] = search_terms
    delivery_fit = _strings(source.get("delivery_fit"))
    if "delivery_fit" in source:
        source["delivery_fit"] = [
            value for value in dict.fromkeys(delivery_fit)
            if value in CONTROLLED_DELIVERY_FIT
        ]
    frequency = str(source.get("usage_frequency") or "").strip()
    if "usage_frequency" in source and frequency not in CONTROLLED_USAGE_FREQUENCY:
        source.pop("usage_frequency", None)
    if "semantic_tags" in source:
        source["semantic_tags"] = [
            value for value in dict.fromkeys(_strings(source.get("semantic_tags")))
            if value in CONTROLLED_SEMANTIC_TAGS
        ][:3]
    if "semantic_modes" in source:
        source["semantic_modes"] = normalize_semantic_modes(source.get("semantic_modes"))
    source.pop("special_tags", None)
    return source


def compact_label_cache(records: Iterable[Mapping]) -> str:
    """Build the per-character comparison memory injected into later batches."""
    lines = []
    for record in records:
        if record.get("failed"):
            continue
        face_id = str(record.get("face_id") or "").strip()
        emotion = str(record.get("primary_emotion") or "").strip()
        usage = str(
            record.get("usage_hint_cn") or record.get("description_cn") or ""
        ).strip()
        if not face_id or not (emotion or usage):
            continue
        value = "｜".join(part for part in (emotion, usage) if part)
        lines.append(f"FACE {face_id}={value}")
    return "\n".join(lines)


def migrate_semantic_storage(con) -> dict[str, int]:
    """Normalize derived model fields in place without touching manual_json."""
    changed_labels = 0
    for row in con.execute(
        """
        SELECT ident,spine_signature,outfit_key,face_id,model,semantic_json
        FROM face_visual_label
        """
    ).fetchall():
        try:
            original = json.loads(row["semantic_json"] or "{}")
        except (TypeError, ValueError):
            original = {}
        normalized = normalize_semantic_payload(original)
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if encoded == str(row["semantic_json"] or "{}"):
            continue
        con.execute(
            """
            UPDATE face_visual_label SET semantic_json=?
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=? AND model=?
            """,
            (
                encoded, row["ident"], row["spine_signature"], row["outfit_key"],
                row["face_id"], row["model"],
            ),
        )
        changed_labels += 1

    changed_evidence = 0
    for row in con.execute(
        """
        SELECT ident,spine_signature,outfit_key,face_id,source,raw
        FROM face_evidence WHERE source LIKE 'vision:%'
        """
    ).fetchall():
        try:
            original = json.loads(row["raw"] or "{}")
        except (TypeError, ValueError):
            continue
        normalized = normalize_semantic_payload(original)
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        if encoded == str(row["raw"] or "{}"):
            continue
        con.execute(
            """
            UPDATE face_evidence SET raw=?
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=? AND source=?
            """,
            (
                encoded, row["ident"], row["spine_signature"], row["outfit_key"],
                row["face_id"], row["source"],
            ),
        )
        changed_evidence += 1
    con.commit()
    return {"visual_labels": changed_labels, "evidence_rows": changed_evidence}
