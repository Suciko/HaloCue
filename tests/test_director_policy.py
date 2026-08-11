from director_policy import normalize_direction_plan
from direction_rules import apply_model_directions, normalize_direction_density

import annotate


def directed_line(index, *, story="bond", function="dialogue", reason="none", **fields):
    direction = {
        "scene_type": story,
        "scene_function": function,
        "reason": reason,
        "continuity": {},
        "visible_characters": ["A", "B"],
    }
    item = {
        "kind": "line", "annotation_id": f"src-{index}", "who": "A",
        "text": f"line {index}", "_director": direction,
        "_director_intent": {
            "scene_type": story, "scene_function": function,
            "reason": reason, "visible_characters": ["A", "B"],
        },
        "_direction_origins": {},
    }
    for field, value in fields.items():
        item[field] = value
        item["_direction_origins"][field] = "model"
    return item


def test_ordinary_dialogue_keeps_state_and_removes_unsupported_noise():
    items = [
        directed_line(
            1, reason="new_stimulus", face="01", emo="惊叹", act="jump",
        ),
        *[
            directed_line(index, face="01", emo="惊叹", act="jump", fx="特写")
            for index in range(2, 11)
        ],
    ]

    beats, diagnostics = normalize_direction_plan(items)

    assert beats == []
    assert items[0]["face"] == "01"
    assert items[0]["emo"] == "惊叹"
    assert items[0]["act"] == "jump"
    assert all(not item.get("face") for item in items[1:])
    assert all(not item.get("emo") and not item.get("act") and not item.get("fx") for item in items[1:])
    assert items[0]["_director_intent"]["visible_characters"] == ["A", "B"]
    assert all("visible_characters" not in item["_director_intent"] for item in items[1:])
    assert any(row["reason"] == "missing_direction_evidence" for row in diagnostics)


def test_empty_agent_intent_is_missing_evidence_not_a_legacy_bypass():
    item = directed_line(1, emo="惊叹", act="jump", fx="特写")
    item["_director_intent"] = {}

    normalize_direction_density([item])

    assert not item.get("emo")
    assert not item.get("act")
    assert not item.get("fx")


def test_stateless_item_without_intent_keeps_legacy_density_behavior():
    item = directed_line(1, emo="惊叹")
    item.pop("_director_intent")

    normalize_direction_density([item])

    assert item["emo"] == "惊叹"


def test_comedy_escalation_allows_distinct_evidenced_reactions():
    items = []
    for index, emo in enumerate(("疑问", "惊叹", "怒筋"), 1):
        item = directed_line(
            index, story="event", function="comedy_escalation",
            reason="comedy_escalation", emo=emo,
        )
        item["_director"]["continuity"]["emo"] = "start" if index == 1 else "escalate"
        item["_director_intent"]["continuity"] = {
            "emo": "start" if index == 1 else "escalate"
        }
        items.append(item)

    normalize_direction_plan(items)

    assert [item.get("emo") for item in items] == ["疑问", "惊叹", "怒筋"]


def test_face_budget_is_shared_across_characters_in_the_window():
    items = []
    for index, (who, face) in enumerate(
        (("A", "01"), ("B", "01"), ("A", "02"), ("B", "02")), 1,
    ):
        item = directed_line(index, story="event", function="dialogue", face=face)
        item["who"] = who
        item["_director"]["continuity"]["face"] = "start"
        item["_director_intent"]["continuity"] = {"face": "start"}
        items.append(item)

    normalize_direction_plan(items)

    assert [item.get("face") for item in items] == ["01", "01", "02", None]


def test_authored_direction_is_never_removed_by_automatic_policy():
    items = [directed_line(index, emo="惊叹", act="jump", fx="特写") for index in range(1, 8)]
    for item in items:
        item["_explicit_direction_fields"] = ("emo", "act", "fx")

    normalize_direction_plan(items)

    assert all((item["emo"], item["act"], item["fx"]) == ("惊叹", "jump", "特写") for item in items)


