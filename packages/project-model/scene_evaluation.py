"""Evaluate one canonical scene into descriptor, timeline, and diagnostics."""

from __future__ import annotations

from typing import Any

from project_model import build_aa_scene_descriptor, migrate_project
from render_timeline import build_render_timeline
from scene_events import scene_event_registry


SCENE_EVALUATION_SCHEMA_VERSION = "scene-evaluation/1.0"


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
    return {
        "schema_version": SCENE_EVALUATION_SCHEMA_VERSION,
        "scene_id": scene_id,
        "descriptor": descriptor,
        "timeline": build_render_timeline(descriptor, frame_rate=frame_rate),
        "diagnostics": diagnostics,
    }
