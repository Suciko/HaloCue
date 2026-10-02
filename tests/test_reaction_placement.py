"""Synthetic held-camera reaction loss; no model, database, or AA data."""

import pytest

from annotate import insert_annotation_beats, render_annotated_items
from script2aap import parse_script, build


def test_reaction_target_remains_visible_under_another_characters_hold(tmp_path):
    items = [
        {"kind": "dir", "raw": "@camera_hold A", "cmd": "camera_hold", "arg": "A"},
        {"kind": "line", "annotation_id": "anchor", "who": "A", "text": "第一句。"},
        {"kind": "line", "annotation_id": "next", "who": "A", "text": "第二句。"},
    ]
    beats = [
        {
            "anchor_id": "anchor",
            "position": "after",
            "who": "B",
            "face": "01",
            "emo": "",
            "act": "wave",
            "wait_ms": 1200,
            "reason": "listener_reaction",
        }
    ]
    text = render_annotated_items(insert_annotation_beats(items, beats))
    path = tmp_path / "source.txt"
    path.write_text(text, encoding="utf-8")
    cast = {"A": {"id": "a", "portrait": True}, "B": {"id": "b", "portrait": True}}
    index = {
        "bg": {"BG_Black": 1},
        "sounds": [],
        "characters": [
            {"identifier": "a", "faces": []},
            {"identifier": "b", "faces": [{"id": "01", "label": "wave"}]},
        ],
        "enums": {"emoticon": {}, "action": {"1": {"verb": "wave", "cn": "招手"}}},
    }
    rows = [
        r
        for _, group in build(parse_script(path, cast), {}, cast, index, "synthetic")
        for r in group
    ]
    assert len(rows) == 3
    reaction = rows[1]
    target = next((c for c in reaction["characters"]["$values"][1:] if c["name"] == "b"), None)
    assert target is not None, text
    assert target["faceId"] == "01"
    assert target["action"] == 1
    assert [c["name"] for c in rows[2]["characters"]["$values"][1:] if c["name"]] == ["a"]


@pytest.mark.parametrize("position", ["before", "after"])
def test_reactions_do_not_consume_authored_prefixes_and_preserve_hold(tmp_path, position):
    from annotate import parse_lines

    source = tmp_path / "author.txt"
    source.write_text(
        "## Scene\n@camera_hold A\n@camera A\n@wait 777\n@fx A 通讯\nA: 第一行。\nA: 下一行。\n",
        encoding="utf-8",
    )
    cast = {"A": {"id": "a", "portrait": True}, "B": {"id": "b", "portrait": True}}
    items = parse_lines(source, cast)
    lines = [i for i in items if i["kind"] == "line"]
    lines[0]["annotation_id"] = "anchor"
    lines[1]["annotation_id"] = "next"
    beat = {
        "anchor_id": "anchor",
        "position": position,
        "who": "B",
        "face": "01",
        "emo": "",
        "act": "wave",
        "wait_ms": 1200,
        "reason": "listener_reaction",
    }
    annotated = render_annotated_items(insert_annotation_beats(items, [beat]))
    output = tmp_path / "annotated.txt"
    output.write_text(annotated, encoding="utf-8")
    idx = {
        "bg": {},
        "sounds": [],
        "characters": [
            {"identifier": "a", "faces": []},
            {"identifier": "b", "faces": [{"id": "01", "label": "smile"}]},
        ],
        "enums": {"emoticon": {}, "action": {"1": {"verb": "wave", "cn": "招手"}}},
    }
    rows = [
        r
        for _, group in build(parse_script(output, cast), {}, cast, idx, "synthetic")
        for r in group
    ]
    original = next(r for r in rows if r["text"] == "第一行。")
    reaction = next(r for r in rows if not r["text"])
    assert original["additionalPrompt"] == "#wait;777"
    assert reaction["additionalPrompt"] == "#wait;1200"
    assert (
        next(c for c in original["characters"]["$values"][1:] if c["name"] == "a")["shapeOverride"]
        == 1
    )
    assert next(c for c in reaction["characters"]["$values"][1:] if c["name"] == "b")["action"] == 1
    assert [r["text"] for r in rows if r["text"]] == ["第一行。", "下一行。"]
    assert [c["name"] for c in rows[-1]["characters"]["$values"][1:] if c["name"]] == ["a"]
    source_nodes = [i["raw"] for i in items if i["kind"] != "line"]
    assert all(raw in annotated for raw in source_nodes)


