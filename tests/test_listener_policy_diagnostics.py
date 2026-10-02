"""Unsupported model camera intent must be explained, never silently claimed applied."""

import pytest

from annotate import annotation_directives, build_postprocessor_proposals
from director_policy import normalize_direction_plan


def row(index, visible, *, speaker="A", portrait=True, explicit=()):
    item = {
        "kind": "line",
        "annotation_id": f"source-{index}",
        "line_no": index,
        "who": speaker,
        "text": "原文。",
        "_speaker_has_portrait": portrait,
        "_explicit_directives": explicit,
        "_director": {
            "focus_kind": "listener",
            "focus_character": "B",
            "visible_characters": visible,
            "reason": "listener_reaction",
            "continuity": {},
        },
        "_director_intent": {
            "visible_characters": visible,
            "focus_kind": "listener",
            "focus_character": "B",
        },
    }
    return item


def test_fresh_listener_only_camera_gets_located_rejection_and_review_proposal():
    item = row(7, ["B"])
    _, diagnostics = normalize_direction_plan([item])
    rejected = [d for d in diagnostics if d.get("reason") == "portrait_speaker_not_visible"]
    assert len(rejected) == 1
    assert rejected[0]["source_id"] == "source-7"
    assert rejected[0]["line_no"] == 7
    assert rejected[0]["level"] == "warning"
    assert "说话者" in rejected[0]["message"]
    assert "visible_characters" not in item["_director_intent"]
    assert annotation_directives(item) == ["@camera_hold auto"]
    proposals = build_postprocessor_proposals([item], rule="continuity_density")
    assert any(
        p["rule"] == "portrait_speaker_not_visible" and p["before"] == ["B"] and p["after"] is None
        for p in proposals
    )


@pytest.mark.parametrize(
    "visible,portrait,explicit",
    [
        (["A", "B"], True, ()),
        (["B"], False, ()),
        (["B"], True, ("camera",)),
        (["B"], True, ("camera_hold",)),
    ],
)
def test_supported_or_authored_camera_does_not_get_this_rejection(visible, portrait, explicit):
    item = row(1, visible, portrait=portrait, explicit=explicit)
    _, diagnostics = normalize_direction_plan([item])
    assert not any(d.get("reason") == "portrait_speaker_not_visible" for d in diagnostics)
    if not explicit:
        assert not item.get("_camera_reset")


def test_repeated_fresh_camera_is_distinct_from_inherited_stale_hold():
    first = row(1, ["B"], speaker="B")
    fresh = row(2, ["B"])
    _, diagnostics = normalize_direction_plan([first, fresh])
    assert any(
        d.get("reason") == "portrait_speaker_not_visible" and d["source_id"] == "source-2"
        for d in diagnostics
    )
    first = row(1, ["B"], speaker="B")
    inherited = row(3, ["B"])
    inherited["_director_intent"].pop("visible_characters")
    _, diagnostics = normalize_direction_plan([first, inherited])
    assert inherited["_camera_reset"] is True
    assert not any(d.get("reason") == "portrait_speaker_not_visible" for d in diagnostics)
