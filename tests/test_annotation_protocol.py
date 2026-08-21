import pytest

import llm
from director_state import BEAT_REASONS, default_director

from annotation_protocol import (
    ChunkProtocolError,
    build_chunk_schema,
    build_compact_chunk_schema,
    expand_compact_chunk_response,
    validate_chunk_response,
)


TARGETS = [
    {"annotation_id": "src-1-0-a", "text_fingerprint": "fp-a"},
    {"annotation_id": "src-2-0-b", "text_fingerprint": "fp-b"},
]


def row(source_id, fingerprint):
    return {
        "source_id": source_id, "text_fingerprint": fingerprint,
        "face": "", "emo": "", "act": "", "fx": "", "se": "",
        "bg": "", "bg_request": "", "place": "", "shake": False,
        "bgfx": "", "trans": "", "move": 0, "shot": "",
    }


def complete_response():
    return {
        "lines": [row("src-1-0-a", "fp-a"), row("src-2-0-b", "fp-b")],
        "state_delta": {}, "memory_events": [],
    }


def test_complete_line_accepts_normalized_director_metadata():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "scene_type": "bond",
        "scene_function": "dialogue",
        "emotion_phase": "hesitating",
        "subtext": "waiting for an answer",
        "relation_distance": "approaching",
        "focus_kind": "listener",
        "focus_character": "Kai",
        "reaction_target": "Kai",
        "visible_characters": ["Kai"],
        "continuity": {
            "face": "hold", "emo": "none", "act": "none",
            "fx": "none", "bgfx": "none",
        },
        "reason": "listener_reaction",
    }

    result = validate_chunk_response(
        response, TARGETS, cast={"Kai": {"id": "kai", "portrait": True}},
    )

    assert result["lines_by_id"]["src-1-0-a"]["direction"]["focus_kind"] == "listener"
    assert result["diagnostics"] == []


def test_explicit_listener_shot_allows_a_portrait_speaker_to_remain_offscreen():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "visible_characters": ["圣娅"],
        "positions": {"圣娅": 3},
        "shot_transition": "cut",
        "focus_kind": "listener",
        "focus_character": "圣娅",
    }
    targets = [dict(TARGETS[0], who="绿"), dict(TARGETS[1], who="圣娅")]
    cast = {
        "圣娅": {"id": "seia", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }

    result = validate_chunk_response(response, targets, cast=cast)

    line = result["lines_by_id"]["src-1-0-a"]
    assert line["direction"]["visible_characters"] == ["圣娅"]
    assert line["direction_intent"]["visible_characters"] == ["圣娅"]


def test_dialogue_cut_can_omit_numeric_positions_for_backend_auto_layout():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "shot_transition": "cut",
        "visible_characters": ["Kai"],
        "focus_kind": "speaker",
    }
    targets = [dict(TARGETS[0], who="Kai"), dict(TARGETS[1], who="Kai")]
    result = validate_chunk_response(
        response, targets, cast={"Kai": {"id": "kai", "portrait": True}},
    )
    assert result["lines_by_id"]["src-1-0-a"]["direction_intent"] == {
        "shot_transition": "cut", "visible_characters": ["Kai"],
        "focus_kind": "speaker",
    }


def test_narration_line_can_carry_an_explicit_visible_listener_reaction():
    response = complete_response()
    response["lines"][0]["reactions"] = [{
        "who": "Kai", "face": "31", "emo": "惊疑", "act": "stiff",
    }]
    response["lines"][0]["direction"] = {
        "focus_kind": "listener",
        "focus_character": "Kai",
        "visible_characters": ["Kai"],
        "positions": {"Kai": 3},
    }
    targets = [dict(TARGETS[0], who="旁白"), dict(TARGETS[1], who="Kai")]
    cast = {
        "旁白": {"id": "narrator", "portrait": False, "narrator": True},
        "Kai": {"id": "kai", "portrait": True, "narrator": False},
    }
    constraints = {
        "faces_by_id": {"kai": {"31"}},
        "ok_emo": {"惊疑"}, "ok_act": {"stiff"}, "sym2cn": {},
    }

    result = validate_chunk_response(
        response, targets, cast=cast, constraints=constraints,
    )

    assert result["lines_by_id"]["src-1-0-a"]["reactions"] == [{
        "who": "Kai", "face": "31", "emo": "惊疑", "act": "stiff",
    }]


@pytest.mark.parametrize(("field", "value", "code"), [
    ("face", "99", "illegal_line_face"),
    ("emo", "惊疑[?!]", "illegal_line_emoticon"),
    ("act", "invented_action", "illegal_line_action"),
])
def test_top_level_line_rejects_unknown_character_resources(field, value, code):
    response = complete_response()
    response["lines"][0][field] = value
    targets = [dict(TARGETS[0], who="Kai"), dict(TARGETS[1], who="Kai")]
    cast = {"Kai": {"id": "kai", "portrait": True, "narrator": False}}
    constraints = {
        "faces_by_id": {"kai": {"03"}},
        "ok_emo": {"惊疑", "疑问"},
        "ok_act": {"stiff"},
        "sym2cn": {},
    }

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(
            response, targets, cast=cast, constraints=constraints,
        )

    assert error.value.code == code


