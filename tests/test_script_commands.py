from build_index import ACTION, EMOTICON
from annotate import insert_annotation_beats, render_annotated_items
import script2aap
from script2aap import AppearanceState, build, parse_bg_argument, parse_script, resolve_act, resolve_emo, warn


def test_background_command_preserves_spaces_in_custom_filename():
    value = "ChatGPT Image 2026年7月19日 01_00_25"

    assert parse_bg_argument(value) == value


def test_background_command_trims_only_outer_whitespace():
    assert parse_bg_argument("  夜晚的 活动室  ") == "夜晚的 活动室"


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
