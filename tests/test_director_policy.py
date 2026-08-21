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


def test_explicit_model_cut_is_preserved_without_backend_aesthetic_override():
    first = directed_line(1, reason="continuity_hold")
    second = directed_line(2, reason="continuity_hold", shot_transition="cut")
    second["_director"]["shot_transition"] = "cut"
    second["_director_intent"]["shot_transition"] = "cut"

    normalize_direction_plan([first, second])

    assert second["_director"].get("shot_transition") == "cut"
    assert second["_director_intent"]["shot_transition"] == "cut"
    assert not any(
        drop["field"] == "shot_transition"
        for drop in second.get("_direction_drops", [])
    )


def test_semantic_switch_group_is_mapped_to_cut():
    first = directed_line(1, reason="continuity_hold")
    second = directed_line(2, reason="new_stimulus", shot_operation="switch_group")
    second["_director"]["shot_operation"] = "switch_group"
    second["_director"]["visible_characters"] = ["A"]
    second["_director_intent"].update({"shot_operation": "switch_group", "visible_characters": ["A"]})

    normalize_direction_plan([first, second])

    assert second["_director"]["shot_transition"] == "cut"


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


def test_explicit_layout_intent_emits_one_compact_semantic_directive():
    item = directed_line(1, reason="relation_shift")
    item["_director"].update({
        "relation_distance": "distant",
        "focus_character": "A",
        "reaction_target": "B",
    })
    item["_director_intent"] = {
        "relation_distance": "distant",
        "focus_character": "A",
        "reaction_target": "B",
        "reason": "relation_shift",
    }

    directives = annotate.annotation_directives(item)

    assert directives.count(
        '@layout {"relation_distance":"distant","focus_character":"A",'
        '"reaction_target":"B"}'
    ) == 1


def test_unchanged_layout_state_is_not_repeated_on_following_line():
    first = directed_line(1, reason="relation_shift")
    second = directed_line(2, reason="continuity_hold")
    for item in (first, second):
        item["_director"].update({
            "relation_distance": "distant",
            "focus_character": "A",
            "reaction_target": "B",
        })
        item["_director_intent"].update({
            "relation_distance": "distant",
            "focus_character": "A",
            "reaction_target": "B",
        })

    normalize_direction_plan([first, second])

    assert any(line.startswith("@layout ") for line in annotate.annotation_directives(first))
    assert not any(line.startswith("@layout ") for line in annotate.annotation_directives(second))


def test_valid_model_camera_is_not_rejected_for_missing_reason():
    listener = directed_line(1, reason="listener_reaction")
    listener["_director"]["visible_characters"] = ["B"]
    listener["_director_intent"]["visible_characters"] = ["B"]
    speaker = directed_line(2, reason="none", face="03")
    speaker["_speaker_has_portrait"] = True

    normalize_direction_plan([listener, speaker])

    assert speaker["_director_intent"]["visible_characters"] == ["A", "B"]
    assert not speaker.get("_camera_reset")


def test_three_person_address_preserves_the_models_authored_shot_groups():
    momoi = directed_line(1, reason="emotional_shift")
    momoi.update({
        "who": "桃井", "text": "那就拜托你们两个了，先从入口区域开始。",
        "_speaker_has_portrait": True,
    })
    momoi["_director"]["visible_characters"] = ["桃井", "爱丽丝"]
    momoi["_director_intent"]["visible_characters"] = ["桃井", "爱丽丝"]

    midori = directed_line(2, reason="listener_reaction")
    midori.update({
        "who": "绿", "text": "桃井，你站那边，我从另一侧看，这样不会漏掉同一个地方。",
        "_speaker_has_portrait": True,
    })
    midori["_director"]["visible_characters"] = ["桃井", "绿"]
    midori["_director_intent"]["visible_characters"] = ["桃井", "绿"]

    aris = directed_line(3, reason="new_stimulus")
    aris.update({
        "who": "爱丽丝", "text": "记录要员爱丽丝，报告：入口区域没有发现异常。",
        "_speaker_has_portrait": True,
    })
    aris["_director"]["visible_characters"] = ["桃井", "爱丽丝"]
    aris["_director_intent"]["visible_characters"] = ["桃井", "爱丽丝"]

    normalize_direction_plan([momoi, midori, aris])

    assert momoi["_director_intent"]["visible_characters"] == ["桃井", "爱丽丝"]
    assert midori["_director_intent"]["visible_characters"] == ["桃井", "绿"]
    assert aris["_director_intent"]["visible_characters"] == ["桃井", "爱丽丝"]
    assert not any(
        drop["reason"] in {
            "three_person_stable_shot_partition",
            "rapid_reverse_shot_safe_group_merge",
            "short_shot_safe_speaker_join",
        }
        for item in (momoi, midori, aris)
        for drop in item.get("_direction_drops", [])
    )


