from __future__ import annotations

from typing import Any

from .errors import ProductionError


_STAGE_COMMANDS = {"enter", "exit", "move", "stage", "auto", "camera", "camera_hold", "fx", "hl"}

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "recommended": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 220},
        "story_beat": {
            "type": "string",
            "enum": ["reveal", "emotional_peak", "quiet_turn", "memory", "transition", "not_recommended"],
        },
        "image_prompt": {"type": "string", "maxLength": 1800},
        "reference_note": {"type": "string", "maxLength": 220},
        "continuity_notes": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 140}},
        "generation_notes": {"type": "array", "maxItems": 5, "items": {"type": "string", "maxLength": 140}},
    },
    "required": [
        "recommended", "reason", "story_beat", "image_prompt", "reference_note",
        "continuity_notes", "generation_notes",
    ],
}

_SYSTEM = """You are a visual-novel CG consultant. The author has already selected one exact range of cards.
Do not suggest another position, do not change the range, do not select a CG asset, and do not create any files.
Your task is only to help the author decide whether this selected range deserves a CG and, if so, provide one concise,
directly usable Chinese image-generation prompt for GPT Image. Use coherent natural language rather than tag piles.
The image prompt should state: medium and aspect ratio, characters' dramatic action, environment, composition/camera,
lighting, mood, and the most important story clue. Keep it positive and concrete. Do not write a negative-prompt section,
do not mention copying an original image, and do not name living artists. If a character reference image is supplied later,
say only that its character design should be followed; do not invent detailed appearance from the script.
For an ordinary exchange that does not earn a full-screen illustration, set recommended=false and leave image_prompt empty.
Return JSON only."""


def advise(provider: Any, *, cards: list[dict[str, Any]], start_card_id: str, end_card_id: str) -> dict[str, Any]:
    start = str(start_card_id or "").strip()
    end = str(end_card_id or "").strip()
    positions = {str(card.get("card_id") or ""): index for index, card in enumerate(cards)}
    if start not in positions or end not in positions or positions[start] > positions[end]:
        raise ProductionError("cg_range_invalid", "请选择有效的 CG 起止卡片")
    span = cards[positions[start] : positions[end] + 1]
    if not any(card.get("kind") == "line" for card in span):
        raise ProductionError("cg_dialogue_required", "CG 范围内至少需要一条台词")
    blocked = next(
        (
            card for card in span
            if card.get("kind") == "dir"
            and str((card.get("current") or {}).get("cmd") or "").casefold() in _STAGE_COMMANDS
        ),
        None,
    )
    if blocked:
        raise ProductionError(
            "cg_range_has_stage_command",
            "该范围含有立绘、镜头或舞台指令；请先缩小到适合 CG 的台词范围",
            details={"card_id": str(blocked.get("card_id") or "")},
        )
    user = (
        f"Author-selected range: {start} to {end}\n"
        "Cards:\n" + "\n".join(_card_line(card) for card in span)
    )
    result = provider.complete_json(
        _SYSTEM,
        "The author controls all CG placement. Give advice for this selected range only.",
        user,
        _SCHEMA,
    )
    if not isinstance(result, dict):
        raise ProductionError("cg_advice_invalid", "AI 没有返回可用的 CG 制作建议", status=502)
    if not result.get("recommended"):
        result["image_prompt"] = ""
    return result


def _card_line(card: dict[str, Any]) -> str:
    current = card.get("current") if isinstance(card.get("current"), dict) else {}
    card_id = str(card.get("card_id") or "")
    kind = str(card.get("kind") or "")
    if kind == "line":
        return f"[{card_id}] {str(current.get('who') or '')}: {str(current.get('text') or '')[:280]}"
    if kind == "scene":
        return f"[{card_id}] Scene: {str(current.get('title') or card.get('raw') or '')[:160]}"
    return f"[{card_id}] {kind}: {str(card.get('raw') or '')[:160]}"
