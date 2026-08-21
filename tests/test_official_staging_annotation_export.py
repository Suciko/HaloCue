import json

from official_staging_annotation_export import (
    build_visual_beats,
    load_group_records,
    render_annotation_text,
    resolve_spatial_states,
)


def _record(index, *, kind, script_events=None, speakers=None, staged=None, text=""):
    return {
        "group_record_index": index,
        "record_uid": f"scenario_0:{index}",
        "semantic_kind": kind,
        "script_events": script_events or [],
        "dialogue_speakers": speakers or [],
        "staged_characters": staged or [],
        "screen_text_events": [],
        "text": {"zh_cn": text},
    }


def test_visual_beats_keep_wait_as_independent_no_dialogue_beat():
    records = [
        _record(15, kind="transition", script_events=[{"command_normalized": "all"}]),
        _record(16, kind="staging", staged=[{"slot": 5, "character_name_kr": "아즈사"}]),
        _record(17, kind="dialogue", speakers=["아즈사"], text="花子，这篇文章是什么？"),
        _record(18, kind="wait", script_events=[{"command_normalized": "wait"}], staged=[{"slot": 1, "character_name_kr": "하나코"}]),
        _record(19, kind="dialogue", speakers=["하나코"], text="这是开头。"),
    ]
    beats = build_visual_beats(records)
    assert [[item["group_record_index"] for item in beat] for beat in beats] == [[15, 16, 17], [18], [19]]


def test_render_does_not_turn_silent_staging_into_speaker_or_narrator():
    records = [
        _record(
            15,
            kind="staging",
            script_events=[{"command_normalized": "all"}],
            staged=[{"slot": 5, "character_name_kr": "아즈사"}, {"slot": 1, "character_name_kr": "하나코"}],
        ),
        _record(
            16,
            kind="dialogue",
            speakers=["아즈사"],
            staged=[{"slot": 5, "character_name_kr": "아즈사"}, {"slot": 1, "character_name_kr": "하나코"}],
            text="花子，这篇文章是什么？",
            script_events=[{"line_type": "character", "character_name_kr": "아즈사", "dialogue_kr": "text"}],
        ),
    ]
    output = render_annotation_text(records)
    assert "# 数组槽立绘声明（N 不是画面位置或说话人）: 梓(槽位5)、花子(槽位1)" in output
    assert "梓: 花子，这篇文章是什么？" in output
    assert "旁白: 花子，这篇文章是什么？" not in output
    assert "# 无对白视觉节拍（不是旁白" not in output


def test_render_preserves_official_face_emoticon_action_and_raw_arguments():
    records = [
        _record(
            2,
            kind="dialogue",
            speakers=["아즈사"],
            staged=[{"slot": 3, "character_name_kr": "아즈사", "face_id": "02"}],
            text="花子，这个问题该怎么解呢？",
            script_events=[
                {
                    "line_type": "character", "slot": 3, "character_name_kr": "아즈사",
                    "face_id": "02", "dialogue_kr": "text", "raw_line": "3;아즈사;02;text",
                },
                {
                    "line_type": "slot_command", "slot": 3, "command_normalized": "a",
                    "command_raw": "a", "arguments_raw": [], "raw_line": "#3;a",
                },
                {
                    "line_type": "slot_command", "slot": 3, "command_normalized": "em",
                    "command_raw": "em", "arguments_raw": ["[반응]"],
                    "emoticon_raw": "[반응]", "raw_line": "#3;em;[반응]",
                },
                {
                    "line_type": "slot_command", "slot": 3, "command_normalized": "stiff",
                    "command_raw": "stiff", "arguments_raw": [], "raw_line": "#3;stiff",
                },
            ],
        ),
    ]
    output = render_annotation_text(records)
    assert "# 底层命令（含参数）: 节点2:#3;a、节点2:#3;em;[반응]、节点2:#3;stiff" in output
    assert "# 官方人脸差分: 梓(槽位3)=face 02" in output
    assert "# 官方气泡: 梓(槽位3)=[반응]（反应）" in output
    assert "# 官方动作: 梓(槽位3)=stiff（小颤抖）" in output


