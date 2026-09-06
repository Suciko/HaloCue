import json
import os
import hashlib
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from draft_store import DraftStore, RevisionConflictError
from teacher_identity import TeacherIdentityError


def test_directory_sync_failure_after_commit_reports_uncertainty_without_claiming_rollback(
    tmp_path, monkeypatch
):
    import teacher_identity_store as transaction

    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    original_sync = transaction._sync_directory

    def sync(directory):
        if (
            not (directory / transaction.JOURNAL).exists()
            and json.loads((directory / "session.json").read_text(encoding="utf-8"))[
                "draft_version"
            ]
            == 2
        ):
            raise OSError("synthetic directory sync failure")
        original_sync(directory)

    with monkeypatch.context() as patch:
        patch.setattr(transaction, "_sync_directory", sync)
        with pytest.raises(TeacherIdentityError) as caught:
            store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
        assert caught.value.code == "teacher_identity_durability_uncertain"
    restored = DraftStore(str(tmp_path / "drafts"))
    current = restored.load_draft("teacher")
    assert current["session"]["draft_version"] == 2
    assert (
        restored.update_teacher_identity("teacher", "Teacher", SELECTION, 2)["session"]
        == current["session"]
    )


SELECTION = {
    "kind": "teacher",
    "schema_version": "teacher-identity/1.0",
    "preset_id": "teacher_shale",
}


def test_teacher_binding_survives_restart_without_changing_source_or_card_ids(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    created = store.create_draft(
        "teacher", "SourceTeacher: Hello.\nStudent: Welcome.\n", cast={"cast": {}}
    )

    updated = store.update_teacher_identity("teacher", "SourceTeacher", SELECTION, 1)

    restarted = DraftStore(str(tmp_path / "drafts"))
    loaded = restarted.load_draft("teacher")
    cast = restarted.load_cast("teacher")
    resources = json.loads(
        (restarted.get_draft_path("teacher") / "resources.json").read_text(encoding="utf-8")
    )
    assert loaded == updated
    assert loaded["session"]["draft_version"] == 2
    assert loaded["session"]["content_revision"] == 2
    assert loaded["edited_text"] == created["edited_text"]
    assert loaded["identities"] == created["identities"]
    assert resources["characters"][0]["identifier"] == cast["teacher_identity"]["character_id"]
    assert cast["cast"]["SourceTeacher"]["portrait"] is False
    assert set(cast["cast"]) == {"SourceTeacher"}


def test_binding_new_alias_preserves_unchanged_reviews_but_rename_resets_all_teacher_aliases(
    tmp_path,
):
    store = DraftStore(str(tmp_path / "drafts"))
    draft = store.create_draft("teacher", "Teacher: One.\nSensei: Two.\nStudent: Three.\n")
    draft = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    for card in draft["identities"]:
        draft = store.update_card_review(
            "teacher", card["card_id"], "approved", draft["session"]["draft_version"]
        )
    original_id = store.load_cast("teacher")["teacher_identity"]["character_id"]

    alias = store.update_teacher_identity(
        "teacher", "Sensei", SELECTION, draft["session"]["draft_version"]
    )
    assert [card["review_state"] for card in alias["identities"]] == [
        "approved",
        "pending",
        "approved",
    ]
    renamed = store.update_teacher_identity(
        "teacher",
        "Sensei",
        {
            "kind": "teacher",
            "schema_version": "teacher-identity/1.0",
            "preset_id": "custom",
            "display_name": "Advisor",
            "organization": "",
        },
        alias["session"]["draft_version"],
    )
    cast = store.load_cast("teacher")
    assert cast["teacher_identity"]["character_id"] == original_id
    assert cast["cast"]["Teacher"] == cast["cast"]["Sensei"]
    assert cast["cast"]["Teacher"]["name"] == "Advisor"
    assert cast["cast"]["Teacher"]["club"] == ""
    assert [card["review_state"] for card in renamed["identities"]] == [
        "pending",
        "pending",
        "approved",
    ]
    assert [card["card_id"] for card in renamed["identities"]] == [
        card["card_id"] for card in draft["identities"]
    ]


def test_reselecting_teacher_is_a_noop_and_stale_version_never_writes(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    created = store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    reviewed = store.update_card_review(
        "teacher", created["identities"][0]["card_id"], "approved", 2
    )
    before = {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    }

    unchanged = store.update_teacher_identity("teacher", "Teacher", SELECTION, 3)
    assert unchanged["session"] == reviewed["session"]
    assert unchanged["identities"] == reviewed["identities"]
    with pytest.raises(RevisionConflictError):
        store.update_teacher_identity("teacher", "Teacher", SELECTION, 2)
    assert {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    } == before


@pytest.mark.parametrize("speaker", ["Unknown", "", None, [], 0])
def test_teacher_cannot_be_bound_without_a_real_source_speaker(tmp_path, speaker):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    with pytest.raises(TeacherIdentityError) as exc:
        store.update_teacher_identity("teacher", speaker, SELECTION, 1)
    assert exc.value.code == "teacher_speaker_not_found"
    assert store.load_draft("teacher")["session"]["draft_version"] == 1


@pytest.mark.parametrize("mapping", [{"kind": "voice", "role": "teacher"}, {"kind": "teacher"}])
def test_generic_cast_update_cannot_forge_a_teacher_declaration(tmp_path, mapping):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    with pytest.raises(TeacherIdentityError) as exc:
        store.update_cast("teacher", "Teacher", mapping, 1)
    assert exc.value.code == "invalid_teacher_identity"
    assert store.load_cast("teacher") == {}


@pytest.mark.parametrize(
    "file,value",
    [
        ("cast.json", []),
        ("resources.json", []),
        ("session.json", {}),
        ("session.json", {"draft_version": 1, "content_revision": "invalid"}),
        ("identity.json", {}),
        ("cast.json", "invalid-json"),
    ],
)
def test_corrupt_draft_records_are_rejected_without_silent_identity_rebuild(tmp_path, file, value):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    target = store.get_draft_path("teacher") / file
    target.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    before = {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    }
    with pytest.raises(TeacherIdentityError) as exc:
        store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    assert exc.value.code == "teacher_identity_corrupt"
    assert {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    "failure_at",
    ["cast.json", "resources.json", "identity.json", "diagnostics.json", "session.json"],
)
def test_partial_teacher_write_rolls_back_before_retry(tmp_path, monkeypatch, failure_at):
    store = DraftStore(str(tmp_path / "drafts"))
    created = store.create_draft("teacher", "Teacher: One.\n")
    before = {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    }
    real_replace = os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if not failed and Path(target).name == failure_at:
            failed = True
            raise OSError("sensitive local path must not be public")
        return real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_once)
        with pytest.raises(TeacherIdentityError) as exc:
            store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    assert exc.value.code == "teacher_identity_write_failed"
    assert "sensitive" not in str(exc.value)
    assert store.load_draft("teacher") == created
    assert {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    } == before
    assert (
        store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)["session"][
            "draft_version"
        ]
        == 2
    )