def test_top_level_line_canonicalizes_documented_emoticon_alias():
    response = complete_response()
    response["lines"][0]["emo"] = "question"
    targets = [dict(TARGETS[0], who="Kai"), dict(TARGETS[1], who="Kai")]
    cast = {"Kai": {"id": "kai", "portrait": True, "narrator": False}}

    result = validate_chunk_response(
        response, targets, cast=cast,
        constraints={"ok_emo": {"疑问"}, "sym2cn": {}},
    )

    assert result["lines_by_id"]["src-1-0-a"]["emo"] == "疑问"


def test_top_level_line_structural_validation_remains_available_without_constraints():
    response = complete_response()
    response["lines"][0]["emo"] = "fixture-only-token"

    result = validate_chunk_response(response, TARGETS)

    assert result["lines_by_id"]["src-1-0-a"]["emo"] == "fixture-only-token"


def test_compact_expansion_preserves_line_reactions_and_marks_intent():
    compact = {
        "lines": [{
            "source_id": "src-1-0-a",
            "reactions": [{"who": "Kai", "face": "", "emo": "惊疑", "act": ""}],
        }],
        "state_delta": {}, "memory_events": [],
    }
    expanded = expand_compact_chunk_response(compact, [dict(TARGETS[0], who="旁白")])

    assert expanded["lines"][0]["reactions"][0]["who"] == "Kai"
    assert "reactions" in expanded.annotation_intents["src-1-0-a"]


def test_line_reaction_cannot_be_attached_to_a_narrator_or_hidden_character():
    response = complete_response()
    response["lines"][0]["reactions"] = [{
        "who": "旁白", "face": "31", "emo": "", "act": "",
    }]
    targets = [dict(TARGETS[0], who="Kai"), dict(TARGETS[1], who="旁白")]
    cast = {
        "Kai": {"id": "kai", "portrait": True, "narrator": False},
        "旁白": {"id": "narrator", "portrait": False, "narrator": True},
    }

    with pytest.raises(ChunkProtocolError, match="角色不可显示"):
        validate_chunk_response(
            response, targets, cast=cast,
            constraints={"faces_by_id": {"kai": {"31"}}},
        )


def test_dialogue_reveal_adds_the_speaker_to_a_continuous_shot_without_cut():
    response = complete_response()
    response["lines"][0]["reveal"] = "right"
    response["lines"][0]["direction"] = {
        "shot_transition": "reframe",
        "visible_characters": ["圣娅", "绿"],
        "positions": {"圣娅": 2, "绿": 5},
    }
    targets = [dict(TARGETS[0], who="绿"), dict(TARGETS[1], who="圣娅")]
    cast = {
        "圣娅": {"id": "seia", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }

    result = validate_chunk_response(response, targets, cast=cast)

    assert result["lines_by_id"]["src-1-0-a"]["reveal"] == "right"

    response["lines"][0]["direction"]["shot_transition"] = "cut"
    with pytest.raises(ChunkProtocolError, match="不能与整镜硬切"):
        validate_chunk_response(response, targets, cast=cast)


@pytest.mark.parametrize("direction", [
    {"camera_hint": "closeup"},
    {"focus_kind": ["listener"]},
    {"visible_characters": "Kai"},
    {"continuity": {"face": 1}},
])
def test_complete_line_rejects_unknown_or_wrongly_typed_director_wire_values(direction):
    response = complete_response()
    response["lines"][0]["direction"] = direction

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_line"


def test_unknown_director_character_degrades_with_diagnostic_without_losing_source():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "focus_kind": "listener",
        "focus_character": "Unknown",
        "visible_characters": ["Kai", "Unknown"],
    }

    result = validate_chunk_response(
        response, TARGETS, cast={"Kai": {"id": "kai", "portrait": True}},
    )

    line = result["lines_by_id"]["src-1-0-a"]
    assert line["direction"]["focus_character"] == ""
    assert line["direction"]["visible_characters"] == ["Kai"]
    assert any(item["code"] == "director_unknown_character" for item in result["diagnostics"])


def test_direction_rejects_a_four_or_more_character_shot_before_normalization():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "reaction_target": "Unknown",
        "visible_characters": ["A", "B", "C", "D", "E", "F"],
    }
    cast = {name: {"id": name.lower(), "portrait": True} for name in "ABCDEF"}

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS, cast=cast)

    assert error.value.code == "invalid_line"


def test_continuity_start_without_a_layer_value_degrades_to_no_command():
    response = complete_response()
    response["lines"][0]["direction"] = {"continuity": {"emo": "start"}}

    result = validate_chunk_response(response, TARGETS)

    line = result["lines_by_id"]["src-1-0-a"]
    assert line["direction"]["continuity"]["emo"] == "none"
    assert any(
        row["code"] == "director_continuity_without_value"
        for row in result["diagnostics"]
    )


def test_visible_character_intent_distinguishes_omission_from_explicit_empty_shot():
    omitted = validate_chunk_response(complete_response(), TARGETS)
    explicit_response = complete_response()
    explicit_response["lines"][0]["direction"] = {"visible_characters": []}
    explicit = validate_chunk_response(explicit_response, TARGETS)

    assert omitted["lines_by_id"]["src-1-0-a"]["direction_intent"] == {}
    assert explicit["lines_by_id"]["src-1-0-a"]["direction_intent"] == {
        "visible_characters": [],
    }

    compact = expand_compact_chunk_response({
        "lines": [{"i": 1, "d": {"visible_characters": []}}, {"i": 2}],
        "state_delta": {}, "memory_events": [],
    }, TARGETS)
    compact_validated = validate_chunk_response(compact, TARGETS)
    assert compact_validated["lines_by_id"]["src-1-0-a"]["direction_intent"] == {
        "visible_characters": [],
    }
    assert compact_validated["lines_by_id"]["src-2-0-b"]["direction_intent"] == {}