def test_rapid_three_person_reverse_shots_are_not_auto_merged():
    dialogue = [
        ("桃井", "那就拜托你们两个了，先从入口区域开始。"),
        ("绿", "桃井，你站那边，我从另一侧看。"),
        ("爱丽丝", "记录要员爱丽丝，报告：入口区域没有发现异常。"),
        ("桃井", "太好了！那我们继续往下检查。"),
        ("绿", "嗯，接下来检查里面。"),
        ("爱丽丝", "了解。"),
    ]
    items = []
    for index, (who, text) in enumerate(dialogue, 1):
        item = directed_line(index, reason="continuity_hold")
        item.update({"who": who, "text": text, "_speaker_has_portrait": True})
        item["_director"]["visible_characters"] = [who]
        item["_director_intent"]["visible_characters"] = [who]
        items.append(item)

    normalize_direction_plan(items, camera_merge_allowed=lambda names: len(names) <= 3)

    assert all(
        item["_director_intent"]["visible_characters"] == [who]
        for item, (who, _text) in zip(items, dialogue)
    )
    assert not any(
        drop["reason"] == "rapid_reverse_shot_safe_group_merge"
        for item in items
        for drop in item.get("_direction_drops", [])
    )


def test_rapid_reverse_shot_keeps_cut_when_portrait_geometry_cannot_fit():
    speakers = ("桃井", "绿", "爱丽丝", "桃井")
    items = []
    for index, who in enumerate(speakers, 1):
        item = directed_line(index, reason="continuity_hold")
        item.update({
            "who": who,
            "text": "拜托你们两个。" if index == 1 else f"line {index}",
            "_speaker_has_portrait": True,
        })
        item["_director"]["visible_characters"] = [who]
        item["_director_intent"]["visible_characters"] = [who]
        items.append(item)

    normalize_direction_plan(items, camera_merge_allowed=lambda _names: False)

    assert items[3]["_director_intent"]["visible_characters"] == ["桃井"]
    assert not any(
        drop["reason"] == "rapid_reverse_shot_safe_group_merge"
        for drop in items[3].get("_direction_drops", [])
    )


def test_next_speaker_is_not_auto_joined_to_a_recent_two_shot():
    dialogue = [
        ("桃井", "那就拜托你们两个了。", True, ["桃井"]),
        ("绿", "我去另一侧检查。", True, ["绿"]),
        ("旁白", "桃井和绿分开站在桌子的两侧。", False, ["桃井", "绿"]),
        ("爱丽丝", "记录要员爱丽丝，报告：没有发现异常。", True, ["爱丽丝"]),
        ("桃井", "太好了。", True, ["桃井"]),
    ]
    items = []
    for index, (who, text, portrait, camera) in enumerate(dialogue, 1):
        item = directed_line(index, reason="continuity_hold")
        item.update({"who": who, "text": text, "_speaker_has_portrait": portrait})
        item["_director"]["visible_characters"] = camera
        item["_director_intent"]["visible_characters"] = camera
        items.append(item)

    normalize_direction_plan(items, camera_merge_allowed=lambda names: len(names) <= 3)

    assert items[2]["_director_intent"]["visible_characters"] == ["桃井", "绿"]
    assert items[3]["_director_intent"]["visible_characters"] == ["爱丽丝"]
    assert items[4]["_director_intent"]["visible_characters"] == ["桃井"]
    assert not any(
        drop["reason"] == "short_shot_safe_speaker_join"
        for item in items
        for drop in item.get("_direction_drops", [])
    )


