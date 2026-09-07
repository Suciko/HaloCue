"""Synthetic, in-memory coverage for reaction-only compilation integrity."""

from copy import deepcopy

import pytest

import document
import script2aap
from reaction_integrity import ReactionIntentError, validate_reaction_output


@pytest.fixture
def inputs():
    cast = {name: {"id": f"synthetic-{name}", "portrait": True} for name in "ABCDEF"}
    cast.update({"Narrator": {"narrator": True}, "Teacher": {"id": "voice", "portrait": False}})
    idx = {
        "characters": [
            {
                "identifier": f"synthetic-{name}",
                "faces": [
                    {"id": "00", "label": "neutral"},
                    {"id": "01", "label": "happy"},
                    {"id": "face_custom", "label": "custom"},
                ],
            }
            for name in "ABCDEF"
        ],
        "enums": {
            "emoticon": {"1": {"sym": "[!]", "cn": "惊讶"}, "2": {"sym": "[?]", "cn": "疑问"}},
            "action": {"1": {"verb": "wave", "cn": "挥手"}, "2": {"verb": "jump", "cn": "跳跃"}},
        },
        "bg": {},
        "sounds": [],
    }
    return cast, idx, {}


def record(output_line=5, **changes):
    return {
        "beat_id": "accepted-beat-B",
        "anchor_id": "source-A",
        "source_line": 17,
        "position": "after",
        "who": "B",
        "face": "01",
        "emo": "!",
        "act": "wave",
        "wait_ms": 1200,
        "output_line": output_line,
        **changes,
    }


GOOD = "@camera_hold A\nA: Before.\n@camera B\n@wait 1200\nB(01)[!]{wave}:\nA: After.\n"


def validate(text, records, inputs):
    cast, idx, cfg = inputs
    return validate_reaction_output(text, records, cast, idx, cfg)


def rows(text, inputs):
    cast, idx, cfg = inputs
    events, _ = document.compile_document(document.parse_document_lossless(text), cast, idx)
    return [
        row for _, scene in script2aap.build(events, cfg, cast, idx, "synthetic") for row in scene
    ]


def assert_lost(text, records, inputs, message=None):
    with pytest.raises(ReactionIntentError) as caught:
        validate(text, records, inputs)
    error = caught.value
    assert isinstance(error, ValueError)
    assert error.code == "reaction_intent_lost"
    diagnostics = error.details["diagnostics"]
    assert diagnostics
    for diagnostic in diagnostics:
        rec = next(rec for rec in records if rec["beat_id"] == diagnostic["beat_id"])
        assert diagnostic == {
            "severity": "error",
            "code": "reaction.intent_lost",
            "line_no": rec["source_line"],
            "source_id": rec["anchor_id"],
            "beat_id": rec["beat_id"],
            "output_line": rec["output_line"],
            "message": diagnostic["message"],
        }
        assert diagnostic["message"]
    if message:
        assert any(message in item["message"] for item in diagnostics)
    return error


def test_held_a_loses_b_but_one_line_camera_preserves_beat_and_restores_a(inputs):
    old = GOOD.replace("@camera B\n", "")
    assert_lost(old, [record(4)], inputs, "visible")
    assert validate(GOOD, [record()], inputs) == [{**record(), "compiled_index": 1}]
    compiled = rows(GOOD, inputs)
    assert [c["name"] for c in compiled[1]["characters"]["$values"][1:] if c["name"]] == [
        "synthetic-B"
    ]
    assert [c["name"] for c in compiled[2]["characters"]["$values"][1:] if c["name"]] == [
        "synthetic-A"
    ]
    assert compiled[1]["additionalPrompt"].splitlines().count("#wait;1200") == 1
    assert not any("beat_id" in row or "compiled_index" in row for row in compiled)


def test_copies_records_and_leaves_all_inputs_unchanged(inputs):
    records = [record(audit={"reason": ["accepted"]})]
    before = deepcopy((records, inputs))
    result = validate(GOOD, records, inputs)
    assert (records, inputs) == before
    assert result is not records and result[0] is not records[0]
    assert result[0]["audit"] == records[0]["audit"]