@pytest.mark.parametrize("lines,code", [
    ([row("src-1-0-a", "fp-a")], "missing_target"),
    ([row("src-1-0-a", "fp-a"), row("src-1-0-a", "fp-a")], "duplicate_target"),
    ([row("src-1-0-a", "fp-a"), row("future", "fp-b")], "unknown_target"),
])
def test_response_requires_exact_target_coverage(lines, code):
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response({"lines": lines, "state_delta": {}, "memory_events": []}, TARGETS)
    assert exc.value.code == code


def test_response_rejects_fingerprint_mismatch():
    response = complete_response()
    response["lines"][1]["text_fingerprint"] = "wrong"
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response(response, TARGETS)
    assert exc.value.code == "fingerprint_mismatch"


def test_state_and_events_must_use_whitelisted_shape():
    response = complete_response()
    response["state_delta"] = {"api_key": "secret"}
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response(response, TARGETS)
    assert exc.value.code == "invalid_state_delta"


@pytest.mark.parametrize("field", [
    "background", "place", "bgfx", "visible_characters", "positions",
    "last_faces", "recent_emoticons", "recent_actions", "recent_sounds",
    "open_threads",
])
def test_optional_state_null_means_no_update(field):
    response = complete_response()
    response["state_delta"] = {field: None}

    validated = validate_chunk_response(response, TARGETS)

    assert validated["state_delta"] == {}


@pytest.mark.parametrize("field,value", [
    ("background", []),
    ("visible_characters", "Kei"),
    ("positions", []),
])
def test_state_delta_still_rejects_wrong_non_null_types(field, value):
    response = complete_response()
    response["state_delta"] = {field: value}

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_state_delta"


def test_explicit_null_beats_is_rejected():
    response = complete_response()
    response["beats"] = None

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_beats"


@pytest.mark.parametrize("field,value", [
    ("source_id", 1),
    ("text_fingerprint", 123),
])
def test_line_identity_fields_require_strings(field, value):
    response = complete_response()
    response["lines"][0][field] = value

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_line"


@pytest.mark.parametrize("field,value", [
    ("face", None),
    ("shake", 1),
    ("move", True),
])
def test_annotation_fields_keep_schema_types(field, value):
    response = complete_response()
    response["lines"][0][field] = value

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_line"


@pytest.mark.parametrize("field,value", [
    ("kind", None),
    ("participants", [None]),
    ("keywords", "callback"),
    ("summary", None),
    ("source_ids", [1]),
    ("evidence", None),
    ("importance", True),
    ("status", None),
])
def test_memory_event_fields_keep_schema_types(field, value):
    response = complete_response()
    response["memory_events"] = [{
        "kind": "callback", "participants": ["凯伊"], "keywords": ["称呼"],
        "summary": "发生了称呼变化", "source_ids": ["src-1-0-a"],
        "evidence": "证据", "importance": 0.8, "status": "open",
    }]
    response["memory_events"][0][field] = value

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_memory_event"


def test_beat_fields_do_not_coerce_null_to_empty_string():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": None,
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction",
    }]

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)

    assert error.value.code == "invalid_beat"


def test_event_requires_visible_source_evidence():
    response = complete_response()
    response["memory_events"] = [{
        "kind": "callback", "participants": ["凯伊"], "keywords": ["称呼"],
        "summary": "发生了称呼变化", "source_ids": ["not-visible"],
        "evidence": "证据", "importance": 0.8, "status": "open",
    }]
    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response(response, TARGETS)
    assert exc.value.code == "invalid_event_source"


def test_valid_response_is_keyed_by_source_id():
    validated = validate_chunk_response(complete_response(), TARGETS)
    assert list(validated["lines_by_id"]) == ["src-1-0-a", "src-2-0-b"]
    assert validated["beats"] == []


def test_valid_dialogue_free_beat_is_normalized_through_resource_constraints():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "[……]", "act": "", "wait_ms": 2500,
        "reason": "listener_reaction",
    }]
    constraints = {
        "faces_by_id": {"kei": {"31"}},
        "sym2cn": {"[……]": "沉默"},
        "ok_emo": {"[……]", "沉默"},
        "ok_act": {"jump"},
    }

    validated = validate_chunk_response(
        response, TARGETS, cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints=constraints,
    )

    assert validated["beats"] == [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "沉默", "act": "", "wait_ms": 2500,
        "reason": "listener_reaction",
        "beat_id": validated["beats"][0]["beat_id"],
    }]
    assert validated["beats"][0]["beat_id"].startswith("beat-")


def test_dialogue_free_beat_preserves_a_valid_reason():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "Kai",
        "face": "", "emo": "", "act": "", "wait_ms": 250,
        "reason": "listener_reaction",
    }]

    validated = validate_chunk_response(
        response, TARGETS, cast={"Kai": {"id": "kai", "portrait": True}},
    )

    assert validated["beats"][0]["reason"] == "listener_reaction"


@pytest.mark.parametrize("reason,code", [
    (None, "invalid_beat"),
    ("dramatic_pause", "invalid_beat_reason"),
])
def test_dialogue_free_beat_rejects_missing_or_unknown_reason(reason, code):
    response = complete_response()
    beat = {
        "anchor_id": "src-1-0-a", "position": "after", "who": "Kai",
        "face": "", "emo": "", "act": "", "wait_ms": 250,
    }
    if reason is not None:
        beat["reason"] = reason
    response["beats"] = [beat]

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(
            response, TARGETS, cast={"Kai": {"id": "kai", "portrait": True}},
        )

    assert error.value.code == code


