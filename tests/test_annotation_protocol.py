import pytest

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
    }]


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


def test_compact_schema_uses_one_based_index_and_optional_annotation_fields():
    schema = build_compact_chunk_schema(2, ["src-1-0-a", "src-2-0-b"])
    row = schema["properties"]["lines"]["items"]

    assert row["required"] == ["i"]
    assert row["properties"]["i"] == {"type": "integer", "minimum": 1, "maximum": 2}
    assert "source_id" not in row["properties"]
    assert "text_fingerprint" not in row["properties"]
    assert row["additionalProperties"] is False


def test_compact_response_restores_identity_and_protocol_defaults():
    expanded = expand_compact_chunk_response({
        "lines": [{"i": 1, "face": "05"}, {"i": 2, "shake": True}],
        "state_delta": {}, "memory_events": [],
    }, TARGETS)

    assert expanded["lines"] == [
        row("src-1-0-a", "fp-a") | {"face": "05"},
        row("src-2-0-b", "fp-b") | {"shake": True},
    ]
    validated = validate_chunk_response(expanded, TARGETS)
    assert list(validated["lines_by_id"]) == ["src-1-0-a", "src-2-0-b"]


def test_compact_response_expands_beat_anchor_index_to_source_id():
    expanded = expand_compact_chunk_response({
        "lines": [{"i": 1}, {"i": 2}],
        "state_delta": {}, "memory_events": [],
        "beats": [{
            "anchor_id": 2, "position": "after", "who": "Kai",
            "face": "", "emo": "", "act": "", "wait_ms": 250,
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
    ([{"i": 1}], "missing_target"),
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
