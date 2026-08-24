"""Read-only `.aap` inspection for the 1.0 import workflow."""

from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from typing import Any

from .repository import sha256_bytes


MAX_AAP_BYTES = 32_000_000


def _values(value: Any) -> list:
    if isinstance(value, dict) and isinstance(value.get("$values"), list):
        return value["$values"]
    return value if isinstance(value, list) else []


def _scripts(payload: dict) -> list[tuple[str, dict]]:
    result = []
    for node in _values(payload.get("nodes")):
        if not isinstance(node, dict):
            continue
        title = str(node.get("NodeName") or node.get("Title") or "未命名场景").strip()
        for script in _values(node.get("Scripts")):
            if isinstance(script, dict):
                result.append((title, script))
    return result


def parse_aap_bytes(filename: str, raw: bytes) -> dict:
    safe_name = str(filename or "").strip().split("\\")[-1].split("/")[-1]
    if not safe_name.lower().endswith(".aap"):
        raise ValueError("请选择 .aap 工程文件。")
    if not raw:
        raise ValueError(".aap 文件为空。")
    if len(raw) > MAX_AAP_BYTES:
        raise ValueError(".aap 文件不能超过 32 MB。")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError(".aap 必须是 UTF-8 JSON。") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f".aap 不是有效工程 JSON（第 {exc.lineno} 行）。") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), dict):
        raise ValueError("这不是可识别的 AA 工程文件。")

    scene_map: dict[str, dict] = {}
    characters: Counter[str] = Counter()
    backgrounds: Counter[str] = Counter()
    sounds: Counter[str] = Counter()
    warnings: list[str] = []
    lines = []
    for index, (scene_title, script) in enumerate(_scripts(payload), start=1):
        scene = scene_map.setdefault(scene_title, {"title": scene_title, "line_count": 0, "first_line": index, "last_line": index})
        text = str(script.get("text") or "").strip()
        speaker_slot = int(script.get("speakerSlotNum") or 0)
        chars = _values(script.get("characters"))
        speaker = chars[speaker_slot] if 0 <= speaker_slot < len(chars) and isinstance(chars[speaker_slot], dict) else {}
        speaker_name = str(speaker.get("name") or "").strip()
        if speaker_name and speaker_name not in {"<Key>", "<key>"}:
            characters[speaker_name] += 1
        bg = str(script.get("bgFriendlyName") or "").strip()
        if bg:
            backgrounds[bg] += 1
        sound = str(script.get("sound") or "").strip()
        if sound:
            sounds[sound] += 1
        scene["line_count"] += 1
        scene["last_line"] = index
        lines.append({"scene": scene_title, "text": text, "speaker": speaker_name, "is_dialogue": bool(script.get("isDialogScript")), "background": bg, "sound": sound})
        if not text and script.get("isDialogScript"):
            warnings.append(f"第 {index} 行对白为空，需要人工补充。")
        if script.get("selectionGroup"):
            warnings.append(f"第 {index} 行包含分支选择，当前只读导入会保留为待处理提示。")

    if not lines:
        warnings.append("工程中没有可识别的 ScriptData 节点。")
    return {
        "schema_version": "story-import/1.0",
        "source_type": "aap",
        "filename": safe_name,
        "source_digest": sha256_bytes(raw),
        "source_size": len(raw),
        "project_title": str(payload.get("ProjectName") or safe_name.removesuffix(".aap")),
        "counts": {"scenes": len(scene_map), "lines": len(lines), "characters": len(characters), "backgrounds": len(backgrounds), "sounds": len(sounds)},
        "scenes": list(scene_map.values()),
        "characters": [{"name": name, "line_count": count} for name, count in characters.most_common()],
        "backgrounds": [{"name": name, "line_count": count} for name, count in backgrounds.most_common()],
        "sounds": [{"name": name, "line_count": count} for name, count in sounds.most_common()],
        "lines": lines,
        "warnings": list(dict.fromkeys(warnings)),
        "write_boundary": "preview_only_until_user_confirmation",
    }


def parse_aap_payload(payload: dict) -> dict:
    filename = str(payload.get("filename") or "")
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        raise ValueError(".aap 文件内容为空。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(".aap 文件编码无效。") from exc
    return parse_aap_bytes(filename, raw)