@pytest.mark.parametrize("patch,code", [
    ({"anchor_id": "future"}, "unknown_beat_anchor"),
    ({"face": "99"}, "illegal_beat_face"),
    ({"wait_ms": -1}, "invalid_beat_wait"),
    ({"wait_ms": 10001}, "invalid_beat_wait"),
])
def test_dialogue_free_beat_rejects_invalid_anchor_assets_and_wait(patch, code):
    response = complete_response()
    beat = {
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "沉默", "act": "", "wait_ms": 2500,
        "reason": "listener_reaction",
    }
    beat.update(patch)
    response["beats"] = [beat]
    constraints = {
        "faces_by_id": {"kei": {"31"}}, "sym2cn": {},
        "ok_emo": {"沉默"}, "ok_act": {"jump"},
    }

    with pytest.raises(ChunkProtocolError) as exc:
        validate_chunk_response(
            response, TARGETS, cast={"凯伊": {"id": "kei", "portrait": True}},
            constraints=constraints,
        )

    assert exc.value.code == code


def test_chunk_schema_offers_optional_bounded_beats():
    schema = build_chunk_schema(["src-1-0-a"])
    beat = schema["properties"]["beats"]["items"]

    assert "beats" not in schema["required"]
    assert beat["properties"]["anchor_id"]["enum"] == ["src-1-0-a"]
    assert beat["properties"]["wait_ms"]["maximum"] == 10000
    assert beat["properties"]["reason"]["enum"] == list(BEAT_REASONS)
    assert "reason" in beat["required"]


def test_silent_beat_schema_can_express_a_true_hard_cut():
    schema = build_chunk_schema(["src-1-0-a"])
    beat = schema["properties"]["beats"]["items"]

    assert beat["properties"]["shot_transition"]["enum"] == ["cut", "reframe"]


def test_narrated_physical_reaction_can_anchor_a_dialogue_free_action_beat():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "", "emo": "", "act": "stiff", "wait_ms": 0,
        "reason": "physical_reaction",
    }]

    validated = validate_chunk_response(
        response, TARGETS, cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints={"faces_by_id": {}, "sym2cn": {}, "ok_emo": set(), "ok_act": {"stiff"}},
    )

    assert validated["beats"][0] == {
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "", "emo": "", "act": "stiff", "wait_ms": 0,
        "reason": "physical_reaction",
        "beat_id": validated["beats"][0]["beat_id"],
    }


def test_beat_id_is_deterministic_and_a_repair_can_preserve_it():
    response = complete_response()
    beat = {
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "", "emo": "", "act": "stiff", "wait_ms": 200,
        "reason": "physical_reaction",
    }
    response["beats"] = [dict(beat)]
    kwargs = {
        "cast": {"凯伊": {"id": "kei", "portrait": True}},
        "constraints": {"faces_by_id": {}, "ok_emo": set(), "ok_act": {"stiff"}},
    }

    first = validate_chunk_response(response, TARGETS, **kwargs)["beats"][0]
    second = validate_chunk_response(response, TARGETS, **kwargs)["beats"][0]
    repaired = dict(beat, beat_id=first["beat_id"], wait_ms=350)
    response["beats"] = [repaired]
    third = validate_chunk_response(response, TARGETS, **kwargs)["beats"][0]

    assert first["beat_id"] == second["beat_id"] == third["beat_id"]


def test_scene_presence_state_delta_accepts_only_tristate_values():
    response = complete_response()
    response["state_delta"] = {
        "scene_presence": {"凯伊": "present", "爱丽丝": "unknown"},
    }
    validated = validate_chunk_response(response, TARGETS)
    assert validated["state_delta"]["scene_presence"] == response["state_delta"]["scene_presence"]

    response["state_delta"] = {"scene_presence": {"凯伊": "enter"}}
    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS)
    assert error.value.code == "invalid_state_delta"


def test_multi_stage_beats_have_no_fixed_chunk_count_and_keep_same_actor_steps():
    response = complete_response()
    response["beats"] = [
        {
            "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
            "face": "31", "emo": "", "act": "", "wait_ms": index * 100,
            "reason": "physical_reaction",
        }
        for index in range(7)
    ]
    validated = validate_chunk_response(
        response,
        TARGETS,
        cast={"凯伊": {"id": "kei", "portrait": True}},
        constraints={"faces_by_id": {"kei": {"31"}}, "ok_emo": set(), "ok_act": set()},
    )

    assert len(validated["beats"]) == 7
    assert [beat["wait_ms"] for beat in validated["beats"]] == list(range(0, 700, 100))


