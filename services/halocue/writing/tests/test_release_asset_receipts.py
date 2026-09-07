"""Release/run-owned receipt history must never become an author source input."""

import pytest

from halocue_writing.repository import canonical_json
from halocue_writing.service import WritingService
from halocue_writing.writing_harness import WritingHarness
from test_scene_asset_references import _freeze_asset_release


@pytest.fixture
def service(tmp_path):
    instance = WritingService(tmp_path)
    instance.production_asset_capabilities = lambda: {"status": "supported"}
    yield instance
    instance.close()


def linked_receipt(service, release, run_id, copy_id):
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE script_releases SET production_run_id=? WHERE id=?",
            (run_id, release["release_id"]),
        )
    references = []
    for group in release["manifest"]["asset_references"]:
        for ref in group["references"]:
            references.append(
                {
                    "scene_id": group["scene_id"],
                    "reference_id": ref["reference_id"],
                    "source_asset_id": ref["source_asset_id"],
                    "source_version": ref["source_version"],
                    "content_hash": ref["content_hash"],
                    "production_copy": {"copy_id": copy_id, "content_hash": ref["content_hash"]},
                }
            )
    return {
        "schema_version": "production-asset-usage/1.0",
        "production_run_id": run_id,
        "references": references,
    }


def freeze_again(service, work_id):
    work = service.get_work(work_id)
    continuity = service.review_continuity(work_id, {"expected_version": work["version"]})
    reviewed = service.review_release(work_id, {"expected_version": continuity["work"]["version"]})
    return service.freeze_release(work_id, {"expected_version": reviewed["work"]["version"]})


def test_matching_receipt_does_not_change_author_rows_or_source_snapshots(service):
    work_id, scene_id, first = _freeze_asset_release(service)
    before = service.get_work(work_id)
    refs = before["chapters"][-1]["scenes"][0]["asset_references"]
    snapshot = service._scene_asset_reference_snapshot(refs)
    receipt = linked_receipt(service, first, "run-one", "copy-one")
    assert (
        service.reconcile_production_asset_copies(first["release_id"], receipt)["status"]
        == "complete"
    )
    after = service.get_work(work_id)
    assert after["version"] == before["version"]
    assert after["chapters"][-1]["scenes"][0]["asset_references"] == refs
    with service.repo.connect() as connection:
        assert (
            WritingHarness._scene_asset_reference_snapshot(connection, work_id, scene_id)
            == snapshot
        )
        assert (
            connection.execute(
                "SELECT production_copy_json FROM scene_asset_references"
            ).fetchone()[0]
            is None
        )


def test_same_source_releases_keep_independent_receipts_and_immutable_manifests(service):
    work_id, _, first = _freeze_asset_release(service)
    manifest_path = service.repo.data_dir / service.get_release(first["release_id"])["manifest_uri"]
    original = manifest_path.read_bytes()
    receipt1 = linked_receipt(service, first, "run-one", "copy-one")
    service.reconcile_production_asset_copies(first["release_id"], receipt1)
    second = freeze_again(service, work_id)
    assert second["manifest"]["asset_references"][0]["references"][0]["production_copy"] is None
    receipt2 = linked_receipt(service, second, "run-two", "copy-two")
    assert service.production_asset_status(second["release_id"])["status"] == "pending"
    service.reconcile_production_asset_copies(second["release_id"], receipt2)
    assert (
        service.production_asset_status(first["release_id"])["references"][0]["production_copy"][
            "copy_id"
        ]
        == "copy-one"
    )
    assert (
        service.production_asset_status(second["release_id"])["references"][0]["production_copy"][
            "copy_id"
        ]
        == "copy-two"
    )
    assert manifest_path.read_bytes() == original


def test_receipt_history_survives_deleting_current_author_reference(service):
    work_id, scene_id, first = _freeze_asset_release(service)
    receipt = linked_receipt(service, first, "run-one", "copy-one")
    work = service.get_work(work_id)
    service.set_scene_asset_references(
        work_id, scene_id, {"expected_version": work["version"], "references": []}
    )
    result = service.reconcile_production_asset_copies(first["release_id"], receipt)
    assert result["status"] == "complete"
    assert (
        service.production_asset_status(first["release_id"])["references"] == receipt["references"]
    )


def test_legacy_unscoped_copy_is_not_promoted_to_a_release_receipt(service):
    work_id, scene_id, first = _freeze_asset_release(service)
    linked_receipt(service, first, "run-one", "copy-one")
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE scene_asset_references SET production_copy_json=?",
            (canonical_json({"copy_id": "legacy-unknown-run", "content_hash": "unknown"}),),
        )
    with service.repo.transaction() as connection:
        connection.execute("DROP TABLE release_asset_receipts")
    service.close()
    reopened = WritingService(service.repo.data_dir)
    reopened.production_asset_capabilities = lambda: {"status": "supported"}
    try:
        status = reopened.production_asset_status(first["release_id"])
        assert status["status"] == "pending"
        assert status["copied_count"] == 0
        with reopened.repo.connect() as connection:
            snapshot = WritingHarness._scene_asset_reference_snapshot(connection, work_id, scene_id)
        assert snapshot[0]["production_copy"] is None
    finally:
        reopened.close()


