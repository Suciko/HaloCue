#!/usr/bin/env python3
"""Lossless, machine-readable extractor for official BA scenario staging data."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.1"
SHARD_NAMES = ("ScenarioScriptExcel_0.json", "ScenarioScriptExcel_1.json", "ScenarioScriptExcel_2.json")
CHARACTER_RE = re.compile(r"^(\d+);([^;\r\n]*);([^;\r\n]*)(?:;(.*))?$", re.DOTALL)
KNOWN_GLOBAL = {
    "title", "place", "na", "wait", "all", "st", "stm", "clearst", "zmc", "zmlt",
    "bgshake", "bgshake", "nextepisode", "continued", "ending", "video", "videons2",
    "timelinens", "hidemenu", "showmenu", "fx", "touch", "str", "fontsize",
}
KNOWN_SLOT = {
    "em", "h", "hide", "a", "d", "al", "ar", "dl", "dr", "m1", "m2", "m3", "m4", "m5",
    "jump", "hophop", "stiff", "greeting", "shake", "closeup", "black", "white", "fx",
    "falldownl", "falldownr", "sig", "wait", "fall" , "crouch",
}
COMMAND_ALIASES = {"wait": "wait", "title": "title", "place": "place", "na": "na", "clearst": "clearst"}
LINE_TYPES = {
    "wait": "wait", "title": "title", "place": "place", "na": "narration", "continued": "flow",
    "nextepisode": "flow", "ending": "flow", "video": "video", "videons2": "video",
    "timelinens": "timeline", "st": "screen_text", "stm": "screen_text", "str": "screen_text",
    "zmc": "camera", "zmlt": "camera", "bgshake": "camera", "clearst": "screen_text",
    "hidemenu": "ui", "showmenu": "ui", "fx": "effect", "touch": "effect", "fontsize": "screen_text",
}


def _json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data_list") if isinstance(payload, dict) else payload
    if isinstance(rows, dict):
        rows = [rows]
    return [row for row in (rows or []) if isinstance(row, dict)]


def normalize_command(command: str) -> tuple[str, str]:
    raw = command.lstrip("#")
    lower = raw.lower()
    normalized = COMMAND_ALIASES.get(lower, lower)
    if lower in KNOWN_GLOBAL or lower in KNOWN_SLOT:
        status = "exact" if raw == lower else "case_variant"
        return normalized, status
    return normalized, "unknown"


def _event_base(index: int, raw_line: str, line_type: str, raw_command: str = "") -> dict[str, Any]:
    normalized, status = normalize_command(raw_command) if raw_command else (None, "exact")
    return {
        "event_index": index,
        "raw_line": raw_line,
        "line_type": line_type,
        "command_raw": raw_command or None,
        "command_normalized": normalized,
        "parse_status": status,
        "semantic_zh": None,
        "arguments_raw": [],
    }


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    """Keep first-seen order while removing duplicate semantic values."""
    result: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _record_semantics(events: list[dict[str, Any]], localized_text: str = "") -> dict[str, Any]:
    """Separate dialogue, staged characters, screen text, and flow commands.

    A character declaration without dialogue is a staging operation, not a
    speaker.  Keeping both views is important because the same row can place
    one character silently while another character speaks.
    """
    character_events = [event for event in events if event.get("line_type") == "character"]
    dialogue_speakers = _ordered_unique(
        str(event.get("character_name_kr") or "")
        for event in character_events
        if str(event.get("dialogue_kr") or "").strip()
    )
    declared_names = _ordered_unique(
        str(event.get("character_name_kr") or "")
        for event in character_events
        if str(event.get("character_name_kr") or "").strip()
    )
    staged_by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
    for event in character_events:
        name = str(event.get("character_name_kr") or "").strip()
        if not name:
            continue
        key = (event.get("slot"), name)
        item = staged_by_key.setdefault(
            key,
            {
                "slot": event.get("slot"),
                "character_name_kr": name,
                "face_id": event.get("face_id"),
                "has_dialogue": False,
            },
        )
        item["has_dialogue"] = bool(item["has_dialogue"] or str(event.get("dialogue_kr") or "").strip())
        if event.get("face_id") not in (None, ""):
            item["face_id"] = event.get("face_id")
    screen_text_events = [
        {
            "event_index": event.get("event_index"),
            "command_normalized": event.get("command_normalized"),
            "screen_text_raw": event.get("screen_text_raw", ""),
            "raw_line": event.get("raw_line", ""),
        }
        for event in events
        if event.get("line_type") == "screen_text"
        and str(event.get("screen_text_raw") or "").strip()
    ]
    localized_text = str(localized_text or "").strip()
    has_narration = any(event.get("line_type") == "narration" and str(event.get("dialogue_kr") or "").strip() for event in events)
    if localized_text and not dialogue_speakers and not has_narration and not any(item["screen_text_raw"] == localized_text for item in screen_text_events):
        screen_text_events.append(
            {
                "event_index": None,
                "command_normalized": None,
                "screen_text_raw": localized_text,
                "raw_line": "<localized text>",
            }
        )
    commands = [str(event.get("command_normalized") or "") for event in events if event.get("command_normalized")]
    transition_commands = [command for command in commands if command in {"all", "st", "stm", "str", "clearst", "zmc", "zmlt", "bgshake", "na", "title", "place"}]
    has_screen_text = bool(screen_text_events)
    has_wait = any(event.get("command_normalized") == "wait" for event in events)
    has_flow = any(event.get("line_type") == "flow" for event in events)
    has_staging = bool(character_events or commands)
    if dialogue_speakers:
        semantic_kind = "dialogue"
    elif has_narration:
        semantic_kind = "narration"
    elif has_screen_text:
        semantic_kind = "screen_text"
    elif has_wait:
        semantic_kind = "wait"
    elif transition_commands:
        semantic_kind = "transition"
    elif has_flow:
        semantic_kind = "flow"
    elif has_staging:
        semantic_kind = "staging"
    else:
        semantic_kind = "empty"
    return {
        "dialogue_speakers": dialogue_speakers,
        "declared_character_names": declared_names,
        "staged_characters": list(staged_by_key.values()),
        "screen_text_events": screen_text_events,
        "transition_commands": _ordered_unique(transition_commands),
        "semantic_kind": semantic_kind,
    }


def parse_script_events(script_kr: str, text_tw: str = "") -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, raw_line in enumerate(str(script_kr or "").splitlines()):
        if not raw_line:
            continue
        character = CHARACTER_RE.match(raw_line)
        if character:
            slot, name, face, dialogue = character.groups()
            event = _event_base(index, raw_line, "character")
            event.update({"slot": int(slot), "character_name_kr": name, "face_id": face, "dialogue_kr": dialogue or ""})
            event["arguments_raw"] = [slot, name, face] + ([dialogue] if dialogue is not None else [])
            if dialogue:
                event["semantic_zh"] = "角色对白"
            else:
                event["semantic_zh"] = "角色演出节点"
            events.append(event)
            continue
        if not raw_line.startswith("#"):
            event = _event_base(index, raw_line, "text")
            event["arguments_raw"] = [raw_line]
            event["parse_status"] = "partial"
            events.append(event)
            continue
        parts = raw_line[1:].split(";")
        if parts and parts[0].isdigit():
            slot = int(parts[0])
            command = parts[1] if len(parts) > 1 else ""
            args = parts[2:]
            normalized, status = normalize_command(command)
            line_type = "slot_command"
            event = _event_base(index, raw_line, line_type, command)
            event.update({"slot": slot, "command_raw": command, "command_normalized": normalized, "arguments_raw": args, "parse_status": status})
            if normalized == "wait" and args and args[0].strip().isdigit():
                event["milliseconds"] = int(args[0].strip())
                event["line_type"] = "slot_wait"
            if normalized == "em" and args:
                event["emoticon_raw"] = args[0]
            events.append(event)
            continue
        command = parts[0] if parts else ""
        args = parts[1:]
        normalized, status = normalize_command(command)
        line_type = LINE_TYPES.get(normalized, "command")
        event = _event_base(index, raw_line, line_type, command)
        event.update({"command_raw": command, "command_normalized": normalized, "arguments_raw": args, "parse_status": status})
        if normalized == "wait" and args and args[0].strip().isdigit():
            event["milliseconds"] = int(args[0].strip())
        if normalized == "na":
            event["narrator_kr"] = args[0] if len(args) > 1 else ""
            event["dialogue_kr"] = args[-1] if args else ""
        if normalized in {"st", "stm", "str"} and args:
            event["screen_text_raw"] = args[-1]
        events.append(event)
    return events


def _load_existing_story_catalog(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    script = repo_root.parent.parent / ".claude" / "skills" / "ba-writing" / "scripts" / "render_global_chinese_corpus.py"
    if not script.is_file():
        return {}
    try:
        spec = importlib.util.spec_from_file_location("ba_render_catalog", script)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        catalog = module.build_story_catalog(repo_root)
    except Exception:
        return {}
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for descriptor in catalog.descriptors:
        base = {"category": descriptor.category, "unit_id": descriptor.unit_id, "title": descriptor.title,
                "character_id": descriptor.character_id, "character_name": descriptor.character_name,
                "favor_rank": descriptor.favor_rank, "order_in_group": descriptor.order_in_group,
                "sort_key": list(descriptor.sort_key), "metadata": dict(descriptor.metadata)}
        for section, groups in descriptor.group_sections:
            for group in groups:
                if group and group != "0":
                    result[str(group)].append({**base, "section": section})
    return dict(result)


def load_story_memberships(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    return _load_existing_story_catalog(repo_root)


def load_resource_catalog(repo_root: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    excel = repo_root / "ExcelDB"
    catalog: dict[str, dict[str, list[dict[str, Any]]]] = {"background": {}, "background_effect": {}, "transition": {}, "bgm": {}}
    def add(kind: str, key: Any, value: Any, source: str, row: dict[str, Any]) -> None:
        if key in (None, "", 0, "0"):
            return
        key = str(key)
        catalog[kind].setdefault(key, []).append({"name": value, "source": source, "row": row})
    for row in _json_rows(excel / "ScenarioBGNameExcel.json"):
        add("background", row.get("name"), row.get("bg_file_name") or row.get("name"), "ScenarioBGNameExcel.json", row)
    for row in _json_rows(excel / "ScenarioBGNameGlobalExcel.json"):
        key = row.get("group_name", row.get("id"))
        value = row.get("name_global") or row.get("name_tw") or row.get("name") or key
        add("background", key, value, "ScenarioBGNameGlobalExcel.json", row)
    for row in _json_rows(excel / "ScenarioBGEffectExcel.json"):
        add("background_effect", row.get("name"), row.get("effect") or row.get("effect2") or row.get("name"), "ScenarioBGEffectExcel.json", row)
    for row in _json_rows(excel / "ScenarioTransitionExcel.json"):
        name = row.get("name")
        add("transition", name, {"out": row.get("transition_out"), "in": row.get("transition_in")}, "ScenarioTransitionExcel.json", row)
    for row in _json_rows(excel / "BGMExcel.json"):
        add("bgm", row.get("id"), row.get("path") or row.get("id"), "BGMExcel.json", row)
    return catalog


def _resource(kind: str, value: Any, catalog: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    candidates = catalog.get(kind, {}).get(str(value), [])
    status = "unmapped" if not candidates else ("mapped" if len(candidates) == 1 else "ambiguous")
    compact = [{"name": item["name"], "source": item["source"]} for item in candidates]
    return {"raw_value": value, "resolved": candidates[0]["name"] if len(candidates) == 1 else None,
            "candidates": compact, "mapping_status": status}


class OfficialStagingExtractor:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.resources = load_resource_catalog(self.repo_root)
        self.story_memberships = load_story_memberships(self.repo_root)

    def extract_row(self, row: dict[str, Any], source_file: str, shard: int, row_index: int, global_index: int) -> dict[str, Any]:
        group_id = str(row.get("group_id", ""))
        memberships = self.story_memberships.get(group_id, [])
        events = parse_script_events(str(row.get("script_kr", "") or ""), str(row.get("text_tw", "") or ""))
        kr_texts = [e.get("dialogue_kr", "") for e in events if e.get("dialogue_kr")]
        dialogue = bool(kr_texts)
        semantics = _record_semantics(events, str(row.get("text_tw", "") or ""))
        has_staging = bool(events) or any(row.get(k) not in (None, "", 0, False) for k in ("bgm_id", "sound", "transition", "bg_name", "bg_effect", "popup_file_name", "voice_id"))
        raw_known = {"group_id", "selection_group", "bgm_id", "sound", "transition", "bg_name", "bg_effect", "popup_file_name", "script_kr", "text_jp", "text_th", "text_tw", "text_en", "voice_id", "teen_mode"}
        raw = {key: row.get(key) for key in raw_known}
        raw["extra_fields"] = {key: value for key, value in row.items() if key not in raw_known and isinstance(value, (str, int, float, bool))}
        field_specs = (
            ("bgm_change", "bgm_id", "bgm"), ("sound", "sound", None),
            ("transition", "transition", "transition"), ("background", "bg_name", "background"),
            ("background_effect", "bg_effect", "background_effect"), ("popup", "popup_file_name", None),
            ("voice", "voice_id", None), ("selection_group", "selection_group", None), ("teen_mode", "teen_mode", None),
        )
        field_events = []
        for event_type, key, resource_kind in field_specs:
            value = row.get(key)
            if value in (None, "", 0, False):
                continue
            resolved = _resource(resource_kind, value, self.resources) if resource_kind else {"raw_value": value, "resolved": None, "candidates": [], "mapping_status": "raw_only"}
            field_events.append({"event_index": len(field_events), "event_type": event_type, **resolved})
        return {
            "schema_version": SCHEMA_VERSION, "record_uid": f"scenario_{shard}:{row_index}", "source_file": source_file,
            "source_shard": shard, "source_row_index": row_index, "global_record_index": global_index, "group_id": group_id,
            "group_record_index": None, "previous_record_uid": None, "next_record_uid": None,
            "story_memberships": memberships, "primary_story_membership": memberships[0] if memberships else None,
            "raw": raw,
            "text": {"zh_tw": str(row.get("text_tw", "") or ""), "zh_cn": _t2s(str(row.get("text_tw", "") or "")),
                     "text_jp": str(row.get("text_jp", "") or ""), "text_en": str(row.get("text_en", "") or ""),
                     "text_th": str(row.get("text_th", "") or ""),
                     "kr_script_dialogue": kr_texts,
                     "localization_status": "official_tw" if row.get("text_tw") else ("missing_tw_with_kr_text" if dialogue else "empty_by_design")},
            "resources": {"background": _resource("background", row.get("bg_name"), self.resources),
                          "background_effect": _resource("background_effect", row.get("bg_effect"), self.resources),
                          "transition": _resource("transition", row.get("transition"), self.resources),
                          "bgm": _resource("bgm", row.get("bgm_id"), self.resources),
                          "sound": {"raw_value": row.get("sound"), "mapping_status": "raw_only"},
                          "popup": {"raw_value": row.get("popup_file_name"), "mapping_status": "raw_only"},
                          "voice": {"raw_value": row.get("voice_id"), "mapping_status": "raw_only"}},
            "field_events": field_events,
            "script_events": events,
            "node_kind": sorted(set([e["line_type"] for e in events] + (["dialogue"] if dialogue else []) + (["staging"] if has_staging else []))),
            # A silent character declaration is staging, not dialogue.
            "speakers": semantics["dialogue_speakers"],
            "dialogue_speakers": semantics["dialogue_speakers"],
            "declared_character_names": semantics["declared_character_names"],
            "staged_characters": semantics["staged_characters"],
            "screen_text_events": semantics["screen_text_events"],
            "transition_commands": semantics["transition_commands"],
            "semantic_kind": semantics["semantic_kind"],
            "visible_character_declarations": [e["slot"] for e in events if e["line_type"] == "character"],
            "has_dialogue": dialogue, "has_official_zh": bool(row.get("text_tw")), "has_staging": has_staging,
            "command_families": sorted({e["command_normalized"] for e in events if e.get("command_normalized")}),
            "resource_types": sorted({kind for kind, value in (("background", row.get("bg_name")), ("background_effect", row.get("bg_effect")), ("transition", row.get("transition")), ("bgm", row.get("bgm_id"))) if value not in (None, "", 0, False)}),
        }


def _t2s(value: str) -> str:
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(value)
    except Exception:
        return value


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def extract_corpus(repo_root: Path, output_root: Path, *, replace: bool = False) -> dict[str, Any]:
    repo_root, output_root = Path(repo_root), Path(output_root)
    if output_root.exists() and not replace:
        raise FileExistsError(f"output exists: {output_root}; pass replace=True")
    temp_root = Path(tempfile.mkdtemp(prefix="official-staging-", dir=str(output_root.parent)))
    try:
        (temp_root / "records").mkdir(); (temp_root / "indexes").mkdir(); (temp_root / "audit").mkdir(); (temp_root / "tools").mkdir()
        extractor = OfficialStagingExtractor(repo_root)
        counts = {"total": 0, "shards": {}}
        command_counts: Counter[str] = Counter(); unknown: list[dict[str, Any]] = []; unresolved: Counter[str] = Counter(); group_rows: dict[str, list[str]] = defaultdict(list); group_story: dict[str, list[dict[str, Any]]] = {}
        global_index = 0
        for shard, filename in enumerate(SHARD_NAMES):
            rows = _json_rows(repo_root / "ExcelDB" / filename)
            path = temp_root / "records" / f"scenario_{shard}.jsonl"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for row_index, row in enumerate(rows):
                    record = extractor.extract_row(row, f"ExcelDB/{filename}", shard, row_index, global_index)
                    group = record["group_id"]; record["group_record_index"] = len(group_rows[group]); group_rows[group].append(record["record_uid"])
                    group_story.setdefault(group, record["story_memberships"])
                    for event in record["script_events"]:
                        command = event.get("command_normalized")
                        if command: command_counts[command] += 1
                        if event.get("parse_status") == "unknown": unknown.append({"record_uid": record["record_uid"], "raw_line": event["raw_line"], "command": command})
                    for kind, resource in record["resources"].items():
                        if resource["mapping_status"] != "mapped" and resource["raw_value"] not in (None, "", 0, False): unresolved[f"{kind}:{resource['raw_value']}"] += 1
                    handle.write(_stable_json(record) + "\n")
                    global_index += 1
            counts["shards"][str(shard)] = len(rows); counts["total"] += len(rows)
        # Patch links in a deterministic second streaming pass. Only one pending row is held.
        for shard in range(3):
            path = temp_root / "records" / f"scenario_{shard}.jsonl"
            patched = path.with_suffix(".patched.jsonl")
            previous: dict[str, Any] | None = None
            with path.open("r", encoding="utf-8") as source, patched.open("w", encoding="utf-8", newline="\n") as target:
                for line in source:
                    current = json.loads(line)
                    group_uids = group_rows[current["group_id"]]
                    group_index = current["group_record_index"]
                    current["previous_record_uid"] = group_uids[group_index - 1] if group_index else None
                    current["next_record_uid"] = group_uids[group_index + 1] if group_index + 1 < len(group_uids) else None
                    if previous is not None:
                        target.write(_stable_json(previous) + "\n")
                    previous = current
                if previous is not None:
                    target.write(_stable_json(previous) + "\n")
            path.unlink()
            patched.rename(path)
        story_units = []
        for group_id, record_uids in sorted(group_rows.items(), key=lambda item: item[0]):
            story_units.append({"group_id": group_id, "record_count": len(record_uids), "record_uids": record_uids, "story_memberships": group_story.get(group_id, [])})
        (temp_root / "indexes" / "story_units.jsonl").write_text("\n".join(_stable_json(r) for r in story_units) + ("\n" if story_units else ""), encoding="utf-8")
        (temp_root / "indexes" / "command_catalog.json").write_text(_stable_json({"counts": dict(sorted(command_counts.items()))}) + "\n", encoding="utf-8")
        (temp_root / "indexes" / "resource_catalog.json").write_text(_stable_json(extractor.resources) + "\n", encoding="utf-8")
        (temp_root / "audit" / "unknown_commands.jsonl").write_text("\n".join(_stable_json(r) for r in unknown) + ("\n" if unknown else ""), encoding="utf-8")
        (temp_root / "audit" / "unresolved_resources.jsonl").write_text("\n".join(_stable_json({"resource": k, "count": v}) for k, v in sorted(unresolved.items())) + ("\n" if unresolved else ""), encoding="utf-8")
        unmapped = [{"group_id": group, "record_count": len(ids)} for group, ids in sorted(group_rows.items()) if not group_story.get(group)]
        (temp_root / "audit" / "unmapped_groups.jsonl").write_text("\n".join(_stable_json(r) for r in unmapped) + ("\n" if unmapped else ""), encoding="utf-8")
        report = {"record_counts": counts, "command_event_count": sum(command_counts.values()), "unknown_command_count": len(unknown), "unmapped_group_count": len(unmapped), "unresolved_resource_count": sum(unresolved.values())}
        (temp_root / "audit" / "extraction_report.json").write_text(_stable_json(report) + "\n", encoding="utf-8")
        source_meta = {}
        for filename in SHARD_NAMES:
            source = repo_root / "ExcelDB" / filename
            source_meta[filename] = {"bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        commit = ""
        try:
            import subprocess
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            pass
        shutil.copy2(Path(__file__), temp_root / "tools" / "extract_official_staging_corpus.py")
        manifest = {"schema_version": SCHEMA_VERSION, "extractor_version": "1.0", "official_repo_commit": commit,
                    "sources": source_meta, "record_counts": counts, "audit": report}
        manifest["files"] = {}
        for file in sorted(temp_root.rglob("*")):
            if file.is_file() and file.name != "manifest.json":
                manifest["files"][str(file.relative_to(temp_root)).replace("\\", "/")] = {"bytes": file.stat().st_size, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
        (temp_root / "manifest.json").write_text(_stable_json(manifest) + "\n", encoding="utf-8")
        if output_root.exists(): shutil.rmtree(output_root)
        temp_root.rename(output_root)
        return manifest
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    manifest = extract_corpus(args.repo_root, args.output_root, replace=args.replace)
    print(json.dumps({"records": manifest["record_counts"], "output": str(args.output_root)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
