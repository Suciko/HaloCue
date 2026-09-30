from __future__ import annotations

import re
from typing import Any


_CORE_NAMES_ZH = {
    "BG_Black": "黑屏",
    "BG_White": "白屏",
    "BG_GameDevRoom": "游戏开发部活动室",
    "BG_ShoppingDistrict": "购物街",
    "BG_MainOffice": "主办公室",
    "BG_MainOffice_Night": "主办公室 · 夜晚",
    "BG_MainOffice_Night2": "主办公室 · 夜晚 2",
    "BG_TrinityTerrace": "三一露台",
    "BG_Karaoke": "卡拉 OK 房",
    "BG_SpecialOperationRoom": "特别作战室",
    "BG_BigSisterRoom": "大姐姐房间",
    "BG_BusStation": "公交车站",
    "BG_BusInside": "公交车内",
    "BG_DestructionFront": "破坏前线",
    "BG_View_Sky2_Night": "天空景观 · 夜晚",
    "BG_EriduCityTown": "艾利都城镇",
    "BG_MilleniumCampus": "千年校园",
}

_TOKEN_NAMES_ZH = {
    "abydos": "阿拜多斯",
    "abandoned": "废弃",
    "warehouse": "仓库",
    "council": "对策委员会",
    "corridor": "走廊",
    "train": "火车",
    "plaza": "广场",
    "desert": "沙漠",
    "ruin": "遗迹",
    "residence": "住宅",
    "gehenna": "格黑娜",
    "arius": "阿里乌斯",
    "millennium": "千年",
    "schale": "夏莱",
    "dorm": "宿舍",
    "dormitory": "宿舍",
    "student": "学生",
    "lounge": "休息室",
    "black": "黑屏",
    "white": "白屏",
    "game": "游戏",
    "dev": "开发部",
    "room": "活动室",
    "shopping": "购物",
    "district": "街区",
    "main": "主",
    "office": "办公室",
    "night": "夜晚",
    "day": "白天",
    "morning": "清晨",
    "dawn": "黎明",
    "evening": "傍晚",
    "sunset": "黄昏",
    "rain": "雨天",
    "snow": "雪天",
    "trinity": "三一",
    "terrace": "露台",
    "karaoke": "卡拉 OK",
    "special": "特别",
    "operation": "作战",
    "big": "大",
    "sister": "姐姐",
    "bus": "公交车",
    "station": "车站",
    "inside": "内部",
    "destruction": "破坏",
    "front": "前线",
    "view": "景观",
    "sky": "天空",
    "eridu": "艾利都",
    "city": "城市",
    "town": "城镇",
    "millenium": "千年",
    "campus": "校园",
    "classroom": "教室",
    "school": "学校",
    "rainy": "雨天",
    "street": "街道",
    "park": "公园",
    "library": "图书馆",
    "lab": "实验室",
    "laboratory": "实验室",
    "cafeteria": "食堂",
    "hall": "大厅",
    "hallway": "走廊",
    "rooftop": "天台",
    "roof": "屋顶",
    "beach": "海滩",
    "forest": "森林",
    "hospital": "医院",
    "class": "教室",
}


def _has_chinese(value: Any) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def _split_resource_key(key: str) -> list[str]:
    body = re.sub(r"^BG_", "", str(key or "").strip(), flags=re.I)
    body = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", body)
    body = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", body)
    return [part for part in re.split(r"[_\s-]+", body) if part]


def _translated_key(key: str) -> str:
    tokens = _split_resource_key(key)
    translated: list[str] = []
    for token in tokens:
        lower = token.casefold()
        value = _TOKEN_NAMES_ZH.get(lower)
        if value:
            translated.append(value)
        elif token.isdigit():
            translated.append(token)
        else:
            return ""
    if not translated:
        return ""
    # Keep the result readable for combinations such as MainOffice_Night.
    return " · ".join(translated) if len(translated) > 2 else "".join(translated)


def background_display_name(key: str, metadata: dict[str, Any] | None = None) -> str:
    """Return a Chinese semantic name while preserving the AA key separately."""
    metadata = metadata if isinstance(metadata, dict) else {}
    for value in (
        metadata.get("name_zh_cn"),
        metadata.get("label_zh_cn"),
        metadata.get("label_cn"),
        metadata.get("place_cn"),
        metadata.get("label"),
        metadata.get("place"),
    ):
        if _has_chinese(value):
            return str(value).strip()
    canonical = _CORE_NAMES_ZH.get(str(key))
    if canonical:
        return canonical
    return _translated_key(str(key)) or str(metadata.get("label") or key)


def background_name_metadata(key: str, metadata: dict[str, Any] | None = None) -> dict[str, str]:
    name = background_display_name(key, metadata)
    result = {"name": name}
    if _has_chinese(name):
        result["name_zh_cn"] = name
    return result
