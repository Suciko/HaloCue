# -*- coding: utf-8 -*-
"""Strict visual semantics for AA backgrounds and CG-like scene assets."""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageOps

import assetdb
from llm import LLMError


RESOURCE_CHANNELS = frozenset({"background", "popup"})
VISUAL_KINDS = frozenset({"background", "cg", "title_card", "effect", "unknown"})
LABEL_STATUSES = frozenset({"pending", "candidate", "ready", "failed", "manual_locked"})
MAIN_CATEGORIES = frozenset({
    "campus", "street", "interior", "nature", "commercial", "transport",
    "event", "abstract", "unknown",
})
MAIN_CATEGORY_CN = {
    "campus": "校园",
    "street": "街道",
    "interior": "室内",
    "nature": "自然",
    "commercial": "商业",
    "transport": "交通",
    "event": "活动",
    "abstract": "抽象",
    "unknown": "未分类",
}
INDOOR_OUTDOOR = frozenset({"indoor", "outdoor", "mixed", "unknown"})
TIME_BUCKETS = frozenset({"dawn", "day", "sunset", "night", "unknown"})
STAGING_CAPACITIES = frozenset({"none", "single", "pair", "group", "unknown"})
SHOT_TYPES = frozenset({"establishing", "wide", "medium", "closeup", "detail", "graphic", "unknown"})
DISPLAY_POLICIES = frozenset({"hold", "short", "flash"})
SETTING_SCOPES = frozenset({"generic", "specific", "mixed", "not_applicable", "unknown"})
REUSE_SCOPES = frozenset({"exclusive", "cross_affiliation", "generic", "not_applicable", "unknown"})
REUSE_SCOPE_CN = {
    "exclusive": "专属",
    "cross_affiliation": "有限跨阵营复用",
    "generic": "通用",
    "not_applicable": "不适用",
    "unknown": "待复核",
}
AFFILIATION_KEYS = frozenset({
    "schale", "federal_student_council", "du", "kivotos_general",
    "abydos", "gehenna", "trinity", "millennium", "hyakkiyako",
    "shanhaijing", "red_winter", "arius", "srt", "valkyrie",
    "highlander", "wildhunt", "kronos", "odyssey", "decagrammaton",
    "other_official",
})
AFFILIATION_CN = {
    "schale": "夏莱",
    "federal_student_council": "联邦学生会",
    "du": "D.U.地区",
    "kivotos_general": "基沃托斯通用区域",
    "abydos": "阿拜多斯",
    "gehenna": "格黑娜",
    "trinity": "崔尼蒂",
    "millennium": "千年",
    "hyakkiyako": "百鬼夜行",
    "shanhaijing": "山海经",
    "red_winter": "赤冬",
    "arius": "阿里乌斯",
    "srt": "SRT",
    "valkyrie": "瓦尔基里",
    "highlander": "海兰德",
    "wildhunt": "狂猎",
    "kronos": "克洛诺斯",
    "odyssey": "奥德赛",
    "decagrammaton": "十字神名",
    "other_official": "其他明确阵营或区域",
}
AFFILIATION_EVIDENCE = frozenset({
    "visual_emblem", "visual_text", "visual_architecture",
    "visual_decoration", "asset_key", "reference", "legacy_category",
})
AFFILIATION_KEY_TOKENS = {
    "schale": ("schale",),
    "federal_student_council": ("federalstudentcouncil", "studentcouncil"),
    "du": ("d_u", "districtdu"),
    "abydos": ("abydos",),
    "gehenna": ("gehenna",),
    "trinity": ("trinity",),
    "millennium": ("millennium", "millenium"),
    "hyakkiyako": ("hyakkiyako", "hyakkayouran"),
    "shanhaijing": ("shanhaijing",),
    "red_winter": ("redwinter",),
    "arius": ("arius",),
    "srt": ("_srt", "srt_"),
    "valkyrie": ("valkyrie",),
    "highlander": ("highlander",),
    "wildhunt": ("wildhunt",),
    "kronos": ("kronos",),
    "odyssey": ("odyssey",),
    "decagrammaton": ("decagrammaton",),
}

