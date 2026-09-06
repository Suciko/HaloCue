"""Synthetic acceptance at the public AA compiler and validator boundaries."""

import copy
import json
from pathlib import Path

import pytest

from document import normalize_draft_nodes, parse_document_lossless
from draft_identity import assign_identity
from script2aap import compile_script
from teacher_reply_plan import make_reply_plan
from teacher_identity import TeacherIdentityError
from aa_teacher_selection import apply_teacher_selections
import verify


TEACHER_ID = "hc-teacher-0123456789abcdef0123456789abcdef"
SELECTION_TYPE = "SelectionNodeData, Assembly-CSharp"


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _inputs(tmp_path, text, *, mode="sel_single"):
    teacher = {
        "kind": "voice",
        "role": "teacher",
        "id": TEACHER_ID,
        "name": "Teacher",
        "club": "Test",
        "portrait": False,
        "narrator": False,
        "teacher_identity_schema": "teacher-identity/1.0",
        "teacher_preset_id": "custom",
    }
    cast = {
        "default_bg": "BG_Black",
        "camera": {"enabled": False},
        "cast": {"Teacher": teacher, "Clerk": {"id": "clerk", "portrait": False}},
        "alias": {"Sensei": "Teacher"},
        "teacher_presentation": {"schema_version": "teacher-presentation/1.0", "mode": mode},
    }
    resources = {
        "bg": {"BG_Black": 0},
        "sounds": [],
        "characters": [
            {
                "identifier": TEACHER_ID,
                "name": "Teacher",
                "club": "Test",
                "role": "teacher",
                "source": "halocue_teacher",
                "portrait": False,
                "spine": "",
                "faces": [],
            }
        ],
        "enums": {"emoticon": {}, "action": {}, "appear": {}, "shape": {}},
    }
    for name in "ABCDE":
        cast["cast"][name] = {"id": name.lower(), "portrait": True}
        resources["characters"].append(
            {
                "identifier": name.lower(),
                "name": name,
                "spine": "synthetic",
                "faces": [],
            }
        )
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "source.txt"
    script.write_text(text, encoding="utf-8")
    _write_json(tmp_path / "cast.json", cast)
    _write_json(tmp_path / "resources.json", resources)
    aa_data = tmp_path / "synthetic-aa"
    for folder in ("projects", "saves", "overrides", "settings"):
        (aa_data / folder).mkdir(parents=True, exist_ok=True)
    identities = [
        row.to_dict()
        for row in assign_identity(normalize_draft_nodes(parse_document_lossless(text)))
    ]
    options = {
        "script": str(script),
        "out": "SingleReply",
        "cast": str(tmp_path / "cast.json"),
        "index": str(tmp_path / "resources.json"),
        "output_root": str(tmp_path / "output"),
        "aa_data": str(aa_data),
        "install": False,
    }
    if mode == "sel_single":
        options["teacher_reply_plan"] = make_reply_plan(text, identities, cast)
    return options, cast, identities


def _compile(options):
    result = compile_script(options)
    return result, json.loads(Path(result["aap_file"]).read_text(encoding="utf-8"))


def _nodes(project):
    return project["nodes"]["$values"]


def _scripts(project):
    return [row for node in _nodes(project) for row in node.get("Scripts", {}).get("$values", [])]


def test_compiler_emits_one_reply_without_repeating_dialogue_or_voice(tmp_path):
    options, _, _ = _inputs(tmp_path, "Teacher: Synthetic answer.\nClerk: Continue.\n")
    before = copy.deepcopy(options)
    result, project = _compile(options)
    replies = [node for node in _nodes(project) if node["$type"] == SELECTION_TYPE]
    assert len(replies) == 1
    reply = replies[0]
    assert reply["selectionTexts"]["$values"] == ["Synthetic answer."] + [""] * 15
    assert reply["Guid"] == options["teacher_reply_plan"]["lines"][0]["reply_id"]
    assert len(reply["ConnectionsTo"]["$values"]) == 1
    rows = _scripts(project)
    assert [row["text"] for row in rows] == ["", "Continue."]
    assert rows[0]["isDialogScript"] is False
    assert rows[0]["voice"] == ""
    assert rows[0]["characters"]["$values"][0]["name"] == TEACHER_ID
    assert rows[1]["isDialogScript"] is True
    listing = (Path(result["project_dir"]) / "voices" / "voices.txt").read_text(encoding="utf-8")
    assert "Synthetic answer." not in listing
    assert "Continue." in listing
    assert options == before

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "aa_single_selection_node.json").read_text()
    )
    fixture.update(
        Guid=reply["Guid"], ConnectionsTo=reply["ConnectionsTo"], X=reply["X"], Y=reply["Y"]
    )
    assert reply == fixture


