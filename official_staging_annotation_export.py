#!/usr/bin/env python3
"""Export official staging records into a human-editable annotation sheet.

The official database stores one visual action per row.  This exporter keeps
those raw row ids, but presents dialogue speakers, staged characters, screen
text, and transition commands as separate concepts so a silent staging row is
never rendered as fake dialogue.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from official_staging_corpus import _record_semantics


DEFAULT_NAME_MAP = {
    "아즈사": "梓",
    "하나코": "花子",
    "코하루": "小春",
    "히후미": "日富美",
    "아이리": "爱莉",
    "아이리 밴드": "爱莉",
    "아이리 학원제": "爱莉",
    "요시미": "好美",
    "요시미 밴드": "好美",
    "선생님": "老师",
    "先生": "老师",
}

OFFICIAL_EMOTICON_CN = {
    "[빠직]": "怒筋", "[재잘]": "叽喳", "…": "沉默", "[...]": "沉默",
    "[!]": "惊叹", "[하트]": "爱心", "[음표]": "音符", "[?]": "疑问",
    "[반응]": "反应", "[///]": "脸红", "[?!]": "惊疑", "[땀]": "冷汗",
    "[반짝]": "闪亮", "[속상함]": "不悦（Upset）", "[딴생각]": "走神",
    "[전구]": "灵光一闪（Bulb）", "[세로선]": "阴沉竖线（Sad）",
    "[한숨]": "叹气（Sigh）", "[스팀]": "冒烟（Steam）",
    "[훌쩍]": "抽泣（Tear）", "[zzz]": "睡眠（Zzz）",
    "{Bulb}": "灵光一闪（Bulb）", "{Sad}": "悲伤（Sad）",
    "{Sigh}": "叹气（Sigh）", "{Steam}": "冒烟（Steam）",
    "{Tear}": "落泪（Tear）", "{Zzz}": "瞌睡（Zzz）",
}

OFFICIAL_ACTION_CN = {
    "greeting": "向下确认", "falldownl": "向左倒", "falldownr": "向右倒",
    "stiff": "小颤抖", "shake": "大颤抖", "jump": "跳", "hophop": "蹦跳",
}

OFFICIAL_SHAPE_CN = {
    "sig": "通讯（shapeOverride=1）",
    "black": "黑屏剪影（shapeOverride=2）",
    "closeup": "特写（shapeOverride=4）",
    # The corpus contains this token, but the AA shape enum has no separately
    # verified white value. Keep the original command visible without guessing.
    "white": "白色效果（原始命令，枚举待确认）",
}

CAMERA_COMMANDS = {"zmc", "zmlt", "bgshake"}


def _enrich(record: dict[str, Any]) -> dict[str, Any]:
    """Support both new records and sealed pre-1.1 corpus records."""
    result = dict(record)
    events = list(record.get("script_events") or [])
    semantics = _record_semantics(events, str((record.get("text") or {}).get("zh_cn") or ""))
    for key, value in semantics.items():
        result.setdefault(key, value)
    result.setdefault("dialogue_speakers", semantics["dialogue_speakers"])
    result.setdefault("speakers", semantics["dialogue_speakers"])
    return result


def _attach_catalog_rows(record: dict[str, Any], catalog: dict[str, Any]) -> None:
    """Restore resource metadata omitted from the compact JSONL candidates."""
    for event in record.get("field_events") or []:
        kind = str(event.get("event_type") or "")
        catalog_candidates = (catalog.get(kind) or {}).get(str(event.get("raw_value"))) or []
        if not catalog_candidates:
            continue
        candidates = event.setdefault("candidates", [])
        for catalog_candidate in catalog_candidates:
            source = catalog_candidate.get("source")
            match = next((item for item in candidates if item.get("source") == source), None)
            if match is None:
                candidates.append(dict(catalog_candidate))
            elif not match.get("row") and catalog_candidate.get("row"):
                match["row"] = catalog_candidate["row"]


def load_group_records(corpus_root: Path, group_id: str) -> list[dict[str, Any]]:
    catalog_path = Path(corpus_root) / "indexes" / "resource_catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    records: list[dict[str, Any]] = []
    for path in sorted((Path(corpus_root) / "records").glob("scenario_*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if str(record.get("group_id")) == str(group_id):
                    _attach_catalog_rows(record, catalog)
                    records.append(_enrich(record))
    return sorted(records, key=lambda item: (int(item.get("group_record_index") or 0), int(item.get("global_record_index") or 0)))


def _commands(record: dict[str, Any]) -> list[str]:
    return [str(event.get("command_normalized") or "") for event in record.get("script_events") or [] if event.get("command_normalized")]


def _command_details(record: dict[str, Any]) -> list[str]:
    """Return lossless command text instead of command family names only."""
    details: list[str] = []
    for event in record.get("script_events") or []:
        if not event.get("command_normalized"):
            continue
        raw_line = str(event.get("raw_line") or "").strip()
        if not raw_line:
            command = str(event.get("command_raw") or event.get("command_normalized") or "")
            args = [str(value) for value in event.get("arguments_raw") or []]
            slot = event.get("slot")
            prefix = f"#{slot};" if isinstance(slot, int) else "#"
            raw_line = prefix + ";".join([command, *args])
        details.append(raw_line)
    return details


def _slot_character(record: dict[str, Any], slot: Any, spatial: dict[str, dict[str, Any]]) -> str:
    if not isinstance(slot, int):
        return ""
    uid = str(record.get("record_uid") or "")
    state = (spatial.get(uid) or {}).get("after") or {}
    item = state.get(slot) or {}
    return str(item.get("character_name_kr") or "")


def _performance_details(
    record: dict[str, Any], spatial: dict[str, dict[str, Any]], name_map: dict[str, str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Expose camera, shape, dialogue focus, and explicit dimming separately."""
    effects: list[str] = []
    camera: list[str] = []
    focus: list[str] = []
    secondary: list[str] = []
    for event in record.get("script_events") or []:
        if event.get("line_type") == "character" and str(event.get("dialogue_kr") or "").strip():
            character_kr = str(event.get("character_name_kr") or "")
            character = _name(character_kr, name_map)
            detail = f"{character}(槽位{event.get('slot')})=说话人默认高光"
            if detail not in focus:
                focus.append(detail)
            continue
        command = str(event.get("command_normalized") or "")
        if command in CAMERA_COMMANDS:
            raw = str(event.get("raw_line") or "").strip()
            detail = raw or command
            if detail not in camera:
                camera.append(detail)
            continue
        slot = event.get("slot")
        character_kr = _slot_character(record, slot, spatial)
        owner = _name(character_kr, name_map) if character_kr else f"槽位{slot}"
        if command in OFFICIAL_SHAPE_CN:
            detail = f"{owner}(槽位{slot})={OFFICIAL_SHAPE_CN[command]}"
            if detail not in effects:
                effects.append(detail)
        elif command == "h":
            # Paired AAP/AAS output proves #N;h is emitted for the secondary,
            # dimmed slot despite AA's misleading highlightedSlotNums field name.
            detail = f"{owner}(槽位{slot})=次要/变暗（#{slot};h）"
            if detail not in secondary:
                secondary.append(detail)
    return effects, camera, focus, secondary


