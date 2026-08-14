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


def test_ordinary_dialogue_keeps_model_direction_without_backend_aesthetic_filtering():
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
    assert all(item.get("emo") == "惊叹" for item in items[1:])
    assert all(item.get("act") == "jump" and item.get("fx") == "特写" for item in items[1:])
    assert items[0]["_director_intent"]["visible_characters"] == ["A", "B"]
    assert all("visible_characters" not in item["_director_intent"] for item in items[1:])
    assert not any(row["reason"] == "missing_direction_evidence" for row in diagnostics)


def test_empty_agent_intent_does_not_delete_valid_model_direction():
    item = directed_line(1, emo="惊叹", act="jump", fx="特写")
    item["_director_intent"] = {}

    normalize_direction_density([item])

    assert item["emo"] == "惊叹"
    assert item["act"] == "jump"
    assert item["fx"] == "特写"


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


def test_director_does_not_cap_evidence_backed_face_changes():
    items = []
    faces = tuple(("A" if index % 2 else "B", f"{index:02d}") for index in range(1, 13))
    for index, (who, face) in enumerate(faces, 1):
        item = directed_line(index, story="event", function="dialogue", face=face)
        item["who"] = who
        item["_director"]["continuity"]["face"] = "start"
        item["_director_intent"]["continuity"] = {"face": "start"}
        items.append(item)

    normalize_direction_plan(items)

    assert [item.get("face") for item in items] == [face for _, face in faces]


def test_repeated_face_is_removed_without_a_density_cap():
    first = directed_line(1, reason="new_stimulus", face="01")
    repeated = directed_line(2, reason="emotional_shift", face="01")
    repeated["_director"]["continuity"]["face"] = "start"
    repeated["_director_intent"]["continuity"] = {"face": "start"}

    normalize_direction_plan([first, repeated])

    assert first["face"] == "01"
    assert not repeated.get("face")
    assert any(
        drop["field"] == "face" and drop["reason"] == "redundant_state_restatement"
        for drop in repeated["_direction_drops"]
    )


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


def test_scene_boundary_keeps_one_establishing_background_and_place():
    first = directed_line(
        1, function="comedy_escalation", reason="none",
        bg="BG_GameCenter", place="游戏中心",
    )
    repeated = directed_line(
        2, function="comedy_escalation", reason="none",
        bg="BG_GameCenter",
    )
    items = [{"kind": "other", "raw": "---"}, first, repeated]

    normalize_direction_plan(items)

    assert first["bg"] == "BG_GameCenter"
    assert first["place"] == "游戏中心"
    assert not repeated.get("bg")
    assert any(
        drop["field"] == "bg" and drop["reason"] == "redundant_state_restatement"
        for drop in repeated["_direction_drops"]
    )


def test_hidden_speaker_direction_releases_persistent_camera():
    listener = directed_line(1, reason="listener_reaction")
    listener["_director"]["visible_characters"] = []
    listener["_director_intent"]["visible_characters"] = []
    speaker = directed_line(2, reason="none", face="03")
    speaker["_speaker_has_portrait"] = True
    speaker["_director_intent"].pop("visible_characters")

    normalize_direction_plan([listener, speaker])

    assert speaker["_camera_reset"] is True
    assert "@camera_hold auto" in annotate.annotation_directives(speaker)


def test_hidden_plain_speaker_also_releases_persistent_camera():
    listener = directed_line(1, reason="listener_reaction")
    listener["_director"]["visible_characters"] = ["B"]
    listener["_director_intent"]["visible_characters"] = ["B"]
    speaker = directed_line(2, reason="none")
    speaker["_speaker_has_portrait"] = True
    speaker["_director_intent"].pop("visible_characters")

    normalize_direction_plan([listener, speaker])

    assert speaker["_camera_reset"] is True
    assert "@camera_hold auto" in annotate.annotation_directives(speaker)


def test_explicit_empty_visibility_is_a_persistent_empty_shot():
    item = directed_line(1, reason="scene_transition")
    item["_director"]["visible_characters"] = []
    item["_director_intent"]["visible_characters"] = []

    directives = annotate.annotation_directives(item)

    assert "@camera_hold -" in directives


def test_valid_model_camera_is_not_rejected_for_missing_reason():
    listener = directed_line(1, reason="listener_reaction")
    listener["_director"]["visible_characters"] = ["B"]
    listener["_director_intent"]["visible_characters"] = ["B"]
    speaker = directed_line(2, reason="none", face="03")
    speaker["_speaker_has_portrait"] = True

    normalize_direction_plan([listener, speaker])

    assert speaker["_director_intent"]["visible_characters"] == ["A", "B"]
    assert not speaker.get("_camera_reset")


def test_narrator_never_receives_character_effect_clear():
    item = {
        "kind": "line", "who": "旁白", "text": "动作发生。",
        "_speaker_has_portrait": False,
        "_director": {"continuity": {"fx": "end"}},
        "_director_intent": {},
    }

    assert "@fx 旁白 无" not in annotate.annotation_directives(item)


def test_reaction_beats_keep_distinct_anchors_and_remove_exact_duplicates():
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
    beats.append(dict(beats[0]))

    kept, diagnostics = normalize_direction_plan(items, beats)

    assert len(kept) == 2
    assert any(row["reason"] == "duplicate_reaction_beat" for row in diagnostics)


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
