from director_state import (
    BEAT_REASONS,
    SCENE_FUNCTIONS,
    apply_continuity,
    default_director,
    normalize_director,
)


def test_canonical_vocabularies_are_immutable_and_exact():
    assert SCENE_FUNCTIONS == (
        "establishing",
        "entrance",
        "exposition",
        "dialogue",
        "comedy_escalation",
        "conflict",
        "emotional_turn",
        "action",
        "closing",
    )
    assert BEAT_REASONS == (
        "await_response",
        "relationship_turn",
        "listener_reaction",
        "comedy_hold",
        "decision_pause",
        "physical_reaction",
    )


def test_default_director_has_canonical_empty_state():
    state = default_director("bond")

    assert state["scene_type"] == "bond"
    assert state["focus_kind"] == "speaker"
    assert state["visible_characters"] == []
    assert state["continuity"] == {
        "face": "none",
        "emo": "none",
        "act": "none",
        "fx": "none",
        "bgfx": "none",
    }


def test_normalize_rejects_unknown_people_and_records_diagnostic():
    state, diagnostics = normalize_director(
        {
            "scene_type": "event",
            "focus_kind": "listener",
            "focus_character": "B",
            "visible_characters": ["A", "B", "C"],
        },
        cast_names={"A", "B"},
        displayable_names={"A", "B"},
    )

    assert state["visible_characters"] == ["A", "B"]
    assert any(diagnostic["code"] == "director_unknown_character" for diagnostic in diagnostics)


def test_normalize_reports_a_non_mapping_root_value():
    state, diagnostics = normalize_director(
        ["not", "a", "director"],
        cast_names=set(),
        displayable_names=set(),
    )

    assert state == default_director()
    assert diagnostics == [{
        "code": "director_invalid_value",
        "level": "warning",
        "field": "value",
        "message": "Director metadata must be an object",
    }]


def test_normalize_downgrades_a_non_displayable_focus_character():
    state, diagnostics = normalize_director(
        {"focus_kind": "listener", "focus_character": "Voice"},
        cast_names={"A", "Voice"}, displayable_names={"A"},
    )

    assert state["focus_character"] == ""
    assert any(
        item["code"] == "director_non_displayable_character"
        and item["field"] == "focus_character"
        for item in diagnostics
    )


def test_apply_continuity_holds_and_ends_named_layers():
    state = apply_continuity(
        {"fx": "通讯", "face": "03"},
        {"fx": "", "face": "04"},
        {"fx": "hold", "face": "end"},
    )

    assert state == {"fx": "通讯", "face": ""}
