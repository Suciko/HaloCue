# -*- coding: utf-8 -*-
"""Vision-assisted semantic labels for registered custom backgrounds."""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


@dataclass(frozen=True)
class BackgroundLabels:
    label: str = ""
    description: str = ""
    place: str = ""
    indoor_outdoor: str = ""
    time: str = ""
    weather: str = ""
    season: str = ""
    mood: str = ""
    tags: str = ""


_TEXT_LIMITS = {
    "label": 120,
    "description": 500,
    "place": 160,
    "indoor_outdoor": 40,
    "time": 80,
    "weather": 80,
    "season": 80,
    "mood": 160,
}
_WINDOWS_PATH = re.compile(r"(?:^|\s)[A-Za-z]:[\\/]")
_UNC_PATH = re.compile(r"(?:^|\s)\\\\[^\\\s]+[\\/]")


def _safe_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > limit:
        return ""
    if text.startswith(("/", "\\\\")) or _WINDOWS_PATH.search(text) or _UNC_PATH.search(text):
        return ""
    return text


def _safe_tags(value: Any) -> str:
    if isinstance(value, str):
        raw = re.split(r"[,，、;；\n]+", value)
    elif isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = []
    tags = []
    seen = set()
    for item in raw[:24]:
        tag = _safe_text(item, 80)
        folded = tag.casefold()
        if tag and folded not in seen:
            tags.append(tag)
            seen.add(folded)
        if len(tags) >= 12:
            break
    return ", ".join(tags)


def normalize_background_labels(value: object) -> dict:
    source = value if isinstance(value, dict) else {}
    labels = BackgroundLabels(
        **{
            field: _safe_text(source.get(field), limit)
            for field, limit in _TEXT_LIMITS.items()
        },
        tags=_safe_tags(source.get("tags")),
    )
    return asdict(labels)


_BACKGROUND_LABEL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **{
            field: {"type": "string"}
            for field in _TEXT_LIMITS
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
        },
    },
    "required": [*_TEXT_LIMITS, "tags"],
}


def _vision_jpeg(image_path: Path) -> bytes:
    with Image.open(image_path) as source:
        image = ImageOps.contain(
            ImageOps.exif_transpose(source).convert("RGB"),
            (1280, 1280),
            Image.Resampling.LANCZOS,
        )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        return output.getvalue()


def label_background(provider, image_path: Path) -> dict:
    labels = provider.complete_json_vision(
        (
            "你是剧情游戏背景素材标注器。只描述画面中能直接观察到的环境，"
            "不要猜测作品名、角色、剧情或文件来源。严格返回符合 schema 的 JSON。"
        ),
        [("background", _vision_jpeg(Path(image_path)))],
        (
            "请给这张无人物背景图生成简洁中文标注：名称、客观描述、地点、"
            "室内外、时间、天气、季节、氛围和最多十二个去重关键词。"
            "不确定的字段返回空字符串。"
        ),
        _BACKGROUND_LABEL_SCHEMA,
    )
    return normalize_background_labels(labels)
