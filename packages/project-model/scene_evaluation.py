"""Evaluate one canonical scene into descriptor, timeline, and diagnostics."""

from __future__ import annotations

from typing import Any

from project_model import build_aa_scene_descriptor, migrate_project
from render_timeline import build_render_timeline
from scene_performance import build_scene_performance
from scene_events import scene_event_registry


SCENE_EVALUATION_SCHEMA_VERSION = "scene-evaluation/1.5"


def _character_motion_diagnostics(descriptor: dict[str, Any]) -> list[dict[str, str]]:
    slots: dict[int, str] = {}
    for actor in descriptor.get("initial_actors", []):
        if not isinstance(actor, dict) or actor.get("state") != "visible":
            continue
        slot = actor.get("slot")
        character_id = actor.get("character_id")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and 1 <= slot <= 5
            and isinstance(character_id, str)
            and character_id
        ):
            slots[slot] = character_id
    diagnostics: list[dict[str, str]] = []
    for event in descriptor.get("events", []):
        if not isinstance(event, dict):
            continue
        kind = event.get("kind")
        slot = event.get("slot")
        if kind == "enter":
            character_id = event.get("character_id")
            if (
                isinstance(slot, int)
                and not isinstance(slot, bool)
                and isinstance(character_id, str)
                and character_id
            ):
                slots[slot] = character_id
            continue
        if kind == "exit":
            if isinstance(slot, int) and not isinstance(slot, bool):
                slots.pop(slot, None)
            continue
        if kind != "character-motion":
            continue
        occupied = slots.get(slot) if isinstance(slot, int) and not isinstance(slot, bool) else None
        character_id = event.get("character_id")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and 1 <= slot <= 5
            and occupied
            and (not character_id or character_id == occupied)
        ):
            continue
        diagnostics.append(
            {
                "code": "scene.character_motion_target_unavailable",
                "severity": "error",
                "path": f"event:{event.get('event_id', '')}",
                "message": f"角色动作 {event.get('event_id', '')} 必须位于目标角色入场之后、退场之前。",
            }
        )
    return diagnostics


def evaluate_scene(
    project: dict[str, Any],
    scene_id: str,
    *,
    frame_rate: int = 30,
) -> dict[str, Any]:
    """Return the shared render intermediate result for one scene.

    The descriptor and timeline remain independently versioned contracts. This
    wrapper makes their relationship explicit and carries non-fatal diagnostics
    for professional events that the AA presentation adapter cannot render yet.
    """

    migrated = migrate_project(project)
    descriptor = build_aa_scene_descriptor(migrated, scene_id)
    diagnostics: list[dict[str, str]] = []
    for chapter in migrated.get("chapters", []):
        for scene in chapter.get("scenes", []):
            if scene.get("scene_id") != scene_id:
                continue
            for cue_index, cue in enumerate(scene.get("cues", [])):
                for event_index, event in enumerate(cue.get("events", [])):
                    kind = event.get("kind") if isinstance(event, dict) else None
                    if (
                        not isinstance(kind, str)
                        or ":" not in kind
                        or scene_event_registry.is_descriptor_renderable(kind)
                    ):
                        continue
                    diagnostics.append(
                        {
                            "code": "scene.advanced_event_omitted",
                            "severity": "warning",
                            "path": f"scene:{scene_id}.cues[{cue_index}].events[{event_index}]",
                            "message": f"专业演出 {kind} 会保留在项目中，但当前 AA 预览不直接渲染。",
                        }
                    )
            break
    timeline = build_render_timeline(descriptor, frame_rate=frame_rate)
    diagnostics.extend(_character_motion_diagnostics(descriptor))
    return {
        "schema_version": SCENE_EVALUATION_SCHEMA_VERSION,
        "scene_id": scene_id,
        "descriptor": descriptor,
        "timeline": timeline,
        "performance": build_scene_performance(descriptor, timeline),
        "diagnostics": diagnostics,
    }