def test_render_distinguishes_upset_from_steam_and_maps_new_official_aliases():
    record = _record(
        2,
        kind="dialogue",
        speakers=["아즈사"],
        staged=[{"slot": 3, "character_name_kr": "아즈사"}],
        text="测试",
        script_events=[
            {"line_type": "character", "slot": 3, "character_name_kr": "아즈사", "dialogue_kr": "测试"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[속상함]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[스팀]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[한숨]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[세로선]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[훌쩍]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[전구]"},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "em", "emoticon_raw": "[zzz]"},
        ],
    )

    output = render_annotation_text([record])

    assert "[속상함]（不悦（Upset））" in output
    assert "[스팀]（冒烟（Steam））" in output
    assert "[한숨]（叹气（Sigh））" in output
    assert "[세로선]（阴沉竖线（Sad））" in output
    assert "[훌쩍]（抽泣（Tear））" in output
    assert "[전구]（灵光一闪（Bulb））" in output
    assert "[zzz]（睡眠（Zzz））" in output


def test_render_exposes_shape_camera_focus_and_secondary_state():
    record = _record(
        9,
        kind="dialogue",
        speakers=["아즈사"],
        staged=[{"slot": 3, "character_name_kr": "아즈사"}, {"slot": 4, "character_name_kr": "하나코"}],
        text="测试",
        script_events=[
            {"line_type": "character", "slot": 3, "character_name_kr": "아즈사", "face_id": "01", "dialogue_kr": "测试"},
            {"line_type": "character", "slot": 4, "character_name_kr": "하나코", "face_id": "02", "dialogue_kr": ""},
            {"line_type": "slot_command", "slot": 3, "command_normalized": "closeup", "raw_line": "#3;closeup"},
            {"line_type": "slot_command", "slot": 4, "command_normalized": "h", "raw_line": "#4;h"},
            {"line_type": "camera", "command_normalized": "zmc", "raw_line": "#zmc;instant;0,0;1300"},
        ],
    )

    output = render_annotation_text([record])

    assert "# 官方立绘效果: 节点9:梓(槽位3)=特写（shapeOverride=4）" in output
    assert "# 官方镜头/运镜: 节点9:#zmc;instant;0,0;1300" in output
    assert "# 官方对话焦点（默认高光）: 节点9:梓(槽位3)=说话人默认高光" in output
    assert "# 官方次要/变暗（#N;h）: 节点9:花子(槽位4)=次要/变暗（#4;h）" in output


def test_render_keeps_repeated_commands_in_original_order():
    records = [
        _record(
            3,
            kind="wait",
            script_events=[
                {"line_type": "wait", "command_normalized": "wait", "raw_line": "#wait;500"},
                {"line_type": "wait", "command_normalized": "wait", "raw_line": "#wait;500"},
            ],
        ),
    ]
    output = render_annotation_text(records)
    assert "节点3:#wait;500、节点3:#wait;500" in output


def test_render_includes_background_transition_duration_and_sound_fields():
    record = _record(15, kind="transition", script_events=[{
        "line_type": "command", "command_normalized": "all", "raw_line": "#all;hide",
    }])
    record["field_events"] = [
        {
            "event_type": "transition", "raw_value": 348351892, "mapping_status": "mapped",
            "candidates": [{"row": {
                "transition_in": "Ᵹ", "transition_in_duration": 1,
                "transition_out": "Ᵹ", "transition_out_duration": 1000,
            }}],
        },
        {
            "event_type": "background", "raw_value": 1047754314,
            "resolved": "UIs/03_Scenario/01_Background/BG_Black", "mapping_status": "mapped",
        },
        {"event_type": "sound", "raw_value": "SE_Door_Open", "mapping_status": "raw_only"},
        {"event_type": "voice", "raw_value": 123456, "mapping_status": "raw_only"},
    ]
    output = render_annotation_text([record])
    assert "节点15:transition=348351892(in=Ᵹ/1ms,out=Ᵹ/1000ms)" in output
    assert "节点15:background=1047754314→UIs/03_Scenario/01_Background/BG_Black" in output
    assert "节点15:sound=SE_Door_Open(映射=raw_only)" in output
    assert "# 官方语音 ID: 节点15:123456" in output


def test_load_group_records_restores_transition_duration_from_resource_catalog(tmp_path):
    records_dir = tmp_path / "records"
    indexes_dir = tmp_path / "indexes"
    records_dir.mkdir()
    indexes_dir.mkdir()
    record = _record(15, kind="transition")
    record.update({
        "group_id": "31070",
        "field_events": [{
            "event_type": "transition", "raw_value": 348351892,
            "mapping_status": "mapped",
            "candidates": [{"name": {"in": "Ᵹ", "out": "Ᵹ"}, "source": "ScenarioTransitionExcel.json"}],
        }],
    })
    (records_dir / "scenario_0.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    (indexes_dir / "resource_catalog.json").write_text(json.dumps({
        "transition": {"348351892": [{
            "name": {"in": "Ᵹ", "out": "Ᵹ"},
            "source": "ScenarioTransitionExcel.json",
            "row": {
                "transition_in": "Ᵹ", "transition_in_duration": 1,
                "transition_out": "Ᵹ", "transition_out_duration": 1000,
            },
        }]},
    }, ensure_ascii=False), encoding="utf-8")

    output = render_annotation_text(load_group_records(tmp_path, "31070"))

    assert "节点15:transition=348351892(in=Ᵹ/1ms,out=Ᵹ/1000ms)" in output


