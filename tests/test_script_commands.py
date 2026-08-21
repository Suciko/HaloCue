from build_index import ACTION, EMOTICON
from annotate import insert_annotation_beats, render_annotated_items
import script2aap
from direction_quality import validate_compiled_staging
from script2aap import AppearanceState, build, compiler_warning_issues, load_cast, parse_bg_argument, parse_script, resolve_act, resolve_background_reference, resolve_emo, warn


def test_compiler_warning_quality_distinguishes_dropped_annotations():
    issues = compiler_warning_issues([
        (12, "未知效果「jump」，已忽略"),
        (15, "草稿包含无意义的空白卡片"),
        (18, "自动修复标注：<jump> 是已注册动作，已按 {jump} 执行"),
        (21, "当前镜头要放 4 个立绘，超过 3 人上限，挤掉：柚子"),
        (24, "未解决的背景请求: 游戏开发部活动室"),
        (27, "@react 目标‘绿’不在当前镜头，已忽略"),
        (30, "「Alice」是有立绘角色但当前不在镜头，本行表情/气泡/动作/效果保留为画外意图，不写入当前 ScriptData"),
    ])

    assert issues[0] == {
        "code": "compiler_annotation_dropped",
        "message": "未知效果「jump」，已忽略",
        "severity": "high",
        "line": 12,
    }
    assert issues[1]["code"] == "compiler_warning"
    assert issues[1]["severity"] == "warning"
    assert issues[2]["code"] == "compiler_annotation_auto_repaired"
    assert issues[2]["severity"] == "info"
    assert issues[3]["code"] == "compiler_annotation_dropped"
    assert issues[3]["severity"] == "high"
    assert issues[4]["code"] == "unresolved_background_request"
    assert issues[4]["severity"] == "warning"
    assert issues[5]["code"] == "compiler_annotation_dropped"
    assert issues[6] == {
        "code": "compiler_annotation_offscreen",
        "message": "「Alice」是有立绘角色但当前不在镜头，本行表情/气泡/动作/效果保留为画外意图，不写入当前 ScriptData",
        "severity": "info",
        "line": 30,
    }
    assert issues[5]["severity"] == "high"


def test_compiler_auto_repairs_registered_action_written_as_effect(tmp_path):
    script = tmp_path / "swapped-action-effect.txt"
    script.write_text("Alice<jump>: jump\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {}, "characters": [],
        "enums": {
            "emoticon": {},
            "action": {"6": {"verb": "jump", "cn": "跳"}},
        },
    }

    warn.items.clear()
    row = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "swapped-action-effect",
    )[0][1][0]
    character = row["characters"]["$values"][row["speakerSlotNum"]]
    issues = compiler_warning_issues(warn.items)

    assert character["action"] == 6
    assert character["shapeOverride"] == 0
    assert [issue["code"] for issue in issues] == [
        "compiler_annotation_auto_repaired",
    ]


def test_load_cast_accepts_unique_display_name_without_guessing_variants(tmp_path):
    path = tmp_path / "cast.json"
    path.write_text(
        '{"cast": {"세이아": {"id": "seia", "name": "圣娅", "portrait": true}}, "alias": {}}',
        encoding="utf-8",
    )

    _, cast, _ = load_cast(str(path))

    assert cast["圣娅"]["id"] == "seia"


def test_load_cast_does_not_auto_alias_colliding_display_names(tmp_path):
    path = tmp_path / "cast.json"
    path.write_text(
        '{"cast": {'
        '"A": {"id": "a", "name": "同名", "portrait": true},'
        '"B": {"id": "b", "name": "同名", "portrait": true}'
        '}, "alias": {}}',
        encoding="utf-8",
    )

    _, cast, _ = load_cast(str(path))

    assert "同名" not in cast


def test_background_command_preserves_spaces_in_custom_filename():
    value = "ChatGPT Image 2026年7月19日 01_00_25"

    assert parse_bg_argument(value) == value


def test_background_command_trims_only_outer_whitespace():
    assert parse_bg_argument("  夜晚的 活动室  ") == "夜晚的 活动室"


def test_registered_numeric_background_key_resolves_to_its_resource_name():
    backgrounds = {
        "ChatGPT Image 2026年8月5日 18_28_00": 3040691084,
        "BG_Black": 1047754314,
    }

    assert resolve_background_reference("3040691084", backgrounds) == (
        "ChatGPT Image 2026年8月5日 18_28_00"
    )
    assert resolve_background_reference("999999", backgrounds) == "999999"