def test_pure_ai_beat_accepts_camera_positions_entry_exit_and_effects():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "沉默", "act": "stiff", "wait_ms": 700,
        "reason": "physical_reaction",
        "visible_characters": ["凯伊", "爱丽丝"],
        "positions": {"凯伊": 1, "爱丽丝": 4},
        "enter": [{"who": "爱丽丝", "slot": 4, "side": "right"}],
        "exit": [{"who": "爱丽丝", "side": "left"}],
        "fx": "通讯+特写", "se": "SE_Step", "bg": "BG_Black",
        "place": "黑场", "trans": "淡入淡出 1000", "bgfx": "闪白", "shake": True,
    }]
    cast = {
        "凯伊": {"id": "kei", "portrait": True},
        "爱丽丝": {"id": "aris", "portrait": True},
    }
    constraints = {
        "faces_by_id": {"kei": {"31"}}, "sym2cn": {},
        "ok_emo": {"沉默"}, "ok_act": {"stiff"}, "ok_fx": {"通讯", "特写"},
        "ok_se": {"SE_Step"}, "ok_bg": {"BG_Black"}, "ok_bgfx": {"闪白"},
        "portrait_profiles_by_name": {
            "凯伊": {"min_slot_gap": 2}, "爱丽丝": {"min_slot_gap": 2},
        },
    }

    beat = validate_chunk_response(response, TARGETS, cast=cast, constraints=constraints)["beats"][0]

    assert beat["positions"] == {"凯伊": 1, "爱丽丝": 4}
    assert beat["enter"] == [{"who": "爱丽丝", "slot": 4, "side": "right"}]
    assert beat["fx"] == "通讯+特写"
    assert beat["bg"] == "BG_Black"
    assert beat["trans"] == "淡入淡出 1000"
    assert beat["shake"] is True


def test_pure_ai_beat_accepts_multiple_simultaneous_character_reactions():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "问号", "act": "", "wait_ms": 900,
        "reason": "listener_reaction",
        "visible_characters": ["凯伊", "爱丽丝"],
        "shot_transition": "cut",
        "positions": {"凯伊": 1, "爱丽丝": 4},
        "reactions": [{
            "who": "爱丽丝", "face": "05", "emo": "问号", "act": "stiff",
        }],
    }]
    cast = {
        "凯伊": {"id": "kei", "portrait": True},
        "爱丽丝": {"id": "aris", "portrait": True},
    }
    constraints = {
        "faces_by_id": {"kei": {"31"}, "aris": {"05"}},
        "sym2cn": {}, "ok_emo": {"问号"}, "ok_act": {"stiff"}, "ok_fx": set(),
    }

    beat = validate_chunk_response(response, TARGETS, cast=cast, constraints=constraints)["beats"][0]

    assert beat["reactions"] == [{
        "who": "爱丽丝", "face": "05", "emo": "问号", "act": "stiff",
    }]
    assert beat["shot_transition"] == "cut"


def test_cut_requires_a_complete_shot_and_cannot_share_physical_entry():
    response = complete_response()
    base = {
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "", "act": "", "wait_ms": 0,
        "reason": "listener_reaction", "shot_transition": "cut",
        "visible_characters": ["凯伊", "爱丽丝"],
    }
    cast = {
        "凯伊": {"id": "kei", "portrait": True},
        "爱丽丝": {"id": "aris", "portrait": True},
    }
    constraints = {
        "faces_by_id": {"kei": {"31"}}, "ok_emo": set(), "ok_act": set(),
    }

    response["beats"] = [dict(base)]
    with pytest.raises(ChunkProtocolError, match="完整镜头"):
        validate_chunk_response(response, TARGETS, cast=cast, constraints=constraints)

    response["beats"] = [{
        **base,
        "positions": {"凯伊": 1, "爱丽丝": 4},
        "enter": [{"who": "爱丽丝", "slot": 4, "side": "right"}],
    }]
    with pytest.raises(ChunkProtocolError, match="不能与真实入场"):
        validate_chunk_response(response, TARGETS, cast=cast, constraints=constraints)


def test_beat_reveal_is_visual_only_and_follows_the_target_slot_side():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "before", "who": "绿",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "entrance_reveal", "shot_transition": "reframe",
        "visible_characters": ["圣娅", "绿"],
        "positions": {"圣娅": 2, "绿": 5},
        "reveal": [{"who": "绿", "slot": 5, "side": "left"}],
    }]
    cast = {
        "圣娅": {"id": "seia", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }

    result = validate_chunk_response(response, TARGETS, cast=cast, constraints={})

    assert result["beats"][0]["reveal"] == [
        {"who": "绿", "slot": 5, "side": "right"},
    ]


def test_beat_conceal_is_visual_only_and_cannot_share_a_hard_cut():
    response = complete_response()
    beat = {
        "anchor_id": "src-1-0-a", "position": "after", "who": "爱丽丝",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "relationship_turn", "shot_transition": "reframe",
        "visible_characters": ["爱丽丝"], "positions": {"爱丽丝": 3},
        "conceal": [{"who": "绿", "side": "fade"}],
    }
    response["beats"] = [beat]
    cast = {
        "爱丽丝": {"id": "aris", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }

    result = validate_chunk_response(response, TARGETS, cast=cast, constraints={})

    assert result["beats"][0]["conceal"] == [{"who": "绿", "side": "fade"}]

    response["beats"] = [{**beat, "shot_transition": "cut"}]
    with pytest.raises(ChunkProtocolError, match="立绘显隐"):
        validate_chunk_response(response, TARGETS, cast=cast, constraints={})


def test_pure_ai_beat_rejects_more_than_three_visible_characters():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "凯伊",
        "face": "31", "emo": "", "act": "", "wait_ms": 900,
        "reason": "listener_reaction",
        "visible_characters": ["凯伊", "爱丽丝", "桃井", "绿"],
    }]
    cast = {
        "凯伊": {"id": "kei", "portrait": True},
        "爱丽丝": {"id": "aris", "portrait": True},
        "桃井": {"id": "momoi", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }
    constraints = {
        "faces_by_id": {"kei": {"31"}}, "ok_emo": set(), "ok_act": set(),
    }

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS, cast=cast, constraints=constraints)

    assert error.value.code == "invalid_beat"