def test_reaction_sidecar_is_stable_and_locates_rendered_line():
    items = [
        {"kind": "line", "annotation_id": "source-a", "line_no": 9, "who": "A", "text": "话。"}
    ]
    beat = {
        "anchor_id": "source-a",
        "position": "after",
        "who": "B",
        "face": "01",
        "act": "",
        "emo": "",
        "wait_ms": 1200,
        "reason": "listener_reaction",
    }
    records = []
    rendered = render_annotated_items(
        insert_annotation_beats(items, [beat]), reaction_records=records
    )
    assert len(records) == 1
    record = records[0]
    assert record["anchor_id"] == "source-a" and record["source_line"] == 9
    assert rendered.splitlines()[record["output_line"] - 1] == "B(01): "
    assert record["who"] == "B" and record["position"] == "after"
    again = []
    render_annotated_items(insert_annotation_beats(items, [beat]), reaction_records=again)
    assert records == again
    assert record["beat_id"] not in rendered


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("lost_target", [False, True])
def test_annotation_pipeline_returns_verified_sidecar_only_for_complete_run(
    tmp_path, monkeypatch, cancelled, lost_target
):
    import json
    import annotate

    source = tmp_path / "source.txt"
    source.write_text("@camera_hold A\nA: 第一句。\nA: 第二句。\n", encoding="utf-8")
    cast = {"A": {"id": "a", "portrait": True}, "B": {"id": "b", "portrait": True}}
    castfile = tmp_path / "cast.json"
    castfile.write_text(json.dumps({"cast": cast}), encoding="utf-8")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "bg": {"BG_Black": 1},
                "sounds": [],
                "characters": [{"identifier": "b", "faces": [{"id": "01", "label": "smile"}]}],
                "enums": {"emoticon": {}, "action": {}},
            }
        ),
        encoding="utf-8",
    )
    llm = tmp_path / "llm.json"
    llm.write_text("{}", encoding="utf-8")
    out = tmp_path / "result.txt"
    out.write_text("previous", encoding="utf-8")

    class Provider:
        name = "synthetic"
        model = "synthetic"
        cfg = {}
        stats = {}

        def report(self):
            return "synthetic"

    def fake_agent(items, **kwargs):
        anchor = next(item for item in items if item["kind"] == "line")
        return {
            "rows_by_id": {},
            "cancelled": cancelled,
            "beats": [
                {
                    "anchor_id": anchor["annotation_id"],
                    "position": "after",
                    "who": "B",
                    "face": "01",
                    "emo": "",
                    "act": "",
                    "wait_ms": 1200,
                    "reason": "listener_reaction",
                }
            ],
        }

    monkeypatch.setattr(annotate, "run_annotation_agent", fake_agent)
    options = {
        "script": str(source),
        "out": str(out),
        "cast": str(castfile),
        "index": str(index),
        "llm": str(llm),
        "agent_enabled": True,
        "checkpoint_dir": str(tmp_path / "checkpoints"),
    }
    if lost_target:
        original_render = annotate.render_annotated_items

        def broken_render(items, **kwargs):
            text = original_render(items, **kwargs)
            # Same number of physical lines, but the target is excluded again.
            return text.replace("@camera B", "@camera A")

        monkeypatch.setattr(annotate, "render_annotated_items", broken_render)
    if lost_target and not cancelled:
        from reaction_integrity import ReactionIntentError

        with pytest.raises(ReactionIntentError) as rejected:
            annotate.annotate_script(options, provider_instance=Provider())
        assert rejected.value.details["diagnostics"][0]["line_no"] == 2
        assert out.read_text(encoding="utf-8") == "previous"
        return
    result = annotate.annotate_script(options, provider_instance=Provider())
    if cancelled:
        assert result["incomplete"] is True
        assert out.read_text(encoding="utf-8") == "previous"
        assert not result.get("reaction_records")
    else:
        record = result["reaction_records"][0]
        assert record["compiled_index"] == 1
        assert record["source_line"] == 2
        assert record["who"] == "B"
        assert out.read_text(encoding="utf-8") == result["text"]


