import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from test_character_card_import import character_artifacts, encoded_payload, formal_card


@pytest.fixture
def setup(tmp_path):
    service = WritingService(tmp_path)
    source = service.create_work({"title": "Source references"})
    result = service.import_character_card(
        source["id"],
        encoded_payload(formal_card("Synthetic character"), expected_version=source["version"]),
    )
    target = service.create_work({"title": "Target manuscript"})
    payload = {
        "source_work_id": source["id"],
        "source_card_id": result["card_id"],
        "source_revision_id": result["revision_id"],
        "expected_version": target["version"],
    }
    return service, result, target, payload


def test_reuse_preserves_profile_provenance_and_independent_import_bytes(setup, tmp_path):
    service, source, target, payload = setup
    original = character_artifacts(source["work"])[0]["current_revision"]["content"]
    result = service.reuse_character_card(target["id"], payload)
    restarted = WritingService(tmp_path)
    card = character_artifacts(restarted.get_work(target["id"]))[0]["current_revision"]["content"]
    assert card["ba_profile"] == original["ba_profile"]
    assert card["validation_report"] == original["validation_report"]
    assert card["source_hash"] == original["source_hash"]
    assert card["source_type"] == original["source_type"]
    assert card["trust_status"] == "unverified"
    assert card["source_refs"][:-1] == original["source_refs"]
    assert card["reuse_origin"]["revision_id"] == source["revision_id"]
    assert result["card_id"] != source["card_id"]
    for kind in ("raw", "cleaned"):
        assert card[f"{kind}_import_uri"] != original[f"{kind}_import_uri"]
        assert (tmp_path / card[f"{kind}_import_uri"]).read_bytes() == (
            tmp_path / original[f"{kind}_import_uri"]
        ).read_bytes()
    assert restarted.get_work(source["work"]["id"])["version"] == source["work"]["version"]
    assert restarted.get_work(target["id"])["chapters"] == target["chapters"]
    with pytest.raises(DomainError) as error:
        service.reuse_character_card(
            target["id"], {**payload, "expected_version": result["work"]["version"]}
        )
    assert error.value.code == "character_card_identity_conflict"
    assert len(character_artifacts(service.get_work(target["id"]))) == 1


@pytest.mark.parametrize(
    "mode",
    ["changed", "archived", "stale_target", "wrong_work", "same_work", "missing_file", "bad_hash"],
)
def test_unsafe_reuse_fails_without_new_card(setup, tmp_path, mode):
    service, source, target, payload = setup
    original = character_artifacts(source["work"])[0]["current_revision"]["content"]
    if mode == "changed":
        payload["source_revision_id"] = "stale-revision"
    elif mode == "archived":
        archived = service.archive_character_card(
            source["work"]["id"], source["card_id"], {"expected_version": source["work"]["version"]}
        )
        payload["source_revision_id"] = archived["revision_id"]
    elif mode == "stale_target":
        payload["expected_version"] = -1
    elif mode == "wrong_work":
        payload["source_work_id"] = "another-work"
    elif mode == "same_work":
        payload["source_work_id"] = target["id"]
    elif mode == "missing_file":
        (tmp_path / original["raw_import_uri"]).unlink()
    elif mode == "bad_hash":
        (tmp_path / original["cleaned_import_uri"]).write_bytes(b"tampered")
    with pytest.raises(DomainError):
        service.reuse_character_card(target["id"], payload)
    result = service.get_work(target["id"])
    assert result["version"] == target["version"]
    assert not character_artifacts(result)


def test_relationship_ids_do_not_cross_work_boundaries(setup):
    service, source, target, payload = setup
    card = character_artifacts(source["work"])[0]["current_revision"]["content"]
    card["relationships"] = [
        {
            "id": "source-edge",
            "target_character_id": "source-other",
            "target": "Other",
            "kind": "ally",
            "summary": "Synthetic",
        }
    ]
    updated = service.save_character_card(
        source["work"]["id"],
        {**card, "card_id": source["card_id"], "expected_version": source["work"]["version"]},
    )
    result = service.reuse_character_card(
        target["id"], {**payload, "source_revision_id": updated["revision_id"]}
    )
    copied = character_artifacts(result["work"])[0]["current_revision"]["content"]
    assert copied["relationships"][0]["target"] == "Other"
    assert "target_character_id" not in copied["relationships"][0]
    assert "id" not in copied["relationships"][0]