def test_first_background_transition_is_ignored_but_later_switch_is_kept(tmp_path):
    script = tmp_path / "transitions.txt"
    script.write_text(
        "@bg BG_First\n@trans 淡入淡出\nAlice: first\n"
        "@bg BG_Second\n@trans 淡入淡出\nAlice: second\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {"BG_First": 1, "BG_Second": 2},
        "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scenes = build(
        parse_script(script, cast),
        {"default_bg": "BG_First", "camera": {"enabled": False}},
        cast,
        index,
        "transitions",
    )

    assert scenes[0][1][0]["transition"] == 0
    assert scenes[0][1][1]["transition"] != 0


def test_transition_is_ignored_when_background_does_not_change(tmp_path):
    script = tmp_path / "duplicate-background-transition.txt"
    script.write_text(
        "@bg BG_First\nAlice: first\n"
        "@bg BG_First\n@trans 淡入淡出\nAlice: second\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {"BG_First": 1}, "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scenes = build(
        parse_script(script, cast),
        {"default_bg": "BG_First", "camera": {"enabled": False}},
        cast,
        index,
        "duplicate-background-transition",
    )

    assert scenes[0][1][0]["transition"] == 0
    assert scenes[0][1][1]["transition"] == 0


def test_face_state_resets_at_scene_and_background_boundaries(tmp_path):
    script = tmp_path / "face-reset.txt"
    script.write_text(
        "## one\nAlice(03): first\n@bg BG_Second\nAlice: after background\n"
        "## two\nAlice: next scene\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {"BG_Second": 2}, "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scenes = build(
        parse_script(script, cast),
        {"default_bg": "BG_Second", "camera": {"enabled": False}},
        cast, index, "face-reset",
    )

    first, after_background = scenes[0][1]
    next_scene = scenes[1][1][0]
    assert first["characters"]["$values"][first["speakerSlotNum"]]["faceId"] == "03"
    assert after_background["characters"]["$values"][after_background["speakerSlotNum"]]["faceId"] == "00"
    assert next_scene["characters"]["$values"][next_scene["speakerSlotNum"]]["faceId"] == "00"


def test_empty_nodialog_face_zero_inherits_the_current_expression(tmp_path):
    script = tmp_path / "empty-beat-face-inheritance.txt"
    script.write_text(
        "Alice(05): upset\n@wait 650\n@nodialog\nAlice(00): \n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scripts = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "empty-beat-face-inheritance",
    )[0][1]

    first = scripts[0]["characters"]["$values"][scripts[0]["speakerSlotNum"]]
    silent = next(
        character
        for character in scripts[1]["characters"]["$values"][1:]
        if character["name"] == "alice"
    )
    assert first["faceId"] == "05"
    assert silent["faceId"] == "05"


def test_empty_nodialog_can_explicitly_reset_face_through_reaction(tmp_path):
    script = tmp_path / "empty-beat-explicit-face-reset.txt"
    script.write_text(
        "Alice(05): upset\n"
        '@react {"who":"Alice","face":"00","emo":"","act":""}\n'
        "@nodialog\nAlice: \n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scripts = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "empty-beat-explicit-face-reset",
    )[0][1]
    silent = next(
        character
        for character in scripts[1]["characters"]["$values"][1:]
        if character["name"] == "alice"
    )

    assert silent["faceId"] == "00"


def test_persistent_character_effect_resets_at_background_boundary(tmp_path):
    script = tmp_path / "fx-reset.txt"
    script.write_text(
        "@fx Alice 特写\nAlice: first\n@bg BG_Second\nAlice: second\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {"BG_Second": 2}, "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scripts = build(
        parse_script(script, cast),
        {"default_bg": "BG_Second", "camera": {"enabled": False}},
        cast, index, "fx-reset",
    )[0][1]

    first = scripts[0]["characters"]["$values"][scripts[0]["speakerSlotNum"]]
    second = scripts[1]["characters"]["$values"][scripts[1]["speakerSlotNum"]]
    assert first["shapeOverride"] & 4
    assert not second["shapeOverride"] & 4
    assert "_sceneReset" not in scripts[1]


def test_layout_directive_drives_and_persists_semantic_pair_spacing(tmp_path):
    script = tmp_path / "semantic-layout.txt"
    script.write_text(
        '@layout {"relation_distance":"distant","focus_character":"Alice",'
        '"reaction_target":"Bob","reason":"relation_shift"}\n'
        "@camera_hold Alice,Bob\nAlice: first\nBob: second\n",
        encoding="utf-8",
    )
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scripts = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "semantic-layout",
    )[0][1]
    slots = []
    for row in scripts:
        slots.append({
            character["name"]: character["endingPos"]
            for character in row["characters"]["$values"][1:]
            if character["name"]
        })

    assert abs(slots[0]["alice"] - slots[0]["bob"]) == 4
    assert slots[1] == slots[0]


def test_semantic_layout_ignores_offscreen_performer_pending_entry(tmp_path):
    script = tmp_path / "offscreen-performer-korean-id.txt"
    script.write_text(
        '@layout {"focus_character":"柚子"}\n'
        "@camera_hold 圣娅,柚子\n"
        "圣娅: first\n"
        "@nodialog\n"
        "桃井: \n",
        encoding="utf-8",
    )
    cast = {
        "圣娅": {"id": "세이아", "portrait": True},
        "柚子": {"id": "유즈", "portrait": True},
        "桃井": {"id": "모모이", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "offscreen-performer",
    )[0][1]

    visible = [
        {character["name"] for character in row["characters"]["$values"] if character["name"]}
        for row in rows
    ]
    assert visible == [{"세이아", "유즈"}, {"세이아", "유즈"}]


def test_old_snapshot_mode_without_layout_metadata_keeps_standard_spacing(tmp_path):
    script = tmp_path / "old-snapshot-layout.txt"
    script.write_text(
        '@layout {"relation_distance":"remote"}\n'
        "@camera_hold Alice,Bob\nAlice: first\n",
        encoding="utf-8",
    )
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    row = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "old-snapshot",
        semantic_layout=False,
    )[0][1][0]
    visible_slots = {
        character["endingPos"]
        for character in row["characters"]["$values"][1:]
        if character["name"]
    }

    assert visible_slots == {1, 5}


def test_background_effect_resets_at_background_boundary(tmp_path):
    script = tmp_path / "bgfx-reset.txt"
    script.write_text(
        "@bgfx 雨\nAlice: first\n@bg BG_Second\nAlice: second\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {"BG_Second": 2}, "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scripts = build(
        parse_script(script, cast),
        {"default_bg": "BG_Second", "camera": {"enabled": False}},
        cast, index, "bgfx-reset",
    )[0][1]

    assert scripts[0]["bgEffect"] != 0
    assert scripts[1]["bgEffect"] == 0


def test_persistent_camera_holds_until_auto_without_changing_authored_one_shot(tmp_path):
    script = tmp_path / "camera-hold.txt"
    script.write_text(
        "@camera_hold Alice\nAlice: first\nBob: listener cut\n"
        "@camera_hold auto\nBob: automatic again\n",
        encoding="utf-8",
    )
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scripts = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "camera-hold",
    )[0][1]

    visible = [
        [character["name"] for character in row["characters"]["$values"][1:] if character["name"]]
        for row in scripts
    ]
    assert visible[:2] == [["alice"], ["alice"]]
    assert "bob" in visible[2]


def test_compiler_marks_exact_duplicate_camera_cut_without_hiding_authored_trace(tmp_path):
    script = tmp_path / "duplicate-camera-cut.txt"
    script.write_text(
        "@camera_cut Alice\n@move Alice 3\nAlice: first\n"
        "@camera_cut Alice\n@move Alice 3\nAlice: second\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scripts = build(
        parse_script(script, cast), {"camera": {"enabled": False}}, cast,
        index, "duplicate-camera-cut",
    )[0][1]

    second_camera = [
        origin for origin in scripts[1]["_trace"]
        if origin.get("command") == "camera_cut"
    ]
    assert second_camera
    assert second_camera[-1]["dedup_reason"] == "duplicate_camera_signature"
    quality = validate_compiled_staging(scripts)
    assert not [
        issue for issue in quality["issues"]
        if issue["code"] == "compiled_redundant_camera_declaration"
    ]


def test_empty_camera_hold_persists_through_narration_and_restores_portrait(tmp_path):
    script = tmp_path / "empty-camera-hold.txt"
    script.write_text(
        "@camera_hold -\n旁白: establishing\n旁白: still establishing\n"
        "Alice: automatic again\n",
        encoding="utf-8",
    )
    cast = {
        "旁白": {"narrator": True},
        "Alice": {"id": "alice", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scripts = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "empty-camera-hold",
    )[0][1]
    visible = [
        [character["name"] for character in row["characters"]["$values"][1:] if character["name"]]
        for row in scripts
    ]

    assert visible[0] == []
    assert visible[1] == []
    assert "alice" in visible[2]


def test_thematic_separator_is_a_real_compiler_scene_boundary(tmp_path):
    script = tmp_path / "separator-scene.txt"
    script.write_text("Alice(03): first\n---\nAlice: second\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scenes = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "separator-scene",
    )

    assert len(scenes) == 2
    second = scenes[1][1][0]
    assert second["characters"]["$values"][second["speakerSlotNum"]]["faceId"] == "00"


def test_chat_and_jump_resolve_to_separate_character_fields():
    assert resolve_emo(EMOTICON[1], {EMOTICON[1]: 1}, {}, 9) == 1
    assert resolve_act(ACTION[6], {ACTION[6]: 6}, {}, 9) == 6


def test_representative_script_writes_chat_and_jump_to_separate_aap_fields(tmp_path):
    script = tmp_path / "symbols.txt"
    script.write_text("Alice[재잘]: chat\nAlice{jump}: jump\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {}, "characters": [],
        "enums": {
            "emoticon": {"1": {"sym": "[재잘]", "cn": "叽喳"}},
            "action": {"6": {"verb": "jump", "cn": "跳"}},
        },
    }

    scenes = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "symbols",
    )
    scripts = scenes[0][1]
    chat = scripts[0]["characters"]["$values"][scripts[0]["speakerSlotNum"]]
    jump = scripts[1]["characters"]["$values"][scripts[1]["speakerSlotNum"]]

    assert (chat["emoticon"], chat["action"]) == (1, 0)
    assert (jump["emoticon"], jump["action"]) == (-1, 6)


def test_scene_end_does_not_inject_exit_signal_into_last_dialogue(tmp_path):
    """Ending a node must not turn the final action into an implicit fade/exit."""
    script = tmp_path / "scene-end.txt"
    script.write_text("Alice: first\nAlice{jump}: last\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {}, "characters": [],
        "enums": {
            "emoticon": {},
            "action": {"6": {"verb": "jump", "cn": "跳"}},
        },
    }

    scenes = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "scene-end",
    )
    final_script = scenes[0][1][-1]
    final_character = final_script["characters"]["$values"][
        final_script["speakerSlotNum"]
    ]

    assert final_character["action"] == 6
    assert final_character["appear"] == 0


def test_dialogue_free_reaction_beat_compiles_to_one_explicit_wait(tmp_path):
    items = [{
        "kind": "line", "annotation_id": "src-1", "raw": "Alice: Really?",
        "who": "Alice", "text": "Really?", "face": "00", "emo": "", "act": "", "fx": "",
    }]
    beats = [{
        "anchor_id": "src-1", "position": "after", "who": "Alice",
        "face": "01", "emo": "沉默", "act": "", "wait_ms": 2500,
    }]
    rendered = render_annotated_items(insert_annotation_beats(items, beats))
    script = tmp_path / "reaction-beat.txt"
    script.write_text(rendered, encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {}, "characters": [],
        "enums": {
            "emoticon": {"0": {"sym": "[…]", "cn": "沉默"}},
            "action": {},
        },
    }

    scripts = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "reaction-beat",
    )[0][1]

    assert len(scripts) == 2
    assert scripts[1]["text"] == ""
    assert scripts[1]["isDialogScript"] is False
    assert scripts[1]["speakerSlotNum"] == 0
    assert scripts[1]["additionalPrompt"] == "#wait;2500"
    assert scripts[1]["additionalPrompt"].count("#wait;") == 1
    visible = [
        character
        for character in scripts[1]["characters"]["$values"][1:]
        if character["name"]
    ]
    assert scripts[1]["highlightedSlotNums"]["$values"] == []
    character = visible[0]
    assert character["emoticon"] == 0