@pytest.mark.parametrize("position", ["before", "after"])
def test_multiple_reactions_with_full_hold_restore_authored_visible_group(tmp_path, position):
    from annotate import parse_lines

    cast = {name: {"id": name.lower(), "portrait": True} for name in "ABCDEFG"}
    source = tmp_path / "source.txt"
    source.write_text("## Scene\n@camera_hold A,B,C,D,E\nA: 原文。\nA: 后续。\n", encoding="utf-8")
    items = parse_lines(source, cast)
    anchor = next(i for i in items if i["kind"] == "line")
    anchor["annotation_id"] = "anchor"
    beats = [
        {
            "anchor_id": "anchor",
            "position": position,
            "who": who,
            "face": "01",
            "emo": "",
            "act": "",
            "wait_ms": 300,
            "reason": "listener_reaction",
        }
        for who in "FG"
    ]
    records = []
    text = render_annotated_items(insert_annotation_beats(items, beats), reaction_records=records)
    output = tmp_path / "annotated.txt"
    output.write_text(text, encoding="utf-8")
    idx = {
        "bg": {},
        "sounds": [],
        "characters": [
            {"identifier": name.lower(), "faces": [{"id": "01", "label": "smile"}]} for name in cast
        ],
        "enums": {"emoticon": {}, "action": {}},
    }
    rows = [
        r
        for _, group in build(parse_script(output, cast), {}, cast, idx, "synthetic")
        for r in group
    ]
    reactions = [r for r in rows if not r["text"]]
    assert [
        [c["name"] for c in r["characters"]["$values"][1:] if c["name"]] for r in reactions
    ] == [["f"], ["g"]]
    assert set(c["name"] for c in rows[-1]["characters"]["$values"][1:] if c["name"]) == set(
        "abcde"
    )
    assert len({record["beat_id"] for record in records}) == 2
    assert all(
        text.splitlines()[record["output_line"] - 1].startswith(record["who"] + "(01)")
        for record in records
    )


def test_before_reaction_does_not_move_to_previous_scene(tmp_path):
    from annotate import parse_lines

    cast = {name: {"id": name.lower(), "portrait": True} for name in "AB"}
    path = tmp_path / "source.txt"
    path.write_text(
        "## First\nA: 之前。\n@wait 11\n---\n## Second\n@camera A\nA: 锚点。\n", encoding="utf-8"
    )
    items = parse_lines(path, cast)
    anchor = [i for i in items if i["kind"] == "line"][-1]
    anchor["annotation_id"] = "second"
    beat = {
        "anchor_id": "second",
        "position": "before",
        "who": "B",
        "face": "",
        "emo": "",
        "act": "",
        "wait_ms": 50,
        "reason": "listener_reaction",
    }
    text = render_annotated_items(insert_annotation_beats(items, [beat]))
    assert text.index("## Second") < text.index("B: ") < text.index("@camera A")
    assert text.index("@wait 11") < text.index("---")


def test_before_reaction_does_not_steal_authored_transition(tmp_path):
    from annotate import parse_lines

    cast = {"A": {"id": "a", "portrait": True}, "B": {"id": "b", "portrait": True}}
    path = tmp_path / "source.txt"
    path.write_text("A: 第一行。\n@trans 1\nA: 锚点。\n", encoding="utf-8")
    items = parse_lines(path, cast)
    anchor = [i for i in items if i["kind"] == "line"][-1]
    anchor["annotation_id"] = "anchor"
    beat = {
        "anchor_id": "anchor",
        "position": "before",
        "who": "B",
        "face": "",
        "emo": "",
        "act": "",
        "wait_ms": 300,
        "reason": "listener_reaction",
    }
    text = render_annotated_items(insert_annotation_beats(items, [beat]))
    path.write_text(text, encoding="utf-8")
    idx = {"bg": {}, "sounds": [], "characters": [], "enums": {"emoticon": {}, "action": {}}}
    rows = [
        r for _, group in build(parse_script(path, cast), {}, cast, idx, "synthetic") for r in group
    ]
    assert [(r["text"], r["transition"]) for r in rows] == [("第一行。", 0), ("", 0), ("锚点。", 1)]
