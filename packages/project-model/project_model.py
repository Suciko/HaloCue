"""Canonical HaloCueProject model helpers for the first BA editor slice.

The model is intentionally plain JSON data.  Presentation adapters consume the
same payload but do not become the source of truth for story state.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PROJECT_SCHEMA_VERSION = "halocue-project/1.0"
SCENE_DESCRIPTOR_SCHEMA_VERSION = "scene-descriptor/1.0"
AA_SLOT_COUNT = 5
STAGE_MEDIA_KINDS = frozenset({"portrait", "spine", "spine-frame"})


def _diagnostic(code: str, path: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "error",
        "path": path,
        "message": message,
    }


def _iter_entities(project: dict[str, Any]):
    for index, character in enumerate(project.get("characters", [])):
        yield character, f"characters[{index}]", "character"
    for index, resource in enumerate(project.get("resources", [])):
        yield resource, f"resources[{index}]", "resource"
    for chapter_index, chapter in enumerate(project.get("chapters", [])):
        yield chapter, f"chapters[{chapter_index}]", "chapter"
        for scene_index, scene in enumerate(chapter.get("scenes", [])):
            scene_path = f"chapters[{chapter_index}].scenes[{scene_index}]"
            yield scene, scene_path, "scene"
            for event_index, event in enumerate(scene.get("events", [])):
                yield event, f"{scene_path}.events[{event_index}]", "event"


def _index_entities(project: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    index: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, str]] = []
    for entity, path, entity_kind in _iter_entities(project):
        if not isinstance(entity, dict):
            diagnostics.append(
                _diagnostic(
                    "project.invalid_entity",
                    path,
                    f"{entity_kind} must be a JSON object",
                )
            )
            continue
        entity_id = entity.get(f"{entity_kind}_id")
        if not isinstance(entity_id, str) or not entity_id.strip():
            diagnostics.append(
                _diagnostic(
                    "project.missing_id",
                    path,
                    f"{entity_kind} must have a non-empty stable ID",
                )
            )
            continue
        if entity_id in index:
            diagnostics.append(
                _diagnostic(
                    "project.duplicate_id",
                    path,
                    f"stable ID {entity_id!r} is already used by {index[entity_id]['path']}",
                )
            )
            continue
        index[entity_id] = {"entity": entity, "kind": entity_kind, "path": path}
    return index, diagnostics


def validate_project(project: Any) -> list[dict[str, str]]:
    """Return stable diagnostics for a canonical project payload."""

    if not isinstance(project, dict):
        return [_diagnostic("project.invalid_shape", "$", "project must be a JSON object")]

    diagnostics: list[dict[str, str]] = []
    if project.get("schema_version") != PROJECT_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                "project.unknown_version",
                "schema_version",
                f"expected {PROJECT_SCHEMA_VERSION!r}",
            )
        )
    if not isinstance(project.get("project_id"), str) or not project["project_id"].strip():
        diagnostics.append(_diagnostic("project.missing_id", "project_id", "project_id is required"))

    index, index_diagnostics = _index_entities(project)
    diagnostics.extend(index_diagnostics)

    resources = {
        entity_id
        for entity_id, record in index.items()
        if record["kind"] == "resource"
    }
    characters = {
        entity_id
        for entity_id, record in index.items()
        if record["kind"] == "character"
    }
    scenes = {
        entity_id
        for entity_id, record in index.items()
        if record["kind"] == "scene"
    }

    for entity, path, entity_kind in _iter_entities(project):
        if not isinstance(entity, dict):
            continue
        if entity_kind == "character" and "stage_media" in entity:
            stage_media = entity.get("stage_media")
            if not isinstance(stage_media, dict):
                diagnostics.append(
                    _diagnostic(
                        "project.invalid_stage_media",
                        f"{path}.stage_media",
                        "stage_media must be an object",
                    )
                )
            else:
                media_kind = stage_media.get("kind")
                if media_kind not in STAGE_MEDIA_KINDS:
                    diagnostics.append(
                        _diagnostic(
                            "project.unknown_stage_media_kind",
                            f"{path}.stage_media.kind",
                            f"stage_media kind must be one of {sorted(STAGE_MEDIA_KINDS)}",
                        )
                    )
                preview_uri = stage_media.get("preview_uri")
                has_spine_bundle = (
                    media_kind == "spine"
                    and isinstance(stage_media.get("bundle_key"), str)
                    and bool(stage_media.get("bundle_key", "").strip())
                )
                if (
                    not isinstance(preview_uri, str) or not preview_uri.strip()
                ) and not has_spine_bundle:
                    diagnostics.append(
                        _diagnostic(
                            "project.missing_stage_media_preview",
                            f"{path}.stage_media.preview_uri",
                            "stage_media preview_uri is required",
                        )
                    )
        resource_id = entity.get("resource_id")
        if resource_id is not None and resource_id not in resources:
            diagnostics.append(
                _diagnostic(
                    "project.unresolved_resource",
                    f"{path}.resource_id",
                    f"resource {resource_id!r} is not declared",
                )
            )
        character_id = entity.get("character_id")
        if character_id is not None and character_id not in characters:
            diagnostics.append(
                _diagnostic(
                    "project.unresolved_character",
                    f"{path}.character_id",
                    f"character {character_id!r} is not declared",
                )
            )
        if entity_kind == "event" and entity.get("kind") not in {
            "background",
            "dialogue",
            "enter",
            "exit",
            "wait",
        }:
            diagnostics.append(
                _diagnostic(
                    "project.unknown_event_kind",
                    f"{path}.kind",
                    f"unsupported event kind {entity.get('kind')!r}",
                )
            )
        if entity_kind == "event" and entity.get("kind") in {"enter", "exit"}:
            slot = entity.get("slot")
            if not isinstance(slot, int) or not 1 <= slot <= AA_SLOT_COUNT:
                diagnostics.append(
                    _diagnostic(
                        "project.invalid_slot",
                        f"{path}.slot",
                        f"slot must be an integer from 1 to {AA_SLOT_COUNT}",
                    )
                )

    if scenes and not isinstance(project.get("chapters"), list):
        diagnostics.append(_diagnostic("project.invalid_chapters", "chapters", "chapters must be an array"))
    return diagnostics


def deserialize_project(payload: Any) -> dict[str, Any]:
    """Validate and copy a JSON project payload."""

    if not isinstance(payload, dict):
        raise ValueError("project must be a JSON object")
    if payload.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported project schema {payload.get('schema_version')!r}; "
            f"expected {PROJECT_SCHEMA_VERSION!r}"
        )
    diagnostics = validate_project(payload)
    if diagnostics:
        summary = "; ".join(f"{item['code']} at {item['path']}" for item in diagnostics)
        raise ValueError(f"invalid HaloCueProject: {summary}")
    return deepcopy(payload)


def _scene_record(project: dict[str, Any], scene_id: str) -> dict[str, Any]:
    for chapter in project.get("chapters", []):
        for scene in chapter.get("scenes", []):
            if scene.get("scene_id") == scene_id:
                return scene
    raise ValueError(f"scene {scene_id!r} is not declared")


def build_aa_scene_descriptor(project: dict[str, Any], scene_id: str) -> dict[str, Any]:
    """Build a deterministic, synthetic-resource AA presentation descriptor."""

    diagnostics = validate_project(project)
    if diagnostics:
        summary = "; ".join(f"{item['code']} at {item['path']}" for item in diagnostics)
        raise ValueError(f"cannot preview invalid HaloCueProject: {summary}")

    scene = _scene_record(project, scene_id)
    characters = {
        item["character_id"]: item for item in project.get("characters", [])
    }
    resources = {
        item["resource_id"]: item for item in project.get("resources", [])
    }
    actors: dict[int, dict[str, Any]] = {
        slot: {
            "slot": slot,
            "character_id": None,
            "display_name": None,
            "resource_id": None,
            "state": "hidden",
        }
        for slot in range(1, AA_SLOT_COUNT + 1)
    }
    background: dict[str, Any] | None = None
    initial_background: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []

    for event in scene.get("events", []):
        kind = event["kind"]
        character_id = event.get("character_id")
        if kind == "enter":
            character = characters[character_id]
            slot = event["slot"]
            actors[slot] = {
                "slot": slot,
                "character_id": character_id,
                "display_name": character.get("name"),
                "resource_id": character.get("resource_id"),
                "state": "visible",
            }
            for key in ("avatar_key", "spine_key", "preview_uri", "stage_media"):
                if character.get(key):
                    actors[slot][key] = deepcopy(character[key])
        elif kind == "exit":
            actors[event["slot"]] = {
                "slot": event["slot"],
                "character_id": None,
                "display_name": None,
                "resource_id": None,
                "state": "hidden",
            }
        elif kind == "background":
            resource = resources[event["resource_id"]]
            background = {
                "resource_id": resource["resource_id"],
                "logical_key": resource["logical_key"],
            }
            if resource.get("aa_key"):
                background["aa_key"] = resource["aa_key"]
            for key in ("focus_x", "focus_y"):
                if key in resource:
                    background[key] = resource[key]
            if initial_background is None:
                initial_background = deepcopy(background)
        event_descriptor = {"event_id": event["event_id"], "kind": kind}
        for key in ("character_id", "resource_id", "text", "slot"):
            if key in event:
                event_descriptor[key] = event[key]
        events.append(event_descriptor)

    # `actors` records the final catalog state for resource lookup, while the
    # initial stage must begin empty and be populated by ordered enter events.
    # Keeping both views avoids showing every eventual actor on the first
    # background frame of a video preview.
    initial_actors = deepcopy(actors)
    for actor in initial_actors.values():
        actor["state"] = "hidden"

    return {
        "schema_version": SCENE_DESCRIPTOR_SCHEMA_VERSION,
        "scene_id": scene_id,
        "background": background,
        "initial_background": initial_background,
        "actors": [actors[slot] for slot in range(1, AA_SLOT_COUNT + 1)],
        "initial_actors": [
            initial_actors[slot] for slot in range(1, AA_SLOT_COUNT + 1)
        ],
        "events": events,
    }
