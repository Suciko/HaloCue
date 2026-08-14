# -*- coding: utf-8 -*-
"""Read semantic face combinations from Spine 3.8 binary skeletons.

This module is deliberately read-only.  It does not render an image, alter a
Spine bundle, or assert that an extracted skin is accepted by AzureArchive.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from asset_validation import extract_expression_capabilities


class _Input:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.strings: list[str | None] = []

    def _take(self, count: int) -> bytes:
        if self.pos + count > len(self.data):
            raise ValueError("Spine binary ended unexpectedly")
        out = self.data[self.pos : self.pos + count]
        self.pos += count
        return out

    def byte(self) -> int:
        return self._take(1)[0]

    def boolean(self) -> bool:
        return self.byte() != 0

    def uint(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def float(self) -> float:
        return struct.unpack(">f", self._take(4))[0]

    def varint(self) -> int:
        value = 0
        shift = 0
        while True:
            byte = self.byte()
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift > 35:
                raise ValueError("Invalid Spine varint")

    def string(self) -> str | None:
        length = self.varint()
        if length == 0:
            return None
        if length == 1:
            return ""
        return self._take(length - 1).decode("utf-8")

    def string_ref(self) -> str | None:
        index = self.varint()
        if index == 0:
            return None
        try:
            return self.strings[index - 1]
        except IndexError as exc:
            raise ValueError(f"Invalid Spine string reference {index}") from exc


def _skip_floats(data: _Input, count: int) -> None:
    data._take(4 * count)


def _skip_vertices(data: _Input, vertex_count: int) -> None:
    if not data.boolean():
        _skip_floats(data, vertex_count * 2)
        return
    for _ in range(vertex_count):
        for _ in range(data.varint()):
            data.varint()
            _skip_floats(data, 3)


def _skip_short_array(data: _Input) -> None:
    data._take(2 * data.varint())


def _skip_curve(data: _Input) -> None:
    curve = data.byte()
    if curve == 2:  # bezier
        _skip_floats(data, 4)
    elif curve not in (0, 1):
        raise ValueError(f"Unsupported Spine curve type {curve}")


def _read_attachment(data: _Input, *, nonessential: bool) -> tuple[str | None, str | None]:
    attachment_name = data.string_ref()
    name = data.string_ref() or attachment_name
    attachment_type = data.byte()
    if attachment_type == 0:  # region
        path = data.string_ref() or name
        _skip_floats(data, 7)
        data.uint()
        return attachment_name, path
    if attachment_type == 1:  # bounding box
        _skip_vertices(data, data.varint())
        if nonessential:
            data.uint()
        return attachment_name, name
    if attachment_type == 2:  # mesh
        path = data.string_ref() or name
        data.uint()
        vertices = data.varint()
        _skip_floats(data, vertices * 2)
        _skip_short_array(data)
        _skip_vertices(data, vertices)
        data.varint()
        if nonessential:
            _skip_short_array(data)
            _skip_floats(data, 2)
        return attachment_name, path
    if attachment_type == 3:  # linked mesh
        path = data.string_ref() or name
        data.uint()
        data.string_ref()
        data.string_ref()
        data.boolean()
        if nonessential:
            _skip_floats(data, 2)
        return attachment_name, path
    if attachment_type == 4:  # path
        data.boolean()
        data.boolean()
        vertices = data.varint()
        _skip_vertices(data, vertices)
        _skip_floats(data, vertices // 3)
        if nonessential:
            data.uint()
        return attachment_name, name
    if attachment_type == 5:  # point
        _skip_floats(data, 3)
        if nonessential:
            data.uint()
        return attachment_name, name
    if attachment_type == 6:  # clipping
        data.varint()
        _skip_vertices(data, data.varint())
        if nonessential:
            data.uint()
        return attachment_name, name
    raise ValueError(f"Unsupported Spine attachment type {attachment_type}")


def _read_skin(data: _Input, *, default: bool, nonessential: bool) -> tuple[str | None, dict[int, dict[str, str]]]:
    if default:
        slot_count = data.varint()
        if not slot_count:
            return None, {}
        name = "default"
    else:
        name = data.string_ref()
        for _ in range(data.varint()):
            data.varint()
        for _ in range(data.varint()):
            data.varint()
        for _ in range(data.varint()):
            data.varint()
        for _ in range(data.varint()):
            data.varint()
        slot_count = data.varint()
    attachments: dict[int, dict[str, str]] = {}
    for _ in range(slot_count):
        slot_index = data.varint()
        for _ in range(data.varint()):
            attachment_name, path = _read_attachment(data, nonessential=nonessential)
            if attachment_name and path:
                attachments.setdefault(slot_index, {})[attachment_name] = path
    return name, attachments


def _skip_header_to_skins(data: _Input) -> None:
    data.string()  # hash
    version = data.string() or ""
    if not version.startswith("3.8"):
        raise ValueError(f"Only Spine 3.8 semantic skeletons are supported, got {version!r}")
    _skip_floats(data, 4)
    nonessential = data.boolean()
    if nonessential:
        data.float()
        data.string()
        data.string()
    data.strings = [data.string() for _ in range(data.varint())]

    for index in range(data.varint()):
        data.string()
        if index:
            data.varint()
        _skip_floats(data, 8)
        data.varint()
        data.boolean()
        if nonessential:
            data.uint()
    data._semantic_slot_defaults = []
    for _ in range(data.varint()):
        data.string()
        data.varint()
        data.uint()
        data.uint()
        data._semantic_slot_defaults.append(data.string_ref())
        data.varint()
    for _ in range(data.varint()):
        data.string()
        data.varint()
        data.boolean()
        for _ in range(data.varint()):
            data.varint()
        data.varint()
        _skip_floats(data, 2)
        data.byte()
        data.boolean()
        data.boolean()
        data.boolean()
    for _ in range(data.varint()):
        data.string()
        data.varint()
        data.boolean()
        for _ in range(data.varint()):
            data.varint()
        data.varint()
        data.boolean()
        data.boolean()
        _skip_floats(data, 10)
    for _ in range(data.varint()):
        data.string()
        data.varint()
        data.boolean()
        for _ in range(data.varint()):
            data.varint()
        data.varint()
        data.varint()
        data.varint()
        data.varint()
        _skip_floats(data, 5)
    data._semantic_nonessential = nonessential


_MECHANICAL_LABELS = {
    "眨眼差分用",
    "可眨眼差分",
    "默认表情差分",
    "默认",
    "1.5",
    "特殊",
    "特殊配合",
    "特殊配合的差分",
    "一般与脸红1.5配合",
    "配合闭眼微笑",
    "不适合大幅度睁眼的差分",
    "更适合闭眼",
}

_PLAIN_SEMANTICS = (
    ("无表情理性嘴", ("无表情", "冷静", "理性")),
    ("微笑嘴", ("轻微微笑", "温和")),
    ("露齿张嘴", ("露齿", "开口")),
    ("普通睁眼", ("平静", "正常")),
    ("默认弯眉", ("平静", "正常")),
    ("闭眼（可眨眼差分）", ("闭眼", "平静")),
    ("半闭眼（眨眼差分用）", ("半闭眼",)),
    ("全脸红", ("强烈脸红", "害羞", "激动")),
    ("普通脸红（默认）", ("脸红", "害羞")),
    ("普通脸红（1.5）", ("明显脸红", "害羞")),
    ("汗珠", ("汗", "无语", "紧张", "尴尬")),
    ("大喊大叫嘴", ("大喊", "激动", "生气")),
    ("生气眼（特殊）", ("生气", "愤怒")),
    ("下压眉plus", ("生气", "恼怒")),
)

_EMOTION_GROUPS = (
    (
        "愤怒",
        ("愤怒", "生气", "恼怒", "恼火", "不满", "烦躁", "不耐烦",
         "敌意", "嫌弃", "警告", "不爽", "不服气", "发火", "抗议",
         "生闷气", "赌气"),
    ),
    (
        "悲伤",
        ("大哭", "悲伤", "难过", "委屈", "无助", "哭诉", "难受",
         "悲痛", "认输", "求助"),
    ),
    (
        "惊讶",
        ("惊讶", "意外", "吃惊", "震惊", "惊叹", "愣住", "好奇",
         "疑惑", "期待"),
    ),
    (
        "尴尬",
        ("尴尬", "心虚", "紧张", "不自在", "为难", "担忧", "害怕",
         "迟疑", "无奈", "沉默", "不知如何回应", "汗", "无语"),
    ),
    (
        "开心",
        ("开心", "欢喜", "愉快", "幸福", "满意", "友好", "微笑",
         "轻微微笑", "温和"),
    ),
)

_PART_WEIGHTS = {
    "eyes": 4,
    "brows": 3,
    "mouth": 2,
    "extra": 2,
    "blush": 1,
    "unknown": 1,
}

_NEUTRAL_LABELS = {"无表情", "冷静", "理性", "平静", "正常", "闭眼", "半闭眼"}


def _semantic_summary(parts: list[dict], labels: list[str]) -> tuple[str, list[str]]:
    """Condense creator part semantics without mixing neutral and active moods."""
    scores = {primary: 0 for primary, _ in _EMOTION_GROUPS}
    labels_by_group = {primary: [] for primary, _ in _EMOTION_GROUPS}
    labels_by_part: dict[str, list[str]] = {}
    tokens_by_group = {
        primary: set(tokens) for primary, tokens in _EMOTION_GROUPS
    }
    for part in parts:
        kind = str(part.get("kind") or "unknown")
        weight = _PART_WEIGHTS.get(kind, 1)
        labels_by_part.setdefault(kind, [])
        for label in part.get("labels") or []:
            if label not in labels_by_part[kind]:
                labels_by_part[kind].append(label)
            for primary, _ in _EMOTION_GROUPS:
                if label in tokens_by_group[primary]:
                    scores[primary] += weight
                    if label not in labels_by_group[primary]:
                        labels_by_group[primary].append(label)

    strongest = max(scores, key=scores.get)
    modifiers: list[str] = []
    if "害羞" in labels:
        modifiers.append("害羞")
    for blush in ("强烈脸红", "明显脸红", "脸红"):
        if blush in labels:
            modifiers.append(blush)
            break
    if "汗" in labels:
        modifiers.append("汗")
    raw_names = [str(part.get("raw_name") or "") for part in parts]
    if "半闭眼" in labels or any("半闭眼" in raw for raw in raw_names):
        modifiers.append("半闭眼")
    elif "闭眼" in labels or any("闭眼" in raw for raw in raw_names):
        modifiers.append("闭眼")
    if "开口" in labels:
        modifiers.append("开口")
    if "露齿" in labels:
        modifiers.append("露齿")

    if scores[strongest] == 0:
        if "平静" in labels or any(label in _NEUTRAL_LABELS for label in labels):
            return "平静", ["平静", *modifiers]
        return (labels[0], [labels[0], *modifiers]) if labels else ("", modifiers)

    selected = labels_by_group[strongest]
    primary = strongest
    for kind in ("eyes", "brows", "mouth", "extra", "blush", "unknown"):
        candidate = next(
            (
                label
                for label in labels_by_part.get(kind, [])
                if label in tokens_by_group[strongest]
            ),
            None,
        )
        if candidate:
            primary = candidate
            break
    if (
        strongest == "尴尬"
        and scores["惊讶"] > 0
        and "汗" in labels
        and "强烈脸红" in labels
    ):
        primary = "慌张"

    canonical = [primary, *modifiers]
    for preferred in dict(_EMOTION_GROUPS)[strongest]:
        if preferred in selected and preferred not in canonical:
            canonical.append(preferred)
        if len(canonical) >= 6:
            break
    return canonical[0], canonical


def _semantic_kind(raw: str, extracted: list[dict]) -> str:
    if extracted:
        return str(extracted[0].get("kind") or "unknown")
    lowered = raw.casefold()
    if "嘴" in raw or "mouth" in lowered:
        return "mouth"
    if "眼" in raw or "eyes" in lowered:
        return "eyes"
    if "眉" in raw or "brow" in lowered:
        return "brows"
    if "脸红" in raw or "blush" in lowered:
        return "blush"
    if "汗" in raw:
        return "extra"
    return "unknown"


def _semantic_parts(paths: list[str]) -> tuple[list[dict], list[str]]:
    parts: list[dict] = []
    labels: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if raw in seen:
            continue
        seen.add(raw)
        extracted = extract_expression_capabilities([raw]).get("parts", [])
        current: list[str] = []
        for part in extracted:
            for label in part["labels"]:
                if label not in _MECHANICAL_LABELS and label not in current:
                    current.append(label)
        for token, additions in _PLAIN_SEMANTICS:
            if token in raw:
                for label in additions:
                    if label not in current:
                        current.append(label)
        if not current:
            continue
        parts.append(
            {
                "kind": _semantic_kind(raw, extracted),
                "raw_name": raw,
                "labels": current,
                "source": "atlas_semantic",
            }
        )
        for label in current:
            if label not in labels:
                labels.append(label)
    return parts, labels


def _read_animation(data: _Input, *, event_has_audio: list[bool]) -> tuple[str | None, dict[int, str]]:
    name = data.string()
    paths: dict[int, str] = {}
    for _ in range(data.varint()):  # slot timelines
        slot_index = data.varint()
        for _ in range(data.varint()):
            timeline_type = data.byte()
            frames = data.varint()
            for frame in range(frames):
                time = data.float()
                if timeline_type == 0:  # attachment
                    path = data.string_ref()
                    # A later first key is commonly the beginning of a blink.
                    # Until that time Spine keeps the setup attachment, so it
                    # must not replace the stable expression combination.
                    if frame == 0 and time <= 0.0001 and path:
                        paths[slot_index] = path
                elif timeline_type == 1:  # color
                    data.uint()
                    if frame < frames - 1:
                        _skip_curve(data)
                elif timeline_type == 2:  # two color
                    data.uint()
                    data.uint()
                    if frame < frames - 1:
                        _skip_curve(data)
                else:
                    raise ValueError(f"Unsupported Spine slot timeline {timeline_type}")
    for _ in range(data.varint()):  # bone timelines
        data.varint()
        for _ in range(data.varint()):
            timeline_type = data.byte()
            frames = data.varint()
            if timeline_type not in (0, 1, 2, 3):
                raise ValueError(f"Unsupported Spine bone timeline {timeline_type}")
            values = 2 if timeline_type == 0 else 3
            for frame in range(frames):
                _skip_floats(data, values)
                if frame < frames - 1:
                    _skip_curve(data)
    for _ in range(data.varint()):  # IK timelines
        data.varint()
        frames = data.varint()
        for frame in range(frames):
            _skip_floats(data, 3)
            data.byte()
            data.boolean()
            data.boolean()
            if frame < frames - 1:
                _skip_curve(data)
    for _ in range(data.varint()):  # transform constraint timelines
        data.varint()
        frames = data.varint()
        for frame in range(frames):
            _skip_floats(data, 5)
            if frame < frames - 1:
                _skip_curve(data)
    for _ in range(data.varint()):  # path constraint timelines
        data.varint()
        for _ in range(data.varint()):
            timeline_type = data.byte()
            frames = data.varint()
            if timeline_type not in (0, 1, 2):
                raise ValueError(f"Unsupported Spine path timeline {timeline_type}")
            values = 2 if timeline_type in (0, 1) else 3
            for frame in range(frames):
                _skip_floats(data, values)
                if frame < frames - 1:
                    _skip_curve(data)
    for _ in range(data.varint()):  # deform timelines
        data.varint()
        for _ in range(data.varint()):
            data.varint()
            for _ in range(data.varint()):
                data.string_ref()
                frames = data.varint()
                for frame in range(frames):
                    data.float()
                    end = data.varint()
                    if end:
                        data.varint()
                        _skip_floats(data, end)
                    if frame < frames - 1:
                        _skip_curve(data)
    for _ in range(data.varint()):  # draw order
        data.float()
        for _ in range(data.varint()):
            data.varint()
            data.varint()
    for _ in range(data.varint()):  # events
        data.float()
        event_index = data.varint()
        data.varint()  # signed or unsigned does not change byte consumption.
        data.float()
        if data.boolean():
            data.string()
        if event_index < len(event_has_audio) and event_has_audio[event_index]:
            _skip_floats(data, 2)
    return name, paths


def _extract_binary_semantic_face_combinations(source: str | Path) -> dict[str, dict]:
    """Return numbered Spine skin combinations with their named semantic parts.

    The output is only a semantic candidate table.  It does not mean a `faceId`
    has been verified in AA, so callers must keep their existing evidence gate.
    """
    data = _Input(Path(source).read_bytes())
    _skip_header_to_skins(data)
    nonessential = data._semantic_nonessential
    _, default_attachments = _read_skin(data, default=True, nonessential=nonessential)
    default_by_slot = {
        index: default_attachments.get(index, {}).get(attachment_name)
        for index, attachment_name in enumerate(data._semantic_slot_defaults)
        if attachment_name and default_attachments.get(index, {}).get(attachment_name)
    }
    for _ in range(data.varint()):
        _read_skin(data, default=False, nonessential=nonessential)
    event_has_audio: list[bool] = []
    for _ in range(data.varint()):
        data.string_ref()
        data.varint()
        data.float()
        data.string()
        event_has_audio.append(data.string() is not None)
        if event_has_audio[-1]:
            _skip_floats(data, 2)
    result: dict[str, dict] = {}
    parts, labels = _semantic_parts(list(default_by_slot.values()))
    primary, semantic_labels = _semantic_summary(parts, labels)
    result["00"] = {
        "face_id": "00",
        "raw_parts": list(dict.fromkeys(default_by_slot.values())),
        "parts": parts,
        "labels": labels,
        "primary_emotion": primary,
        "semantic_labels": semantic_labels,
        "special": False,
        "source": "spine_binary_semantic",
    }
    for _ in range(data.varint()):
        name, replacements = _read_animation(data, event_has_audio=event_has_audio)
        if not name or not re.fullmatch(r"\d{2}", name):
            continue
        all_paths = list({**default_by_slot, **replacements}.values())
        parts, labels = _semantic_parts(all_paths)
        primary, semantic_labels = _semantic_summary(parts, labels)
        result[name] = {
            "face_id": name,
            "raw_parts": list(dict.fromkeys(all_paths)),
            "parts": parts,
            "labels": labels,
            "primary_emotion": primary,
            "semantic_labels": semantic_labels,
            "special": name == "99",
            "source": "spine_binary_semantic",
        }
    return dict(sorted(result.items()))


def _atlas_text(source: str | Path) -> list[str]:
    raw = Path(source).read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError("Unsupported Spine atlas text encoding")


def extract_atlas_face_combinations(source: str | Path) -> dict[str, dict]:
    """Build a conservative face table from numbered atlas regions.

    This is the Android fallback for Spine versions whose binary layout is not
    supported by the read-only 3.8 parser.  It preserves IDs and obvious names
    without claiming that atlas naming proves a complete AA face mapping.
    """
    from asset_validation import extract_expression_capabilities

    lines = _atlas_text(source)
    capabilities = extract_expression_capabilities(lines)
    names: dict[str, str] = {}
    for line in lines:
        raw = line.strip()
        if not raw or line[:1].isspace() or ":" in raw:
            continue
        match = re.fullmatch(r"(\d{2})(?:_(.*))?", raw)
        if match:
            names.setdefault(match.group(1), raw)
    names.update({face_id: names.get(face_id, face_id) for face_id in capabilities["faces"]})
    aliases = {
        "default": "neutral",
        "normal": "neutral",
        "eyeclose": "neutral",
        "respond": "respond",
        "smile": "joy",
        "embarrassed": "embarrassment",
        "serious": "serious",
        "depressed": "sadness",
    }
    result = {}
    for face_id, raw in sorted(names.items()):
        suffix = raw.partition("_")[2].strip().casefold()
        primary = aliases.get(suffix, suffix or "neutral")
        labels = [primary]
        if suffix and suffix != primary:
            labels.append(suffix)
        result[face_id] = {
            "face_id": face_id,
            "raw_parts": [raw],
            "parts": [],
            "labels": labels,
            "primary_emotion": primary,
            "semantic_labels": labels,
            "special": face_id == "99",
            "source": "spine_atlas_fallback",
        }
    return result


def extract_semantic_face_combinations(source: str | Path) -> dict[str, dict]:
    """Read binary semantics, falling back to atlas IDs for unsupported Spine versions."""
    try:
        return _extract_binary_semantic_face_combinations(source)
    except (UnicodeDecodeError, ValueError, IndexError, struct.error):
        atlas = Path(source).with_suffix(".atlas")
        if not atlas.is_file():
            raise
        return extract_atlas_face_combinations(atlas)
