from pathlib import Path

import merge_manual_annotation
from merge_manual_annotation import load_user_blocks, merge_annotation_sheet


def test_load_user_blocks_keys_by_stable_official_node_id(tmp_path: Path):
    source = tmp_path / "manual.txt"
    source.write_text(
        "# [官方节点 2 | scenario_0:108598]\n梓: 台词\n我的镜头标注\n"
        "# [官方节点 5 | scenario_0:108601]\n日富美: ……\n",
        encoding="utf-8",
    )
    blocks = load_user_blocks(source)
    assert blocks[2] == ["梓: 台词", "我的镜头标注"]
    assert blocks[5] == ["日富美: ……"]


def test_merge_sheet_keeps_official_face_emoticon_and_action_details(tmp_path: Path, monkeypatch):
    original = tmp_path / "manual.txt"
    original.write_text(
        "# [官方节点 2 | scenario_0:108598]\n梓: 台词\n用户镜头标注\n",
        encoding="utf-8",
    )
    records = [{
        "group_record_index": 2,
        "record_uid": "scenario_0:108598",
        "semantic_kind": "dialogue",
        "dialogue_speakers": ["아즈사"],
        "staged_characters": [{"slot": 3, "character_name_kr": "아즈사", "face_id": "02"}],
        "screen_text_events": [],
        "field_events": [{
            "event_type": "background", "raw_value": 1047754314,
            "resolved": "UIs/03_Scenario/01_Background/BG_Black", "mapping_status": "mapped",
        }],
        "text": {"zh_cn": "花子，这个问题该怎么解呢？"},
        "script_events": [
            {"line_type": "character", "slot": 3, "character_name_kr": "아즈사", "face_id": "02", "dialogue_kr": "text"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "a", "raw_line": "#3;a"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[반응]", "raw_line": "#3;em;[반응]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "greeting", "raw_line": "#3;greeting"},
        ],
    }]
    monkeypatch.setattr(merge_manual_annotation, "load_group_records", lambda *_: records)
    output_path = tmp_path / "merged.txt"
    merge_annotation_sheet(tmp_path, "31070", original, output_path)
    output = output_path.read_text(encoding="utf-8")
    assert "# 底层命令（含参数）：#3;a、#3;em;[반응]、#3;greeting" in output
    assert "# 官方人脸差分：梓(槽位3)=face 02" in output
    assert "# 官方气泡：梓(槽位3)=[반응]（反应）" in output
    assert "# 官方动作：梓(槽位3)=greeting（向下确认）" in output
    assert "# 官方场景字段：background=1047754314→UIs/03_Scenario/01_Background/BG_Black" in output
    assert "用户镜头标注" in output