def test_client_source_fingerprint_does_not_reuse_a_stale_global_copy():
    import json
    import subprocess
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    function = next(
        line
        for line in script.splitlines()
        if line.startswith("function releaseSceneRevisionRefs()")
    )
    probe = (
        """
const stale = {id:'reference-one', source_snapshot:{key:'background-one'}, production_copy:{copy_id:'old-run-copy'}};
const state = {work:{artifacts:[]}};
const scenes = () => [{id:'scene-one', asset_references:[stale]}];
"""
        + function
        + "\nconsole.log(JSON.stringify(releaseSceneRevisionRefs()[0].asset_references[0]));"
    )
    result = subprocess.run(["node", "-e", probe], check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["production_copy"] is None


def test_scene_asset_ui_does_not_claim_a_global_production_copy():
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(
        encoding="utf-8"
    )
    assert "副本回执按发布版本记录" in script
    assert "已收到任务副本" not in script


@pytest.mark.parametrize("broken", ["run", "source", "version", "hash", "duplicate"])
def test_invalid_receipt_is_rejected_without_changing_previous_proof(service, broken):
    from copy import deepcopy
    from halocue_writing.errors import DomainError

    _, _, first = _freeze_asset_release(service)
    receipt = linked_receipt(service, first, "run-one", "copy-one")
    service.reconcile_production_asset_copies(first["release_id"], receipt)
    invalid = deepcopy(receipt)
    if broken == "run":
        invalid["production_run_id"] = "run-other"
    elif broken == "duplicate":
        invalid["references"].append(deepcopy(invalid["references"][0]))
    else:
        field = {"source": "source_asset_id", "version": "source_version", "hash": "content_hash"}[
            broken
        ]
        invalid["references"][0][field] = "wrong"
    with pytest.raises(DomainError) as rejected:
        service.reconcile_production_asset_copies(first["release_id"], invalid)
    assert rejected.value.code == "production_asset_usage_mismatch"
    assert (
        service.production_asset_status(first["release_id"])["references"] == receipt["references"]
    )


def test_release_receipt_survives_backup_restore_without_live_author_reference(service, tmp_path):
    from halocue_writing.backup import WritingBackupManager

    work_id, scene_id, first = _freeze_asset_release(service)
    receipt = linked_receipt(service, first, "run-one", "copy-one")
    service.reconcile_production_asset_copies(first["release_id"], receipt)
    work = service.get_work(work_id)
    service.set_scene_asset_references(
        work_id, scene_id, {"expected_version": work["version"], "references": []}
    )
    service.close()
    _, archive, summary = WritingBackupManager(service.repo.data_dir).export()
    target = tmp_path / "restored"
    WritingService(target).close()
    WritingBackupManager(target).restore(archive, summary["backup_hash"])
    restored = WritingService(target)
    restored.production_asset_capabilities = lambda: {"status": "supported"}
    try:
        assert (
            restored.production_asset_status(first["release_id"])["references"]
            == receipt["references"]
        )
        assert restored.get_release(first["release_id"])["manifest"] == first["manifest"]
    finally:
        restored.close()


def test_old_frozen_copy_is_preserved_not_silently_rewritten(service, monkeypatch):
    from halocue_writing.release_integrity import build_production_handoff, verify_script_release

    work_id, scene_id, _ = _freeze_asset_release(service)
    old_copy = {"copy_id": "legacy-copy", "content_hash": "legacy-hash"}
    serializer = service._scene_asset_reference_snapshot
    harness_serializer = WritingHarness._scene_asset_reference_snapshot
    with monkeypatch.context() as legacy:
        legacy.setattr(
            service,
            "_scene_asset_reference_snapshot",
            lambda refs: [{**ref, "production_copy": old_copy} for ref in serializer(refs)],
        )
        legacy.setattr(
            WritingHarness,
            "_scene_asset_reference_snapshot",
            staticmethod(
                lambda connection, work, scene: [
                    {**ref, "production_copy": old_copy}
                    for ref in harness_serializer(connection, work, scene)
                ]
            ),
        )
        frozen = freeze_again(service, work_id)
    row = service.get_release(frozen["release_id"])
    path = service.repo.data_dir / row["manifest_uri"]
    original = path.read_bytes()
    verified = verify_script_release(service.repo, row)
    handoff = build_production_handoff(verified, "Legacy synthetic release")
    reference = handoff["asset_handoff"]["references"][0]["references"][0]
    assert reference["production_copy"] == old_copy
    assert path.read_bytes() == original
    fresh = freeze_again(service, work_id)
    assert fresh["manifest"]["asset_references"][0]["references"][0]["production_copy"] is None


def test_partial_receipts_accumulate_only_inside_their_release_and_run(service):
    from copy import deepcopy
    from test_scene_asset_references import scene_asset_reference

    work_id, scene_id, _ = _freeze_asset_release(service)
    work = service.get_work(work_id)
    service.set_scene_asset_references(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "references": [scene_asset_reference(), scene_asset_reference("sound", "SE_Synthetic")],
        },
    )
    release = freeze_again(service, work_id)
    receipt = linked_receipt(service, release, "run-one", "copy-one")
    first = deepcopy(receipt)
    first["references"] = receipt["references"][:1]
    second = deepcopy(receipt)
    second["references"] = receipt["references"][1:]
    assert (
        service.reconcile_production_asset_copies(release["release_id"], first)["status"]
        == "pending"
    )
    assert (
        service.reconcile_production_asset_copies(release["release_id"], second)["confirmed_count"]
        == 2
    )
    assert (
        service.production_asset_status(release["release_id"])["references"]
        == receipt["references"]
    )
    linked_receipt(service, release, "run-other", "copy-other")
    assert service.production_asset_status(release["release_id"])["copied_count"] == 0
    linked_receipt(service, release, "run-one", "copy-one")
    assert service.production_asset_status(release["release_id"])["copied_count"] == 2
