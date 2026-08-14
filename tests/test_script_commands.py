from build_index import ACTION, EMOTICON
from annotate import insert_annotation_beats, render_annotated_items
import script2aap
from script2aap import AppearanceState, build, parse_bg_argument, parse_script, resolve_act, resolve_background_reference, resolve_emo, warn


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
    assert scripts[1]["additionalPrompt"] == "#wait;2500"
    assert scripts[1]["additionalPrompt"].count("#wait;") == 1
    character = scripts[1]["characters"]["$values"][scripts[1]["speakerSlotNum"]]
    assert character["emoticon"] == 0


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
        ("alice", 2, 3), ("bob", 4, 3),
    }


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


def test_explicit_camera_caps_visible_portraits_at_five(tmp_path):
    names = ["A", "B", "C", "D", "E", "F"]
    script = tmp_path / "five-camera.txt"
    script.write_text("@camera " + ",".join(names) + "\nA: first\n", encoding="utf-8")
    cast = {name: {"id": name.lower(), "portrait": True} for name in names}
    index = {"bg": {}, "characters": [], "enums": {"emoticon": {}, "action": {}}}
    warn.items.clear()

    row = build(parse_script(script, cast), {}, cast, index, "five-camera")[0][1][0]
    visible = [char["name"] for char in row["characters"]["$values"][1:] if char["name"]]

    assert len(visible) == 5
    assert "f" not in visible
    assert any("最多显示 5 个立绘" in message for _, message in warn.items)


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
