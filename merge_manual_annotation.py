#!/usr/bin/env python3
"""Merge corrected machine semantics into an existing manual annotation sheet.

The user's original node blocks are copied byte-for-byte (apart from the
header separator) and remain authoritative.  The generated copy only adds a
machine-semantic sidebar keyed by the stable official node id.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from official_staging_annotation_export import (
    DEFAULT_NAME_MAP,
    OFFICIAL_ACTION_CN,
    OFFICIAL_EMOTICON_CN,
    _command_details,
    _field_event_details,
    _performance_details,
    _slot_character,
    build_visual_beats,
    load_group_records,
    resolve_spatial_states,
)


NODE_RE = re.compile(r"^# \[官方节点 (\d+) \| ([^]]+)\]")


def load_user_blocks(path: Path) -> dict[int, list[str]]:
    blocks: dict[int, list[str]] = {}
    current: int | None = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = NODE_RE.match(line)
        if match:
            current = int(match.group(1))
            blocks[current] = []
            continue
        if current is not None:
            blocks[current].append(line)
    return blocks


def merge_annotation_sheet(corpus_root: Path, group_id: str, original: Path, output: Path) -> Path:
    records = load_group_records(corpus_root, group_id)
    if not records:
        raise ValueError(f"group not found: {group_id}")
    user_blocks = load_user_blocks(original)
    beat_by_uid = {
        record["record_uid"]: beat_index
        for beat_index, beat in enumerate(build_visual_beats(records))
        for record in beat
    }
    spatial = resolve_spatial_states(records)
    lines = [
        "# 官方主线 3-1-7 手工演出标注底稿（保留原标注 + 机器语义旁注）",
        "# 规则：以下‘用户原标注’内容来自原文件，保持原样并优先于机器推断。",
        "# 机器语义只用于解释解包数据，不是官方镜头答案。",
        "",
    ]
    for record in records:
        node = int(record.get("group_record_index") or 0)
        uid = str(record.get("record_uid") or "")
        staged = []
        for item in record.get("staged_characters") or []:
            label = f"{DEFAULT_NAME_MAP.get(str(item.get('character_name_kr') or ''), str(item.get('character_name_kr') or '未知角色'))}(槽位{item.get('slot')})"
            if label not in staged:
                staged.append(label)
        speakers = [DEFAULT_NAME_MAP.get(str(value), str(value)) for value in record.get("dialogue_speakers") or []]
        commands = [str(event.get("command_normalized") or "") for event in record.get("script_events") or [] if event.get("command_normalized")]
        faces: list[str] = []
        emoticons: list[str] = []
        actions: list[str] = []
        effects, camera, focus, secondary = _performance_details(record, spatial, DEFAULT_NAME_MAP)
        for event in record.get("script_events") or []:
            if event.get("line_type") == "character":
                character_kr = str(event.get("character_name_kr") or "")
                character = DEFAULT_NAME_MAP.get(character_kr, character_kr or "未知角色")
                detail = f"{character}(槽位{event.get('slot')})=face {event.get('face_id')}"
                if detail not in faces:
                    faces.append(detail)
                continue
            command = str(event.get("command_normalized") or "")
            slot = event.get("slot")
            character_kr = _slot_character(record, slot, spatial)
            owner = DEFAULT_NAME_MAP.get(character_kr, character_kr) if character_kr else f"槽位{slot}"
            if command == "em":
                raw = str(event.get("emoticon_raw") or "").strip()
                detail = f"{owner}(槽位{slot})={raw}（{OFFICIAL_EMOTICON_CN.get(raw, '未映射')}）"
                if detail not in emoticons:
                    emoticons.append(detail)
            elif command in OFFICIAL_ACTION_CN:
                detail = f"{owner}(槽位{slot})={command}（{OFFICIAL_ACTION_CN[command]}）"
                if detail not in actions:
                    actions.append(detail)
        lines.append(f"# [官方节点 {node} | {uid}]")
        lines.append(f"# 机器语义：{record.get('semantic_kind') or 'unknown'}；所属视觉节拍 {beat_by_uid.get(uid, '?')}")
        lines.append("# 控制槽声明（不等于实际画面位置或说话人）：" + ("、".join(staged) if staged else "无"))
        lines.append("# 实际说话人：" + ("、".join(speakers) if speakers else "无"))
        lines.append("# 底层命令：" + ("、".join(dict.fromkeys(commands)) if commands else "无"))
        lines.append("# 底层命令（含参数）：" + ("、".join(_command_details(record)) if commands else "无"))
        lines.append("# 官方人脸差分：" + ("、".join(faces) if faces else "无"))
        lines.append("# 官方气泡：" + ("、".join(emoticons) if emoticons else "无"))
        lines.append("# 官方动作：" + ("、".join(actions) if actions else "无"))
        lines.append("# 官方立绘效果：" + ("、".join(effects) if effects else "无"))
        lines.append("# 官方镜头/运镜：" + ("、".join(camera) if camera else "无"))
        lines.append("# 官方对话焦点（默认高光）：" + ("、".join(focus) if focus else "无"))
        lines.append("# 官方次要/变暗（#N;h）：" + ("、".join(secondary) if secondary else "无"))
        scene_fields, voice_ids = _field_event_details(record)
        lines.append("# 官方场景字段：" + ("、".join(scene_fields) if scene_fields else "无"))
        lines.append("# 官方语音 ID：" + ("、".join(voice_ids) if voice_ids else "无"))
        positions = []
        for item in (spatial.get(uid, {}).get("after") or {}).values():
            label = f"{DEFAULT_NAME_MAP.get(str(item.get('character_name_kr') or ''), str(item.get('character_name_kr') or '未知角色'))}=画面{item.get('physical_position')}"
            if label not in positions:
                positions.append(label)
        lines.append("# 本节点处理后的跟踪画面位置：" + ("、".join(positions) if positions else "无"))
        text = str((record.get("text") or {}).get("zh_cn") or "").strip()
        if text and not speakers and record.get("semantic_kind") == "screen_text":
            lines.append(f"# 屏幕文字定位：{text}")
        if node in user_blocks:
            lines.append("# 用户原标注（原文保留）：")
            block = user_blocks[node]
            while block and not block[0].strip():
                block.pop(0)
            while block and not block[-1].strip():
                block.pop()
            lines.extend(block)
        else:
            lines.append("# 用户原文件未包含这一节点的标注；机器字段不能替代视频观察。")
        lines.append("")
    Path(output).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return Path(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--group-id", default="31070")
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(merge_annotation_sheet(args.corpus_root, args.group_id, args.original, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
