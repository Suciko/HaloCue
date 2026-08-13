import pytest

import llm
from director_state import default_director

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


def test_reaction_target_and_visible_cast_are_bounded_by_the_real_cast_and_aa_slots():
    response = complete_response()
    response["lines"][0]["direction"] = {
        "reaction_target": "Unknown",
        "visible_characters": ["A", "B", "C", "D", "E", "F"],
    }
    cast = {name: {"id": name.lower(), "portrait": True} for name in "ABCDEF"}

    result = validate_chunk_response(response, TARGETS, cast=cast)
    direction = result["lines_by_id"]["src-1-0-a"]["direction"]

    assert direction["reaction_target"] == ""
    assert direction["visible_characters"] == ["A", "B", "C", "D", "E"]
    assert {row["code"] for row in result["diagnostics"]} >= {
        "director_unknown_character", "director_visible_characters_limited",
    }


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
    }]


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
    assert beat["properties"]["reason"]["enum"] == [
        "await_response", "relationship_turn", "listener_reaction",
        "comedy_hold", "decision_pause", "physical_reaction",
    ]
    assert "reason" in beat["required"]


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
    }


def test_complete_and_compact_schemas_expose_strict_optional_direction_objects():
    complete_line = build_chunk_schema(["src-1-0-a"])["properties"]["lines"]["items"]
    compact_line = build_compact_chunk_schema(1)["properties"]["lines"]["items"]

    assert "direction" not in complete_line["required"]
    assert complete_line["properties"]["direction"]["additionalProperties"] is False
    assert "d" not in compact_line["required"]
    assert compact_line["properties"]["d"]["additionalProperties"] is False


def test_compact_schema_uses_one_based_index_and_optional_annotation_fields():
    schema = build_compact_chunk_schema(2, ["src-1-0-a", "src-2-0-b"])
    row = schema["properties"]["lines"]["items"]

    assert row["required"] == ["i"]
    assert row["properties"]["i"] == {"type": "integer", "minimum": 1, "maximum": 2}
    assert "source_id" not in row["properties"]
    assert "text_fingerprint" not in row["properties"]
    assert row["additionalProperties"] is False
    assert schema["properties"]["lines"]["maxItems"] == 2


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

    assert state["visible_characters"]["maxItems"] == 5
    assert state["recent_actions"]["maxItems"] == 12
    assert state["open_threads"]["maxItems"] == 20
    assert state["positions"]["maxProperties"] == 5


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
