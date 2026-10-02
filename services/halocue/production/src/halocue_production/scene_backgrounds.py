"""Read-only, explainable background ranking from scene headings and annotations.

Dialogue is deliberately excluded: mentioning another place is not a scene change.
No probabilities, generated prose, persistent state, or resource-key invention.
"""

from __future__ import annotations

import re
from typing import Any

TIME = {
    "夜间": ("night", "夜间", "夜晚", "晚上", "深夜", "午夜", "雨夜", "雪夜"),
    "白天": ("day", "daytime", "白天", "日间", "上午", "中午", "下午", "午后"),
    "黄昏": ("sunset", "evening", "黄昏", "傍晚", "夕阳", "日落"),
    "清晨": ("dawn", "morning", "清晨", "黎明", "拂晓"),
}
SPACE = {
    "室内": ("indoor", "inside", "interior", "室内", "屋内"),
    "室外": ("outdoor", "outside", "exterior", "室外", "户外"),
}
WEATHER = {
    "雨天": ("rain", "rainy", "雨天", "下雨", "暴雨", "雨夜"),
    "雪天": ("snow", "snowy", "雪天", "下雪", "雪夜"),
    "晴天": ("sunny", "clear", "晴天", "晴朗"),
}
PLACES = {
    "社团室": ("社团室", "社团活动室", "clubroom", "club room"),
    "教室": ("教室", "classroom"),
    "办公室": ("办公室", "office"),
    "天台": ("天台", "屋顶", "rooftop"),
    "操场": ("操场", "playground"),
    "走廊": ("走廊", "corridor"),
    "街道": ("街道", "街头", "street"),
    "公园": ("公园", "park"),
    "车站": ("车站", "站台", "station"),
    "海滩": ("海滩", "沙滩", "beach"),
}
DIMENSIONS = {
    "time": ("时间", TIME),
    "space": ("室内外", SPACE),
    "weather": ("天气", WEATHER),
    "place": ("地点", PLACES),
}


def categories(text: Any, aliases: dict) -> set[str]:
    value = str(text or "").casefold()

    def contains(term):
        if term.isascii():
            return bool(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", value))
        return term in value

    return {name for name, words in aliases.items() if any(contains(word) for word in words)}


def scene_context(cards: list[dict], scene_id: str, overrides: dict[str, str]) -> dict:
    position = next(
        (
            i
            for i, card in enumerate(cards)
            if card.get("card_id") == scene_id and card.get("kind") == "scene"
        ),
        None,
    )
    if position is None:
        from .errors import ProductionError

        raise ProductionError("scene_not_found", "场景已变化，请关闭素材选择后重新打开", status=404)
    scene = cards[position]
    title = str((scene.get("current") or {}).get("title") or "未命名场景")
    current = ""
    for card in cards[position + 1 :]:
        if card.get("kind") in {"scene", "title"}:
            break
        fields = card.get("current") or {}
        if card.get("kind") == "dir" and fields.get("cmd") == "bg":
            current = str(fields.get("arg") or "")
            break
    requirements, sources, ambiguous = {}, {}, []
    for key, (label, aliases) in DIMENSIONS.items():
        explicit = str(overrides.get(key) or "").strip()[:100]
        explicit = (
            {"雨": "雨天", "雪": "雪天", "晴": "晴天"}.get(explicit, explicit)
            if key == "weather"
            else explicit
        )
        values = categories(explicit or title, aliases)
        if explicit:
            requirements[key] = next(iter(values)) if len(values) == 1 else explicit
            sources[key] = "本次筛选"
        elif len(values) == 1:
            requirements[key] = next(iter(values))
            sources[key] = "场景标题"
        elif len(values) > 1:
            ambiguous.append(f"标题包含多个{label}，未自动设定")
    return {
        "scene_card_id": scene_id,
        "title": title,
        "current_background": current,
        "requirements": requirements,
        "sources": sources,
        "notes": ambiguous,
        "read_only": True,
    }


def assess_background(item: dict, context: dict) -> dict:
    matches, conflicts, unknown = [], [], []
    requirements = context["requirements"]
    for field, wanted in requirements.items():
        label, aliases = DIMENSIONS[field]
        raw = item.get("indoor_outdoor" if field == "space" else field)
        candidates = categories(raw, aliases)
        if field == "place" and raw:
            # Exact/contained explicit location text is evidence; unknown synonyms
            # are not a hard conflict unless both sides have known categories.
            if str(wanted).casefold() in str(raw).casefold():
                matches.append(f"{label}：{wanted}")
                continue
        if len(candidates) > 1:
            unknown.append(f"{label}未确认：素材包含多个标记（{' / '.join(sorted(candidates))}）")
        elif wanted in candidates:
            matches.append(f"{label}：{wanted}")
        elif candidates and wanted in aliases:
            conflicts.append(
                f"{label}冲突：需要{wanted}，素材标记为{' / '.join(sorted(candidates))}"
            )
        else:
            unknown.append(f"{label}未确认：需要{wanted}，素材标记不足")
    if item.get("has_fixed_characters") is True:
        conflicts.append("画面含固定人物，不是纯环境背景")
    if item.get("dialogue_suitable") is False:
        conflicts.append("素材已标记为不适合普通对话")
    status = "conflict" if conflicts else "unknown" if unknown or not requirements else "match"
    return {
        "status": status,
        "matches": matches,
        "conflicts": conflicts,
        "unknown": unknown,
        "current": item.get("key") == context.get("current_background"),
    }


def rank_items(items: list[dict], context: dict) -> list[dict]:
    enriched = [{**item, "scene_match": assess_background(item, context)} for item in items]
    order = {"match": 0, "unknown": 1, "conflict": 2}
    return sorted(
        enriched,
        key=lambda item: (
            order[item["scene_match"]["status"]],
            -len(item["scene_match"]["matches"]),
            len(item["scene_match"]["conflicts"]),
            str(item.get("name") or ""),
            str(item["key"]),
        ),
    )