def _field_event_details(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Expose top-level scene fields that are not part of script_kr commands."""
    scene: list[str] = []
    voices: list[str] = []
    for event in record.get("field_events") or []:
        kind = str(event.get("event_type") or "unknown")
        raw = event.get("raw_value")
        if kind == "voice":
            voices.append(str(raw))
            continue
        if kind == "transition":
            row = {}
            candidates = event.get("candidates") or []
            if candidates and isinstance(candidates[0], dict):
                row = candidates[0].get("row") or {}
            if isinstance(row, dict) and row:
                scene.append(
                    f"transition={raw}"
                    f"(in={row.get('transition_in')}/{row.get('transition_in_duration')}ms,"
                    f"out={row.get('transition_out')}/{row.get('transition_out_duration')}ms)"
                )
            else:
                scene.append(f"transition={raw}(映射={event.get('mapping_status') or 'unknown'})")
            continue
        resolved = event.get("resolved")
        if isinstance(resolved, list):
            resolved_text = ",".join(str(value) for value in resolved)
        elif isinstance(resolved, dict):
            resolved_text = json.dumps(resolved, ensure_ascii=False, sort_keys=True)
        else:
            resolved_text = str(resolved or "")
        detail = f"{kind}={raw}"
        if resolved_text:
            detail += f"→{resolved_text}"
        elif event.get("mapping_status"):
            detail += f"(映射={event.get('mapping_status')})"
        scene.append(detail)
    return scene, voices


def resolve_spatial_states(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Track array index, rendered position, and frame state separately.

    In the unpacked format the leading number in ``N;character;face`` and
    ``#N;command`` is the ``characters[N]`` array index.  ``#N;mK`` changes
    that record's rendered position to K.  A later row can legally keep N or
    move the same character record to another array index, so N must never be
    presented as a physical position or an identity key.

    The result deliberately distinguishes engine-frame state from narrative
    presence: ``#all;hide`` clears the current rendered frame, but cannot
    prove that every character has left the story world.
    """
    state: dict[int, dict[str, Any]] = {}
    resolved: dict[str, dict[str, Any]] = {}

    def snapshot() -> dict[int, dict[str, Any]]:
        return {slot: dict(value) for slot, value in state.items()}

    for record in records:
        uid = str(record.get("record_uid") or "")
        before = snapshot()
        frame_cleared = False
        reindexed: list[dict[str, Any]] = []
        for event in record.get("script_events") or []:
            line_type = event.get("line_type")
            if line_type == "character":
                slot = event.get("slot")
                name = str(event.get("character_name_kr") or "").strip()
                if not isinstance(slot, int) or not name:
                    continue
                previous = state.get(slot)
                if previous and previous.get("character_name_kr") == name:
                    previous["face_id"] = event.get("face_id") or previous.get("face_id")
                    previous["visible"] = True
                    previous["visibility_source"] = "character_declaration"
                else:
                    # The same character can move to a different array index
                    # on the next ScriptData row.  Carry the position forward
                    # and remove the old record so it cannot become a phantom
                    # duplicate in the exported staging sheet.
                    prior_slots = [
                        old_slot for old_slot, item in state.items()
                        if old_slot != slot
                        and item.get("character_name_kr") == name
                    ]
                    if len(prior_slots) == 1:
                        old_slot = prior_slots[0]
                        carried = state.pop(old_slot)
                        carried["array_index"] = slot
                        carried["face_id"] = event.get("face_id") or carried.get("face_id")
                        carried["visible"] = True
                        carried["visibility_source"] = "character_declaration"
                        state[slot] = carried
                        reindexed.append({
                            "character_name_kr": name,
                            "from_array_index": old_slot,
                            "to_array_index": slot,
                            "physical_position": carried.get("physical_position"),
                        })
                    else:
                        state[slot] = {
                            "array_index": slot,
                            "character_name_kr": name,
                            "physical_position": slot,
                            "face_id": event.get("face_id"),
                            # A character record is present in this ScriptData
                            # before any same-node appearance/disappearance
                            # command is applied.
                            "visible": True,
                            "visibility_source": "character_declaration",
                        }
                continue
            command = str(event.get("command_normalized") or "")
            args = [str(value).strip().lower() for value in event.get("arguments_raw") or []]
            if command == "all" and "hide" in args:
                state.clear()
                frame_cleared = True
                continue
            slot = event.get("slot")
            if not isinstance(slot, int) or slot not in state:
                continue
            if command in {"a", "al", "ar"}:
                state[slot]["visible"] = True
                state[slot]["visibility_source"] = command
            elif command in {"d", "dl", "dr", "hide"}:
                state[slot]["visible"] = False
                state[slot]["visibility_source"] = command
            elif command.startswith("m") and command[1:].isdigit():
                target = int(command[1:])
                if 1 <= target <= 5:
                    state[slot]["physical_position"] = target
        resolved[uid] = {
            "before": before,
            "after": snapshot(),
            "frame_cleared": frame_cleared,
            "reindexed": reindexed,
        }
    return resolved


def _has_wait(record: dict[str, Any]) -> bool:
    return "wait" in _commands(record)


def _has_dialogue(record: dict[str, Any]) -> bool:
    return bool(record.get("dialogue_speakers")) or any(
        event.get("line_type") == "narration" and str(event.get("dialogue_kr") or "").strip()
        for event in record.get("script_events") or []
    )


def build_visual_beats(records: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group low-level setup rows without erasing their original boundaries.

    A wait marks an independent no-dialogue display beat.  Otherwise, silent
    setup rows immediately before a dialogue row are presented with that row,
    which matches how the official script applies a cut/reveal before the next
    line.  Every raw record remains inside exactly one returned beat.
    """
    beats: list[list[dict[str, Any]]] = []
    pending: list[dict[str, Any]] = []
    for record in records:
        if _has_dialogue(record):
            if pending and any(_has_wait(item) for item in pending):
                beats.append(pending)
                pending = []
            beats.append(pending + [record])
            pending = []
            continue
        if record.get("semantic_kind") in {"screen_text", "narration"}:
            if pending:
                beats.append(pending)
                pending = []
            beats.append([record])
            continue
        pending.append(record)
        if _has_wait(record):
            beats.append(pending)
            pending = []
    if pending:
        beats.append(pending)
    return beats


def _name(value: str, name_map: dict[str, str]) -> str:
    return name_map.get(value, value or "未知角色")


def _record_label(record: dict[str, Any]) -> str:
    uid = str(record.get("record_uid") or "")
    index = record.get("group_record_index")
    return f"节点 {index} | {uid}" if index is not None else uid


def render_annotation_text(
    records: Iterable[dict[str, Any]],
    *,
    title: str = "主线 3-1-7《备考》",
    name_map: dict[str, str] | None = None,
) -> str:
    name_map = {**DEFAULT_NAME_MAP, **(name_map or {})}
    records = list(records)
    beats = build_visual_beats(records)
    spatial = resolve_spatial_states(records)
    lines = [
        f"# 官方 {title} 手工演出标注底稿（修正版）",
        "# 槽位说明：#N 的 N 是 characters 数组下标；mK 的 K 才是画面位置。数组下标可在后续节点迁移。",
        "# 说明：角色声明只表示当前引擎节点中被放置/操作的角色；只有‘实际说话人’才是对白归属。",
        "# #all;hide 和退场命令只描述当前画面状态，不能推断角色在叙事世界中离场。",
        "# 无对白节拍不会伪造旁白；请在对应节拍后补 camera / face / emo / act / fx / reveal / enter / exit / Wait。",
        "",
    ]
    for beat_index, beat in enumerate(beats):
        first = beat[0]
        last = beat[-1]
        indices = [str(item.get("group_record_index")) for item in beat]
        lines.append(f"# [视觉节拍 {beat_index} | 原始节点 {indices[0]}-{indices[-1]}]")
        lines.append("# 原始记录: " + ", ".join(_record_label(item) for item in beat))
        kinds = ", ".join(dict.fromkeys(str(item.get("semantic_kind") or "unknown") for item in beat))
        lines.append(f"# 节拍类型: {kinds}")
        staged: list[str] = []
        speakers: list[str] = []
        commands: list[str] = []
        command_details: list[str] = []
        official_faces: list[str] = []
        official_emoticons: list[str] = []
        official_actions: list[str] = []
        official_effects: list[str] = []
        official_camera: list[str] = []
        official_focus: list[str] = []
        official_secondary: list[str] = []
        scene_fields: list[str] = []
        voice_ids: list[str] = []
        screen_text: list[str] = []
        for record in beat:
            for item in record.get("staged_characters") or []:
                label = f"{_name(str(item.get('character_name_kr') or ''), name_map)}(槽位{item.get('slot')})"
                if label not in staged:
                    staged.append(label)
            for speaker in record.get("dialogue_speakers") or []:
                label = _name(str(speaker), name_map)
                if label not in speakers:
                    speakers.append(label)
            for command in _commands(record):
                if command not in commands:
                    commands.append(command)
            node = record.get("group_record_index")
            command_details.extend(
                f"节点{node}:{detail}" for detail in _command_details(record)
            )
            record_scene_fields, record_voice_ids = _field_event_details(record)
            scene_fields.extend(f"节点{node}:{detail}" for detail in record_scene_fields)
            voice_ids.extend(f"节点{node}:{detail}" for detail in record_voice_ids)
            effects, camera, focus, secondary = _performance_details(record, spatial, name_map)
            official_effects.extend(f"节点{node}:{detail}" for detail in effects)
            official_camera.extend(f"节点{node}:{detail}" for detail in camera)
            official_focus.extend(f"节点{node}:{detail}" for detail in focus)
            official_secondary.extend(f"节点{node}:{detail}" for detail in secondary)
            for event in record.get("script_events") or []:
                if event.get("line_type") == "character":
                    character = _name(str(event.get("character_name_kr") or ""), name_map)
                    detail = f"{character}(槽位{event.get('slot')})=face {event.get('face_id')}"
                    if detail not in official_faces:
                        official_faces.append(detail)
                    continue
                command = str(event.get("command_normalized") or "")
                slot = event.get("slot")
                character_kr = _slot_character(record, slot, spatial)
                owner = _name(character_kr, name_map) if character_kr else f"槽位{slot}"
                if command == "em":
                    raw = str(event.get("emoticon_raw") or "").strip()
                    label = OFFICIAL_EMOTICON_CN.get(raw, "未映射")
                    detail = f"{owner}(槽位{slot})={raw}（{label}）"
                    if detail not in official_emoticons:
                        official_emoticons.append(detail)
                elif command in OFFICIAL_ACTION_CN:
                    detail = f"{owner}(槽位{slot})={command}（{OFFICIAL_ACTION_CN[command]}）"
                    if detail not in official_actions:
                        official_actions.append(detail)
            for event in record.get("screen_text_events") or []:
                value = str(event.get("screen_text_raw") or "").strip()
                if value and value not in screen_text:
                    screen_text.append(value)
            text_value = str((record.get("text") or {}).get("zh_cn") or "").strip()
            if record.get("semantic_kind") == "screen_text" and text_value and text_value not in screen_text:
                screen_text.append(text_value)
        lines.append("# 数组槽立绘声明（N 不是画面位置或说话人）: " + ("、".join(staged) if staged else "无"))
        lines.append("# 实际说话人: " + ("、".join(speakers) if speakers else "无"))
        lines.append("# 底层命令: " + ("、".join(commands) if commands else "无"))
        lines.append("# 底层命令（含参数）: " + ("、".join(command_details) if command_details else "无"))
        lines.append("# 官方人脸差分: " + ("、".join(official_faces) if official_faces else "无"))
        lines.append("# 官方气泡: " + ("、".join(official_emoticons) if official_emoticons else "无"))
        lines.append("# 官方动作: " + ("、".join(official_actions) if official_actions else "无"))
        lines.append("# 官方立绘效果: " + ("、".join(official_effects) if official_effects else "无"))
        lines.append("# 官方镜头/运镜: " + ("、".join(official_camera) if official_camera else "无"))
        lines.append("# 官方对话焦点（默认高光）: " + ("、".join(official_focus) if official_focus else "无"))
        lines.append("# 官方次要/变暗（#N;h）: " + ("、".join(official_secondary) if official_secondary else "无"))
        lines.append("# 官方场景字段: " + ("、".join(scene_fields) if scene_fields else "无"))
        lines.append("# 官方语音 ID: " + ("、".join(voice_ids) if voice_ids else "无"))
        migrations: list[str] = []
        for record in beat:
            state_change = spatial.get(str(record.get("record_uid") or ""), {})
            for move in state_change.get("reindexed") or []:
                label = _name(str(move.get("character_name_kr") or ""), name_map)
                detail = (
                    f"{label}:数组槽{move.get('from_array_index')}→{move.get('to_array_index')}"
                    f"（画面{move.get('physical_position')}不变）"
                )
                if detail not in migrations:
                    migrations.append(detail)
        lines.append("# 本节拍数组槽迁移: " + ("、".join(migrations) if migrations else "无"))

        final_state = spatial.get(str(last.get("record_uid") or ""), {})
        positions: list[str] = []
        for item in (final_state.get("after") or {}).values():
            label = _name(str(item.get("character_name_kr") or ""), name_map)
            status = "画面可见" if item.get("visible") else f"本节点{item.get('visibility_source') or '隐藏'}后不可见"
            value = f"{label}=画面{item.get('physical_position')}（数组槽{item.get('array_index')}，{status}）"
            if value not in positions:
                positions.append(value)
        if not positions and final_state.get("frame_cleared"):
            positions.append("无（#all;hide 清空当前镜头；不推断叙事退场）")
        lines.append("# 本节拍处理后的引擎画面状态: " + ("、".join(positions) if positions else "无"))
        if screen_text:
            lines.append("屏幕文字: " + " / ".join(screen_text))
        dialogue_record = next((item for item in beat if _has_dialogue(item)), None)
        if dialogue_record is not None:
            text_value = str((dialogue_record.get("text") or {}).get("zh_cn") or "").strip()
            event_speaker = next(
                (event.get("character_name_kr") for event in dialogue_record.get("script_events") or [] if event.get("line_type") == "character" and str(event.get("dialogue_kr") or "").strip()),
                None,
            )
            if event_speaker:
                lines.append(f"{_name(str(event_speaker), name_map)}: {text_value}")
            else:
                lines.append(f"旁白: {text_value}")
        else:
            lines.append("# 无对白视觉节拍（不是旁白；请按视频标注镜头和动作）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_group(corpus_root: Path, group_id: str, output: Path, *, title: str = "主线 3-1-7《备考》") -> Path:
    records = load_group_records(corpus_root, group_id)
    if not records:
        raise ValueError(f"group not found: {group_id}")
    output = Path(output)
    output.write_text(render_annotation_text(records, title=title), encoding="utf-8", newline="\n")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--group-id", default="31070")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="主线 3-1-7《备考》")
    args = parser.parse_args()
    path = export_group(args.corpus_root, args.group_id, args.output, title=args.title)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