def test_move_updates_physical_position_but_later_declaration_keeps_array_index():
    records = [
        _record(
            2,
            kind="dialogue",
            speakers=["아즈사"],
            staged=[{"slot": 3, "character_name_kr": "아즈사"}],
            script_events=[
                {"line_type": "character", "slot": 3, "character_name_kr": "아즈사", "dialogue_kr": "first"},
                {"line_type": "slot_command", "slot": 3, "command_normalized": "a"},
            ],
            text="第一句",
        ),
        _record(
            3,
            kind="dialogue",
            speakers=["하나코"],
            staged=[{"slot": 3, "character_name_kr": "아즈사"}, {"slot": 2, "character_name_kr": "하나코"}],
            script_events=[
                {"line_type": "character", "slot": 3, "character_name_kr": "아즈사", "dialogue_kr": ""},
                {"line_type": "character", "slot": 2, "character_name_kr": "하나코", "dialogue_kr": "second"},
                {"line_type": "slot_command", "slot": 2, "command_normalized": "a"},
                {"line_type": "slot_command", "slot": 3, "command_normalized": "m4"},
            ],
            text="第二句",
        ),
        _record(
            4,
            kind="dialogue",
            speakers=["아즈사"],
            staged=[{"slot": 2, "character_name_kr": "하나코"}, {"slot": 3, "character_name_kr": "아즈사"}],
            script_events=[
                {"line_type": "character", "slot": 2, "character_name_kr": "하나코", "dialogue_kr": ""},
                {"line_type": "character", "slot": 3, "character_name_kr": "아즈사", "dialogue_kr": "third"},
            ],
            text="第三句",
        ),
    ]
    resolved = resolve_spatial_states(records)
    assert resolved["scenario_0:3"]["after"][3]["array_index"] == 3
    assert resolved["scenario_0:3"]["after"][3]["physical_position"] == 4
    assert resolved["scenario_0:4"]["before"][3]["physical_position"] == 4


def test_reindex_after_move_preserves_position_without_duplicate_identity():
    records = [
        _record(
            1,
            kind="dialogue",
            script_events=[
                {"line_type": "character", "slot": 3, "character_name_kr": "아즈사"},
                {"line_type": "slot_command", "slot": 3, "command_normalized": "m5"},
            ],
        ),
        _record(
            2,
            kind="dialogue",
            script_events=[
                {"line_type": "character", "slot": 5, "character_name_kr": "아즈사"},
            ],
        ),
    ]

    resolved = resolve_spatial_states(records)
    after = resolved["scenario_0:2"]["after"]

    assert set(after) == {5}
    assert after[5]["array_index"] == 5
    assert after[5]["physical_position"] == 5
    assert resolved["scenario_0:2"]["reindexed"] == [{
        "character_name_kr": "아즈사",
        "from_array_index": 3,
        "to_array_index": 5,
        "physical_position": 5,
    }]


def test_declaration_after_frame_clear_is_visible_without_fake_appearance_command():
    records = [
        _record(
            1,
            kind="transition",
            script_events=[
                {"line_type": "command", "command_normalized": "all", "arguments_raw": ["hide"]},
            ],
        ),
        _record(
            2,
            kind="staging",
            script_events=[
                {"line_type": "character", "slot": 1, "character_name_kr": "하나코"},
                {"line_type": "character", "slot": 5, "character_name_kr": "아즈사"},
                {"line_type": "slot_command", "slot": 1, "command_normalized": "h"},
                {"line_type": "slot_command", "slot": 5, "command_normalized": "closeup"},
            ],
        ),
    ]

    resolved = resolve_spatial_states(records)

    assert resolved["scenario_0:1"]["frame_cleared"] is True
    assert all(item["visible"] for item in resolved["scenario_0:2"]["after"].values())
    output = render_annotation_text(records)
    assert "# 数组槽立绘声明（N 不是画面位置或说话人）" in output
    assert "花子=画面1（数组槽1，画面可见）" in output
