from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


SCENE_READINESS_SCHEMA_VERSION = "scene-readiness/1.0"


def build_scene_readiness(
    *,
    provider: Mapping[str, Any],
    skill_runtime: Mapping[str, Any],
    runtime_character_cards: Sequence[Mapping[str, Any]],
    missing_runtime_character_cards: Sequence[str],
    explicit_character_selection: bool,
    context_ready: bool = True,
) -> dict[str, Any]:
    """Build the stable, author-facing readiness contract for one scene."""

    missing_cards = [str(item) for item in missing_runtime_character_cards]
    context_ready = bool(context_ready)
    provider_ready = bool(provider.get("can_call_model")) and not bool(
        provider.get("is_simulation")
    )
    skill_ready = skill_runtime.get("status") == "ready"
    runtime_cards_ready = bool(runtime_character_cards) and not missing_cards

    blocking_reasons: list[dict[str, Any]] = []
    if not context_ready:
        blocking_reasons.append(
            {
                "code": "scene_context_not_ready",
                "message": "本场上下文尚未完整装配。",
                "details": {},
            }
        )
    if not runtime_cards_ready:
        if missing_cards:
            message = "缺少经来源校验的运行时人物卡：" + "、".join(missing_cards)
        elif explicit_character_selection:
            message = "本场没有选择已确认的人物卡。"
        else:
            message = "本场没有可用的已确认运行时人物卡。"
        blocking_reasons.append(
            {
                "code": "runtime_character_cards_not_ready",
                "message": message,
                "details": {
                    "missing_runtime_character_cards": missing_cards,
                    "runtime_character_card_count": len(runtime_character_cards),
                },
            }
        )
    if not skill_ready:
        blocking_reasons.append(
            {
                "code": "ba_writing_skill_not_ready",
                "message": "BA Writing Skill 规则源不完整。",
                "details": {
                    "status": skill_runtime.get("status"),
                    "missing_files": list(skill_runtime.get("missing_files") or []),
                },
            }
        )
    if not provider_ready:
        blocking_reasons.append(
            {
                "code": "writing_provider_not_ready",
                "message": "尚未配置可调用真实模型的写作 Provider。",
                "details": {
                    "kind": provider.get("kind"),
                    "is_simulation": bool(provider.get("is_simulation")),
                    "can_call_model": bool(provider.get("can_call_model")),
                },
            }
        )

    provider_context_ready = context_ready and skill_ready and runtime_cards_ready
    can_run = provider_context_ready and provider_ready
    reason = (
        blocking_reasons[0]["message"]
        if blocking_reasons
        else "本场上下文、运行时人物卡、Skill 与真实模型 Provider 均已就绪。"
    )
    return {
        "schema_version": SCENE_READINESS_SCHEMA_VERSION,
        "can_run": can_run,
        "context_ready": context_ready,
        "provider_ready": provider_ready,
        "skill_ready": skill_ready,
        "runtime_cards_ready": runtime_cards_ready,
        "blocking_reasons": blocking_reasons,
        # Compatibility fields for existing clients and backend gates.
        "fake_provider": "ready",
        "real_ba_writing": (
            "ready_for_provider" if provider_context_ready else "blocked"
        ),
        "skill_source": "ready" if skill_ready else "blocked",
        "missing_runtime_character_cards": missing_cards,
        "reason": reason,
    }