def test_dialogue_free_beat_applies_multiple_reactions_in_one_highlighted_node(tmp_path):
    items = [{
        "kind": "line", "annotation_id": "src-1", "raw": "Alice: What?",
        "who": "Alice", "text": "What?", "face": "00", "emo": "", "act": "", "fx": "",
    }]
    beats = [{
        "anchor_id": "src-1", "position": "after", "who": "Alice",
        "face": "01", "emo": "问号", "act": "", "wait_ms": 900,
        "visible_characters": ["Alice", "Bob"],
        "positions": {"Alice": 1, "Bob": 4},
        "reactions": [{"who": "Bob", "face": "02", "emo": "问号", "act": ""}],
    }]
    rendered = render_annotated_items(insert_annotation_beats(items, beats))
    assert rendered.count("@nodialog") == 1
    assert rendered.count("@react ") == 1

    script = tmp_path / "shared-reaction.txt"
    script.write_text(rendered + "Alice: next\n", encoding="utf-8")
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {
        "bg": {},
        "characters": [],
        "enums": {
            "emoticon": {"6": {"sym": "[?]", "cn": "问号"}},
            "action": {},
        },
    }

    scripts = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "shared-reaction",
    )[0][1]

    beat = scripts[1]
    assert beat["isDialogScript"] is False
    assert beat["speakerSlotNum"] == 0
    visible_slots = {
        slot
        for slot, character in enumerate(beat["characters"]["$values"])
        if slot and character["name"]
    }
    assert len(visible_slots) == 2
    assert beat["highlightedSlotNums"]["$values"] == []
    by_name = {c["name"]: c for c in beat["characters"]["$values"] if c["name"]}
    assert (by_name["alice"]["faceId"], by_name["alice"]["emoticon"]) == ("01", 6)
    assert (by_name["bob"]["faceId"], by_name["bob"]["emoticon"]) == ("02", 6)
    dialogue = scripts[2]
    bob_slot = next(
        slot for slot, character in enumerate(dialogue["characters"]["$values"])
        if character["name"] == "bob"
    )
    assert dialogue["speakerSlotNum"] != 0
    assert dialogue["highlightedSlotNums"]["$values"] == [bob_slot]
    assert scripts[2]["sound"] == ""