def test_pure_ai_beat_rejects_portrait_geometry_overlap():
    response = complete_response()
    response["beats"] = [{
        "anchor_id": "src-1-0-a", "position": "after", "who": "桃井",
        "face": "", "emo": "", "act": "", "wait_ms": 0,
        "reason": "physical_reaction",
        "visible_characters": ["桃井", "绿"],
        "positions": {"桃井": 2, "绿": 3},
    }]
    cast = {
        "桃井": {"id": "momoi", "portrait": True},
        "绿": {"id": "midori", "portrait": True},
    }
    constraints = {
        "faces_by_id": {}, "ok_emo": set(), "ok_act": set(),
        "portrait_profiles_by_name": {
            "桃井": {"min_slot_gap": 2}, "绿": {"min_slot_gap": 2},
        },
    }

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(response, TARGETS, cast=cast, constraints=constraints)

    assert error.value.code == "unsafe_beat_spacing"


def test_line_geometry_reports_every_overlap_for_one_repair_attempt():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "visible_characters": ["爱丽丝", "桃井"],
        "positions": {"爱丽丝": 3, "桃井": 4},
    }
    response["lines"][1]["direction"] = {
        "visible_characters": ["爱丽丝", "柚子"],
        "positions": {"爱丽丝": 3, "柚子": 2},
    }
    cast = {
        "爱丽丝": {"id": "aris", "portrait": True},
        "桃井": {"id": "momoi", "portrait": True},
        "柚子": {"id": "yuzu", "portrait": True},
    }
    constraints = {
        "portrait_profiles_by_name": {
            name: {"min_slot_gap": 2} for name in cast
        },
    }

    with pytest.raises(ChunkProtocolError) as error:
        validate_chunk_response(
            response, TARGETS, cast=cast, constraints=constraints,
        )

    assert error.value.code == "unsafe_direction_spacing"
    assert "TARGET i=1" in error.value.detail
    assert "TARGET i=2" in error.value.detail


def test_complete_and_compact_schemas_expose_strict_optional_direction_objects():
    complete_line = build_chunk_schema(["src-1-0-a"])["properties"]["lines"]["items"]
    compact_line = build_compact_chunk_schema(1)["properties"]["lines"]["items"]

    assert "direction" not in complete_line["required"]
    assert complete_line["properties"]["direction"]["additionalProperties"] is False
    assert "d" not in compact_line["required"]
    assert compact_line["properties"]["d"]["additionalProperties"] is False


def test_compact_schema_uses_one_based_index_and_optional_annotation_fields():
    schema = build_compact_chunk_schema(2)
    row = schema["properties"]["lines"]["items"]

    assert row["required"] == ["i"]
    assert row["properties"]["i"] == {"type": "integer", "minimum": 1, "maximum": 2}
    assert "source_id" not in row["properties"]
    assert "text_fingerprint" not in row["properties"]
    assert row["additionalProperties"] is False
    assert schema["properties"]["lines"]["maxItems"] == 2


def test_compact_schema_reveal_is_a_direction_enum_not_a_character_name():
    line = build_compact_chunk_schema(1)["properties"]["lines"]["items"]

    assert line["properties"]["reveal"]["enum"] == ["", "left", "right", "fade"]
    assert "不是角色名" in line["properties"]["reveal"]["description"]
    assert "不能与当前行的 shot_transition=cut 同时使用" in line["properties"]["reveal"]["description"]


def test_compact_schema_forbids_reveal_with_nested_or_flat_cut():
    line = build_compact_chunk_schema(1)["properties"]["lines"]["items"]

    assert line["allOf"] == [
        {
            "not": {
                "required": ["reveal", "d"],
                "properties": {
                    "reveal": {"enum": ["left", "right", "fade"]},
                    "d": {
                        "required": ["shot_transition"],
                        "properties": {"shot_transition": {"const": "cut"}},
                    },
                },
            },
        },
        {
            "not": {
                "required": ["reveal", "shot_transition"],
                "properties": {
                    "reveal": {"enum": ["left", "right", "fade"]},
                    "shot_transition": {"const": "cut"},
                },
            },
        },
    ]


def test_compact_repair_schema_uses_stable_source_ids():
    target_ids = ["src-1-0-a", "src-2-0-b"]
    schema = build_compact_chunk_schema(2, target_ids)
    line = schema["properties"]["lines"]["items"]
    beat = schema["properties"]["beats"]["items"]
    event = schema["properties"]["memory_events"]["items"]

    assert line["required"] == ["source_id"]
    assert line["properties"]["source_id"] == {"type": "string", "enum": target_ids}
    assert "i" not in line["properties"]
    assert beat["properties"]["anchor_id"] == {"type": "string", "enum": target_ids}
    assert event["properties"]["source_ids"]["items"] == {
        "type": "string", "enum": target_ids,
    }


def test_compact_response_expands_stable_source_id_rows():
    response = {
        "lines": [{"source_id": "src-2-0-b", "face": "05"}],
        "state_delta": {}, "memory_events": [],
    }

    expanded = expand_compact_chunk_response(response, TARGETS)

    assert expanded["lines"][0]["source_id"] == "src-1-0-a"
    assert expanded["lines"][0]["face"] == ""
    assert expanded["lines"][1]["source_id"] == "src-2-0-b"
    assert expanded["lines"][1]["face"] == "05"


