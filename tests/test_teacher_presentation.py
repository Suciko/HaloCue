import json
import os
from pathlib import Path

import pytest

from draft_store import DraftStore, RevisionConflictError
from teacher_identity import TeacherIdentityError


SELECTION = {
    "kind": "teacher",
    "schema_version": "teacher-identity/1.0",
    "preset_id": "teacher_shale",
}
SINGLE = {"schema_version": "teacher-presentation/1.0", "mode": "sel_single"}
SLOT_ZERO = {"schema_version": "teacher-presentation/1.0", "mode": "slot_zero"}


def test_single_answer_survives_restart_without_changing_identity_source_or_resources(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\nStudent: Two.\n")
    created = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    original_cast = store.load_cast("teacher")
    resources_path = store.get_draft_path("teacher") / "resources.json"
    original_resources = json.loads(resources_path.read_text(encoding="utf-8"))

    changed = store.update_teacher_identity(
        "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 2
    )

    restarted = DraftStore(str(store.base_dir))
    cast = restarted.load_cast("teacher")
    assert cast["teacher_presentation"] == SINGLE
    assert cast["teacher_identity"] == original_cast["teacher_identity"]
    assert cast["cast"] == original_cast["cast"]
    assert json.loads(resources_path.read_text(encoding="utf-8")) == original_resources
    assert restarted.load_draft("teacher") == changed
    assert changed["edited_text"] == created["edited_text"]
    assert changed["identities"] == created["identities"]
    assert changed["session"]["draft_version"] == 3
    assert changed["session"]["content_revision"] == 3


def test_reply_ids_are_stable_source_ids_in_a_fixed_namespace():
    from teacher_presentation import teacher_reply_ids

    card_id = "00000000-0000-4000-8000-000000000001"
    expected = {
        "reply_id": "b54719de-4838-5f64-8641-0ac782e1af57",
        "continuation_id": "c7ad1b81-b4d5-516d-b6fc-f5e4c7a5bbf6",
    }
    assert teacher_reply_ids(card_id) == expected
    assert teacher_reply_ids(card_id) is not teacher_reply_ids(card_id)
    assert teacher_reply_ids("00000000-0000-4000-8000-000000000002") != expected


def test_moving_and_editing_a_card_preserves_its_reply_identifiers(tmp_path):
    from teacher_presentation import teacher_reply_ids

    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\nStudent: Two.\n")
    draft = store.update_teacher_identity(
        "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 1
    )
    card_id = draft["identities"][0]["card_id"]
    reply_ids = teacher_reply_ids(card_id)
    moved = store.move_card("teacher", card_id, None, 2)
    assert moved["identities"][-1]["card_id"] == card_id
    assert teacher_reply_ids(moved["identities"][-1]["card_id"]) == reply_ids
    edited = store.update_card_content("teacher", card_id, {"text": "A changed response."}, 3)
    assert "A changed response." in edited["edited_text"]
    assert teacher_reply_ids(edited["identities"][-1]["card_id"]) == reply_ids
    restarted = DraftStore(str(store.base_dir)).load_draft("teacher")
    assert teacher_reply_ids(restarted["identities"][-1]["card_id"]) == reply_ids


@pytest.mark.parametrize("card_id", [None, 1, True, [], "", " ", " id", "id\n", "a" * 257])
def test_reply_ids_require_a_stable_nonempty_source_id(card_id):
    from teacher_presentation import teacher_reply_ids

    with pytest.raises(TeacherIdentityError) as error:
        teacher_reply_ids(card_id)
    assert error.value.code == "invalid_teacher_reply_source"


@pytest.mark.parametrize("presentation", [SINGLE, SLOT_ZERO])
def test_presentation_round_trip_returns_independent_values(presentation):
    from teacher_presentation import (
        effective_teacher_presentation,
        validate_teacher_presentation,
    )

    decoded = json.loads(json.dumps(presentation))
    validated = validate_teacher_presentation(decoded)
    effective = effective_teacher_presentation({"teacher_presentation": decoded})
    assert validated == effective == presentation
    validated["mode"] = "modified"
    effective["mode"] = "modified"
    assert decoded == presentation
    default = effective_teacher_presentation({})
    assert default == SLOT_ZERO
    default["mode"] = "modified"
    assert effective_teacher_presentation({}) == SLOT_ZERO


@pytest.mark.parametrize(
    "presentation,code",
    [
        (None, "invalid_teacher_presentation"),
        ([], "invalid_teacher_presentation"),
        ("sel_single", "invalid_teacher_presentation"),
        (True, "invalid_teacher_presentation"),
        ({}, "teacher_presentation_version_unsupported"),
        (
            {**SINGLE, "schema_version": "teacher-presentation/2.0"},
            "teacher_presentation_version_unsupported",
        ),
        ({**SINGLE, "mode": "choice"}, "invalid_teacher_presentation"),
        ({**SINGLE, "mode": []}, "invalid_teacher_presentation"),
        ({**SINGLE, "mode": None}, "invalid_teacher_presentation"),
        ({**SINGLE, "options": []}, "invalid_teacher_presentation"),
        ({"schema_version": SINGLE["schema_version"]}, "invalid_teacher_presentation"),
    ],
)
def test_invalid_presentation_never_changes_an_existing_draft(tmp_path, presentation, code):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    original = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    original_cast = store.load_cast("teacher")

    with pytest.raises(TeacherIdentityError) as error:
        store.update_teacher_identity(
            "teacher", "Teacher", {**SELECTION, "presentation": presentation}, 2
        )

    assert error.value.code == code
    assert error.value.status == 400
    assert store.load_draft("teacher") == original
    assert store.load_cast("teacher") == original_cast


@pytest.mark.parametrize("presentation", [None, {}, [], {**SINGLE, "mode": "unknown"}])
def test_corrupt_saved_presentation_is_not_silently_overwritten(tmp_path, presentation):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    original = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    cast = store.load_cast("teacher")
    cast["teacher_presentation"] = presentation
    store.save_cast("teacher", cast)

    with pytest.raises(TeacherIdentityError) as error:
        store.update_teacher_identity(
            "teacher", "Teacher", {**SELECTION, "presentation": SLOT_ZERO}, 2
        )

    assert error.value.code == "teacher_presentation_corrupt"
    assert error.value.status == 409
    assert store.load_draft("teacher")["session"] == original["session"]
    assert store.load_cast("teacher") == cast


@pytest.mark.parametrize("explicit", [False, True])
def test_default_presentation_does_not_rewrite_old_tasks_or_discard_review(tmp_path, explicit):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    created = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    reviewed = store.update_card_review(
        "teacher", created["identities"][0]["card_id"], "approved", 2
    )
    before = {p.name: p.read_bytes() for p in store.get_draft_path("teacher").iterdir()}
    selection = {**SELECTION, "presentation": SLOT_ZERO} if explicit else SELECTION

    assert store.update_teacher_identity("teacher", "Teacher", selection, 3) == reviewed
    assert "teacher_presentation" not in store.load_cast("teacher")
    assert {p.name: p.read_bytes() for p in store.get_draft_path("teacher").iterdir()} == before


def test_old_client_omission_keeps_single_answer_and_approved_reviews(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    created = store.update_teacher_identity(
        "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 1
    )
    reviewed = store.update_card_review(
        "teacher", created["identities"][0]["card_id"], "approved", 2
    )
    before = {p.name: p.read_bytes() for p in store.get_draft_path("teacher").iterdir()}

    restarted = DraftStore(str(store.base_dir))
    assert restarted.update_teacher_identity("teacher", "Teacher", SELECTION, 3) == reviewed
    assert (
        restarted.update_teacher_identity(
            "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 3
        )
        == reviewed
    )
    assert restarted.load_cast("teacher")["teacher_presentation"] == SINGLE
    assert {p.name: p.read_bytes() for p in store.get_draft_path("teacher").iterdir()} == before
    with pytest.raises(RevisionConflictError):
        restarted.update_teacher_identity(
            "teacher", "Teacher", {**SELECTION, "presentation": SLOT_ZERO}, 2
        )
    assert restarted.load_draft("teacher") == reviewed


def test_mode_change_reopens_all_teacher_aliases_but_not_ordinary_voices(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft(
        "teacher",
        "Teacher: One.\nSensei: Two.\nClerk: Three.\n",
        cast={"cast": {"Clerk": {"kind": "voice", "id": "clerk", "portrait": False}}},
    )
    store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    draft = store.update_teacher_identity("teacher", "Sensei", SELECTION, 2)
    for card in draft["identities"]:
        draft = store.update_card_review(
            "teacher", card["card_id"], "approved", draft["session"]["draft_version"]
        )
    original_cast = store.load_cast("teacher")
    changed = store.update_teacher_identity(
        "teacher",
        "Sensei",
        {**SELECTION, "presentation": SINGLE},
        draft["session"]["draft_version"],
    )
    assert [card["review_state"] for card in changed["identities"]] == [
        "pending",
        "pending",
        "approved",
    ]
    assert store.load_cast("teacher")["cast"] == original_cast["cast"]
    assert changed["edited_text"] == draft["edited_text"]
    assert [card["card_id"] for card in changed["identities"]] == [
        card["card_id"] for card in draft["identities"]
    ]
    for card in changed["identities"][:2]:
        changed = store.update_card_review(
            "teacher", card["card_id"], "approved", changed["session"]["draft_version"]
        )
    back = store.update_teacher_identity(
        "teacher",
        "Teacher",
        {**SELECTION, "presentation": SLOT_ZERO},
        changed["session"]["draft_version"],
    )
    assert store.load_cast("teacher")["teacher_presentation"] == SLOT_ZERO
    assert [card["review_state"] for card in back["identities"]] == [
        "pending",
        "pending",
        "approved",
    ]


def test_binding_and_renaming_alias_preserves_saved_presentation(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\nSensei: Two.\n")
    created = store.update_teacher_identity(
        "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 1
    )
    reviewed = store.update_card_review(
        "teacher", created["identities"][0]["card_id"], "approved", 2
    )
    identifier = store.load_cast("teacher")["teacher_identity"]["character_id"]
    bound = store.update_teacher_identity(
        "teacher", "Sensei", SELECTION, reviewed["session"]["draft_version"]
    )
    assert [card["review_state"] for card in bound["identities"]] == ["approved", "pending"]
    store.update_teacher_identity(
        "teacher",
        "Sensei",
        {**SELECTION, "preset_id": "custom", "display_name": "Advisor", "organization": ""},
        bound["session"]["draft_version"],
    )
    cast = store.load_cast("teacher")
    assert cast["teacher_presentation"] == SINGLE
    assert cast["teacher_identity"]["character_id"] == identifier
    assert cast["cast"]["Teacher"] == cast["cast"]["Sensei"]


@pytest.mark.parametrize(
    "failure_at",
    ["cast.json", "resources.json", "identity.json", "diagnostics.json", "session.json"],
)
@pytest.mark.parametrize("crash", [False, True])
def test_failed_mode_change_restores_previous_mode_and_review_on_restart(
    tmp_path, monkeypatch, failure_at, crash
):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    created = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    reviewed = store.update_card_review(
        "teacher", created["identities"][0]["card_id"], "approved", 2
    )
    original_cast = store.load_cast("teacher")
    real_replace = os.replace
    failed = False

    def interrupted_replace(source, target):
        nonlocal failed
        if not failed and Path(target).name == failure_at:
            failed = True
            if crash:
                real_replace(source, target)
                raise SystemExit("simulated process exit")
            raise OSError("private path must not leak")
        return real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", interrupted_replace)
        with pytest.raises(SystemExit if crash else TeacherIdentityError) as error:
            store.update_teacher_identity(
                "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 3
            )
    if not crash:
        assert error.value.code == "teacher_identity_write_failed"
        assert "private" not in str(error.value)
    restarted = DraftStore(str(store.base_dir))
    assert restarted.load_draft("teacher") == reviewed
    assert restarted.load_cast("teacher") == original_cast
    assert (
        restarted.update_teacher_identity(
            "teacher", "Teacher", {**SELECTION, "presentation": SINGLE}, 3
        )["session"]["draft_version"]
        == 4
    )