_TEXT_LIMITS = {
    "label": 120,
    "description": 500,
    "subcategory": 80,
    "place": 160,
    "weather": 80,
    "season": 80,
    "mood": 160,
    "usage_hint_cn": 300,
    "avoid_when_cn": 300,
    "narrative_action_cn": 300,
    "character_description_cn": 300,
    "affiliation_hint_cn": 300,
    "reuse_hint_cn": 300,
}
_ENUM_FIELDS = {
    "visual_kind": VISUAL_KINDS,
    "main_category": MAIN_CATEGORIES,
    "indoor_outdoor": INDOOR_OUTDOOR,
    "time": TIME_BUCKETS,
    "staging_capacity": STAGING_CAPACITIES,
    "shot_type": SHOT_TYPES,
    "display_policy": DISPLAY_POLICIES,
    "setting_scope": SETTING_SCOPES,
    "reuse_scope": REUSE_SCOPES,
}


@dataclass(frozen=True)
class SceneVisionInput:
    item_id: str
    asset_key: str
    resource_channel: str
    image_path: Path
    source_kind: str
    content_sha256: str
    source_category: str = ""
    original_filename: str = ""
    reference_description: str = ""


class SceneBatchValidationError(ValueError):
    """The model did not return exactly one valid row per requested image."""


def _safe_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] if text else ""


def _safe_terms(value: Any, *, limit: int = 12) -> list[str]:
    raw = value if isinstance(value, (list, tuple)) else []
    result = []
    seen = set()
    for item in raw:
        text = _safe_text(item, 80)
        folded = text.casefold()
        if text and folded not in seen:
            result.append(text)
            seen.add(folded)
        if len(result) >= limit:
            break
    return result


def normalize_scene_labels(value: object) -> dict:
    source = value if isinstance(value, Mapping) else {}
    result = {
        field: _safe_text(source.get(field), limit)
        for field, limit in _TEXT_LIMITS.items()
    }
    for field, allowed in _ENUM_FIELDS.items():
        raw = str(source.get(field) or "").strip()
        fallback = "short" if field == "display_policy" else "unknown"
        result[field] = raw if raw in allowed else fallback
    result["main_category_cn"] = MAIN_CATEGORY_CN[result["main_category"]]
    result["tags"] = _safe_terms(source.get("tags"))
    result["search_terms_cn"] = _safe_terms(source.get("search_terms_cn"), limit=16)
    result["affiliation_keys"] = [
        key for key in _safe_terms(source.get("affiliation_keys"), limit=6)
        if key in AFFILIATION_KEYS
    ]
    result["affiliation_names_cn"] = [
        AFFILIATION_CN[key] for key in result["affiliation_keys"]
    ]
    result["compatible_affiliation_keys"] = [
        key for key in _safe_terms(source.get("compatible_affiliation_keys"), limit=8)
        if key in AFFILIATION_KEYS
    ]
    result["compatible_affiliation_names_cn"] = [
        AFFILIATION_CN[key] for key in result["compatible_affiliation_keys"]
    ]
    result["reuse_scope_cn"] = REUSE_SCOPE_CN[result["reuse_scope"]]
    result["affiliation_evidence"] = [
        key for key in _safe_terms(source.get("affiliation_evidence"), limit=4)
        if key in AFFILIATION_EVIDENCE
    ]
    result["has_fixed_characters"] = source.get("has_fixed_characters") is True
    result["dialogue_suitable"] = source.get("dialogue_suitable") is True
    count = source.get("visible_character_count")
    result["visible_character_count"] = (
        count if isinstance(count, int) and not isinstance(count, bool) and 0 <= count <= 20
        else 0
    )
    confidence = source.get("confidence")
    result["confidence"] = (
        float(confidence)
        if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
        and math.isfinite(float(confidence)) and 0 <= float(confidence) <= 1
        else 0.0
    )
    affiliation_confidence = source.get("affiliation_confidence")
    result["affiliation_confidence"] = (
        float(affiliation_confidence)
        if isinstance(affiliation_confidence, (int, float))
        and not isinstance(affiliation_confidence, bool)
        and math.isfinite(float(affiliation_confidence))
        and 0 <= float(affiliation_confidence) <= 1
        else 0.0
    )
    if result["setting_scope"] in {"generic", "not_applicable", "unknown"}:
        result["affiliation_confidence"] = 0.0
    if result["setting_scope"] == "generic":
        result["reuse_scope"] = "generic"
        result["compatible_affiliation_keys"] = []
        result["compatible_affiliation_names_cn"] = []
    elif result["setting_scope"] == "not_applicable":
        result["reuse_scope"] = "not_applicable"
        result["compatible_affiliation_keys"] = []
        result["compatible_affiliation_names_cn"] = []
    elif result["setting_scope"] == "unknown":
        result["reuse_scope"] = "unknown"
        result["compatible_affiliation_keys"] = []
        result["compatible_affiliation_names_cn"] = []
    result["reuse_scope_cn"] = REUSE_SCOPE_CN[result["reuse_scope"]]
    if result["visual_kind"] != "background":
        result["dialogue_suitable"] = False
        result["staging_capacity"] = "none"
        result["setting_scope"] = "not_applicable"
        result["affiliation_keys"] = []
        result["affiliation_names_cn"] = []
        result["affiliation_evidence"] = []
        result["affiliation_confidence"] = 0.0
        result["reuse_scope"] = "not_applicable"
        result["reuse_scope_cn"] = REUSE_SCOPE_CN["not_applicable"]
        result["compatible_affiliation_keys"] = []
        result["compatible_affiliation_names_cn"] = []
        result["reuse_hint_cn"] = "非普通背景，不参与跨场景复用判断"
    if result["affiliation_names_cn"]:
        affiliation_path = "、".join(result["affiliation_names_cn"])
    elif result["setting_scope"] == "generic":
        affiliation_path = "通用"
    elif result["setting_scope"] == "not_applicable":
        affiliation_path = "非地点资源"
    else:
        affiliation_path = "待复核"
    result["category_path_cn"] = " / ".join(filter(None, (
        affiliation_path,
        result["main_category_cn"],
        result["subcategory"],
    )))
    return result


