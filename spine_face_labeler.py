# -*- coding: utf-8 -*-
"""Multimodal semantic labels for rendered Spine face animations."""

from __future__ import annotations

import io
import json
import math
import threading
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

import assetdb
from face_label_backend import (
    VISUAL_FACT_ENUMS,
    VISUAL_FACT_FIELDS,
    normalize_visual_facts,
    resolve_backend_label,
)
from face_semantics import (
    CONTROLLED_BEAT_FIT,
    CONTROLLED_DELIVERY_FIT,
    CONTROLLED_SEMANTIC_TAGS,
    CONTROLLED_USAGE_FREQUENCY,
    compact_label_cache,
    normalize_semantic_modes,
    normalize_semantic_payload,
)
from spine_face_renderer import RenderedFace


_EDITABLE_FACE_FIELDS = frozenset({
    "primary_emotion",
    "secondary_emotions",
    "valence",
    "arousal",
    "eyes",
    "brows",
    "mouth",
    "blush",
    "tears",
    "description_cn",
    "usage_hint_cn",
    "emotion_family",
    "intensity",
    "expression_class",
    "beat_fit",
    "hold_policy",
    "special_tags",
    "search_terms_cn",
    "near_duplicate_of",
    "avoid_when_cn",
    "delivery_fit",
    "usage_frequency",
    "semantic_confidence",
    "semantic_tags",
    "semantic_modes",
    "visual_facts",
})

_SEMANTIC_FIELDS = frozenset({
    "emotion_family", "intensity", "expression_class", "beat_fit",
    "hold_policy", "special_tags", "search_terms_cn", "near_duplicate_of",
    "avoid_when_cn", "delivery_fit", "usage_frequency", "semantic_confidence",
    "semantic_tags",
    "semantic_modes",
})
_EMOTION_FAMILIES = frozenset({
    "neutral", "joy", "surprise_fear", "embarrassment",
    "irritation_anger", "sadness_hurt", "confusion_resignation",
})
_EXPRESSION_CLASSES = frozenset({"base", "accent", "peak", "special"})
_HOLD_POLICIES = frozenset({"hold", "short", "flash"})
_UNUSABLE_PRIMARY_EMOTIONS = frozenset({
    "无法识别", "不可识别", "无法判断", "unknown", "unrecognized",
})
_VISUAL_USAGE_MARKERS = (
    "眼睛", "眼神", "睁眼", "闭眼", "眉毛", "眉头", "嘴巴", "嘴角",
    "脸红", "泛红", "泪水", "流泪", "冷汗", "画面中", "图中",
)
_VISUAL_TAG_SEMANTIC_MARKERS = (
    "平静", "淡漠", "常态", "开朗", "治愈", "开心", "快乐", "愉快",
    "悲伤", "难过", "愤怒", "生气", "害羞", "紧张", "恐惧", "惊讶",
    "困惑", "无奈", "温柔", "严肃", "认真", "自信", "痛苦", "慌乱",
    "崩溃", "情绪", "人格", "角色", "语义", "用途", "calm", "happy",
    "sad", "angry", "emotion", "persona", "cheerful", "healing",
)
_REDUNDANT_VISUAL_TAGS = frozenset({
    "睁眼", "双眼睁开", "大睁眼", "半睁眼", "眯眼", "闭眼", "双眼闭合",
    "闭眼笑", "弯月眼", "闭嘴", "双唇闭合", "张嘴", "微笑", "笑",
    "脸红", "腮红", "泪", "泪水", "汗", "阴影", "closed_eyes",
    "closed_mouth", "open_eyes", "open_mouth", "smile",
})
_REVIEW_NOTE_EVIDENCE_MARKERS = (
    "复核", "不确定", "无法", "看不清", "遮挡", "模糊", "边界", "暂标",
    "暂按", "难以", "像素", "可能", "疑似", "不足", "不能确认",
)


VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "face_id": {"type": "string"},
                    "primary_emotion": {"type": "string"},
                    "usage_hint_cn": {"type": "string"},
                    "eyes": {"type": "string"},
                    "brows": {"type": "string"},
                    "mouth": {"type": "string"},
                    "blush": {"type": "boolean"},
                    "tears": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "emotion_family": {"type": "string", "enum": sorted(_EMOTION_FAMILIES)},
                    "intensity": {"type": "integer", "minimum": 0, "maximum": 3},
                    "expression_class": {"type": "string", "enum": sorted(_EXPRESSION_CLASSES)},
                    "beat_fit": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(CONTROLLED_BEAT_FIT)},
                    },
                    "hold_policy": {"type": "string", "enum": sorted(_HOLD_POLICIES)},
                    "delivery_fit": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(CONTROLLED_DELIVERY_FIT)},
                    },
                    "usage_frequency": {
                        "type": "string", "enum": sorted(CONTROLLED_USAGE_FREQUENCY),
                    },
                    "semantic_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "semantic_tags": {
                        "type": "array", "maxItems": 3,
                        "items": {"type": "string", "enum": sorted(CONTROLLED_SEMANTIC_TAGS)},
                    },
                    "semantic_modes": {
                        "type": "array", "minItems": 1, "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label_cn": {"type": "string"},
                                "beat_fit": {
                                    "type": "array",
                                    "items": {"type": "string", "enum": sorted(CONTROLLED_BEAT_FIT)},
                                },
                                "delivery_fit": {
                                    "type": "array",
                                    "items": {"type": "string", "enum": sorted(CONTROLLED_DELIVERY_FIT)},
                                },
                                "intensity": {"type": "integer", "minimum": 0, "maximum": 3},
                                "semantic_tags": {
                                    "type": "array", "maxItems": 3,
                                    "items": {"type": "string", "enum": sorted(CONTROLLED_SEMANTIC_TAGS)},
                                },
                                "avoid_when_cn": {"type": "string"},
                            },
                            "required": [
                                "label_cn", "beat_fit", "delivery_fit", "intensity",
                                "semantic_tags", "avoid_when_cn",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "special_tags": {"type": "array", "items": {"type": "string"}},
                    "search_terms_cn": {"type": "array", "items": {"type": "string"}},
                    "avoid_when_cn": {"type": "string"},
                    "visual_facts": {
                        "type": "object",
                        "description": "只记录图片中可见的面部事实；后端会独立裁决语义候选",
                        "properties": {
                            "eye_openness": {"type": "string", "enum": ["open", "wide_open", "half_open", "squint", "closed", "wink", "occluded", "unknown"]},
                            "gaze": {"type": "string", "enum": ["forward", "left", "right", "up", "down", "away", "not_visible", "unknown"]},
                            "iris_color": {"type": "string", "enum": ["blue", "cyan", "green", "pink", "red", "purple", "amber", "gold", "gray", "heterochromia", "other", "not_visible", "unknown"]},
                            "eye_effect": {"type": "string", "enum": ["normal", "glow", "blank", "stylized", "occluded", "unknown"]},
                            "brow_shape": {"type": "string", "enum": ["relaxed", "raised", "inner_raised", "lowered_inward", "knitted", "asymmetric", "occluded", "unknown"]},
                            "mouth_openness": {"type": "string", "enum": ["closed", "slightly_open", "open", "wide_open", "occluded", "unknown"]},
                            "mouth_shape": {"type": "string", "enum": ["neutral", "smile", "downturned", "round", "gritted", "wavy", "other", "occluded", "unknown"]},
                            "blush_level": {"type": "string", "enum": ["none", "base", "expressive", "strong", "unknown"]},
                            "tears_level": {"type": "string", "enum": ["none", "watery_eyes", "tear_drop", "streaming", "unknown"]},
                            "sweat_level": {"type": "string", "enum": ["none", "single", "multiple", "unknown"]},
                            "face_shadow": {"type": "string", "enum": ["none", "upper", "full", "unknown"]},
                            "visual_tags": {
                                "type": "array",
                                "description": "仅写枚举无法表达的客观可见记号；不得复述眼眉嘴泪汗阴影，不得写情绪、人格或用途；通常为空数组",
                                "items": {"type": "string"},
                            },
                            "visual_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "review_note_cn": {"type": "string"},
                        },
                        "required": ["eye_openness", "gaze", "iris_color", "eye_effect", "brow_shape", "mouth_openness", "mouth_shape", "blush_level", "tears_level", "sweat_level", "face_shadow", "visual_tags", "visual_confidence", "review_note_cn"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "face_id",
                    "primary_emotion",
                    "usage_hint_cn",
                    "eyes",
                    "brows",
                    "mouth",
                    "blush",
                    "tears",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


_VISION_STRING_FIELDS = frozenset({
    "face_id", "primary_emotion", "usage_hint_cn", "eyes", "brows", "mouth",
})


def usage_hint_cn(item: Mapping) -> str:
    """Return the selection hint from the compact or legacy label shape."""
    return str(
        item.get("usage_hint_cn") or item.get("description_cn") or ""
    ).strip()


def _manual_usage_hint(item: Mapping) -> tuple[bool, str]:
    """Return whether a manual hint override exists, including an empty one."""
    if "description_cn" in item:
        return True, str(item.get("description_cn") or "").strip()
    if "usage_hint_cn" in item:
        return True, str(item.get("usage_hint_cn") or "").strip()
    return False, ""


def selection_semantics(primary_emotion: str, usage_hint: str) -> str:
    """Combine the two fields the story model uses to choose a face."""
    emotion = str(primary_emotion or "").strip()
    hint = str(usage_hint or "").strip()
    if emotion and hint and emotion != hint:
        return f"{emotion}｜{hint}"
    return emotion or hint


def _compact_vision_item(item: Mapping) -> dict:
    compact = dict(item)
    if "usage_hint_cn" in item:
        compact["usage_hint_cn"] = item.get("usage_hint_cn")
    elif "description_cn" in item:
        compact["usage_hint_cn"] = item.get("description_cn")
    return compact


def _invalid_visual_tags(facts: Mapping) -> list[str]:
    invalid = []
    for value in facts.get("visual_tags") or ():
        tag = str(value or "").strip()
        normalized = tag.casefold().replace(" ", "")
        if (
            normalized in _REDUNDANT_VISUAL_TAGS
            or any(marker.casefold() in normalized for marker in _VISUAL_TAG_SEMANTIC_MARKERS)
        ):
            invalid.append(tag)
    return invalid


def _review_note_is_justified(facts: Mapping) -> bool:
    note = str(facts.get("review_note_cn") or "").strip()
    if not note:
        return True
    if any(
        facts.get(field) in {"unknown", "occluded", "other"}
        for field in VISUAL_FACT_ENUMS
    ):
        return True
    return any(marker in note for marker in _REVIEW_NOTE_EVIDENCE_MARKERS)


def _vision_item_validation_error(item: dict, required: set[str]) -> str:
    missing = sorted(required - set(item))
    if missing:
        return "missing_fields=" + ",".join(missing)
    facts = item.get("visual_facts")
    if isinstance(facts, Mapping):
        invalid_tags = _invalid_visual_tags(facts)
        if invalid_tags:
            return "visual_tags_contain_semantics_or_redundant_facts"
        if not _review_note_is_justified(facts):
            return "review_note_cn_is_not_justified"
        backend = resolve_backend_label(
            item,
            face_id=str(item.get("face_id") or ""),
        )
        hard_blocks = backend.get("hard_blocks") or []
        if hard_blocks:
            return "backend_hard_blocks=" + ",".join(map(str, hard_blocks))
    return "field_or_schema_validation_failed"


def _valid_vision_item(item: dict, required: set[str]) -> bool:
    if not required.issubset(item):
        return False
    if any(not isinstance(item.get(field), str) for field in _VISION_STRING_FIELDS):
        return False
    if str(item.get("primary_emotion") or "").strip().casefold() in _UNUSABLE_PRIMARY_EMOTIONS:
        return False
    if any(not isinstance(item.get(field), bool) for field in ("blush", "tears")):
        return False
    confidence = item.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    if not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
        return False
    family = item.get("emotion_family")
    if family is not None and family not in _EMOTION_FAMILIES:
        return False
    intensity = item.get("intensity")
    if intensity is not None and (
        isinstance(intensity, bool) or not isinstance(intensity, int)
        or not 0 <= intensity <= 3
    ):
        return False
    expression_class = item.get("expression_class")
    if expression_class is not None and expression_class not in _EXPRESSION_CLASSES:
        return False
    hold_policy = item.get("hold_policy")
    if hold_policy is not None and hold_policy not in _HOLD_POLICIES:
        return False
    for field in ("beat_fit", "special_tags", "search_terms_cn"):
        value = item.get(field)
        if value is not None and (
            not isinstance(value, list) or any(not isinstance(entry, str) for entry in value)
        ):
            return False
    if any(value not in CONTROLLED_BEAT_FIT for value in item.get("beat_fit") or []):
        return False
    delivery_fit = item.get("delivery_fit")
    if delivery_fit is not None and (
        not isinstance(delivery_fit, list)
        or any(value not in CONTROLLED_DELIVERY_FIT for value in delivery_fit)
    ):
        return False
    frequency = item.get("usage_frequency")
    if frequency is not None and frequency not in CONTROLLED_USAGE_FREQUENCY:
        return False
    semantic_confidence = item.get("semantic_confidence")
    if semantic_confidence is not None and (
        isinstance(semantic_confidence, bool)
        or not isinstance(semantic_confidence, (int, float))
        or not math.isfinite(float(semantic_confidence))
        or not 0 <= float(semantic_confidence) <= 1
    ):
        return False
    semantic_tags = item.get("semantic_tags")
    if semantic_tags is not None and (
        not isinstance(semantic_tags, list) or len(semantic_tags) > 3
        or any(value not in CONTROLLED_SEMANTIC_TAGS for value in semantic_tags)
    ):
        return False
    semantic_modes = item.get("semantic_modes")
    if semantic_modes is not None:
        if not isinstance(semantic_modes, list) or not 1 <= len(semantic_modes) <= 3:
            return False
        for mode in semantic_modes:
            if not isinstance(mode, dict) or set(mode) != {
                "label_cn", "beat_fit", "delivery_fit", "intensity",
                "semantic_tags", "avoid_when_cn",
            }:
                return False
            if not isinstance(mode["label_cn"], str) or not mode["label_cn"].strip():
                return False
            if (
                not isinstance(mode["beat_fit"], list)
                or any(value not in CONTROLLED_BEAT_FIT for value in mode["beat_fit"])
                or not isinstance(mode["delivery_fit"], list)
                or any(value not in CONTROLLED_DELIVERY_FIT for value in mode["delivery_fit"])
                or isinstance(mode["intensity"], bool)
                or not isinstance(mode["intensity"], int)
                or not 0 <= mode["intensity"] <= 3
                or not isinstance(mode["semantic_tags"], list)
                or len(mode["semantic_tags"]) > 3
                or any(value not in CONTROLLED_SEMANTIC_TAGS for value in mode["semantic_tags"])
                or not isinstance(mode["avoid_when_cn"], str)
            ):
                return False
    if "avoid_when_cn" in item and not isinstance(item["avoid_when_cn"], str):
        return False
    if "visual_facts" in item:
        facts = item.get("visual_facts")
        if not isinstance(facts, dict):
            return False
        nested_required = set(
            VISION_SCHEMA["properties"]["items"]["items"]["properties"]
            ["visual_facts"]["required"]
        )
        if "visual_facts" in required and not nested_required.issubset(facts):
            return False
        allowed = {
            "eye_openness", "gaze", "iris_color", "eye_effect", "brow_shape",
            "mouth_openness", "mouth_shape", "blush_level", "tears_level",
            "sweat_level", "face_shadow", "visual_tags", "visual_confidence",
            "review_note_cn",
        }
        if not set(facts) <= allowed:
            return False
        if any(
            key in facts and not isinstance(facts[key], str)
            for key in allowed - {"visual_tags", "visual_confidence"}
        ):
            return False
        if "visual_tags" in facts and (
            not isinstance(facts["visual_tags"], list)
            or any(not isinstance(value, str) for value in facts["visual_tags"])
        ):
            return False
        if _invalid_visual_tags(facts) or not _review_note_is_justified(facts):
            return False
        if "visual_confidence" in facts:
            value = facts["visual_confidence"]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
                return False
        if any(
            field in facts and facts[field] not in values
            for field, values in VISUAL_FACT_ENUMS.items()
        ):
            return False
        special_visual = bool(
            facts.get("eye_effect") in {"blank", "glow", "stylized"}
            or facts.get("sweat_level") == "multiple"
            or facts.get("face_shadow") in {"upper", "full"}
            or facts.get("tears_level") in {"tear_drop", "streaming"}
        )
        if special_visual and expression_class not in {"special", "peak"}:
            return False
        if expression_class in {"special", "peak"} and frequency in {"default", "common"}:
            return False
        if (
            facts.get("eye_openness") == "closed"
            and facts.get("iris_color") != "not_visible"
        ):
            return False
        if float(facts.get("visual_confidence") or 0.0) < 0.65:
            return False
        if semantic_confidence is not None and float(semantic_confidence) < 0.65:
            return False
        backend = resolve_backend_label(
            item,
            face_id=str(item.get("face_id") or ""),
        )
        if backend.get("hard_blocks"):
            return False
    return True


_SYSTEM = """你在为视觉小说角色立绘建立供剧情选择的双层表情表。
你现在执行的是“两阶段标注”的第一阶段：你是视觉观察员，不是最终标签裁判。
第一层是客观面部构成：eyes 只写眼睛开合、视线、瞳色或特殊瞳孔状态，brows 只写眉形，mouth 只写嘴型与开合，
blush 和 tears 只按画面可见事实填写。闭眼与眯眼必须区分，闭嘴与张嘴必须区分；冷汗、脸部阴影、空白眼等
无法放进五个基础字段的可见记号写入 special_tags。看不清时明确写不可判断，不得猜测。
第二层是整体情绪、态度和适用的台词语境。客观构成与演出语义必须分别判断：不能因为闭眼就必然判为满足，
也不能因为张嘴就必然判为惊讶；同一种面部构成可以服务不同潜台词和反应阶段。
不要根据编号猜测，不要根据文件名猜测，也不要把服装、姿势或角色身份当成情绪。
同一批图片属于同一角色，重点比较它们之间的细微差别。
primary_emotion 使用简洁自然的中文，例如“轻微微笑”“不满”“尴尬”“惊讶”。
usage_hint_cn 写成一句简短的使用语境，例如适合怎样的台词、语气、反应或情绪阶段。
使用语境不是关键词触发规则，不得用是否闭眼、脸红、流泪等单一视觉现象决定是否使用。
不同 face_id 可以拥有完全相同的情绪和使用语境，不要为了区分编号强行制造差异。
visual_facts 是后端保存的原始观察记录；请完整填写所有枚举字段。eye_openness 记录眼睛开合，gaze 记录视线，
iris_color 只记录实际可见瞳色，eye_effect 记录发光/空白眼/特殊眼；brow_shape、mouth_openness、mouth_shape
分别记录眉形、嘴巴开合和嘴形。blush_level 必须区分角色底图自带的 base 与剧情强化的 expressive/strong；
tears_level 必须区分泪光、单滴泪和流泪；sweat_level 与 face_shadow 只按可见事实。闭眼时 iris_color 必须为
not_visible。空白眼只写入 eye_effect=blank；eye_openness 仍按画面填写实际开合状态。
看不清或遮挡时用 unknown/occluded 并降低 visual_confidence，不得硬猜。
visual_tags 只用于上述枚举确实无法表达的客观可见记号。不得在其中复述睁闭眼、眉形、嘴形、脸红、泪、汗或阴影，
不得写平静、开朗、治愈、悲伤等情绪词，也不得写人格、角色或用途；没有额外客观记号时必须返回空数组。
review_note_cn 只在使用 other/unknown/occluded 或确有像素边界需要人工复核时填写，否则必须为空字符串。
顶层 eyes/brows/mouth/blush/tears
是兼容字段，必须与 visual_facts 一致。primary_emotion、usage_hint_cn 仍需给出，但它们只是“语义候选”，
后端会结合骨骼事实、官方使用证据和人工覆盖进行最终校验；不要为了让候选看起来丰富而改写图片事实。
如果输出结构允许，还要填写：emotion_family（七类情绪族）、intensity（0-3）、
expression_class（base/accent/peak/special）、beat_fit（适合的剧情节拍）、
hold_policy（hold/short/flash）、delivery_fit、usage_frequency、semantic_confidence、
semantic_tags、special_tags 和 avoid_when_cn。
semantic_modes 用 1 到 3 个受控模式记录同一张脸确实成立的不同演出用途；每个模式分别给出简短中文名、
beat_fit、delivery_fit、intensity、semantic_tags 和 avoid_when_cn。它不是为了凑数量：只有一种用途时只写一个，
有倾听/轻声说明、认真报告/坚定宣告等不同潜台词时才拆开，不得改变视觉事实。
delivery_fit 必须明确这个表情适合 silent_reaction（无对话框反应）、listening（倾听）、
soft_speech（轻声说话）、normal_speech（普通说话）、emphatic_speech（强调说话）、shout（喊叫）中的哪些状态。
它不是嘴型检测：闭嘴也可能适合克制说话，张嘴也可能只是惊讶；必须结合整张脸判断。
usage_frequency 使用 default/common/conditional/rare。无神、人格切换、极端崩溃或高度特殊表情应为 rare，
不能因为它与默认脸接近就标成普通对话常用。semantic_confidence 只表示语义和适用范围判断的置信度，
不得与 visual_confidence 混为一项。
空白眼、发光/风格化眼效、多滴汗、上半脸/全脸阴影、单滴泪或流泪属于特殊视觉，expression_class 必须为
special 或 peak；special/peak 的 usage_frequency 不得为 default/common。
semantic_tags 最多选择三个受控标签，用来区分七类 emotion_family 内部的细义，例如 serious/assertive 与 angry、
blank 与 neutral、curious 与 resigned；不得写自由词或视觉零件。
这些字段描述剧情使用方式，不得改写成眉眼嘴等视觉零件清单。
置信度范围为 0 到 1；确实模糊时降低置信度，不要硬猜。"""


_SYSTEM += """
跨批次标注同一角色时，CHARACTER_LABEL_CACHE 是已经确认的同角色表情摘要。
必须比较缓存与当前图片，找出当前表情可见的最小语义差异，并让使用语境足以区分实际用途；不得仅换同义词制造区别。
如果画面确实等价，可以保持相同语义，但不得根据编号臆造差别。
beat_fit 只能使用给定枚举；自由中文检索词只能写入 search_terms_cn。
如果收到 OFFICIAL_USAGE_CONTEXT，它是后端整理出的官方使用证据，不是让你反向猜图的标签。
官方文本/动作只帮助判断该脸适合的剧情拍点；视觉字段必须逐格以图片为准。
如果 OFFICIAL_USAGE_PROFILE 显示某 face 的正常词汇台词占明显多数，说明它确实被频繁用于说话；
primary_emotion 和 usage_hint_cn 不得把它限定为“沉睡、入眠、熟睡”等只能睡眠时使用的表情。
这条规则只校准剧情用途，绝对不能据此把闭眼改成睁眼或反推任何视觉事实。
"""


def _needs_single_face_review(
    record: Mapping,
    confidence_threshold: float,
    *,
    require_backend_review: bool = False,
) -> bool:
    if record.get("failed"):
        return True
    if float(record.get("confidence") or 0.0) < confidence_threshold:
        return True
    backend = record.get("backend_resolution")
    if (
        require_backend_review
        and isinstance(backend, Mapping)
        and backend.get("review_required")
    ):
        return True
    emotion = str(record.get("primary_emotion") or "").strip()
    usage = usage_hint_cn(record)
    if not emotion or len(usage) < 4:
        return True
    return any(marker in usage for marker in _VISUAL_USAGE_MARKERS)


def make_vision_sheet(
    faces: Sequence[RenderedFace],
    *,
    cell_size: int = 384,
    columns: int = 2,
) -> tuple[bytes, list[str]]:
    """Build one fixed 3x3 comparison sheet with readable face IDs."""
    if columns not in (2, 3):
        raise ValueError("vision sheets must use two or three columns")
    max_faces = 4 if columns == 2 else 9
    if not 1 <= len(faces) <= max_faces:
        raise ValueError(f"vision sheets must contain between 1 and {max_faces} faces")
    if cell_size < 120:
        raise ValueError("vision sheet cells must be at least 120 pixels")
    ordered = sorted(faces, key=lambda face: face.face_id)
    face_ids = [face.face_id for face in ordered]
    sheet = Image.new(
        "RGB",
        (columns * cell_size, columns * cell_size),
        (54, 57, 63),
    )
    draw = ImageDraw.Draw(sheet)
    label_height = max(38, cell_size // 7)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(22, cell_size // 11))
    except OSError:
        font = ImageFont.load_default()
    for index, face in enumerate(ordered):
        x = (index % columns) * cell_size
        y = (index // columns) * cell_size
        tile = Image.new("RGB", (cell_size, cell_size), (226, 228, 232))
        head = Image.open(face.head_path).convert("RGBA")
        head.thumbnail(
            (cell_size - 20, cell_size - label_height - 18),
            Image.Resampling.LANCZOS,
        )
        tile.paste(
            head.convert("RGB"),
            ((cell_size - head.width) // 2, (cell_size - label_height - head.height) // 2),
            head.getchannel("A"),
        )
        sheet.paste(tile, (x, y))
        draw.rectangle(
            (x, y + cell_size - label_height, x + cell_size, y + cell_size),
            fill=(19, 25, 36),
        )
        label = f"FACE {face.face_id}"
        draw.text(
            (x + 12, y + cell_size - label_height + 5),
            label,
            fill=(255, 255, 255),
            font=font,
        )
    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=92, optimize=True)
    return buffer.getvalue(), face_ids


def label_face_images(
    provider,
    faces: Sequence[RenderedFace],
    *,
    batch_size: int = 4,
    batch_workers: int = 2,
    confidence_threshold: float = 0.6,
    semantic_hints: dict[str, dict] | None = None,
    official_usage: Mapping[str, Sequence[Mapping]] | None = None,
    official_profiles: Mapping[str, Mapping] | None = None,
    comparison_memory: bool = False,
    require_visual_facts: bool = False,
    require_semantic_profile: bool = False,
    require_semantic_modes: bool = False,
    max_attempts: int = 3,
    diagnostic_errors: bool = False,
    progress: Callable[[int, int, int, int], None] | None = None,
) -> list[dict]:
    """Label numbered 3x3 sheets concurrently, then review uncertain faces."""
    if not 1 <= batch_size <= 9:
        raise ValueError("batch_size must be between 1 and 9")
    if batch_workers < 1:
        raise ValueError("batch_workers must be at least 1")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    ordered = sorted(faces, key=lambda face: face.face_id)
    hints = semantic_hints or {}
    official = official_usage or {}
    usage_profiles = official_profiles or {}
    if not ordered:
        return []
    batches = [
        ordered[start : start + batch_size]
        for start in range(0, len(ordered), batch_size)
    ]
    initial_singletons = {
        batch[0].face_id for batch in batches if len(batch) == 1
    }
    required = set(VISION_SCHEMA["properties"]["items"]["items"]["required"])
    if require_visual_facts:
        required.add("visual_facts")
    if require_semantic_profile:
        required.update({
            "emotion_family", "intensity", "expression_class", "beat_fit",
            "hold_policy", "delivery_fit", "usage_frequency",
            "semantic_confidence", "semantic_tags", "avoid_when_cn",
        })
    if require_semantic_modes:
        required.add("semantic_modes")
    request_schema = deepcopy(VISION_SCHEMA)
    request_schema["properties"]["items"]["items"]["required"] = sorted(required)

    def request_batch(
        batch: Sequence[RenderedFace], prior_records: Sequence[Mapping] = ()
    ) -> list[dict]:
        sheet, expected = make_vision_sheet(batch, columns=2 if len(batch) <= 4 else 3)
        images = [("编号九宫格:" + ",".join(expected), sheet)]
        hint_lines = []
        for face in batch:
            labels = hints.get(face.face_id, {}).get("labels") or []
            if labels:
                hint_lines.append(
                    f"{face.face_id}: 骨骼部件名候选={','.join(map(str, labels))}"
                )
        user = (
            "请读取这张带 FACE 编号的九宫格，逐格标注以下 face_id，"
            "返回数量和编号必须完全一致："
            + "、".join(expected)
            + '\n必须只返回一个 JSON 对象，根键必须是 "items"。'
            + "items 数组中每项必须完整包含：face_id、primary_emotion、"
            + "usage_hint_cn、eyes、brows、mouth、blush、tears、confidence。"
            + "眼眉嘴等字段只写客观可见构成；瞳色变化和特殊瞳孔状态也必须记录；"
            + "visual_facts 的所有枚举字段必须填写；闭眼时 iris_color 必须为 not_visible；"
            + "泪光、单滴泪、流泪以及底图腮红和剧情强化脸红必须区分；"
            + "visual_tags 不得复述枚举事实或写入情绪/人格/用途，通常必须为空数组；"
            + "review_note_cn 仅在 unknown/occluded/other 或确需人工复核时填写；"
            + "整体情绪和使用语境必须另行判断，"
            + "不得由某一个面部特征直接推出。"
            + "必须填写 delivery_fit、usage_frequency、semantic_confidence；"
            + "必须填写 semantic_modes（1 到 3 个真实可用的演出语义模式），"
            + "同一张脸存在多种合理潜台词时分开记录，不要钉死成唯一情绪；"
            + "尤其区分无对话框反应、倾听、轻声/普通/强调说话和喊叫。"
        )
        if hint_lines:
            user += (
                "\n以下只是制作者命名提供的弱提示；与画面冲突时必须以画面为准：\n"
                + "\n".join(hint_lines)
            )
        usage_lines = []
        for face_id in expected:
            examples = official.get(face_id) or []
            if not examples:
                continue
            compact = []
            for example in examples:
                if not isinstance(example, Mapping):
                    continue
                text = str(example.get("text") or "").strip()
                value = f"‘{text}’" if text else "无对话框反应"
                extras = []
                emoticons = [str(item) for item in example.get("emoticons") or [] if str(item).strip()]
                actions = [str(item) for item in example.get("actions") or [] if str(item).strip()]
                if emoticons:
                    extras.append("气泡=" + "/".join(emoticons))
                if actions:
                    extras.append("动作=" + "/".join(actions))
                if example.get("closeup"):
                    extras.append("特写")
                if extras:
                    value += "（" + "、".join(extras) + "）"
                compact.append(value)
            if compact:
                usage_lines.append(f"{face_id}: " + "；".join(compact))
        if usage_lines:
            user += (
                "\n\nOFFICIAL_USAGE_CONTEXT（后端从官方语料筛选的弱证据，只用于辅助判断适用拍点）：\n"
                + "\n".join(usage_lines)
                + "\n这些语境不是视觉事实，不能据此推断眼睛、眉毛、嘴巴、瞳色或脸红。"
                "若图像与语境冲突，以图像为准，并降低 confidence 或标记需要复核；不要复制官方台词。"
            )
        profile_lines = []
        for face_id in expected:
            profile = usage_profiles.get(face_id)
            if not isinstance(profile, Mapping) or not profile.get("total_count"):
                continue
            profile_lines.append(
                f"{face_id}: 总计={int(profile.get('total_count') or 0)}，"
                f"正常词汇台词={int(profile.get('lexical_dialogue_count') or 0)}，"
                f"纯停顿/非词汇发声={int(profile.get('nonlexical_dialogue_count') or 0)}，"
                f"无对话框={int(profile.get('no_dialogue_count') or 0)}"
            )
        if profile_lines:
            user += (
                "\n\nOFFICIAL_USAGE_PROFILE（后端对全部适用官方证据的确定性计数）：\n"
                + "\n".join(profile_lines)
                + "\n它只校准 delivery_fit 和 usage_frequency，不覆盖图片事实。"
                "正常词汇台词为 0 且证据充足的脸，不得标成普通说话默认脸；"
                "正常词汇台词占明显多数的脸，不得把整体语义限定成只能沉睡、入眠或熟睡时使用。"
            )
        cache = compact_label_cache(prior_records)
        if comparison_memory and cache:
            user += (
                "\n\nCHARACTER_LABEL_CACHE（同一角色此前已完成的表情，仅用于比较和避免语义重复）：\n"
                + cache
                + "\n请明确区分当前图片与缓存中最接近的表情；不得只改同义词，也不得编造画面中不存在的差异。"
            )
        last_error: Exception | None = None
        items: list[dict] | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_user = user
            if attempt > 1:
                attempt_user += (
                    f"\n这是第 {attempt} 次校正请求。上次响应为空、结构错误或字段不完整。"
                    "不要使用 Markdown 说明，不要省略字段，严格按上述 JSON 结构重答。"
                )
                if last_error is not None:
                    attempt_user += (
                        "上次后端校验原因："
                        + str(last_error)
                        + "。请只修正冲突字段，不要改写无关视觉事实。"
                        "若原因为 special_visual_requires_special_class，必须保持特殊视觉事实，"
                        "并把 expression_class 改为 special 或 peak；"
                        "若原因为 special_class_frequency_too_common，必须把 usage_frequency "
                        "改为 conditional 或 rare。"
                    )
            try:
                response = provider.complete_json_vision(
                    _SYSTEM, images, attempt_user, request_schema
                )
                if not isinstance(response, dict):
                    raise ValueError("response root is not an object")
                candidate = response.get("items")
                if not isinstance(candidate, list):
                    raise ValueError('response root does not contain an "items" array')
                if not all(isinstance(item, dict) for item in candidate):
                    raise ValueError("items contains a non-object value")
                items = [_compact_vision_item(item) for item in candidate]
                if len(batch) == 1:
                    matches = [
                        item for item in items
                        if str(item.get("face_id") or "") == expected[0]
                    ]
                    detail = ""
                    if len(matches) != 1:
                        detail = "face_id_count_mismatch"
                    elif not _valid_vision_item(matches[0], required):
                        detail = _vision_item_validation_error(matches[0], required)
                    else:
                        reviewed_backend = resolve_backend_label(
                            matches[0],
                            official.get(expected[0]) or (),
                            usage_profiles.get(expected[0]) or {},
                        )
                        hard_blocks = reviewed_backend.get("hard_blocks") or []
                        if hard_blocks:
                            detail = "backend_hard_blocks=" + ",".join(
                                map(str, hard_blocks)
                            )
                    if detail:
                        raise ValueError(
                            "single-face response failed validation: " + detail
                        )
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if not bool(getattr(exc, "retryable", True)):
                    break
        occurrences: dict[str, list[dict]] = {face_id: [] for face_id in expected}
        for item in items or []:
            face_id = str(item.get("face_id") or "")
            if face_id in occurrences:
                occurrences[face_id].append(item)
        records = []
        for face in batch:
            matches = occurrences[face.face_id]
            if len(matches) != 1 or not _valid_vision_item(matches[0], required):
                failed = {
                    "face_id": face.face_id,
                    "head_path": str(face.head_path),
                    "failed": True,
                    "error": "vision_label_failed",
                }
                if diagnostic_errors and last_error is not None:
                    failed["error_detail"] = (
                        f"{type(last_error).__name__}: {last_error}"
                    )
                records.append(failed)
                continue
            record = dict(matches[0])
            record["face_id"] = face.face_id
            record["head_path"] = str(face.head_path)
            record["confidence"] = max(
                0.0, min(1.0, float(record.get("confidence") or 0.0))
            )
            record["visual_facts"] = normalize_visual_facts(record)
            record["backend_resolution"] = resolve_backend_label(
                record, official.get(face.face_id) or (),
                usage_profiles.get(face.face_id) or {},
            )
            records.append(record)
        return records

    completed = 0
    completed_batches = 0
    reviewed = 0
    state_lock = threading.Lock()
    if comparison_memory:
        results = []
        for batch in batches:
            records = request_batch(batch, results)
            results.extend(records)
            completed += len(records)
            completed_batches += 1
            if progress:
                progress(completed, len(ordered), completed_batches, reviewed)
    else:
        batch_results: dict[int, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=min(2, batch_workers, len(batches))) as executor:
            future_to_index = {
                executor.submit(request_batch, batch): index
                for index, batch in enumerate(batches)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                records = future.result()
                batch_results[index] = records
                with state_lock:
                    completed += len(records)
                    completed_batches += 1
                    if progress:
                        progress(completed, len(ordered), completed_batches, reviewed)
        results = [
            record
            for index in range(len(batches))
            for record in batch_results[index]
        ]

    duplicate_of = {}
    if comparison_memory:
        seen_semantics = {}
        for record in results:
            if record.get("failed"):
                continue
            key = (
                str(record.get("primary_emotion") or "").strip().casefold(),
                usage_hint_cn(record).casefold(),
            )
            if key in seen_semantics:
                duplicate_of[str(record["face_id"])] = seen_semantics[key]
            else:
                seen_semantics[key] = str(record["face_id"])
    face_by_id = {face.face_id: face for face in ordered}
    for index, record in enumerate(list(results)):
        face_id = str(record["face_id"])
        if record.get("failed") and face_id in initial_singletons:
            continue
        if (
            not _needs_single_face_review(
                record,
                confidence_threshold,
                require_backend_review=require_visual_facts,
            )
            and face_id not in duplicate_of
        ):
            continue
        comparison = [
            other for other in results if str(other.get("face_id")) != face_id
        ] if comparison_memory else []
        reviewed_record = request_batch([face_by_id[face_id]], comparison)[0]
        if not reviewed_record.get("failed"):
            reviewed_hard_blocks = (
                reviewed_record.get("backend_resolution", {}).get("hard_blocks") or []
                if isinstance(reviewed_record.get("backend_resolution"), Mapping) else []
            )
            if require_visual_facts and reviewed_hard_blocks:
                reviewed_record = {
                    "face_id": face_id,
                    "head_path": str(face_by_id[face_id].head_path),
                    "failed": True,
                    "error": "backend_validation_failed",
                    "error_detail": ",".join(map(str, reviewed_hard_blocks)),
                }
        original_hard_blocks = (
            record.get("backend_resolution", {}).get("hard_blocks") or []
            if isinstance(record.get("backend_resolution"), Mapping) else []
        )
        if (
            record.get("failed")
            or not reviewed_record.get("failed")
            or (require_visual_facts and original_hard_blocks)
        ):
            results[index] = reviewed_record
        if face_id in duplicate_of and not reviewed_record.get("failed"):
            reference = duplicate_of[face_id]
            reference_record = next(
                (item for item in results if str(item.get("face_id")) == reference), {}
            )
            reviewed_key = (
                str(reviewed_record.get("primary_emotion") or "").strip().casefold(),
                usage_hint_cn(reviewed_record).casefold(),
            )
            reference_key = (
                str(reference_record.get("primary_emotion") or "").strip().casefold(),
                usage_hint_cn(reference_record).casefold(),
            )
            if reviewed_key == reference_key:
                results[index]["near_duplicate_of"] = reference
        reviewed += 1
        if progress:
            progress(completed, len(ordered), completed_batches, reviewed)
    return sorted(results, key=lambda item: str(item["face_id"]))


def persist_visual_face_labels(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    model: str,
    labels: Iterable[dict],
) -> dict:
    """Upsert one model's labels while retaining user-authored overrides."""
    ident = str(ident)
    signature = str(spine_signature or "")
    outfit = str(outfit_key or "")
    model = str(model)
    source = f"vision:{model}"
    records = [normalize_semantic_payload(item) for item in labels]
    con.execute(
        """
        INSERT OR IGNORE INTO character_variant(ident,spine_signature,outfit_key,spine)
        VALUES (?, ?, ?, '')
        """,
        (ident, signature, outfit),
    )
    completed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    for item in records:
        face_id = str(item["face_id"])
        if item.get("failed"):
            continue
        primary = str(item.get("primary_emotion") or "").strip()
        secondary = [
            str(value).strip()
            for value in item.get("secondary_emotions") or []
            if str(value).strip()
        ]
        manual_row = con.execute(
            """
            SELECT manual_json FROM face_visual_label
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND manual_json IS NOT NULL AND manual_json!='{}'
            ORDER BY updated_at DESC, model
            LIMIT 1
            """,
            (ident, signature, outfit, face_id),
        ).fetchone()
        manual = _safe_json_object(manual_row["manual_json"] if manual_row else "{}")
        con.execute(
            """
            INSERT INTO face_visual_label
              (ident,spine_signature,outfit_key,face_id,model,primary_emotion,
               secondary_json,valence,arousal,eyes,brows,mouth,blush,tears,
               confidence,description_cn,semantic_json,observation_json,backend_json,
               head_path,reviewed,manual_json,version,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ident,spine_signature,outfit_key,face_id,model) DO UPDATE SET
              primary_emotion=excluded.primary_emotion,
              secondary_json=excluded.secondary_json,
              valence=excluded.valence,
              arousal=excluded.arousal,
              eyes=excluded.eyes,
              brows=excluded.brows,
              mouth=excluded.mouth,
              blush=excluded.blush,
              tears=excluded.tears,
              confidence=excluded.confidence,
              description_cn=excluded.description_cn,
              semantic_json=excluded.semantic_json,
              observation_json=excluded.observation_json,
              backend_json=excluded.backend_json,
              head_path=excluded.head_path,
              version=face_visual_label.version+1,
              updated_at=excluded.updated_at
            """,
            (
                ident,
                signature,
                outfit,
                face_id,
                model,
                primary,
                json.dumps(secondary, ensure_ascii=False),
                str(item.get("valence") or ""),
                str(item.get("arousal") or ""),
                str(item.get("eyes") or ""),
                str(item.get("brows") or ""),
                str(item.get("mouth") or ""),
                int(bool(item.get("blush"))),
                int(bool(item.get("tears"))),
                float(item.get("confidence") or 0.0),
                usage_hint_cn(item),
                json.dumps(
                    {key: item[key] for key in _SEMANTIC_FIELDS if key in item},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                json.dumps(
                    normalize_visual_facts(item),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                json.dumps(
                    resolve_backend_label(
                        item,
                        official_profile=(item.get("backend_resolution") or {}).get(
                            "official_evidence", {}
                        ),
                        ident=ident,
                        face_id=face_id,
                    ),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                str(item.get("head_path") or ""),
                int(bool(manual)),
                json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
                1,
                completed_at,
            ),
        )
        effective_primary = str(manual.get("primary_emotion", primary))
        has_manual_usage, manual_usage = _manual_usage_hint(manual)
        effective_usage = (
            manual_usage if has_manual_usage else usage_hint_cn(item)
        )
        effective_semantics = selection_semantics(
            effective_primary, effective_usage
        )
        con.execute(
            """
            DELETE FROM face_evidence
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND source=?
            """,
            (ident, signature, outfit, face_id, source),
        )
        con.execute(
            """
            INSERT INTO face_evidence
              (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
            VALUES (?,?,?,?,?,?,?,?,0)
            """,
            (
                ident,
                signature,
                outfit,
                face_id,
                source,
                json.dumps(item, ensure_ascii=False),
                effective_semantics,
                effective_semantics,
            ),
        )
    con.commit()
    failures = []
    for item in records:
        if not item.get("failed"):
            continue
        failure = {
            "face_id": str(item["face_id"]),
            "error": str(item.get("error") or "vision_label_failed"),
        }
        if item.get("error_detail"):
            failure["detail"] = str(item["error_detail"])
        failures.append(failure)
    return {
        "saved_count": len(records) - len(failures),
        "failed_count": len(failures),
        "failures": failures,
        "completed_at": completed_at,
    }


def refresh_visual_face_preview_paths(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    faces: Iterable[RenderedFace],
) -> int:
    """Point every saved model row at the latest rendered head preview."""
    scope = (
        str(ident),
        str(spine_signature or ""),
        str(outfit_key or ""),
    )
    updated_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    changed = 0
    for face in faces:
        head_path = str(Path(face.head_path).resolve())
        cursor = con.execute(
            """
            UPDATE face_visual_label
            SET head_path=?, version=version+1, updated_at=?
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND COALESCE(head_path, '')<>?
            """,
            (
                head_path,
                updated_at,
                *scope,
                str(face.face_id),
                head_path,
            ),
        )
        changed += max(0, int(cursor.rowcount or 0))
    con.commit()
    return changed


def _safe_json_object(value) -> dict:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _visual_label_record(row) -> dict:
    try:
        secondary = json.loads(row["secondary_json"] or "[]")
    except (TypeError, ValueError):
        secondary = []
    if not isinstance(secondary, list):
        secondary = []
    hint = str(row["description_cn"] or "")
    try:
        semantic = normalize_semantic_payload(_safe_json_object(row["semantic_json"]))
    except (KeyError, TypeError):
        semantic = {}
    try:
        observation = _safe_json_object(row["observation_json"])
    except (KeyError, TypeError):
        observation = {}
    try:
        backend = _safe_json_object(row["backend_json"])
    except (KeyError, TypeError):
        backend = {}
    ai = {
        "primary_emotion": str(row["primary_emotion"] or ""),
        "secondary_emotions": [str(value) for value in secondary],
        "valence": str(row["valence"] or ""),
        "arousal": str(row["arousal"] or ""),
        "eyes": str(row["eyes"] or ""),
        "brows": str(row["brows"] or ""),
        "mouth": str(row["mouth"] or ""),
        "blush": bool(row["blush"]),
        "tears": bool(row["tears"]),
        "confidence": max(0.0, min(1.0, float(row["confidence"] or 0.0))),
        "description_cn": str(row["description_cn"] or ""),
        "usage_hint_cn": hint,
    }
    ai.update(semantic)
    ai["semantic_level"] = "rich" if semantic else (
        "basic" if ai["primary_emotion"] or ai["usage_hint_cn"] else "unknown"
    )
    manual = {
        key: value
        for key, value in _safe_json_object(row["manual_json"]).items()
        if key in _EDITABLE_FACE_FIELDS
    }
    has_manual_hint, manual_hint = _manual_usage_hint(manual)
    if has_manual_hint:
        manual["usage_hint_cn"] = manual_hint
        manual["description_cn"] = manual_hint
    effective = normalize_semantic_payload({**ai, **manual})
    effective_hint = manual_hint if has_manual_hint else hint
    effective["usage_hint_cn"] = effective_hint
    effective["description_cn"] = effective_hint
    effective_observation = dict(observation)
    if isinstance(manual.get("visual_facts"), Mapping):
        effective_observation.update(manual["visual_facts"])
    return {
        "ident": str(row["ident"]),
        "spine_signature": str(row["spine_signature"]),
        "outfit_key": str(row["outfit_key"]),
        "face_id": str(row["face_id"]),
        "model": str(row["model"]),
        "ai": ai,
        "observation": observation,
        "effective_observation": effective_observation,
        "backend": backend,
        "manual": manual,
        "effective": effective,
        "head_path": str(row["head_path"] or ""),
        "reviewed": bool(manual),
        "version": max(1, int(row["version"] or 1)),
        "updated_at": str(row["updated_at"] or ""),
    }


def list_visual_face_labels(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
) -> list[dict]:
    """Return one current, editable visual record for every face ID."""
    rows = assetdb.effective_visual_label_rows(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
    )
    records: dict[str, dict] = {}
    for row in rows:
        face_id = str(row["face_id"])
        records.setdefault(face_id, _visual_label_record(row))
    return [records[face_id] for face_id in sorted(records)]


def _validate_manual_patch(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("标注内容必须是对象")
    unknown = set(patch) - _EDITABLE_FACE_FIELDS
    if unknown:
        raise ValueError("不支持的标注字段：" + "、".join(sorted(unknown)))
    if (
        "usage_hint_cn" in patch
        and "description_cn" in patch
        and patch["usage_hint_cn"] != patch["description_cn"]
    ):
        raise ValueError("usage_hint_cn 与 description_cn 不能冲突")
    normalized = dict(patch)
    if "usage_hint_cn" in normalized:
        normalized["description_cn"] = normalized.pop("usage_hint_cn")
    clean = {}
    for key, value in normalized.items():
        if value is None:
            clean[key] = None
        elif key == "visual_facts":
            if not isinstance(value, Mapping):
                raise ValueError("标注字段 visual_facts 必须是对象")
            unknown_visual = set(value) - set(VISUAL_FACT_FIELDS)
            if unknown_visual:
                raise ValueError("visual_facts 包含未知字段：" + "、".join(sorted(unknown_visual)))
            clean[key] = {
                field: normalized_value
                for field, normalized_value in normalize_visual_facts(
                    {"visual_facts": value}
                ).items()
                if field in value
            }
        elif key == "semantic_modes":
            modes = normalize_semantic_modes(value)
            if not modes:
                raise ValueError("标注字段 semantic_modes 必须包含 1 到 3 个合法模式")
            clean[key] = modes
        elif key in {"blush", "tears"}:
            if not isinstance(value, bool):
                raise ValueError(f"标注字段 {key} 必须是布尔值")
            clean[key] = value
        elif key in {
            "secondary_emotions", "beat_fit", "delivery_fit", "semantic_tags",
            "special_tags", "search_terms_cn",
        }:
            if not isinstance(value, list):
                raise ValueError(f"标注字段 {key} 必须是数组")
            clean[key] = [str(item).strip() for item in value if str(item).strip()]
        elif key == "intensity":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
                raise ValueError("标注字段 intensity 必须是 0 到 3 的整数")
            clean[key] = value
        elif key == "semantic_confidence":
            if (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or not 0 <= float(value) <= 1
            ):
                raise ValueError("标注字段 semantic_confidence 必须是 0 到 1 的数字")
            clean[key] = float(value)
        else:
            clean[key] = str(value).strip()
    if any(
        value not in CONTROLLED_BEAT_FIT
        for value in clean.get("beat_fit") or []
        if value is not None
    ):
        raise ValueError("标注字段 beat_fit 包含未受控的节拍值")
    if any(
        value not in CONTROLLED_DELIVERY_FIT
        for value in clean.get("delivery_fit") or []
    ):
        raise ValueError("标注字段 delivery_fit 包含未受控的台词状态")
    if any(
        value not in CONTROLLED_SEMANTIC_TAGS
        for value in clean.get("semantic_tags") or []
    ) or len(clean.get("semantic_tags") or []) > 3:
        raise ValueError("标注字段 semantic_tags 无效或超过三个")
    if (
        "usage_frequency" in clean
        and clean["usage_frequency"] not in CONTROLLED_USAGE_FREQUENCY
    ):
        raise ValueError("标注字段 usage_frequency 无效")
    return clean


def update_visual_face_label(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    face_id: str,
    patch: dict,
    expected_version: int,
) -> dict:
    """Apply a manual override with optimistic locking and return merged data."""
    clean = _validate_manual_patch(patch)
    scope = (
        str(ident), str(spine_signature or ""), str(outfit_key or ""), str(face_id)
    )
    row = con.execute(
        """
        SELECT * FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
        ORDER BY updated_at DESC, confidence DESC, model
        LIMIT 1
        """,
        scope,
    ).fetchone()
    if row is None:
        raise KeyError("表情标注不存在")
    if int(row["version"] or 1) != int(expected_version):
        raise ValueError("标注版本已更新，请刷新后重试")
    manual = _safe_json_object(row["manual_json"])
    for key, value in clean.items():
        if value is None:
            manual.pop(key, None)
        else:
            manual[key] = value
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = con.execute(
        """
        UPDATE face_visual_label
        SET manual_json=?, reviewed=?, version=version+1, updated_at=?
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
          AND model=? AND version=?
        """,
        (
            json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
            int(bool(manual)),
            updated_at,
            *scope,
            str(row["model"]),
            int(expected_version),
        ),
    )
    if cursor.rowcount != 1:
        con.rollback()
        raise ValueError("标注版本已更新，请刷新后重试")
    con.execute(
        """
        UPDATE face_visual_label
        SET manual_json=?, reviewed=?, version=version+1, updated_at=?
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
          AND model!=?
        """,
        (
            json.dumps(manual, ensure_ascii=False, separators=(",", ":")),
            int(bool(manual)),
            updated_at,
            *scope,
            str(row["model"]),
        ),
    )
    has_manual_usage, manual_usage = _manual_usage_hint(manual)
    model_rows = con.execute(
        """
        SELECT * FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
        """,
        scope,
    ).fetchall()
    for model_row in model_rows:
        effective_primary = str(
            manual.get("primary_emotion", model_row["primary_emotion"] or "")
        )
        effective_usage = (
            manual_usage
            if has_manual_usage
            else str(model_row["description_cn"] or "")
        )
        effective_semantics = selection_semantics(
            effective_primary, effective_usage
        )
        semantic = normalize_semantic_payload(
            _safe_json_object(model_row["semantic_json"])
        )
        observation = _safe_json_object(model_row["observation_json"])
        manual_visual = manual.get("visual_facts")
        if isinstance(manual_visual, Mapping):
            observation = {**observation, **manual_visual}
        effective_item = {
            **semantic,
            "primary_emotion": effective_primary,
            "usage_hint_cn": effective_usage,
            "eyes": str(manual.get("eyes", model_row["eyes"] or "")),
            "brows": str(manual.get("brows", model_row["brows"] or "")),
            "mouth": str(manual.get("mouth", model_row["mouth"] or "")),
            "blush": bool(manual.get("blush", model_row["blush"])),
            "tears": bool(manual.get("tears", model_row["tears"])),
            "confidence": float(model_row["confidence"] or 0.0),
            "visual_facts": observation,
            **{
                key: value for key, value in manual.items()
                if key not in {
                    "description_cn", "usage_hint_cn", "visual_facts",
                }
            },
        }
        previous_backend = _safe_json_object(model_row["backend_json"])
        official_profile = assetdb.official_face_usage_profiles(
            con,
            ident=str(ident),
            face_ids=[str(face_id)],
            spine_signature=str(spine_signature or ""),
            outfit_key=str(outfit_key or ""),
        ).get(str(face_id)) or previous_backend.get("official_evidence") or {}
        backend = resolve_backend_label(
            effective_item,
            official_profile=official_profile,
            ident=str(ident),
            face_id=str(face_id),
        )
        con.execute(
            """
            UPDATE face_visual_label SET backend_json=?
            WHERE ident=? AND spine_signature=? AND outfit_key=?
              AND face_id=? AND model=?
            """,
            (
                json.dumps(backend, ensure_ascii=False, separators=(",", ":")),
                *scope, str(model_row["model"]),
            ),
        )
        con.execute(
            """
            UPDATE face_evidence
            SET label=?, label_cn=?
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
              AND source=?
            """,
            (
                effective_semantics,
                effective_semantics,
                *scope,
                f"vision:{model_row['model']}",
            ),
        )
    con.commit()
    refreshed = con.execute(
        """
        SELECT * FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=? AND model=?
        """,
        (*scope, str(row["model"])),
    ).fetchone()
    return _visual_label_record(refreshed)


def make_contact_sheet(
    faces: Sequence[RenderedFace],
    output: str | Path,
    *,
    columns: int = 6,
    cell_size: int = 224,
) -> Path:
    """Create a review sheet with a stable face ID under each cropped head."""
    ordered = sorted(faces, key=lambda face: face.face_id)
    rows = (len(ordered) + columns - 1) // columns
    label_height = 30
    sheet = Image.new(
        "RGB",
        (columns * cell_size, rows * (cell_size + label_height)),
        (42, 42, 46),
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, face in enumerate(ordered):
        x = (index % columns) * cell_size
        y = (index // columns) * (cell_size + label_height)
        head = Image.open(face.head_path).convert("RGBA")
        head.thumbnail((cell_size, cell_size), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (cell_size, cell_size), (220, 220, 220))
        tile.paste(
            head.convert("RGB"),
            ((cell_size - head.width) // 2, (cell_size - head.height) // 2),
            head.getchannel("A"),
        )
        sheet.paste(tile, (x, y))
        draw.text((x + 8, y + cell_size + 7), face.face_id, fill="white", font=font)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="JPEG", quality=92)
    return destination