def test_validator_accepts_single_answer_graph_and_rejects_dangling_selection(tmp_path):
    options, _, _ = _inputs(tmp_path, "Teacher: One answer.\n")
    _, project = _compile(options)
    verify.errs.clear()
    verify.warns.clear()
    verify.check(project)
    assert verify.errs == []
    reply = next(node for node in _nodes(project) if node["$type"] == SELECTION_TYPE)
    reply["ConnectionsTo"]["$values"] = ["missing-target"]
    verify.check(project)
    assert any("selection_target_missing" in message for message in verify.errs)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Teacher: First.\nClerk: Next.\n", ["First.", "Next."]),
        ("Clerk: First.\nTeacher: Last.\n", ["First.", "Last."]),
        ("Teacher: Same.\nSensei: Same.\nTeacher: End.\n", ["Same.", "Same.", "End."]),
        ("## Before\nTeacher: Across.\n## After\nTeacher: End.\n", ["Across.", "End."]),
        ("Teacher: Across.\n## After\nClerk: End.\n", ["Across.", "End."]),
    ],
)
def test_graph_traversal_preserves_first_last_consecutive_and_scene_answers(
    tmp_path, text, expected
):
    options, _, _ = _inputs(tmp_path, text)
    _, project = _compile(options)
    nodes = {node["Guid"]: node for node in _nodes(project)}
    current = nodes["00000000-0000-0000-0000-000000000000"]
    seen, spoken = set(), []
    while True:
        assert current["Guid"] not in seen
        seen.add(current["Guid"])
        if current["$type"] == SELECTION_TYPE:
            spoken.append(current["selectionTexts"]["$values"][0])
        elif "Scripts" in current:
            assert current["Scripts"]["$values"]
            spoken.extend(
                row["text"] for row in current["Scripts"]["$values"] if row["isDialogScript"]
            )
        targets = current["ConnectionsTo"]["$values"]
        if not targets:
            assert current["$type"] == "ExitNodeData, Assembly-CSharp"
            break
        assert len(targets) == 1
        current = nodes[targets[0]]
    assert spoken == expected
    assert seen == set(nodes)
    teacher_rows = [row for row in options["teacher_reply_plan"]["lines"] if row["teacher"]]
    replies = [node for node in _nodes(project) if node["$type"] == SELECTION_TYPE]
    assert [node["Guid"] for node in replies] == [row["reply_id"] for row in teacher_rows]
    assert all(node["ConnectionsTo"]["$values"] for node in replies)
    assert len({node["Guid"] for node in replies}) == len(replies)
    _, repeated = _compile(options)
    assert repeated == project


def test_five_portraits_stage_and_commands_are_preserved_once(tmp_path):
    text = (
        "@stage A@1 B@2 C@3 D@4 E@5\n@raw #bgshake\nTeacher: All five remain.\nClerk: Continue.\n"
    )
    options, cast, identities = _inputs(tmp_path, text, mode="slot_zero")
    _, ordinary = _compile(options)
    cast["teacher_presentation"]["mode"] = "sel_single"
    _write_json(Path(options["cast"]), cast)
    options["teacher_reply_plan"] = make_reply_plan(text, identities, cast)
    _, selected = _compile(options)
    original_rows, selected_rows = _scripts(ordinary), _scripts(selected)
    assert len(original_rows) == len(selected_rows) == 2
    assert selected_rows[0] == {
        **original_rows[0],
        "text": "",
        "voice": "",
        "isDialogScript": False,
    }
    assert selected_rows[1] == original_rows[1]
    assert {row["name"] for row in selected_rows[0]["characters"]["$values"][1:]} == set("abcde")
    assert sum(row["additionalPrompt"].count("#bgshake") for row in selected_rows) == 1
    assert all(row["selectionGroup"] == 0 for row in selected_rows)
    before, plan_before = copy.deepcopy(ordinary), copy.deepcopy(options["teacher_reply_plan"])
    projected = apply_teacher_selections(ordinary, options["teacher_reply_plan"])
    assert projected == selected
    assert ordinary == before
    assert options["teacher_reply_plan"] == plan_before


def test_slot_zero_default_is_byte_compatible_and_ignores_unused_reply_plan(tmp_path):
    options, cast, _ = _inputs(tmp_path, "Teacher: Original.\n", mode="slot_zero")
    result, explicit = _compile(options)
    explicit_bytes = Path(result["aap_file"]).read_bytes()
    del cast["teacher_presentation"]
    _write_json(Path(options["cast"]), cast)
    options["teacher_reply_plan"] = {"schema_version": "future"}
    result, default = _compile(options)
    assert default == explicit
    assert Path(result["aap_file"]).read_bytes() == explicit_bytes
    assert _scripts(default)[0]["text"] == "Original."