SCENE_VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "visual_kind": {"type": "string", "enum": sorted(VISUAL_KINDS)},
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                    "main_category": {"type": "string", "enum": sorted(MAIN_CATEGORIES)},
                    "subcategory": {"type": "string"},
                    "place": {"type": "string"},
                    "indoor_outdoor": {"type": "string", "enum": sorted(INDOOR_OUTDOOR)},
                    "time": {"type": "string", "enum": sorted(TIME_BUCKETS)},
                    "weather": {"type": "string"},
                    "season": {"type": "string"},
                    "mood": {"type": "string"},
                    "staging_capacity": {"type": "string", "enum": sorted(STAGING_CAPACITIES)},
                    "has_fixed_characters": {"type": "boolean"},
                    "visible_character_count": {"type": "integer", "minimum": 0, "maximum": 20},
                    "dialogue_suitable": {"type": "boolean"},
                    "usage_hint_cn": {"type": "string"},
                    "avoid_when_cn": {"type": "string"},
                    "narrative_action_cn": {"type": "string"},
                    "character_description_cn": {"type": "string"},
                    "shot_type": {"type": "string", "enum": sorted(SHOT_TYPES)},
                    "display_policy": {"type": "string", "enum": sorted(DISPLAY_POLICIES)},
                    "setting_scope": {"type": "string", "enum": sorted(SETTING_SCOPES)},
                    "reuse_scope": {"type": "string", "enum": sorted(REUSE_SCOPES)},
                    "affiliation_keys": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(AFFILIATION_KEYS)},
                        "maxItems": 6,
                    },
                    "affiliation_evidence": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(AFFILIATION_EVIDENCE)},
                        "maxItems": 4,
                    },
                    "affiliation_hint_cn": {"type": "string"},
                    "compatible_affiliation_keys": {
                        "type": "array",
                        "items": {"type": "string", "enum": sorted(AFFILIATION_KEYS)},
                        "maxItems": 8,
                    },
                    "reuse_hint_cn": {"type": "string"},
                    "affiliation_confidence": {
                        "type": "number", "minimum": 0, "maximum": 1,
                    },
                    "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
                    "search_terms_cn": {
                        "type": "array", "items": {"type": "string"}, "maxItems": 16,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "item_id", "visual_kind", "label", "description",
                    "main_category", "subcategory", "place", "indoor_outdoor",
                    "time", "weather", "season", "mood", "staging_capacity",
                    "has_fixed_characters", "visible_character_count",
                    "dialogue_suitable", "usage_hint_cn", "avoid_when_cn",
                    "narrative_action_cn", "character_description_cn", "shot_type",
                    "display_policy", "tags", "confidence",
                    "search_terms_cn",
                    "setting_scope", "affiliation_keys", "affiliation_evidence",
                    "affiliation_hint_cn", "reuse_scope",
                    "compatible_affiliation_keys", "reuse_hint_cn",
                    "affiliation_confidence",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


_SYSTEM = """你在为视觉小说自动演出系统标注真实存在的场景图片。
必须先按画面内容判断 visual_kind：
- background：可重复承载对白和角色立绘的环境，不能有占据叙事主体的固定角色或一次性事件动作；
- cg：固定人物、事件动作或一次性剧情构图是画面主体；
- title_card：以标题、字幕、标志、署名或 UI 信息为主体；
- effect：抽象光效、转场、纹理或无法作为具体空间的效果图；
- unknown：确实无法判断。

resource_channel 是 AA 的真实调用通道，只是辅助信息，绝不能用它代替视觉判断。
所以 background 通道中也可能是 cg，popup 通道通常是 cg 但仍须看图确认。
不要根据文件名猜角色名、剧情名或地点专名；认不出角色时只写人数和外观特征。
普通背景要说明地点、时段、氛围、可容纳的立绘数量以及是否适合持续对白。
CG 要说明画面动作、人物外观、构图和适合出现的剧情瞬间；不得标为适合持续对白。
main_category 应优先从 campus、street、interior、nature、commercial、transport、event、abstract 中选择。
它描述画面的主要空间或叙事用途，不是文件目录：人物或事件型 CG 通常按 event 判断，物件特写、纯图形与难以归入具体空间的画面可按 abstract 判断。
只有画面本身无法辨认、确实不能归入上述任一类时才使用 unknown。
还要判断 setting_scope，它描述场景是否属于明确阵营或区域，而不只限于学院：
- generic：通用场景，没有可靠的专属归属，affiliation_keys 必须为空；
- specific：明确属于夏莱、联邦学生会、D.U.、某学院或其他单一场景体系，至少返回一个 affiliation_key；
- mixed：画面明确同时涉及两个或更多阵营，至少返回两个 affiliation_key；
- not_applicable：纯效果、标题卡或与地点归属无关的物件图，affiliation_keys 必须为空；
- unknown：画面与上下文都不足以判断，affiliation_keys 必须为空。
setting_scope 只描述画面中的物理地点、固定布景或区域归属，绝不描述出场人物属于哪个学院或组织。
不能因为认出了某个角色，就把通用街道、祭典、海滩或室内归给该角色所属阵营；mixed 也不能由多个阵营的角色同框推出。
明确地点命名、完整资源 token、校徽、招牌和文字属于强证据；没有标志时，稳定且独特的建筑、材质、纹样、家具、配色与空间结构组合也可以作为风格证据标为 specific。
风格判断必须依据一组相互支持的场景特征，不能只凭单一颜色、普通欧式/日式/科技感或人物服装推断。
例如圣三一与格黑娜可以凭各自稳定的学院建筑和装饰体系区分，但普通教堂、普通工业设施仍应保持 generic。
人物特写或物件特写若没有可识别的地点布景，应使用 not_applicable，而不是人物或物件的所属阵营。
asset_key、原文件名和参考描述可作为归属证据；Schale、Trinity、Gehenna、Millennium 等明确完整 token 可以采用，模糊缩写不能单独定案。
affiliation_evidence 只能记录实际使用过的 visual_emblem、visual_text、visual_architecture、visual_decoration、asset_key、reference、legacy_category。
affiliation_hint_cn 用中文说明物理场景依据；affiliation_confidence 单独表示归属判断置信度，明确标识通常高于风格推断。
原始归属与实际复用范围必须分开判断。affiliation_keys 表示资源的原始地点、美术体系或可追溯来源；reuse_scope 表示自动演出能否把画面用于其他地点：
- exclusive：校徽、文字、专属地标或高度唯一的布景使它只能用于原归属，compatible_affiliation_keys 为空；
- cross_affiliation：仍有原归属风格，但适合少数其他阵营，列出 compatible_affiliation_keys；
- generic：虽然资源名或风格可能有原始归属，但画面没有妨碍复用的专属元素，可作为通用场景，compatible_affiliation_keys 为空；
- not_applicable：效果、标题、人物或物件特写等不适合做地点复用判断；
- unknown：无法判断复用范围。
文件名带学院或组织名只能证明原始归属，不能单独证明 exclusive。复用范围必须以最终画面中实际可见的文字、校徽、地标和风格独特程度判断。
compatible_affiliation_keys 只能列出 affiliation_keys 之外的额外兼容对象，两个数组不得重复同一个 key。
只有 visual_kind=background 的普通背景需要判断复用范围；cg、title_card、effect 必须返回 reuse_scope=not_applicable。
search_terms_cn 只填写便于人类搜索的简洁中文近义词、场所词和画面元素，不放资源 key，不作为程序枚举或硬过滤依据。
search_terms_cn 与 tags 都不得填写仅凭看图猜测的角色名、剧情名或活动专名；阵营名已由 affiliation_keys 单独提供，也不要重复塞进搜索词。
subcategory 必须填写简洁的中文子分类，例如“教室”“走廊”“天台”“祭典群像”，不要填写英文分类词。
自由中文语义由你根据画面决定，不使用关键词模板机械套用。不确定字段留空或选择 unknown。
每张图必须原样返回给定 item_id，严格返回符合 schema 的 JSON。"""


def _vision_jpeg(path: Path) -> bytes:
    with Image.open(path) as source:
        image = ImageOps.contain(
            ImageOps.exif_transpose(source).convert("RGB"),
            (1280, 1280),
            Image.Resampling.LANCZOS,
        )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()


def _validate_batch_response(response: object, targets: Sequence[SceneVisionInput]) -> list[dict]:
    if not isinstance(response, Mapping) or not isinstance(response.get("items"), list):
        raise SceneBatchValidationError("response.items must be an array")
    expected = {target.item_id for target in targets}
    rows = response["items"]
    ids = [row.get("item_id") for row in rows if isinstance(row, Mapping)]
    if len(rows) != len(targets) or len(ids) != len(rows):
        raise SceneBatchValidationError("batch row count mismatch")
    if len(ids) != len(set(ids)):
        raise SceneBatchValidationError("duplicate item_id")
    if set(ids) != expected:
        raise SceneBatchValidationError("missing or unknown item_id")
    normalized = []
    targets_by_id = {target.item_id: target for target in targets}
    for row in rows:
        labels = normalize_scene_labels(row)
        target = targets_by_id[row["item_id"]]
        if not labels["label"] or not labels["description"]:
            raise SceneBatchValidationError(f"empty core semantics for {row['item_id']}")
        subcategory = labels["subcategory"]
        if subcategory and not any("\u4e00" <= char <= "\u9fff" for char in subcategory):
            raise SceneBatchValidationError(
                f"subcategory must use Chinese for {row['item_id']}"
            )
        scope = labels["setting_scope"]
        affiliations = labels["affiliation_keys"]
        evidence = labels["affiliation_evidence"]
        if scope in {"generic", "not_applicable", "unknown"} and affiliations:
            raise SceneBatchValidationError(
                f"{scope} must not include affiliations for {row['item_id']}"
            )
        if scope == "specific" and not affiliations:
            raise SceneBatchValidationError(
                f"specific scope requires affiliation for {row['item_id']}"
            )
        if scope == "mixed" and len(affiliations) < 2:
            raise SceneBatchValidationError(
                f"mixed scope requires multiple affiliations for {row['item_id']}"
            )
        if scope in {"specific", "mixed"} and not evidence:
            raise SceneBatchValidationError(
                f"affiliation requires evidence for {row['item_id']}"
            )
        if "asset_key" in evidence:
            folded_key = target.asset_key.replace("-", "_").casefold()
            if not any(
                token in folded_key
                for affiliation in affiliations
                for token in AFFILIATION_KEY_TOKENS.get(affiliation, ())
            ):
                evidence = [item for item in evidence if item != "asset_key"]
                labels["affiliation_evidence"] = evidence
                if scope in {"specific", "mixed"} and not evidence:
                    raise SceneBatchValidationError(
                        f"affiliation has no verifiable evidence for {row['item_id']}"
                    )
        style_only = evidence and set(evidence) <= {
            "visual_architecture", "visual_decoration", "legacy_category",
        }
        if style_only and labels["affiliation_confidence"] > 0.89:
            labels["affiliation_confidence"] = 0.89
        if scope in {"specific", "mixed"} and labels["affiliation_confidence"] < 0.65:
            raise SceneBatchValidationError(
                f"affiliation confidence too low for {row['item_id']}"
            )
        if scope in {"generic", "not_applicable"} and labels["affiliation_confidence"] != 0:
            raise SceneBatchValidationError(
                f"{scope} affiliation confidence must be zero for {row['item_id']}"
            )
        reuse_scope = labels["reuse_scope"]
        compatible = labels["compatible_affiliation_keys"]
        if reuse_scope == "cross_affiliation" and not compatible:
            raise SceneBatchValidationError(
                f"cross affiliation requires compatible affiliations for {row['item_id']}"
            )
        if reuse_scope != "cross_affiliation" and compatible:
            raise SceneBatchValidationError(
                f"{reuse_scope} must not include compatible affiliations for {row['item_id']}"
            )
        if set(compatible) & set(affiliations):
            raise SceneBatchValidationError(
                f"compatible affiliations duplicate origin for {row['item_id']}"
            )
        normalized.append({"item_id": row["item_id"], **labels})
    by_id = {row["item_id"]: row for row in normalized}
    return [by_id[target.item_id] for target in targets]


def label_scene_images(
    provider,
    targets: Sequence[SceneVisionInput],
    *,
    retries: int = 3,
) -> list[dict]:
    if not 1 <= len(targets) <= 4:
        raise ValueError("scene batches must contain one to four images")
    if len({target.item_id for target in targets}) != len(targets):
        raise ValueError("scene batch item IDs must be unique")
    images = [(target.item_id, _vision_jpeg(target.image_path)) for target in targets]
    context = []
    for target in targets:
        reference = _safe_text(target.reference_description, 500)
        context.append(
            f"- item_id={target.item_id}; resource_channel={target.resource_channel}; "
            f"asset_key={target.asset_key}; original_filename="
            f"{target.original_filename or target.image_path.name}; "
            f"source_category={target.source_category or '(none)'}; "
            f"reference_description={reference or '(none)'}"
        )
    user = (
        f"请逐一比较并标注这 {len(targets)} 张图片。文件名和参考描述仅作辅助，"
        "冲突时以像素为准。\n" + "\n".join(context)
    )
    last_error: Exception | None = None
    for attempt in range(max(1, int(retries))):
        retry_note = "" if attempt == 0 else (
            "\n上次返回未通过整批校验。必须恰好返回每个预期 item_id 一次，不能遗漏、重复或新增。"
        )
        try:
            response = provider.complete_json_vision(
                _SYSTEM + retry_note, images, user, SCENE_VISION_SCHEMA
            )
            return _validate_batch_response(response, targets)
        except (LLMError, SceneBatchValidationError) as exc:
            last_error = exc
            if isinstance(exc, LLMError) and not exc.retryable:
                break
    raise SceneBatchValidationError(f"scene batch failed after retries: {last_error}") from last_error


def _manual_locked(con, target: SceneVisionInput) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM scene_visual_label
        WHERE resource_channel=? AND LOWER(asset_key)=LOWER(?)
          AND content_sha256=?
          AND (status='manual_locked'
            OR TRIM(COALESCE(manual_json,'')) NOT IN ('','{}','null'))
        LIMIT 1
        """,
        (target.resource_channel, target.asset_key, target.content_sha256),
    ).fetchone()
    return row is not None


def persist_scene_label(
    con,
    *,
    target: SceneVisionInput,
    model: str,
    labels: Mapping,
    status: str = "ready",
    evidence: Mapping | None = None,
) -> bool:
    if target.resource_channel not in RESOURCE_CHANNELS:
        raise ValueError("invalid resource channel")
    if status not in LABEL_STATUSES - {"manual_locked"}:
        raise ValueError("invalid automatic label status")
    if _manual_locked(con, target):
        return False
    normalized = normalize_scene_labels(labels)
    timestamp = datetime.now(timezone.utc).isoformat()
    with con:
        con.execute(
            """
            INSERT INTO scene_visual_label
              (resource_channel,asset_key,content_sha256,source_kind,model,
               visual_kind,label_json,evidence_json,confidence,status,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(resource_channel,asset_key,content_sha256,model) DO UPDATE SET
              source_kind=excluded.source_kind,
              visual_kind=excluded.visual_kind,
              label_json=excluded.label_json,
              evidence_json=excluded.evidence_json,
              confidence=excluded.confidence,
              status=excluded.status,
              updated_at=excluded.updated_at
            WHERE scene_visual_label.status<>'manual_locked'
              AND TRIM(COALESCE(scene_visual_label.manual_json,'')) IN ('','{}','null')
            """,
            (
                target.resource_channel, target.asset_key, target.content_sha256,
                target.source_kind, str(model or "").strip(), normalized["visual_kind"],
                json.dumps(normalized, ensure_ascii=False),
                json.dumps({
                    "source_category": target.source_category,
                    **dict(evidence or {}),
                }, ensure_ascii=False),
                normalized["confidence"], status, timestamp,
            ),
        )
        by = f"vision:{model}"
        if target.resource_channel == "background":
            con.execute(
                "INSERT OR IGNORE INTO bg(name,hash) VALUES(?,?)",
                (target.asset_key, int(assetdb.bg_id(target.asset_key))),
            )
            if status == "ready":
                con.execute(
                    """
                    UPDATE bg SET label=?,place=?,time=?,mood=?,tags=?,labeled_by=?
                    WHERE name=? AND COALESCE(labeled_by,'')<>'manual'
                    """,
                    (
                        normalized["label"], normalized["indoor_outdoor"],
                        normalized["time"], normalized["mood"],
                        ",".join(normalized["tags"]), by, target.asset_key,
                    ),
                )
        elif status == "ready":
            con.execute(
                """
                INSERT INTO popup(name,label,descr,chars,tags,labeled_by)
                VALUES(?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
                  label=CASE WHEN popup.labeled_by='manual' THEN popup.label ELSE excluded.label END,
                  descr=CASE WHEN popup.labeled_by='manual' THEN popup.descr ELSE excluded.descr END,
                  chars=CASE WHEN popup.labeled_by='manual' THEN popup.chars ELSE excluded.chars END,
                  tags=CASE WHEN popup.labeled_by='manual' THEN popup.tags ELSE excluded.tags END,
                  labeled_by=CASE WHEN popup.labeled_by='manual' THEN popup.labeled_by ELSE excluded.labeled_by END
                """,
                (
                    target.asset_key, normalized["label"], normalized["description"],
                    normalized["character_description_cn"],
                    ",".join(normalized["tags"]), by,
                ),
            )
    return True


def scene_label_from_row(row: Mapping) -> dict:
    labels = json.loads(row["label_json"] or "{}")
    manual = json.loads(row["manual_json"] or "{}")
    evidence = json.loads(row["evidence_json"] or "{}")
    merged = normalize_scene_labels({**labels, **manual})
    return {
        "asset_key": str(row["asset_key"]),
        "resource_channel": str(row["resource_channel"]),
        "source_kind": str(row["source_kind"]),
        "source_category": str(evidence.get("source_category") or ""),
        "status": str(row["status"]),
        **merged,
    }


def generator_background_keys(index: Mapping) -> set[str]:
    """Return real background keys that may be used for sustained AA scenes.

    Unlabeled keys retain the legacy fallback. Once a ready visual record says
    an image is CG, a title card, or an effect, it leaves both prompt exposure
    and the runtime allowlist.
    """
    keys = {str(value) for value in (index.get("bg") or {})}
    scene_groups = index.get("scene_labels") or {}
    records = scene_groups.get("background") if isinstance(scene_groups, Mapping) else {}
    if not isinstance(records, Mapping):
        return keys
    by_folded = {
        str(key).casefold(): value
        for key, value in records.items()
        if isinstance(value, Mapping)
    }
    usable = set()
    for key in keys:
        record = by_folded.get(key.casefold())
        if record is None:
            usable.add(key)
            continue
        if (
            str(record.get("status") or "ready") in {"ready", "manual_locked"}
            and record.get("visual_kind") == "background"
            and record.get("dialogue_suitable") is not False
        ):
            usable.add(key)
    return usable