def test_multi_stage_beat_renders_entry_camera_positions_exit_and_effects():
    items = [{
        "kind": "line", "annotation_id": "src-1", "raw": "Alice: Go",
        "who": "Alice", "text": "Go", "face": "00", "emo": "", "act": "", "fx": "",
        "bg": "BG_Room",
    }]
    beats = [{
        "anchor_id": "src-1", "position": "after", "who": "Alice",
        "face": "01", "emo": "", "act": "stiff", "wait_ms": 700,
        "visible_characters": ["Alice", "Bob"],
        "shot_transition": "reframe",
        "positions": {"Alice": 1, "Bob": 4},
        "enter": [{"who": "Bob", "slot": 4, "side": "right"}],
        "exit": [{"who": "Bob", "side": "left"}],
        "se": "SE_Step", "bg": "BG_Black", "place": "黑场",
        "trans": "淡入淡出 1000", "bgfx": "闪白", "shake": True,
    }]

    rendered = render_annotated_items(insert_annotation_beats(items, beats))

    assert "@enter Bob 4 右" in rendered
    assert "@exit Bob 左" in rendered
    assert "@move Alice 1" in rendered and "@move Bob 4" in rendered
    assert "@camera_hold Alice,Bob" in rendered
    assert "@bg BG_Black" in rendered and "@trans 淡入淡出 1000" in rendered
    assert "@place 黑场" in rendered
    assert "@se SE_Step" in rendered and "@bgfx 闪白" in rendered
    assert "@bgshake" in rendered and "@wait 700" in rendered