def test_compact_protocol_recovers_line_emo_accidentally_nested_in_direction():
    response = {
        "lines": [{
            "i": 1,
            "d": {"emo": "惊叹", "continuity": {"emo": "start"}},
        }],
        "state_delta": {},
        "memory_events": [],
    }
    schema = build_compact_chunk_schema(2)

    llm.validate_json_schema(response, schema)
    expanded = expand_compact_chunk_response(response, TARGETS)

    assert expanded["lines"][0]["emo"] == "惊叹"
    assert expanded["lines"][0]["direction"]["continuity"]["emo"] == "start"
    assert expanded.director_intents["src-1-0-a"] == {
        "continuity": {"emo": "start"},
    }


def test_compact_fx_release_becomes_explicit_lifecycle_end():
    response = {
        "lines": [{"i": 1, "fx": "无"}],
        "state_delta": {}, "memory_events": [],
    }

    expanded = expand_compact_chunk_response(response, TARGETS)

    assert expanded["lines"][0]["fx"] == "无"
    assert expanded["lines"][0]["direction"]["continuity"]["fx"] == "end"
    assert expanded.director_intents["src-1-0-a"] == {
        "continuity": {"fx": "end"},
    }


def test_compact_protocol_rejects_conflicting_nested_annotation_alias():
    response = {
        "lines": [{"i": 1, "emo": "疑问", "d": {"emo": "惊叹"}}],
        "state_delta": {},
        "memory_events": [],
    }

    with pytest.raises(ChunkProtocolError, match="冲突"):
        expand_compact_chunk_response(response, TARGETS)


def test_compact_protocol_recovers_direction_fields_accidentally_flattened_on_line():
    response = {
        "lines": [{
            "i": 1,
            "visible_characters": ["凯伊", "老师"],
            "focus_kind": "listener",
            "d": {"reason": "listener_reaction"},
        }],
        "state_delta": {},
        "memory_events": [],
    }
    schema = build_compact_chunk_schema(2)

    llm.validate_json_schema(response, schema)
    expanded = expand_compact_chunk_response(response, TARGETS)

    assert expanded["lines"][0]["direction"]["visible_characters"] == ["凯伊", "老师"]
    assert expanded["lines"][0]["direction"]["focus_kind"] == "listener"
    assert expanded.director_intents["src-1-0-a"] == {
        "visible_characters": ["凯伊", "老师"],
        "focus_kind": "listener",
        "reason": "listener_reaction",
    }


def test_compact_top_level_camera_fields_remain_explicit_direction_intent():
    response = {
        "lines": [{
            "i": 1,
            "shot_operation": "switch_group",
            "shot_transition": "cut",
            "visible_characters": ["凯伊", "老师"],
            "positions": {"凯伊": 1, "老师": 5},
        }],
        "state_delta": {},
        "memory_events": [],
    }

    expanded = expand_compact_chunk_response(response, TARGETS)
    validated = validate_chunk_response(
        expanded, TARGETS,
        cast={
            "凯伊": {"id": "kei", "portrait": True},
            "老师": {"id": "sensei", "portrait": True},
        },
    )

    assert validated["lines_by_id"]["src-1-0-a"]["direction_intent"] == {
        "shot_operation": "switch_group",
        "shot_transition": "cut",
        "visible_characters": ["凯伊", "老师"],
        "positions": {"凯伊": 1, "老师": 5},
    }


def test_compact_top_level_and_nested_direction_shapes_are_equivalent():
    direction = {
        "scene_type": "event",
        "scene_function": "emotional_turn",
        "emotion_phase": "冲击后的承接",
        "subtext": "先看听者的反应",
        "relation_distance": "normal",
        "focus_kind": "listener",
        "focus_character": "老师",
        "reaction_target": "老师",
        "reason": "listener_reaction",
        "shot_operation": "switch_group",
        "shot_transition": "cut",
        "visible_characters": ["凯伊", "老师"],
        "positions": {"凯伊": 1, "老师": 5},
        "continuity": {"face": "hold", "emo": "none"},
    }
    cast = {
        "凯伊": {"id": "kei", "portrait": True},
        "老师": {"id": "sensei", "portrait": True},
    }

    top_level = expand_compact_chunk_response({
        "lines": [{"i": 1, **direction}],
        "state_delta": {},
        "memory_events": [],
    }, TARGETS)
    nested = expand_compact_chunk_response({
        "lines": [{"i": 1, "d": direction}],
        "state_delta": {},
        "memory_events": [],
    }, TARGETS)
    top_level_row = validate_chunk_response(
        top_level, TARGETS, cast=cast,
    )["lines_by_id"]["src-1-0-a"]
    nested_row = validate_chunk_response(
        nested, TARGETS, cast=cast,
    )["lines_by_id"]["src-1-0-a"]

    assert top_level_row["direction"] == nested_row["direction"]
    assert top_level_row["direction_intent"] == nested_row["direction_intent"] == direction


def test_compact_protocol_tracks_only_explicit_annotation_fields_for_local_repair():
    expanded = expand_compact_chunk_response({
        "lines": [{"i": 1, "face": "03", "move": 2}],
        "state_delta": {},
        "memory_events": [],
    }, TARGETS)
    validated = validate_chunk_response(expanded, TARGETS)

    assert validated["lines_by_id"]["src-1-0-a"]["annotation_intent_fields"] == [
        "face", "move",
    ]
    assert validated["lines_by_id"]["src-2-0-b"]["annotation_intent_fields"] == []


