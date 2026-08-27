"""Versioned scene-event registry adapter.

The JSON manifest under ``packages/contracts`` is the source of event kind,
renderability, and duration policy. This module keeps the Python interface
small so model validation and offline rendering do not maintain their own
copies of those rules.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "contracts" / "scene-events" / "1.1.json"
MANIFEST_SCHEMA_VERSION = "scene-events/1.1"
TYPEWRITER_GRAPHEME_MS = 32
TYPEWRITER_PUNCTUATION_PAUSE_MS = 96
TYPEWRITER_NEWLINE_PAUSE_MS = 192
DIALOGUE_HOLD_MS = 650
PUNCTUATION = frozenset("，。！？；：、,.!?;:")


class JsonSceneEventRegistry:
    """Read-only adapter for the checked-in scene event manifest."""

    def __init__(self, manifest: dict[str, Any] | None = None) -> None:
        payload = manifest
        if payload is None:
            payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self._definitions = self._validate(payload)
        self._by_kind = {item["kind"]: item for item in self._definitions}

    @staticmethod
    def _validate(payload: Any) -> tuple[dict[str, Any], ...]:
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("unsupported scene event manifest schema")
        events = payload.get("events")
        if not isinstance(events, list) or not events:
            raise ValueError("scene event manifest events must be a non-empty array")
        definitions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError(f"scene event definition {index} must be an object")
            kind = event.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError(f"scene event definition {index} must have a non-empty kind")
            kind = kind.strip()
            if kind in seen:
                raise ValueError(f"duplicate scene event kind {kind}")
            seen.add(kind)
            if (
                not isinstance(event.get("descriptor_renderable"), bool)
                or not isinstance(event.get("timeline_supported"), bool)
                or not isinstance(event.get("visual_only"), bool)
                or not isinstance(event.get("editor_label"), str)
                or not event["editor_label"].strip()
                or (
                    event.get("simple_action") is not None
                    and not isinstance(event.get("simple_action"), str)
                )
            ):
                raise ValueError(f"scene event definition {kind} has invalid metadata")
            policy = event.get("duration_policy")
            default_duration = event.get("default_duration_ms")
            if policy == "fixed":
                if (
                    isinstance(default_duration, bool)
                    or not isinstance(default_duration, int)
                    or default_duration <= 0
                ):
                    raise ValueError(
                        f"fixed scene event {kind} must have a positive default duration"
                    )
            elif policy == "dialogue-aa-v1":
                if default_duration is not None:
                    raise ValueError(f"dialogue event {kind} cannot have a fixed duration")
            else:
                raise ValueError(f"scene event {kind} has an unknown duration policy")
            normalized = deepcopy(event)
            normalized["kind"] = kind
            definitions.append(normalized)
        return tuple(definitions)

    def definitions(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(item) for item in self._definitions)

    def definition(self, kind: Any) -> dict[str, Any] | None:
        item = self._by_kind.get(kind) if isinstance(kind, str) else None
        return deepcopy(item) if item is not None else None

    def is_timeline_supported(self, kind: Any) -> bool:
        item = self._by_kind.get(kind) if isinstance(kind, str) else None
        return bool(item and item.get("timeline_supported"))

    def is_descriptor_renderable(self, kind: Any) -> bool:
        item = self._by_kind.get(kind) if isinstance(kind, str) else None
        return bool(item and item.get("descriptor_renderable"))

    def is_visual_only(self, kind: Any) -> bool:
        item = self._by_kind.get(kind) if isinstance(kind, str) else None
        return bool(item and item.get("visual_only"))

    @staticmethod
    def _dialogue_duration_ms(text: Any) -> int:
        value = "" if text is None else str(text)
        duration = DIALOGUE_HOLD_MS
        for grapheme in value:
            duration += TYPEWRITER_GRAPHEME_MS
            if grapheme == "\n":
                duration += TYPEWRITER_NEWLINE_PAUSE_MS
            elif grapheme in PUNCTUATION:
                duration += TYPEWRITER_PUNCTUATION_PAUSE_MS
        return duration

    def duration_ms(self, event: dict[str, Any]) -> int:
        kind = event.get("kind") if isinstance(event, dict) else None
        definition = self._by_kind.get(kind) if isinstance(kind, str) else None
        if not definition or not definition.get("timeline_supported"):
            raise ValueError(f"unsupported render event kind {kind!r}")
        explicit = event.get("duration_ms")
        if explicit is not None:
            if isinstance(explicit, bool) or not isinstance(explicit, (int, float)):
                raise ValueError("event duration_ms must be a finite positive number")
            if not math.isfinite(explicit) or explicit <= 0:
                raise ValueError("event duration_ms must be a finite positive number")
            return max(1, math.ceil(explicit))
        if definition["duration_policy"] == "dialogue-aa-v1":
            return self._dialogue_duration_ms(event.get("text"))
        return int(definition["default_duration_ms"])


scene_event_registry = JsonSceneEventRegistry()
RENDERABLE_EVENT_KINDS = frozenset(
    item["kind"] for item in scene_event_registry.definitions() if item["descriptor_renderable"]
)
SUPPORTED_EVENT_KINDS = frozenset(
    item["kind"] for item in scene_event_registry.definitions() if item["timeline_supported"]
)
DEFAULT_EVENT_DURATION_MS = {
    item["kind"]: item["default_duration_ms"]
    for item in scene_event_registry.definitions()
    if item["timeline_supported"] and item["default_duration_ms"] is not None
}