def test_pure_ai_beats_can_fade_to_black_and_return_to_scene_background():
    items = [{
        "kind": "line", "annotation_id": "src-1", "raw": "Alice: first",
        "who": "Alice", "text": "first",
    }]
    beats = [
        {
            "anchor_id": "src-1", "position": "after", "who": "Alice",
            "face": "", "emo": "", "act": "", "wait_ms": 0,
            "bg": "BG_Black", "trans": "淡入淡出 1000",
        },
        {
            "anchor_id": "src-1", "position": "after", "who": "Alice",
            "face": "", "emo": "", "act": "", "wait_ms": 0,
            "bg": "BG_GameDevelopmentRoom", "trans": "淡入淡出 1000",
        },
    ]

    rendered = render_annotated_items(insert_annotation_beats(items, beats))

    assert rendered.count("@trans 淡入淡出 1000") == 2
    assert "@bg BG_Black\n@trans 淡入淡出 1000" in rendered
    assert "@bg BG_GameDevelopmentRoom\n@trans 淡入淡出 1000" in rendered


def test_implicit_first_appearance_fades_on_the_spoken_node_without_wait(tmp_path):
    script = tmp_path / "implicit-entry.txt"
    script.write_text("Alice: first line\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {}, "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scenes = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "implicit-entry",
    )
    first_script = scenes[0][1][0]
    first_character = first_script["characters"]["$values"][
        first_script["speakerSlotNum"]
    ]

    assert first_character["appear"] == 3
    assert first_character["startingPos"] == 3
    assert first_character["endingPos"] == 3
    assert first_script["additionalPrompt"] == ""


def test_appearance_state_fades_scene_first_and_eight_line_reentry_only():
    state = AppearanceState(reappear_after=8)

    assert state.observe(["alice"]) == {"alice"}
    assert state.observe([]) == set()
    for _ in range(7):
        assert state.observe(["bob"]) in ({"bob"}, set())
    assert state.observe(["alice"]) == {"alice"}

    state.reset_scene()
    assert state.observe(["alice"]) == {"alice"}


