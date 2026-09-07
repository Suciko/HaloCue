"""Known canonical face IDs must survive the full synthetic compiler boundary."""

import pytest
from script2aap import build, parse_script


@pytest.mark.parametrize("face", ["S2_01", "alternate", "01"])
def test_frozen_canonical_face_id_is_consumed(tmp_path, face):
    cast = {"A": {"id": "a", "portrait": True}}
    idx = {
        "bg": {"BG_Black": 1},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
        "characters": [
            {
                "identifier": "a",
                "faces": [
                    {"id": "00", "label": "neutral"},
                    {"id": "01", "label": "smile"},
                    {"id": "S2_01", "label": "alternate"},
                ],
            }
        ],
    }
    script = tmp_path / "source.txt"
    script.write_text(f"A({face}): 合成对白。\n", encoding="utf-8")
    rows = [
        row
        for _, lines in build(
            parse_script(script, cast), {"camera": {"enabled": False}}, cast, idx, "synthetic"
        )
        for row in lines
    ]
    portrait = next(c for c in rows[0]["characters"]["$values"] if c["name"] == "a")
    assert portrait["faceId"] == ("01" if face == "01" else "S2_01")


@pytest.mark.parametrize(
    "face,label,expected",
    [
        ("S2_01", "", "S2_01"),
        ("s2_01", "alternate", None),
        ("ALTERNATE", "alternate", "S2_01"),
        ("alternate", "Alternate", "S2_01"),
        ("invented", "alternate", None),
    ],
)
def test_canonical_id_and_alias_namespaces_remain_character_scoped(face, label, expected):
    from script2aap import res_lookup, resolve_face

    idx = {
        "enums": {"emoticon": {}, "action": {}},
        "characters": [
            {"identifier": "a", "faces": [{"id": "S2_01", "label": label}]},
            {"identifier": "a-other-costume", "faces": [{"id": "Other_01", "label": "alternate"}]},
        ],
    }
    lookup = res_lookup(idx)[-1]
    assert resolve_face(face, "a", lookup, 1) == expected
    assert resolve_face("S2_01", "a-other-costume", lookup, 1) is None


def test_exact_id_has_priority_over_an_alias_with_the_same_spelling():
    from script2aap import res_lookup, resolve_face

    idx = {
        "enums": {"emoticon": {}, "action": {}},
        "characters": [
            {
                "identifier": "a",
                "faces": [
                    {"id": "S2_01", "label": "alternate"},
                    {"id": "03", "label": "S2_01"},
                ],
            }
        ],
    }
    assert resolve_face("S2_01", "a", res_lookup(idx)[-1], 1) == "S2_01"


@pytest.mark.parametrize(
    "evidence,accepted",
    [
        ("visual_confirmed", True),
        ("asset_semantic", True),
        ("context_inferred", False),
        ("unknown", False),
    ],
)
def test_annotation_guard_render_parse_and_build_agree_on_frozen_face_id(
    tmp_path, evidence, accepted
):
    from annotation_safety import filter_annotation_row
    from annotate import render
    import script2aap

    item = {"who": "A", "text": "合成对白。"}
    character = {
        "id": "a-costume",
        "portrait": True,
        "outfit_key": "costume",
        "spine_signature": "synthetic",
    }
    constraints = {
        "faces_by_id": {"a-costume": {"S2_01"}},
        "face_evidence_by_id": {"a-costume": {"S2_01": evidence}},
    }
    clean, dropped = filter_annotation_row({"face": "S2_01"}, item, character, constraints)
    assert (clean.get("face") == "S2_01") is accepted
    if not accepted:
        assert dropped
        return
    assert dropped == []
    script = tmp_path / "accepted.txt"
    script.write_text(render({**item, **clean}) + "\n", encoding="utf-8")
    idx = {
        "bg": {"BG_Black": 1},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
        "characters": [{"identifier": "a-costume", "faces": [{"id": "S2_01"}]}],
    }
    start = len(script2aap.warn.items)
    rows = [
        row
        for _, lines in build(
            parse_script(script, {"A": character}), {}, {"A": character}, idx, "synthetic"
        )
        for row in lines
    ]
    assert (
        next(c for c in rows[0]["characters"]["$values"] if c["name"] == "a-costume")["faceId"]
        == "S2_01"
    )
    assert not any("表情" in message for _, message in script2aap.warn.items[start:])


def test_unknown_nonnumeric_face_still_has_source_line_warning():
    import script2aap

    start = len(script2aap.warn.items)
    assert script2aap.resolve_face("Unregistered_09", "a", {}, 17) is None
    assert script2aap.warn.items[start:][0][0] == 17
    assert "Unregistered_09" in script2aap.warn.items[start:][0][1]
