# -*- coding: utf-8 -*-
"""Deterministic post-processing for two-stage face labeling.

The vision model observes pixels.  This module does not look at an image and
never invents a new face id; it only normalizes the observation, validates the
model's semantic candidate against those observations, and creates a compact
selection record for the runtime.  Keeping this boundary explicit lets us
re-label without losing the raw AI answer or manual overrides.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from face_semantics import CONTROLLED_DELIVERY_FIT, CONTROLLED_USAGE_FREQUENCY


VISUAL_FACT_FIELDS = (
    "eye_openness", "gaze", "iris_color", "eye_effect", "brow_shape",
    "mouth_openness", "mouth_shape", "blush_level", "tears_level",
    "sweat_level", "face_shadow", "visual_tags", "visual_confidence",
    "review_note_cn",
)

VISUAL_FACT_ENUMS = {
    "eye_openness": frozenset({
        "open", "wide_open", "half_open", "squint", "closed", "wink",
        "occluded", "unknown",
    }),
    "gaze": frozenset({
        "forward", "left", "right", "up", "down", "away",
        "not_visible", "unknown",
    }),
    "iris_color": frozenset({
        "blue", "cyan", "green", "pink", "red", "purple", "amber",
        "gold", "gray", "heterochromia", "other", "not_visible", "unknown",
    }),
    "eye_effect": frozenset({"normal", "glow", "blank", "stylized", "occluded", "unknown"}),
    "brow_shape": frozenset({
        "relaxed", "raised", "inner_raised", "lowered_inward", "knitted",
        "asymmetric", "occluded", "unknown",
    }),
    "mouth_openness": frozenset({"closed", "slightly_open", "open", "wide_open", "occluded", "unknown"}),
    "mouth_shape": frozenset({"neutral", "smile", "downturned", "round", "gritted", "wavy", "other", "occluded", "unknown"}),
    "blush_level": frozenset({"none", "base", "expressive", "strong", "unknown"}),
    "tears_level": frozenset({"none", "watery_eyes", "tear_drop", "streaming", "unknown"}),
    "sweat_level": frozenset({"none", "single", "multiple", "unknown"}),
    "face_shadow": frozenset({"none", "upper", "full", "unknown"}),
}

_SLEEP_ONLY_TERMS = ("沉睡", "入眠", "熟睡", "睡着", "睡眠")
_NEGATED_SLEEP_SUFFIXES = (
    "不", "非", "无", "不是", "并非", "不等于", "不等同", "不等同于",
    "不代表", "并不代表", "不能视为", "不可视为", "不能限定为", "不能只用于",
)
_NORMAL_ARIS_IDS = frozenset({"아리스", "아리스N", "아리스NF"})
_KEI_PERSONA_FACE_IDS = frozenset({"12", "14", "15", "16", "17", "18", "19"})


def persona_scope_for(ident: object) -> str:
    return "normal_aris" if _text(ident) in _NORMAL_ARIS_IDS else "default"


def is_persona_face_blocked(ident: object, face_id: object) -> bool:
    return (
        persona_scope_for(ident) == "normal_aris"
        and _text(face_id) in _KEI_PERSONA_FACE_IDS
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def _claims_sleep_only(value: object) -> bool:
    """Ignore explicit negations while retaining any positive sleep claim."""
    text = "".join(_text(value).split())
    for term in _SLEEP_ONLY_TERMS:
        start = 0
        while (index := text.find(term, start)) >= 0:
            prefix = text[max(0, index - 8):index]
            if not any(prefix.endswith(suffix) for suffix in _NEGATED_SLEEP_SUFFIXES):
                return True
            start = index + len(term)
    return False


def normalize_visual_facts(item: Mapping | None) -> dict:
    """Return a compact, stable observation record.

    ``visual_facts`` is the new AI shape.  Legacy top-level fields are copied
    as a fallback so old providers and old checkpoints remain readable.
    """
    source = dict(item or {})
    nested = source.get("visual_facts")
    nested = dict(nested) if isinstance(nested, Mapping) else {}
    result: dict[str, object] = {}
    for field, allowed in VISUAL_FACT_ENUMS.items():
        value = _text(nested.get(field))
        result[field] = value if value in allowed else "unknown"

    # Legacy providers still populate only five free-text fields.  Convert the
    # obvious cases and leave ambiguous details unknown instead of guessing.
    eyes = _text(source.get("eyes"))
    if result["eye_openness"] == "unknown":
        if "闭眼" in eyes:
            result["eye_openness"] = "closed"
        elif "眯眼" in eyes or "半闭" in eyes:
            result["eye_openness"] = "half_open"
        elif "睁" in eyes:
            result["eye_openness"] = "wide_open" if "大" in eyes or "圆" in eyes else "open"
    if result["eye_openness"] == "closed" and result["iris_color"] == "unknown":
        result["iris_color"] = "not_visible"
    mouth = _text(source.get("mouth"))
    if result["mouth_openness"] == "unknown":
        if "闭" in mouth:
            result["mouth_openness"] = "closed"
        elif "微张" in mouth:
            result["mouth_openness"] = "slightly_open"
        elif "张" in mouth or "开" in mouth:
            result["mouth_openness"] = "wide_open" if "大" in mouth else "open"
    if result["mouth_shape"] == "unknown":
        if "笑" in mouth or "上扬" in mouth:
            result["mouth_shape"] = "smile"
        elif "撇" in mouth or "下垂" in mouth:
            result["mouth_shape"] = "downturned"
    brows = _text(source.get("brows"))
    if result["brow_shape"] == "unknown":
        if "上扬" in brows or "抬" in brows:
            result["brow_shape"] = "raised"
        elif "皱" in brows or "紧" in brows:
            result["brow_shape"] = "knitted"
        elif brows:
            result["brow_shape"] = "relaxed"
    if result["blush_level"] == "unknown" and isinstance(source.get("blush"), bool):
        result["blush_level"] = "expressive" if source["blush"] else "none"
    if result["tears_level"] == "unknown" and isinstance(source.get("tears"), bool):
        result["tears_level"] = "tear_drop" if source["tears"] else "none"

    tags = nested.get("visual_tags", source.get("visual_tags", []))
    if isinstance(tags, (list, tuple, set, frozenset)):
        result["visual_tags"] = list(dict.fromkeys(_text(value) for value in tags if _text(value)))
    else:
        result["visual_tags"] = []
    result["review_note_cn"] = _text(nested.get("review_note_cn"))
    confidence = nested.get("visual_confidence", source.get("confidence"))
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    result["visual_confidence"] = max(0.0, min(1.0, confidence)) if math.isfinite(confidence) else 0.0
    return result


def _official_summary(examples: Sequence[Mapping] | None) -> dict:
    """Keep only tiny aggregate evidence; never persist or inject all examples."""
    rows = [item for item in (examples or ()) if isinstance(item, Mapping)]
    emoticons: list[str] = []
    actions: list[str] = []
    for row in rows:
        for value in row.get("emoticons") or ():
            value = _text(value)
            if value and value not in emoticons:
                emoticons.append(value)
        for value in row.get("actions") or ():
            value = _text(value)
            if value and value not in actions:
                actions.append(value)
    return {
        "examples": len(rows),
        "silent_examples": sum(bool(row.get("silent")) for row in rows),
        "closeup_examples": sum(bool(row.get("closeup")) for row in rows),
        "emoticons": emoticons[:8],
        "actions": actions[:8],
    }


def resolve_backend_label(
    item: Mapping,
    official_examples: Sequence[Mapping] | None = None,
    official_profile: Mapping | None = None,
    *,
    ident: str = "",
    face_id: str = "",
) -> dict:
    """Validate an AI candidate and produce a compact backend decision.

    This is intentionally conservative: a conflict is flagged for review, not
    silently “corrected” into a different emotion.  The runtime can therefore
    use the candidate while the workbench knows exactly why it needs review.
    """
    facts = normalize_visual_facts(item)
    primary = _text(item.get("primary_emotion"))
    usage = _text(item.get("usage_hint_cn") or item.get("description_cn"))
    delivery_fit = list(dict.fromkeys(
        _text(value) for value in item.get("delivery_fit") or () if _text(value)
    ))
    usage_frequency = _text(item.get("usage_frequency"))
    try:
        semantic_confidence = float(item.get("semantic_confidence"))
    except (TypeError, ValueError):
        semantic_confidence = 0.0
    if not math.isfinite(semantic_confidence):
        semantic_confidence = 0.0
    semantic_confidence = max(0.0, min(1.0, semantic_confidence))
    flags: list[str] = []
    unknown_fields = [
        field for field in VISUAL_FACT_ENUMS
        if facts.get(field) in {"unknown", "occluded"}
    ]
    if unknown_fields:
        flags.append("visual_facts_incomplete")
    if float(facts.get("visual_confidence") or 0.0) < 0.65:
        flags.append("visual_facts_low_confidence")
    if not primary or len(usage) < 2:
        flags.append("semantic_candidate_incomplete")
    if item.get("delivery_fit") is not None and (
        not delivery_fit
        or any(value not in CONTROLLED_DELIVERY_FIT for value in delivery_fit)
    ):
        flags.append("delivery_fit_invalid")
    if item.get("usage_frequency") is not None and usage_frequency not in CONTROLLED_USAGE_FREQUENCY:
        flags.append("usage_frequency_invalid")
    if "semantic_confidence" in item and semantic_confidence < 0.65:
        flags.append("semantic_low_confidence")

    expression_class = _text(item.get("expression_class"))
    special_visual = bool(
        facts.get("eye_effect") in {"blank", "glow", "stylized"}
        or facts.get("sweat_level") == "multiple"
        or facts.get("face_shadow") in {"upper", "full"}
        or facts.get("tears_level") in {"tear_drop", "streaming"}
    )
    if special_visual and expression_class not in {"special", "peak"}:
        flags.append("special_visual_requires_special_class")
    if (
        expression_class in {"special", "peak"}
        and usage_frequency in {"default", "common"}
    ):
        flags.append("special_class_frequency_too_common")
    normalized_ident = _text(ident)
    normalized_face_id = _text(face_id or item.get("face_id"))
    persona_scope = persona_scope_for(normalized_ident)
    if is_persona_face_blocked(normalized_ident, normalized_face_id):
        flags.append("persona_scope_blocked")

    combined = f"{primary} {usage}"
    if facts.get("eye_openness") == "closed" and facts.get("iris_color") != "not_visible":
        flags.append("closed_eye_cannot_expose_iris_color")
    if facts.get("eye_openness") == "closed" and any(term in combined for term in ("睁眼", "圆睁")):
        flags.append("candidate_conflicts_with_eyes")
    if facts.get("tears_level") == "none" and any(term in combined for term in ("流泪", "哭泣", "泪")):
        flags.append("candidate_conflicts_with_tears")
    if facts.get("blush_level") == "none" and "脸红" in combined:
        flags.append("candidate_conflicts_with_blush")

    official = _official_summary(official_examples)
    if isinstance(official_profile, Mapping):
        for key in (
            "total_count", "lexical_dialogue_count", "nonlexical_dialogue_count",
            "no_dialogue_count", "action_count", "emoticon_count",
            "closeup_count", "variant_exact",
        ):
            if key in official_profile:
                official[key] = official_profile[key]
    blocking_flags = {
        "closed_eye_cannot_expose_iris_color",
        "candidate_conflicts_with_eyes",
        "candidate_conflicts_with_tears",
        "candidate_conflicts_with_blush",
        "delivery_fit_invalid",
        "usage_frequency_invalid",
        "visual_facts_low_confidence",
        "semantic_low_confidence",
        "special_visual_requires_special_class",
        "special_class_frequency_too_common",
        "persona_scope_blocked",
    }
    effective_delivery_fit = list(delivery_fit)
    effective_frequency = usage_frequency
    evidence_adjustments = []
    total = int(official.get("total_count") or 0)
    lexical = int(official.get("lexical_dialogue_count") or 0)
    nonlexical = int(official.get("nonlexical_dialogue_count") or 0)
    no_dialogue = int(official.get("no_dialogue_count") or 0)
    if (
        total >= 5
        and lexical / total >= 0.6
        and _claims_sleep_only(combined)
    ):
        flags.append("candidate_conflicts_with_official_speech")
        blocking_flags.add("candidate_conflicts_with_official_speech")
    if total >= 5 and lexical == 0 and nonlexical + no_dialogue == total:
        effective_delivery_fit = [
            value for value in effective_delivery_fit
            if value not in {"normal_speech", "emphatic_speech", "shout"}
        ]
        for value in ("silent_reaction", "listening"):
            if value not in effective_delivery_fit:
                effective_delivery_fit.append(value)
        if effective_frequency in {"default", "common", ""}:
            effective_frequency = "conditional"
        evidence_adjustments.append("official_nonlexical_usage_profile")
    semantic_profile = {
        "delivery_fit": effective_delivery_fit,
        "usage_frequency": effective_frequency,
        "intensity": item.get("intensity"),
        "expression_class": _text(item.get("expression_class")),
        "semantic_confidence": semantic_confidence,
        "semantic_tags": [
            _text(value) for value in item.get("semantic_tags") or () if _text(value)
        ],
        "semantic_modes": [
            dict(value) for value in item.get("semantic_modes") or ()
            if isinstance(value, Mapping)
        ],
    }
    hard_blocks = sorted(blocking_flags.intersection(flags))
    return {
        "pipeline": "vision-observation+semantic-profile+backend-validation-v4",
        "semantic_source": "ai_candidate_validated_by_backend",
        "selection_ready": bool(primary and usage and not hard_blocks),
        "review_required": bool(flags),
        "review_flags": flags,
        "hard_blocks": hard_blocks,
        "persona_scope": persona_scope,
        "selection_terms": [value for value in (primary, usage) if value],
        "selection_profile": semantic_profile,
        "rank_features": {
            "beat_fit": [
                _text(value) for value in item.get("beat_fit") or () if _text(value)
            ],
            "delivery_fit": effective_delivery_fit,
            "intensity": item.get("intensity"),
            "usage_frequency": effective_frequency,
            "expression_class": expression_class,
        },
        "evidence_adjustments": evidence_adjustments,
        "official_evidence": official,
    }