def test_appearance_state_does_not_refade_after_a_short_camera_cut():
    state = AppearanceState(reappear_after=8)

    assert state.observe(["alice"]) == {"alice"}
    for _ in range(7):
        state.observe(["bob"])

    assert state.observe(["alice"]) == set()


def test_long_camera_cut_does_not_turn_present_character_into_a_reentry_fade(tmp_path):
    script = tmp_path / "long-reverse-shot.txt"
    script.write_text(
        "@camera_hold Alice\nAlice(03): first\n"
        "@camera_hold Bob\n"
        + "\n".join(f"Bob: reverse {index}" for index in range(1, 10))
        + "\n@camera_hold Alice\nAlice: return\n",
        encoding="utf-8",
    )
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}},
        cast,
        index,
        "long-reverse-shot",
    )[0][1]
    returning = next(
        character
        for character in rows[-1]["characters"]["$values"]
        if character["name"] == "alice"
    )

    assert returning["appear"] == 0
    assert returning["faceId"] == "03"


def test_multi_character_first_appearance_uses_normal_slots(monkeypatch, tmp_path):
    script = tmp_path / "multi-entry.txt"
    script.write_text("Alice: first\nBob: second\n", encoding="utf-8")
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    monkeypatch.setattr(script2aap.camera, "plan_camera", lambda lines, opts: [["alice", "bob"], ["alice", "bob"]])

    scripts = build(parse_script(script, cast), {}, cast, index, "multi-entry")[0][1]

    visible = [char for char in scripts[0]["characters"]["$values"] if char["name"]]
    assert {(char["name"], char["endingPos"], char["appear"]) for char in visible} == {
        ("alice", 1, 3), ("bob", 5, 3),
    }


def test_automatic_camera_never_exceeds_three_portraits_even_with_legacy_config():
    lines = [
        {"speaker": name, "text": f"line {index}"}
        for index, name in enumerate(("alice", "bob", "carol", "dave"), 1)
    ]

    shots = script2aap.camera.plan_camera(
        lines,
        {"max_on_cam": 5, "new_face_hold": 99, "stale_after": 99},
    )

    assert max(map(len, shots)) == 3
    assert shots[-1] == ["bob", "carol", "dave"]