def test_closeup_can_break_a_recent_three_person_shot_pattern():
    speakers = ("桃井", "绿", "爱丽丝", "桃井")
    items = []
    for index, who in enumerate(speakers, 1):
        item = directed_line(index, reason="continuity_hold")
        item.update({
            "who": who,
            "text": "拜托你们两个。" if index == 1 else f"line {index}",
            "_speaker_has_portrait": True,
        })
        item["_director"]["visible_characters"] = [who]
        item["_director_intent"]["visible_characters"] = [who]
        items.append(item)
    items[3]["fx"] = "特写"
    items[3]["_director"]["reason"] = "action_impact"

    normalize_direction_plan(items, camera_merge_allowed=lambda _names: True)

    assert items[3]["_director_intent"]["visible_characters"] == ["桃井"]


def test_unmotivated_two_shot_single_occupant_swap_is_left_for_quality_gate_repair():
    first = directed_line(1, reason="listener_reaction")
    first.update({"who": "A", "text": "first", "_speaker_has_portrait": True})
    first["_director"]["visible_characters"] = ["A", "B"]
    first["_director_intent"]["visible_characters"] = ["A", "B"]

    second = directed_line(2, reason="listener_reaction")
    second.update({"who": "C", "text": "second", "_speaker_has_portrait": True})
    second["_director"]["visible_characters"] = ["A", "C"]
    second["_director_intent"]["visible_characters"] = ["A", "C"]

    normalize_direction_plan([first, second])

    assert second["_director_intent"]["visible_characters"] == ["A", "C"]
    assert not any(
        drop["reason"] == "unmotivated_single_occupant_swap"
        for drop in second.get("_direction_drops", [])
    )


def test_narration_never_turns_a_two_shot_swap_into_a_narrator_camera():
    first = directed_line(1, reason="listener_reaction")
    first["_director"]["visible_characters"] = ["A", "B"]
    first["_director_intent"]["visible_characters"] = ["A", "B"]
    narration = directed_line(2, reason="listener_reaction")
    narration.update({
        "who": "旁白", "text": "镜头越过房间。", "_speaker_has_portrait": False,
    })
    narration["_director"]["visible_characters"] = ["A", "C"]
    narration["_director_intent"]["visible_characters"] = ["A", "C"]

    normalize_direction_plan([first, narration])

    assert narration["_director_intent"]["visible_characters"] == ["A", "C"]
    assert "旁白" not in narration["_director_intent"]["visible_characters"]


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


def test_before_silent_beat_advances_camera_state_before_anchor_line():
    first = directed_line(1, reason="listener_reaction")
    first.update({"who": "A", "_speaker_has_portrait": True})
    first["_director"]["visible_characters"] = ["A"]
    first["_director_intent"]["visible_characters"] = ["A"]
    anchor = directed_line(2, reason="continuity_hold")
    anchor.update({"who": "B", "_speaker_has_portrait": True})
    anchor["_director_intent"].pop("visible_characters")
    beats = [{
        "beat_id": "beat-before-b",
        "anchor_id": "src-2",
        "position": "before",
        "who": "B",
        "visible_characters": ["B"],
        "wait_ms": 500,
    }]

    kept, _diagnostics = normalize_direction_plan([first, anchor], beats)

    assert kept == beats
    assert not anchor.get("_camera_reset")


def test_after_silent_beat_advances_camera_state_before_next_line():
    first = directed_line(1, reason="listener_reaction")
    first.update({"who": "A", "_speaker_has_portrait": True})
    first["_director"]["visible_characters"] = ["A"]
    first["_director_intent"]["visible_characters"] = ["A"]
    second = directed_line(2, reason="continuity_hold")
    second.update({"who": "B", "_speaker_has_portrait": True})
    second["_director_intent"].pop("visible_characters")
    beats = [{
        "beat_id": "beat-after-a",
        "anchor_id": "src-1",
        "position": "after",
        "who": "B",
        "visible_characters": ["B"],
        "wait_ms": 500,
    }]

    normalize_direction_plan([first, second], beats)

    assert not second.get("_camera_reset")


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