@pytest.mark.parametrize(
    "plan_change,code",
    [
        ("missing", "teacher_reply_plan_invalid"),
        ("version", "teacher_reply_plan_invalid"),
        ("card_id", "teacher_reply_source_mismatch"),
        ("teacher", "teacher_reply_source_mismatch"),
        ("character_id", "teacher_reply_source_mismatch"),
        ("text_sha256", "teacher_reply_source_mismatch"),
    ],
)
def test_invalid_frozen_plan_never_writes_an_output(tmp_path, plan_change, code):
    options, _, _ = _inputs(tmp_path, "Teacher: Answer.\n")
    if plan_change == "missing":
        del options["teacher_reply_plan"]
    elif plan_change == "version":
        options["teacher_reply_plan"]["schema_version"] = "teacher-reply-plan/9.0"
    else:
        options["teacher_reply_plan"]["lines"][0][plan_change] = "invalid"
    with pytest.raises(TeacherIdentityError) as caught:
        compile_script(options)
    assert caught.value.code == code
    assert not Path(options["output_root"]).exists()


@pytest.mark.parametrize(
    "answer,code",
    [
        ("", "teacher_reply_empty"),
        ("   ", "teacher_reply_empty"),
        ("[s9] Another branch", "teacher_reply_unsafe_text"),
        ("#wait;9000", "teacher_reply_unsafe_text"),
        (r"Answer\n#wait;9000", "teacher_reply_unsafe_text"),
    ],
)
def test_empty_or_control_like_answer_is_rejected_without_rewriting_source(tmp_path, answer, code):
    text = f"Teacher: {answer}\n"
    with pytest.raises(TeacherIdentityError) as caught:
        _inputs(tmp_path, text)
    assert caught.value.code == code
    assert (tmp_path / "source.txt").read_text(encoding="utf-8") == text
    assert not (tmp_path / "output").exists()


def test_teacher_answer_never_consumes_supplied_audio_or_shifts_other_voice_ids(tmp_path):
    text = "Teacher: Silent choice.\nClerk: Spoken answer.\n"
    options, cast, identities = _inputs(tmp_path, text, mode="slot_zero")
    _, ordinary = _compile(options)
    teacher_voice, clerk_voice = [row["voice"] for row in _scripts(ordinary)]
    voice_dir = tmp_path / "incoming-voices"
    voice_dir.mkdir()
    (voice_dir / f"{teacher_voice}.ogg").write_bytes(b"synthetic teacher audio")
    (voice_dir / f"{clerk_voice}.ogg").write_bytes(b"synthetic clerk audio")
    cast["teacher_presentation"]["mode"] = "sel_single"
    _write_json(Path(options["cast"]), cast)
    options["teacher_reply_plan"] = make_reply_plan(text, identities, cast)
    options["voices"] = str(voice_dir)
    result, selected = _compile(options)
    target = Path(result["project_dir"])
    assert not (target / "voices" / f"{teacher_voice}.ogg").exists()
    assert (target / "voices" / f"{clerk_voice}.ogg").read_bytes() == b"synthetic clerk audio"
    assert _scripts(selected)[1]["voice"] == clerk_voice
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["VoiceOverrides"] == [f"voices/{clerk_voice}.ogg"]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"selectionTexts": {"$type": "wrong", "$values": ["Answer"]}}, "selection_text_invalid"),
        (
            {
                "selectionTexts": {
                    "$type": "System.Collections.Generic.List`1[[System.String, mscorlib]], mscorlib",
                    "$values": [],
                }
            },
            "selection_text_invalid",
        ),
        (
            {
                "selectionTexts": {
                    "$type": "System.Collections.Generic.List`1[[System.String, mscorlib]], mscorlib",
                    "$values": ["Answer", "Second answer"],
                }
            },
            "selection_text_invalid",
        ),
        ({"ConnectionsTo": None}, "selection_edge_invalid"),
        (
            {
                "ConnectionsTo": {
                    "$type": "System.Collections.Generic.List`1[[System.Guid, mscorlib]], mscorlib",
                    "$values": [],
                }
            },
            "selection_edge_invalid",
        ),
        ({"selectionGroup": 12}, "selection_node_shape_invalid"),
    ],
)
def test_validator_rejects_unsupported_single_answer_shapes(tmp_path, change, code):
    options, _, _ = _inputs(tmp_path, "Teacher: Valid answer.\n")
    _, project = _compile(options)
    reply = next(node for node in _nodes(project) if node["$type"] == SELECTION_TYPE)
    reply.update(change)
    verify.errs.clear()
    verify.warns.clear()
    verify.check(project)
    assert code in verify.errs


def test_validator_rejects_selection_that_loops_back_to_its_preparation(tmp_path):
    options, _, _ = _inputs(tmp_path, "Teacher: Valid answer.\n")
    _, project = _compile(options)
    nodes = _nodes(project)
    reply = next(node for node in nodes if node["$type"] == SELECTION_TYPE)
    reply["ConnectionsTo"]["$values"] = [nodes[1]["Guid"]]
    verify.errs.clear()
    verify.warns.clear()
    verify.check(project)
    assert "selection_graph_cycle" in verify.errs