@pytest.mark.parametrize(
    "old,new,message",
    [
        ("B(01)", "B(00)", "face"),
        ("[!]", "[?]", "emo"),
        ("{wave}", "{jump}", "act"),
        ("1200", "120", "wait"),
        ("@wait 1200", "@raw #wait;12000", "wait"),
        ("B(01)[!]{wave}:", "B(01)[!]{wave}: Stolen dialogue", "empty"),
        ("B(01)[!]{wave}:", "C(01)[!]{wave}:", "target"),
        ("@camera B", "@camera -", "visible"),
    ],
)
def test_wrong_rendered_intent_is_blocking(inputs, old, new, message):
    assert_lost(GOOD.replace(old, new), [record()], inputs, message)


def test_duplicate_requested_wait_is_not_satisfied_by_presence(inputs):
    text = GOOD.replace("@wait 1200", "@wait 1200\n@raw #wait;1200")
    assert_lost(text, [record(6)], inputs, "wait")


@pytest.mark.parametrize("wait", ["", "@wait 777\n"])
def test_zero_wait_does_not_impose_an_extra_wait_expectation(inputs, wait):
    text = f"@camera B\n{wait}B(01)[!]{{wave}}:\n"
    assert validate(text, [record(2 + bool(wait), wait_ms=0)], inputs)[0]["compiled_index"] == 0


@pytest.mark.parametrize("output_line", [0, -1, 99, 3, 2, True, "5", None])
def test_invalid_or_stale_output_line_is_rejected(inputs, output_line):
    assert_lost(GOOD, [record(output_line)], inputs)


@pytest.mark.parametrize("who", ["Unknown", "Narrator", "Teacher"])
def test_reaction_requires_known_portrait_target(inputs, who):
    text = f"{who}:\n"
    assert_lost(text, [record(1, who=who, face="", emo="", act="", wait_ms=0)], inputs, "target")


def test_unknown_parsed_target_is_not_silently_skipped(inputs):
    assert_lost(GOOD.replace("B(01)[!]{wave}:", "Unknown:"), [record()], inputs, "target")


@pytest.mark.parametrize(
    "field,token",
    [
        ("face", "99"),
        ("face", "missing"),
        ("emo", "missing"),
        ("act", "missing"),
        ("emo", "19"),
        ("act", "7"),
    ],
)
def test_unknown_resources_cannot_pass_via_compiler_fallback_or_numeric_regex(inputs, field, token):
    # Both the request and rendered value agree; absent index evidence still fails.
    text = f"@camera B\nB({token if field == 'face' else '01'})[{token if field == 'emo' else '!'}]{{{token if field == 'act' else 'wave'}}}:\n"
    assert_lost(text, [record(2, **{field: token, "wait_ms": 0})], inputs, field)


@pytest.mark.parametrize(
    "face,emo,act", [("1", "1", "1"), ("happy", "惊讶", "挥手"), ("face_custom", "!", "wave")]
)
def test_evidenced_numeric_ids_aliases_and_custom_face_ids_resolve(inputs, face, emo, act):
    text = f"@camera B\nB({face})[{emo}]{{{act}}}:\n"
    assert (
        validate(text, [record(2, face=face, emo=emo, act=act, wait_ms=0)], inputs)[0][
            "compiled_index"
        ]
        == 0
    )


def test_empty_requests_do_not_require_face_emo_or_action(inputs):
    assert (
        validate("B:\n", [record(1, face="", emo="", act="", wait_ms=0)], inputs)[0][
            "compiled_index"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "marker", ["# stale beat accepted-beat-B\n", "Unknown:\n", "unparsed marker\n"]
)
def test_marker_is_not_a_valid_empty_reaction_line(inputs, marker):
    assert_lost(marker, [record(1)], inputs)


def test_no_records_does_not_parse_or_compile_even_invalid_normal_text(inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("no reaction records must not invoke compiler")

    monkeypatch.setattr(document, "parse_document_lossless", forbidden)
    monkeypatch.setattr(document, "compile_document", forbidden)
    monkeypatch.setattr(script2aap, "build", forbidden)
    assert validate("unknown text", [], inputs) == []


def test_normal_offscreen_narrator_teacher_lines_are_not_reaction_targets(inputs):
    text = GOOD + "@camera B\nA: offscreen\nNarrator: wind\nTeacher: hello\n"
    assert validate(text, [record()], inputs)[0]["compiled_index"] == 1


@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5])
def test_all_five_visible_slots_are_valid(inputs, slot):
    names = list("ABCDE")
    names.remove("B")
    names.insert(slot - 1, "B")
    stage = " ".join(f"{name}@{i}" for i, name in enumerate(names, 1))
    text = f"@stage {stage}\n@camera {' '.join(names)}\n@wait 1200\nB(01)[!]{{wave}}:\n"
    assert rows(text, inputs)[0]["characters"]["$values"][slot]["name"] == "synthetic-B"
    assert validate(text, [record(4)], inputs)[0]["compiled_index"] == 0