@pytest.mark.parametrize(
    "failure_at",
    ["cast.json", "resources.json", "identity.json", "diagnostics.json", "session.json"],
)
def test_service_restart_recovers_unacknowledged_teacher_transaction(
    tmp_path, monkeypatch, failure_at
):
    store = DraftStore(str(tmp_path / "drafts"))
    created = store.create_draft("teacher", "Teacher: One.\n")
    real_replace = os.replace

    def crash(source, target):
        real_replace(source, target)
        if Path(target).name == failure_at:
            raise SystemExit("simulated service exit")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", crash)
        with pytest.raises(SystemExit):
            store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)

    restarted = DraftStore(str(tmp_path / "drafts"))
    assert restarted.load_draft("teacher") == created
    assert restarted.load_cast("teacher") == {}
    assert not (restarted.get_draft_path("teacher") / "resources.json").exists()
    assert (
        restarted.update_teacher_identity("teacher", "Teacher", SELECTION, 1)["session"][
            "draft_version"
        ]
        == 2
    )


def test_killed_writer_is_recovered_by_a_new_store(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    original = store.create_draft("teacher", "Teacher: One.\n")
    script = """
import os, sys
from pathlib import Path
from draft_store import DraftStore
replace = os.replace
def exit_after_resource(source, target):
    replace(source, target)
    if Path(target).name == 'resources.json':
        os._exit(73)
os.replace = exit_after_resource
DraftStore(sys.argv[1]).update_teacher_identity('teacher', 'Teacher', {
    'kind':'teacher', 'schema_version':'teacher-identity/1.0', 'preset_id':'teacher_shale'
}, 1)
"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(store.base_dir)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 73
    restarted = DraftStore(str(store.base_dir))
    assert restarted.load_draft("teacher") == original
    assert restarted.load_cast("teacher") == {}


@pytest.mark.parametrize("damage", ["json", "checksum", "traversal", "file_checksum"])
def test_corrupt_recovery_journal_blocks_reads_without_modifying_any_file(
    tmp_path, monkeypatch, damage
):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    real_replace = os.replace

    def crash(source, target):
        real_replace(source, target)
        if Path(target).name == "cast.json":
            raise SystemExit

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", crash)
        with pytest.raises(SystemExit):
            store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    journal = store.get_draft_path("teacher") / ".teacher-identity-transaction.json"
    envelope = json.loads(journal.read_text(encoding="utf-8"))
    if damage == "json":
        journal.write_text("{broken", encoding="utf-8")
    else:
        if damage == "checksum":
            envelope["sha256"] = "0" * 64
        else:
            if damage == "traversal":
                envelope["payload"]["before"]["../outside.json"] = None
            else:
                envelope["payload"]["before"]["cast.json"]["sha256"] = "0" * 64
            envelope["sha256"] = hashlib.sha256(
                json.dumps(
                    envelope["payload"], sort_keys=True, ensure_ascii=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        journal.write_text(json.dumps(envelope), encoding="utf-8")
    before = {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    }

    with pytest.raises(TeacherIdentityError) as exc:
        DraftStore(str(store.base_dir)).load_draft("teacher")
    assert exc.value.code == "teacher_identity_journal_corrupt"
    assert {
        path.name: path.read_bytes()
        for path in store.get_draft_path("teacher").iterdir()
        if path.is_file()
    } == before


@pytest.mark.parametrize("version", [True, "1", None, 0, -1])
def test_teacher_write_requires_positive_integer_version(tmp_path, version):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    with pytest.raises(TeacherIdentityError) as exc:
        store.update_teacher_identity("teacher", "Teacher", SELECTION, version)
    assert exc.value.code == "invalid_teacher_identity"


@pytest.mark.parametrize(
    "counter,value",
    [("draft_version", True), ("content_revision", "invalid"), ("content_revision", -1)],
)
def test_corrupt_stored_versions_never_mutate_teacher_or_raise_raw_errors(tmp_path, counter, value):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    session_path = store.get_draft_path("teacher") / "session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    session[counter] = value
    session_path.write_text(json.dumps(session), encoding="utf-8")
    with pytest.raises(TeacherIdentityError) as exc:
        store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    assert exc.value.code == "teacher_identity_corrupt"


def test_concurrent_teacher_updates_accept_exactly_one_version(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\nSensei: Two.\n")
    start = threading.Barrier(3)
    outcomes = []

    def select(speaker):
        start.wait(timeout=5)
        try:
            store.update_teacher_identity("teacher", speaker, SELECTION, 1)
            outcomes.append("success")
        except RevisionConflictError:
            outcomes.append("conflict")

    workers = [
        threading.Thread(target=select, args=(speaker,)) for speaker in ("Teacher", "Sensei")
    ]
    for worker in workers:
        worker.start()
    start.wait(timeout=5)
    for worker in workers:
        worker.join(timeout=5)
    assert sorted(outcomes) == ["conflict", "success"]
    assert len(store.load_cast("teacher")["cast"]) == 1
    assert store.load_draft("teacher")["session"]["content_revision"] == 2


def test_teacher_may_be_unbound_and_rebound_without_allocating_a_second_identity(tmp_path):
    store = DraftStore(str(tmp_path / "drafts"))
    store.create_draft("teacher", "Teacher: One.\n")
    store.update_teacher_identity("teacher", "Teacher", SELECTION, 1)
    identifier = store.load_cast("teacher")["teacher_identity"]["character_id"]
    store.update_cast("teacher", "Teacher", {"kind": "unset"}, 2)
    store.update_teacher_identity("teacher", "Teacher", SELECTION, 3)
    assert store.load_cast("teacher")["teacher_identity"]["character_id"] == identifier
    assert (
        len(
            json.loads(
                (store.get_draft_path("teacher") / "resources.json").read_text(encoding="utf-8")
            )["characters"]
        )
        == 1
    )