def test_compact_protocol_recovers_state_delta_accidentally_nested_in_line():
    response = {
        "lines": [{
            "i": 1,
            "state_delta": {"background": "BG_Riverside", "place": "河堤"},
        }],
        "state_delta": {"visible_characters": ["凯伊"]},
        "memory_events": [],
    }
    schema = build_compact_chunk_schema(2)

    llm.validate_json_schema(response, schema)
    expanded = expand_compact_chunk_response(response, TARGETS)

    assert expanded["state_delta"] == {
        "background": "BG_Riverside", "place": "河堤",
        "visible_characters": ["凯伊"],
    }


def test_compact_protocol_keeps_canonical_root_state_over_nested_snapshot():
    response = {
        "lines": [{"i": 1, "state_delta": {"background": "BG_A"}}],
        "state_delta": {"background": "BG_B"}, "memory_events": [],
    }

    expanded = expand_compact_chunk_response(response, TARGETS)

    assert expanded["state_delta"] == {"background": "BG_B"}


def test_compact_protocol_rejects_conflicting_flattened_direction_alias():
    response = {
        "lines": [{
            "i": 1,
            "focus_kind": "speaker",
            "d": {"focus_kind": "listener"},
        }],
        "state_delta": {},
        "memory_events": [],
    }

    with pytest.raises(ChunkProtocolError, match="冲突"):
        expand_compact_chunk_response(response, TARGETS)


def test_state_delta_schema_matches_memory_bounds():
    state = build_compact_chunk_schema(3)["properties"]["state_delta"]["properties"]

    assert state["visible_characters"]["maxItems"] == 3
    assert state["recent_actions"]["maxItems"] == 12
    assert state["open_threads"]["maxItems"] == 20
    assert state["positions"]["maxProperties"] == 3


def test_compact_response_restores_completely_omitted_noop_rows():
    expanded = expand_compact_chunk_response({
        "lines": [], "state_delta": {}, "memory_events": [],
    }, TARGETS)

    assert expanded["lines"] == [
        row("src-1-0-a", "fp-a") | {"direction": default_director()},
        row("src-2-0-b", "fp-b") | {"direction": default_director()},
    ]
    validated = validate_chunk_response(expanded, TARGETS)
    assert set(validated["lines_by_id"]) == {"src-1-0-a", "src-2-0-b"}


def test_compact_response_restores_identity_and_protocol_defaults():
    expanded = expand_compact_chunk_response({
        "lines": [{"i": 1, "face": "05"}, {"i": 2, "shake": True}],
        "state_delta": {}, "memory_events": [],
    }, TARGETS)

    assert expanded["lines"] == [
        row("src-1-0-a", "fp-a") | {"face": "05", "direction": default_director()},
        row("src-2-0-b", "fp-b") | {"shake": True, "direction": default_director()},
    ]
    validated = validate_chunk_response(expanded, TARGETS)
    assert list(validated["lines_by_id"]) == ["src-1-0-a", "src-2-0-b"]


def test_compact_direction_expands_and_omitted_direction_uses_defaults():
    expanded = expand_compact_chunk_response({
        "lines": [{
            "i": 1,
            "d": {"scene_type": "event", "continuity": {"face": "hold"}},
        }, {"i": 2}],
        "state_delta": {}, "memory_events": [],
    }, TARGETS)

    assert expanded["lines"][0]["direction"]["scene_type"] == "event"
    assert expanded["lines"][0]["direction"]["continuity"] == {
        "face": "hold", "emo": "none", "act": "none",
        "fx": "none", "bgfx": "none",
    }
    assert expanded["lines"][1]["direction"]["scene_type"] == "other"
    assert expanded["lines"][1]["direction"]["focus_kind"] == "speaker"

    validated = validate_chunk_response(expanded, TARGETS)
    assert validated["lines_by_id"]["src-1-0-a"]["direction_intent"] == {
        "scene_type": "event", "continuity": {"face": "hold"},
    }
    assert validated["lines_by_id"]["src-2-0-b"]["direction_intent"] == {}


def test_compact_response_expands_beat_anchor_index_to_source_id():
    expanded = expand_compact_chunk_response({
        "lines": [{"i": 1}, {"i": 2}],
        "state_delta": {}, "memory_events": [],
        "beats": [{
            "anchor_id": 2, "position": "after", "who": "Kai",
            "face": "", "emo": "", "act": "", "wait_ms": 250,
            "reason": "listener_reaction",
        }],
    }, TARGETS)

    assert expanded["beats"][0]["anchor_id"] == "src-2-0-b"


def test_compact_response_expands_event_source_indices_to_source_ids():
    expanded = expand_compact_chunk_response({
        "lines": [{"i": 1}, {"i": 2}], "state_delta": {},
        "memory_events": [{
            "kind": "callback", "participants": ["Kai"], "keywords": ["ticket"],
            "summary": "remember", "source_ids": [1, 2], "evidence": "line",
            "importance": 0.8, "status": "open",
        }],
    }, TARGETS)

    assert expanded["memory_events"][0]["source_ids"] == ["src-1-0-a", "src-2-0-b"]


@pytest.mark.parametrize("lines,code", [
    ([{"i": 1}, {"i": 1}], "duplicate_target"),
    ([{"i": 1}, {"i": 3}], "unknown_target"),
    ([{"i": True}, {"i": 2}], "invalid_line"),
])
def test_compact_response_rejects_unsafe_index_coverage(lines, code):
    with pytest.raises(ChunkProtocolError) as error:
        expand_compact_chunk_response({
            "lines": lines, "state_delta": {}, "memory_events": [],
        }, TARGETS)

    assert error.value.code == code