def test_slot_zero_is_not_a_visible_reaction_portrait(inputs, monkeypatch):
    original = script2aap.build

    def hidden(*args):
        scenes = original(*args)
        chars = scenes[0][1][1]["characters"]["$values"]
        slot = next(i for i, char in enumerate(chars) if char["name"] == "synthetic-B")
        chars[0], chars[slot] = chars[slot], chars[0]
        return scenes

    monkeypatch.setattr(script2aap, "build", hidden)
    assert_lost(GOOD, [record()], inputs, "visible")


def test_multiple_scenes_prefix_only_scene_and_unsorted_records_map_exactly(inputs):
    text = "\ufeff# title\r\n## unused\r\n@camera A\r\n## first\r\nB:\r\n---\r\nC:\r\n"
    records = [
        record(7, beat_id="beat-C", who="C", face="", emo="", act="", wait_ms=0),
        record(5, face="", emo="", act="", wait_ms=0),
    ]
    assert [r["compiled_index"] for r in validate(text, records, inputs)] == [1, 0]


def test_two_beats_cannot_claim_the_same_rendered_line(inputs):
    assert_lost(GOOD, [record(), record(beat_id="second-beat")], inputs, "mapping")


@pytest.mark.parametrize("mutation", ["missing", "extra", "swap", "bad_shape"])
def test_bad_compiled_row_mapping_never_silently_zips(inputs, monkeypatch, mutation):
    original = script2aap.build

    def broken(*args):
        scenes = original(*args)
        scripts = scenes[0][1]
        if mutation == "missing":
            scripts.pop(0)
        elif mutation == "extra":
            scripts.append(deepcopy(scripts[0]))
        elif mutation == "swap":
            scripts[0], scripts[1] = scripts[1], scripts[0]
        else:
            scripts[1] = {}
        return scenes

    monkeypatch.setattr(script2aap, "build", broken)
    assert_lost(GOOD, [record()], inputs, "mapping")


def test_equal_total_but_wrong_per_scene_row_counts_fail(inputs, monkeypatch):
    original = script2aap.build

    def broken(*args):
        scenes = original(*args)
        scenes[1][1].insert(0, scenes[0][1].pop())
        return scenes

    monkeypatch.setattr(script2aap, "build", broken)
    text = "## first\nB:\n## second\nB:\n"
    assert_lost(text, [record(2, face="", emo="", act="", wait_ms=0)], inputs, "mapping")


@pytest.mark.parametrize("mutation", ["duplicate_no", "unknown_no", "missing_target"])
def test_invalid_event_line_mapping_is_blocking(inputs, monkeypatch, mutation):
    original = document.compile_document

    def broken(*args):
        events, diagnostics = original(*args)
        lines = [e for e in events if e["k"] == "line"]
        if mutation == "duplicate_no":
            lines[1]["no"] = lines[0]["no"]
        elif mutation == "unknown_no":
            lines[1]["no"] = 999
        else:
            events.remove(lines[1])
        return events, diagnostics

    monkeypatch.setattr(document, "compile_document", broken)
    assert_lost(GOOD, [record()], inputs, "mapping")


@pytest.mark.parametrize("phase", ["parse", "compile", "build"])
def test_compiler_exceptions_become_source_located_reaction_error(inputs, monkeypatch, phase):
    def broken(*args):
        raise ValueError("synthetic compiler failure")

    if phase == "build":
        monkeypatch.setattr(script2aap, "build", broken)
    else:
        monkeypatch.setattr(
            document, "parse_document_lossless" if phase == "parse" else "compile_document", broken
        )
    error = assert_lost(GOOD, [record()], inputs, "synthetic compiler failure")
    assert isinstance(error.__cause__, ValueError)


@pytest.mark.parametrize("legacy_cast", [None, {}, {"Unbound": {}}, {"Legacy": {"portrait": True}}])
def test_empty_sidecar_bypasses_unsupported_legacy_inputs(legacy_cast, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("legacy no-record path must remain uncompiled")

    monkeypatch.setattr(document, "parse_document_lossless", forbidden)
    monkeypatch.setattr(document, "compile_document", forbidden)
    monkeypatch.setattr(script2aap, "build", forbidden)
    assert validate_reaction_output("Legacy: ordinary dialogue", [], legacy_cast, None, None) == []