def test_scene_boundary_resets_face_and_shot_state():
    first = directed_line(1, reason="new_stimulus", face="01")
    second = directed_line(2, reason="new_stimulus", face="01")
    second["_director_intent"].pop("visible_characters")
    items = [first, {"kind": "other", "raw": "---"}, second]

    normalize_direction_plan(items)

    assert first.get("face") == "01" and second.get("face") == "01"
    assert first["_director_intent"]["visible_characters"] == ["A", "B"]
    assert "visible_characters" not in second["_director_intent"]


def test_reaction_beats_have_a_scene_function_cap_and_no_duplicate_anchor():
    items = [
        directed_line(1, reason="listener_reaction"),
        directed_line(2, reason="listener_reaction"),
    ]
    beats = [
        {
            "anchor_id": f"src-{index}", "position": "after", "who": "B",
            "face": "", "emo": "沉默", "act": "", "wait_ms": 1200,
            "reason": "listener_reaction",
        }
        for index in (1, 2)
    ]

    kept, diagnostics = normalize_direction_plan(items, beats)

    assert len(kept) == 1
    assert any(row["field"] == "beat" for row in diagnostics)


def test_authored_directives_take_priority_over_generated_fields_and_camera(tmp_path):
    source = tmp_path / "authored.txt"
    source.write_text(
        "@camera A,B\n@bg BG_Authored\n@se SE_Authored\nA: hello\n",
        encoding="utf-8",
    )
    items = annotate.parse_lines(source, {
        "A": {"id": "a", "portrait": True},
        "B": {"id": "b", "portrait": True},
    })
    line = next(item for item in items if item.get("kind") == "line")
    applied = apply_model_directions(line, {
        "bg": "BG_Model", "se": "SE_Model", "emo": "惊叹",
    })
    line["_director"] = {
        "scene_type": "event", "scene_function": "dialogue",
        "reason": "listener_reaction", "visible_characters": ["A"],
        "continuity": {},
    }
    line["_director_intent"] = {
        "reason": "listener_reaction", "visible_characters": ["A"],
    }

    normalize_direction_plan(items)
    rendered = annotate.render_annotated_items(items)

    assert applied == {"emo": "惊叹"}
    assert rendered.splitlines().count("@camera A,B") == 1
    assert "@camera_hold auto" in rendered
    assert "@bg BG_Authored" in rendered and "BG_Model" not in rendered
    assert "@se SE_Authored" in rendered and "SE_Model" not in rendered


def test_authored_camera_hold_is_not_cancelled_by_generated_auto_reset(tmp_path):
    source = tmp_path / "authored-hold.txt"
    source.write_text("@camera_hold A\nA: hello\n", encoding="utf-8")
    items = annotate.parse_lines(source, {"A": {"id": "a", "portrait": True}})
    line = next(item for item in items if item.get("kind") == "line")
    line["_director"] = {
        "scene_type": "bond", "scene_function": "dialogue",
        "reason": "new_stimulus", "visible_characters": ["A"],
        "continuity": {},
    }
    line["_director_intent"] = {
        "reason": "new_stimulus", "visible_characters": ["A"],
    }

    normalize_direction_plan(items)
    rendered = annotate.render_annotated_items(items)

    assert rendered.splitlines().count("@camera_hold A") == 1
    assert "@camera_hold auto" not in rendered


def test_authored_camera_hold_blocks_generated_cameras_until_released(tmp_path):
    source = tmp_path / "authored-hold-range.txt"
    source.write_text("@camera_hold A\nA: one\nB: two\n", encoding="utf-8")
    items = annotate.parse_lines(source, {
        "A": {"id": "a", "portrait": True},
        "B": {"id": "b", "portrait": True},
    })
    for item in items:
        if item.get("kind") != "line":
            continue
        item["_director"] = {
            "scene_type": "bond", "scene_function": "dialogue",
            "reason": "listener_reaction", "visible_characters": ["B"],
            "continuity": {},
        }
        item["_director_intent"] = {
            "reason": "listener_reaction", "visible_characters": ["B"],
        }

    normalize_direction_plan(items)
    rendered = annotate.render_annotated_items(items)

    assert rendered.splitlines().count("@camera_hold A") == 1
    assert "@camera_hold B" not in rendered
