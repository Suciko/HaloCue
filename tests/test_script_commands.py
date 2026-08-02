from build_index import ACTION, EMOTICON
from script2aap import build, parse_bg_argument, parse_script, resolve_act, resolve_emo, warn


def test_background_command_preserves_spaces_in_custom_filename():
    value = "ChatGPT Image 2026年7月19日 01_00_25"

    assert parse_bg_argument(value) == value


def test_background_command_trims_only_outer_whitespace():
    assert parse_bg_argument("  夜晚的 活动室  ") == "夜晚的 活动室"


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


def test_implicit_first_appearance_has_no_entry_animation(tmp_path):
    """The opening line starts composed; fades are reserved for later arrivals."""
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

    assert first_character["appear"] == 0


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
