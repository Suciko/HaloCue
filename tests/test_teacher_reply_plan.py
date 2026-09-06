import json

import pytest

from draft_store import DraftStore
from teacher_identity import TeacherIdentityError


def test_reply_plan_preserves_stable_cards_and_exact_text_across_duplicate_lines(tmp_path):
    from teacher_reply_plan import make_reply_plan

    store = DraftStore(str(tmp_path / "drafts"))
    draft = store.create_draft("demo", "Teacher: Same text.\nTeacher: Same text.\n")
    store.update_teacher_identity(
        "demo",
        "Teacher",
        {
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "teacher_shale",
            "presentation": {"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
        },
        1,
    )
    plan = make_reply_plan(draft["edited_text"], draft["identities"], store.load_cast("demo"))
    assert json.loads(json.dumps(plan)) == plan
    assert [item["card_id"] for item in plan["lines"]] == [
        item["card_id"] for item in draft["identities"]
    ]
    assert all(item["teacher"] for item in plan["lines"])
    assert plan["lines"][0]["reply_id"] != plan["lines"][1]["reply_id"]
    assert plan["lines"][0]["text_sha256"] == plan["lines"][1]["text_sha256"]


def test_compile_snapshot_freezes_reply_plan_before_later_mode_change(tmp_path):
    from build_bundle import BuildBundleManager

    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("demo", "Teacher: Keep me.\n")
    selection = {
        "kind": "teacher",
        "schema_version": "teacher-identity/1.0",
        "preset_id": "teacher_shale",
        "presentation": {"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
    }
    store.update_teacher_identity("demo", "Teacher", selection, 1)
    manager = BuildBundleManager(store=store)
    build_id = manager.create_compile_snapshot("demo", 2)
    snapshot = store.get_draft_path("demo") / "builds" / ".tmp" / build_id / "input"
    plan = json.loads((snapshot / "teacher-reply-plan.json").read_text(encoding="utf-8"))
    assert plan["presentation"]["mode"] == "sel_single"
    store.update_teacher_identity(
        "demo",
        "Teacher",
        {
            **selection,
            "presentation": {"schema_version": "teacher-presentation/1.0", "mode": "slot_zero"},
        },
        2,
    )
    assert json.loads((snapshot / "teacher-reply-plan.json").read_text(encoding="utf-8")) == plan


def test_cg_retarget_keeps_teacher_id_and_source_cards_when_ordinary_portrait_is_hidden(tmp_path):
    from teacher_reply_plan import make_reply_plan, retarget_reply_plan
    from halocue_production.cg_segments import transform_for_compile

    store = DraftStore(str(tmp_path / "drafts"))
    draft = store.create_draft(
        "demo",
        "Teacher: Ready.\nStudent: Yes.\n",
        cast={
            "cast": {"Student": {"id": "student-portrait", "kind": "portrait", "portrait": True}}
        },
    )
    store.update_teacher_identity(
        "demo",
        "Teacher",
        {
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "teacher_shale",
            "presentation": {"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
        },
        1,
    )
    cast = store.load_cast("demo")
    plan = make_reply_plan(draft["edited_text"], draft["identities"], cast)
    segment = {
        "segment_id": "cg-1",
        "start_card_id": draft["identities"][0]["card_id"],
        "end_card_id": draft["identities"][1]["card_id"],
        "background_key": "BG_CS_Fixture",
    }
    text, aliases = transform_for_compile(
        text=draft["edited_text"], identities=draft["identities"], segments=[segment]
    )
    for key, mapping in list(aliases.items()):
        if mapping["id"] == "Teacher":
            aliases[key] = cast["cast"]["Teacher"]
    cast["cast"].update(aliases)
    retargeted = retarget_reply_plan(plan, text, cast)
    assert [row["card_id"] for row in retargeted["lines"]] == [
        row["card_id"] for row in plan["lines"]
    ]
    assert retargeted["lines"][0]["character_id"] == plan["lines"][0]["character_id"]
    assert retargeted["lines"][1]["source_character_id"] == "student-portrait"
    assert retargeted["lines"][1]["character_id"] == "Student"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "  ",
        "one\ntwo",
        "one\rtwo",
        "one\ttwo",
        "[s1] extra",
        "[S -2] extra",
        "#wait;1",
        r"one\n#wait;1",
        "one\u2028two",
    ],
)
def test_sel_answer_control_or_empty_text_is_blocked(text):
    from teacher_reply_plan import validate_reply_text

    with pytest.raises(TeacherIdentityError):
        validate_reply_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "Let's go!",
        "[b]回答[/b]",
        "问题？可以。",
        "[size=60]Hello[/size]",
        "use # for a heading",
        "[s]strike[/s]",
    ],
)
def test_plain_answer_and_documented_styling_are_preserved(text):
    from teacher_reply_plan import validate_reply_text

    assert validate_reply_text(text) == text


@pytest.mark.parametrize(
    "damage",
    [
        "schema",
        "mode",
        "compiled_hash",
        "text_hash",
        "card",
        "reply",
        "teacher",
        "character",
        "count",
        "reorder",
    ],
)
def test_reply_plan_mismatch_is_rejected_before_native_export(tmp_path, damage):
    from teacher_reply_plan import make_reply_plan, validate_reply_plan

    store = DraftStore(str(tmp_path / "drafts"))
    draft = store.create_draft("demo", "Teacher: One.\nTeacher: Two.\n")
    store.update_teacher_identity(
        "demo",
        "Teacher",
        {
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "teacher_shale",
            "presentation": {"schema_version": "teacher-presentation/1.0", "mode": "sel_single"},
        },
        1,
    )
    cast = store.load_cast("demo")
    plan = make_reply_plan(draft["edited_text"], draft["identities"], cast)
    if damage == "schema":
        plan["schema_version"] = "unknown/1.0"
    elif damage == "mode":
        plan["presentation"]["mode"] = "slot_zero"
    elif damage == "compiled_hash":
        plan["compiled_text_sha256"] = "0" * 64
    elif damage == "text_hash":
        plan["lines"][0]["text_sha256"] = "0" * 64
    elif damage == "card":
        plan["lines"][0]["card_id"] = plan["lines"][1]["card_id"]
    elif damage == "reply":
        plan["lines"][0]["reply_id"] = plan["lines"][1]["reply_id"]
    elif damage == "teacher":
        plan["lines"][0]["teacher"] = False
    elif damage == "character":
        plan["lines"][0]["character_id"] = "other"
    elif damage == "count":
        plan["lines"].pop()
    else:
        plan["lines"].reverse()
    with pytest.raises(TeacherIdentityError):
        validate_reply_plan(plan, draft["edited_text"], cast)
