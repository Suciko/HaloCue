"""Pending prefixes must not silently disappear at a scene boundary or EOF."""

from copy import deepcopy

import pytest

from diagnostics import validate_script_diagnostics
from document import compile_document, parse_document_lossless, serialize_document
from script2aap import build


CAST = {"Narrator": {"narrator": True}, "Actor": {"id": "synthetic", "portrait": True}}
ASSETS = {
    "bg": {},
    "sounds": ["synthetic_se"],
    "characters": [],
    "enums": {"emoticon": {}, "action": {}},
}
PREFIXES = [
    "wait 100",
    "se synthetic_se",
    "sound synthetic_se",
    "place Room",
    "popup CG_Test",
    "raw #wait;100",
    "bgshake",
    "clearst",
    "hidemenu",
    "showmenu",
    "aronatouch",
    "shot 1",
    "st [0,0] instant 20",
    "stm [0,0] instant 20",
    "zoom instant 0,0 100",
    "enter Actor",
    "exit Actor",
    "move Actor 2",
    "fx Actor 0",
    "camera -",
    "hl -",
]


def terminal(diagnostics):
    return [item for item in diagnostics if item["code"] == "dir.unconsumed"]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_each_pending_kind_requires_a_following_dialogue(prefix):
    nodes = parse_document_lossless(f"Narrator: Before.\n@{prefix}\n")
    errors = terminal(validate_script_diagnostics(nodes, CAST, ASSETS))
    assert len(errors) == 1
    assert errors[0]["line_no"] == 2
    assert errors[0]["severity"] == "error"
    assert f"@{prefix.split()[0]}" in errors[0]["message"]


@pytest.mark.parametrize(
    "boundary",
    [
        "",
        "## Next\nNarrator: After.\n",
        "---\nNarrator: After.\n",
        "* * *\nNarrator: After.\n",
        "___\nNarrator: After.\n",
    ],
)
def test_every_terminal_prefix_is_reported_losslessly(boundary):
    text = (
        "\ufeff## First\r\nNarrator: Before.\r\n@wait 100\r\n@se synthetic_se\r\n@clearst\r\n"
        + boundary
    )
    nodes = parse_document_lossless(text)
    before = deepcopy(nodes)
    events, diagnostics = compile_document(nodes, CAST, ASSETS)
    assert [item["line_no"] for item in terminal(diagnostics)] == [3, 4, 5]
    assert nodes == before
    assert serialize_document(nodes) == text
    assert [event["no"] for event in events if event["k"] == "dir"] == [3, 4, 5]
    scenes = build(events, {"camera": {"enabled": False}}, CAST, ASSETS, "Synthetic")
    scripts = [script for _, scene in scenes for script in scene]
    assert all(script["additionalPrompt"] == "" and script["sound"] == "" for script in scripts)
    assert len(scripts) == (2 if boundary else 1)


def test_prefix_only_scenes_do_not_gain_standalone_events():
    nodes = parse_document_lossless("@wait 1\n## Only\n@clearst\n---\n@wait 2\n")
    events, diagnostics = compile_document(nodes, CAST, ASSETS)
    assert [item["line_no"] for item in terminal(diagnostics)] == [1, 3, 5]
    assert build(events, {}, CAST, ASSETS, "Synthetic") == []


@pytest.mark.parametrize("prefix", PREFIXES)
def test_normal_attached_prefix_is_consumed(prefix):
    nodes = parse_document_lossless(f"@{prefix}\nNarrator: After.\n")
    assert terminal(compile_document(nodes, CAST, ASSETS)[1]) == []


def test_duplicate_waits_keep_order_and_both_cues():
    nodes = parse_document_lossless("@wait 100\n@wait 200\nNarrator: After.\n")
    events, diagnostics = compile_document(nodes, CAST, ASSETS)
    assert diagnostics == []
    scenes = build(events, {"camera": {"enabled": False}}, CAST, ASSETS, "Synthetic")
    assert len(scenes) == 1 and len(scenes[0][1]) == 1
    assert scenes[0][1][0]["additionalPrompt"] == "#wait;100\n#wait;200"


@pytest.mark.parametrize(
    "suffix, expected",
    [
        ("Unbound: Skipped.\n", [1]),
        ("Not dialogue\n", [1]),
        ("# Title\n", [1]),
        ("\n", [1]),
        ("Unbound: Skipped.\nNarrator: Consumes.\n", []),
        ("Not dialogue\nNarrator: Consumes.\n", []),
        ("# Title\nNarrator: Consumes.\n", []),
    ],
)
def test_only_emitted_dialogue_consumes_pending(suffix, expected):
    nodes = parse_document_lossless("@wait 1\n" + suffix)
    assert [item["line_no"] for item in terminal(compile_document(nodes, CAST)[1])] == expected


def test_empty_cast_follows_compile_documents_unbound_event_policy():
    nodes = parse_document_lossless("@wait 1\nUnbound: Still emitted without cast.\n")
    events, diagnostics = compile_document(nodes, {})
    assert [event["k"] for event in events] == ["dir", "line"]
    assert terminal(diagnostics) == []
    assert any(item["code"] == "actor.unbound" for item in diagnostics)


@pytest.mark.parametrize("boundary", ["", "## Next\n", "---\n"])
def test_persistent_commands_are_exempt(boundary):
    text = (
        "@bg BG_Black\n@trans 0\n@bgm 999\n@music 999\n@bgfx 0\n@stage Actor@2\n@auto\n@camera_hold -\n"
        + boundary
    )
    assert terminal(compile_document(parse_document_lossless(text), CAST, ASSETS)[1]) == []


def test_existing_unknown_and_invalid_diagnostics_survive():
    text = "@unknown value\n@wait nope\n@move Actor 9\n"
    diagnostics = compile_document(parse_document_lossless(text), CAST, ASSETS)[1]
    assert {(item["code"], item["line_no"]) for item in diagnostics} >= {
        ("dir.unknown", 1),
        ("dir.argument_error", 2),
        ("move.position_invalid", 3),
    }
    assert all(item["line_no"] != 1 for item in terminal(diagnostics))