def test_camera_hold_auto_returns_to_a_three_person_plan_without_dropping_speaker(
    tmp_path,
):
    script = tmp_path / "held-beat-then-auto.txt"
    script.write_text(
        "Alice: one\n"
        "Bob: two\n"
        "Carol: three\n"
        "@camera_hold Alice\n"
        "Alice: held insert\n"
        "@camera_hold auto\n"
        "Dave: returns to plan\n",
        encoding="utf-8",
    )
    cast = {
        name.title(): {"id": name, "portrait": True}
        for name in ("alice", "bob", "carol", "dave")
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(
        parse_script(script, cast),
        {"camera": {"max_on_cam": 5, "new_face_hold": 99, "stale_after": 99}},
        cast,
        index,
        "held-beat-then-auto",
    )[0][1]
    final_visible = [
        char["name"]
        for char in rows[-1]["characters"]["$values"]
        if char["name"]
    ]

    assert len(final_visible) == 3
    assert "dave" in final_visible


def test_background_scene_break_refades_a_returning_character(tmp_path):
    script = tmp_path / "scene-break-entry.txt"
    script.write_text(
        "Alice: first\n@bg BG_Second\nAlice: after switch\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {
        "bg": {"BG_Second": 2}, "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scripts = build(parse_script(script, cast), {}, cast, index, "scene-break-entry")[0][1]
    second_character = scripts[1]["characters"]["$values"][scripts[1]["speakerSlotNum"]]

    assert second_character["appear"] == 3
    assert scripts[1]["additionalPrompt"] == ""


def test_shot_target_name_resolves_to_the_target_current_stage_slot(tmp_path):
    """Automatic annotations name a victim; only the renderer knows its slot."""
    script = tmp_path / "shot-target.txt"
    script.write_text("Alice: Look out!\n@shot Alice\nBob: I was hit.\n", encoding="utf-8")
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    scenes = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "shot-target",
    )

    hit_script = scenes[0][1][1]
    alice_slot = next(
        slot for slot, char in enumerate(hit_script["characters"]["$values"])
        if char["name"] == "alice"
    )
    assert hit_script["additionalPrompt"] == f"#{alice_slot};fx;{{shot}}"
    assert hit_script["sound"] == ""


def test_shot_target_is_rejected_when_that_character_is_not_on_screen(tmp_path):
    script = tmp_path / "offscreen-shot.txt"
    script.write_text("@shot Alice\nBob: I was hit.\n", encoding="utf-8")
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    scenes = build(
        parse_script(script, cast),
        {"camera": {"enabled": False}}, cast, index, "offscreen-shot",
    )

    assert scenes[0][1][0]["additionalPrompt"] == ""
    assert any("不在当前画面" in message for _, message in warn.items)


def test_camera_dash_compiles_an_empty_shot(tmp_path):
    script = tmp_path / "empty-shot.txt"
    script.write_text("@camera -\nAlice: 画外声音\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    row = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "empty-shot",
    )[0][1][0]

    assert row["speakerSlotNum"] == 0
    assert not any(character["name"] for character in row["characters"]["$values"][1:])


def test_slot_zero_distinguishes_narration_from_named_voice_characters(tmp_path):
    script = tmp_path / "slot-zero-speakers.txt"
    script.write_text(
        "旁白: 场景开始。\n老师: 听得见吗？\n神秘店员: 欢迎光临。\n",
        encoding="utf-8",
    )
    cast = {
        "旁白": {"narrator": True},
        "老师": {"id": "45145456", "name": "老师", "portrait": False},
        "神秘店员": {"id": "voice-clerk", "name": "神秘店员", "portrait": False},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "slot-zero-speakers",
    )[0][1]

    assert rows[0]["speakerSlotNum"] == 0
    assert rows[0]["characters"]["$values"][0]["name"] == ""
    assert [row["speakerSlotNum"] for row in rows[1:]] == [0, 0]
    assert [
        row["characters"]["$values"][0]["name"]
        for row in rows[1:]
    ] == ["45145456", "voice-clerk"]


def test_explicit_camera_is_one_shot_and_deduplicates_names(tmp_path):
    script = tmp_path / "listener-shot.txt"
    script.write_text(
        "@camera Bob,Bob\nAlice: first\nAlice: second\n",
        encoding="utf-8",
    )
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(parse_script(script, cast), {}, cast, index, "listener-shot")[0][1]

    assert [
        char["name"] for char in rows[0]["characters"]["$values"][1:]
        if char["name"]
    ] == ["bob"]
    assert rows[0]["speakerSlotNum"] == 0
    assert any(char["name"] == "alice" for char in rows[1]["characters"]["$values"][1:])


def test_invalid_explicit_camera_falls_back_to_automatic_shot(tmp_path):
    script = tmp_path / "invalid-camera.txt"
    script.write_text("@camera Bob,Missing\nAlice: first\n", encoding="utf-8")
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    row = build(parse_script(script, cast), {}, cast, index, "invalid-camera")[0][1][0]

    assert any(char["name"] == "alice" for char in row["characters"]["$values"][1:])
    assert not any(char["name"] == "bob" for char in row["characters"]["$values"][1:])
    assert any("未知角色" in message for _, message in warn.items)


def test_explicit_camera_caps_visible_portraits_at_three(tmp_path):
    names = ["A", "B", "C", "D", "E", "F"]
    script = tmp_path / "five-camera.txt"
    script.write_text("@camera " + ",".join(names) + "\nA: first\n", encoding="utf-8")
    cast = {name: {"id": name.lower(), "portrait": True} for name in names}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    row = build(parse_script(script, cast), {}, cast, index, "five-camera")[0][1][0]
    visible = [char["name"] for char in row["characters"]["$values"][1:] if char["name"]]

    assert len(visible) == 3
    assert not {"d", "e", "f"} & set(visible)
    assert any("最多显示 3 个立绘" in message for _, message in warn.items)


def test_entry_side_is_corrected_to_match_the_target_side_of_the_frame(tmp_path):
    script = tmp_path / "entry-side.txt"
    script.write_text("@enter Bob 4 左\nBob: arrived\n", encoding="utf-8")
    cast = {"Bob": {"id": "bob", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    row = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "entry-side",
    )[0][1][0]
    bob = next(character for character in row["characters"]["$values"] if character["name"] == "bob")

    assert bob["endingPos"] == 4
    assert bob["appear"] == 1
    assert any("入场方向" in message for _, message in warn.items)


def test_reveal_slides_an_offscreen_present_character_into_a_continuous_shot(tmp_path):
    script = tmp_path / "reveal-side.txt"
    script.write_text(
        "@camera_hold 圣娅\n圣娅: first\n"
        "@move 绿 5\n@camera_hold 圣娅,绿\n@reveal 绿 右\n绿: hello\n"
        "绿: again\n",
        encoding="utf-8",
    )
    cast = {
        "圣娅": {"id": "seia", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    rows = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "reveal-side",
    )[0][1]
    revealed = next(
        character for character in rows[1]["characters"]["$values"]
        if character["name"] == "midori"
    )
    held = next(
        character for character in rows[2]["characters"]["$values"]
        if character["name"] == "midori"
    )

    assert revealed["endingPos"] == 5
    assert revealed["appear"] == 1
    assert held["appear"] == 0
    assert not warn.items


def test_conceal_fades_a_portrait_out_but_allows_visual_reveal_without_reentry(tmp_path):
    script = tmp_path / "conceal-and-reveal.txt"
    script.write_text(
        "@camera_hold Alice,Bob\nAlice: together\n"
        "@conceal Bob\n@hl Alice\n@nodialog\n@wait 500\nAlice: \n"
        "@reveal Bob\nBob: back\n",
        encoding="utf-8",
    )
    cast = {
        "Alice": {"id": "alice", "portrait": True},
        "Bob": {"id": "bob", "portrait": True},
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    rows = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "conceal-and-reveal",
    )[0][1]
    concealed = next(
        character for character in rows[1]["characters"]["$values"]
        if character["name"] == "bob"
    )
    revealed = next(
        character for character in rows[2]["characters"]["$values"]
        if character["name"] == "bob"
    )

    assert concealed["appear"] == 6
    assert rows[1]["highlightedSlotNums"]["$values"] == []
    assert revealed["appear"] == 3
    assert not any("@enter" in message for _, message in warn.items)


def test_camera_cut_rebuilds_the_whole_shot_without_movement_or_entry_animation(tmp_path):
    script = tmp_path / "camera-cut.txt"
    script.write_text(
        "@move A 1\n@move B 4\n@camera_hold A,B\nA: first\n"
        "@camera_cut A,C\nC: second\n",
        encoding="utf-8",
    )
    cast = {
        name: {"id": name.lower(), "portrait": True}
        for name in ("A", "B", "C")
    }
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "camera-cut",
    )[0][1]
    cut = rows[1]
    by_name = {character["name"]: character for character in cut["characters"]["$values"] if character["name"]}

    assert set(by_name) == {"a", "c"}
    assert "b" not in by_name
    assert all(character["startingPos"] == character["endingPos"] for character in by_name.values())
    assert all(character["appear"] == 0 for character in by_name.values())
    assert "camera_cut" in {
        origin.get("command") for origin in cut["_trace"]
    }


def test_dialogue_free_offscreen_cue_can_hold_a_real_empty_shot(tmp_path):
    script = tmp_path / "empty-shot.txt"
    script.write_text(
        "@camera_cut -\n@nodialog\n@wait 500\nAlice: \nAlice: return\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(
        parse_script(script, cast), {"camera": {"enabled": False}},
        cast, index, "empty-shot",
    )[0][1]

    assert rows[0]["isDialogScript"] is False
    assert rows[0]["speakerSlotNum"] == 0
    assert not any(character["name"] for character in rows[0]["characters"]["$values"][1:])
    assert any(character["name"] == "alice" for character in rows[1]["characters"]["$values"][1:])


def test_pure_ai_compile_does_not_invoke_the_automatic_camera_planner(monkeypatch, tmp_path):
    script = tmp_path / "pure-ai-camera.txt"
    script.write_text("@camera_cut Alice\nAlice: line\n", encoding="utf-8")
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    monkeypatch.setattr(
        script2aap.camera, "plan_camera",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("automatic camera called")),
    )

    rows = build(
        parse_script(script, cast), {}, cast, index, "pure-ai-camera",
        layout_mode="pure_ai",
    )[0][1]

    assert any(character["name"] == "alice" for character in rows[0]["characters"]["$values"])


def test_explicit_fx_clear_ends_persistent_closeup_without_serializing_marker(tmp_path):
    script = tmp_path / "fx-end.txt"
    script.write_text(
        "@camera Alice\n@fx Alice 特写\nAlice: start\n"
        "@camera Alice\n@fx Alice 无\nAlice: end\n",
        encoding="utf-8",
    )
    cast = {"Alice": {"id": "alice", "portrait": True}}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}

    rows = build(parse_script(script, cast), {}, cast, index, "fx-end")[0][1]
    first = next(char for char in rows[0]["characters"]["$values"] if char["name"] == "alice")
    second = next(char for char in rows[1]["characters"]["$values"] if char["name"] == "alice")

    assert first["shapeOverride"] == 4
    assert second["shapeOverride"] == 0
    assert all("_explicitFxEnds" not in row for row in rows)
