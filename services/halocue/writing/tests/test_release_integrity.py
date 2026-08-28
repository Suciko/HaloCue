import json
import threading
import urllib.error
import urllib.request
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.app import make_handler
from halocue_writing.release_integrity import (
    build_production_handoff,
    source_set_digest,
    verify_script_release,
)
from halocue_writing.service import WritingService


def test_release_ui_compares_dependency_values_not_json_object_key_order():
    app_js = (
        Path(__file__).resolve().parents[1] / "web" / "app.js"
    ).read_text(encoding="utf-8")
    drift_helper = app_js[app_js.index("function releaseSnapshotDrift") : app_js.index("function renderRelease(el)")]
    continuity_surface = app_js[app_js.index("const renderReleaseBeforeContinuityGuide") :]
    assert "const signature=item=>[item.kind,item.scope_type,item.scope_id,item.revision_id,item.content_hash]" in drift_helper
    assert "releaseSnapshotDrift" in continuity_surface
    assert (
        "JSON.stringify(gate.snapshot.dependency_refs||[])===JSON.stringify(dependencyRefs)"
        not in continuity_surface
    )


def _build_release(service: WritingService):
    work = service.create_work({"title": "发布完整性验收"})
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "凯伊发现旧机器在深夜自行启动",
            "mode": "bond_short",
            "characters": ["爱丽丝", "凯伊"],
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"],
        {"expected_version": blueprint["work"]["version"], "title": "第一章"},
    )
    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "提示灯",
            "location": "游戏开发部活动室",
            "goal": "确认异常提示灯的来源",
        },
    )
    candidate = service.generate_scene_candidate(
        work["id"], scene["scene_id"], {"expected_version": scene["work"]["version"]}
    )
    accepted = service.accept_proposal(
        work["id"], candidate["proposal_id"], {"expected_version": candidate["work"]["version"]}
    )
    reviewed = service.review_scene(
        work["id"], scene["scene_id"], {"expected_version": accepted["work"]["version"]}
    )
    memory = service.skip_scene_memory_maintenance(
        work["id"],
        scene["scene_id"],
        {"expected_version": reviewed["work"]["version"], "note": "测试明确跳过。"},
    )
    continuity = service.review_continuity(
        work["id"], {"expected_version": memory["work"]["version"]}
    )
    release_review = service.review_release(
        work["id"], {"expected_version": continuity["work"]["version"]}
    )
    release = service.freeze_release(
        work["id"], {"expected_version": release_review["work"]["version"]}
    )
    return work, release


def _release_row(service, release_id):
    with service.repo.connect() as connection:
        return dict(
            connection.execute(
                "SELECT * FROM script_releases WHERE id=?", (release_id,)
            ).fetchone()
        )


def _write_manifest(service, row, manifest):
    path = service.repo.data_dir / row["manifest_uri"]
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_integrity_failure(service, release_id, reason):
    with pytest.raises(DomainError) as caught:
        service.get_release(release_id)
    assert caught.value.code == "release_integrity_failed"
    assert caught.value.status == 409
    assert caught.value.details == {"release_id": release_id, "reason": reason}


def test_release_contracts_are_versioned_and_complete(tmp_path):
    service = WritingService(tmp_path)
    work, release = _build_release(service)
    loaded = service.get_release(release["release_id"])

    root = Path(__file__).resolve().parents[1]
    release_schema = json.loads(
        (root / "docs/contracts/script-release-1.0.schema.json").read_text(encoding="utf-8")
    )
    handoff_schema = json.loads(
        (root / "docs/contracts/production-handoff-1.0.schema.json").read_text(encoding="utf-8")
    )
    assert loaded["manifest"]["schema_version"] == "script-release/1.0"
    assert set(release_schema["required"]) <= set(loaded["manifest"])
    assert loaded["manifest"]["ba_writing_source_digest"].startswith("sha256:")
    assert loaded["manifest"]["source_set_digest"] == source_set_digest(loaded["manifest"])
    assert handoff_schema["properties"]["schema_version"]["const"] == "production-handoff/1.0"
    assert {
        "ba_writing_source_digest",
        "source_set_digest",
    } <= set(handoff_schema["properties"]["script_release"]["required"])
    assert loaded["work_id"] == work["id"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda value: value.update(schema_version="1.0"), "unsupported_manifest_schema"),
        (lambda value: value.update(release_id="release-forged"), "database_identity_mismatch"),
        (
            lambda value: value.update(ba_writing_source_digest="sha256:" + "0" * 64),
            "source_set_digest_mismatch",
        ),
        (
            lambda value: value["memory_maintenance"][0].update(status="failed"),
            "source_set_digest_mismatch",
        ),
        (
            lambda value: value["scenes"][0].update(title="被篡改的标题"),
            "source_set_digest_mismatch",
        ),
    ],
)
def test_manifest_tampering_is_rejected(tmp_path, mutation, reason):
    service = WritingService(tmp_path)
    _, release = _build_release(service)
    row = _release_row(service, release["release_id"])
    manifest = deepcopy(release["manifest"])
    mutation(manifest)
    _write_manifest(service, row, manifest)
    _assert_integrity_failure(service, release["release_id"], reason)


def test_coordinated_manifest_and_digest_tampering_is_rejected_by_gate_snapshot(tmp_path):
    service = WritingService(tmp_path)
    _, release = _build_release(service)
    row = _release_row(service, release["release_id"])
    manifest = deepcopy(release["manifest"])
    manifest["memory_maintenance"][0]["status"] = "failed"
    manifest["source_set_digest"] = source_set_digest(manifest)
    _write_manifest(service, row, manifest)

    _assert_integrity_failure(
        service, release["release_id"], "release_gate_snapshot_mismatch"
    )


def test_database_identity_and_revision_material_tampering_are_rejected(tmp_path):
    service = WritingService(tmp_path)
    _, release = _build_release(service)
    release_id = release["release_id"]
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE script_releases SET display_version='v-forged' WHERE id=?", (release_id,)
        )
    _assert_integrity_failure(service, release_id, "database_identity_mismatch")

    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE script_releases SET display_version='v1' WHERE id=?", (release_id,)
        )
        revision = connection.execute(
            """SELECT revision.content_uri FROM revisions AS revision
               JOIN scenes AS scene ON scene.current_revision_id=revision.id
               WHERE scene.work_id=?""",
            (release["work"]["id"],),
        ).fetchone()
    (service.repo.data_dir / revision["content_uri"]).write_text("{}\n", encoding="utf-8")
    _assert_integrity_failure(service, release_id, "revision_material_mismatch")


def test_handoff_verifies_before_any_upstream_request(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    _, release = _build_release(service)
    row = _release_row(service, release["release_id"])
    (service.repo.data_dir / row["content_uri"]).write_text("tampered\n", encoding="utf-8")
    calls = []

    def unexpected_request(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("integrity failure must stop before upstream I/O")

    monkeypatch.setattr("halocue_writing.service.urllib.request.urlopen", unexpected_request)
    with pytest.raises(DomainError) as caught:
        service.handoff_release(release["release_id"])
    assert caught.value.code == "release_integrity_failed"
    assert calls == []


def test_handoff_keeps_release_unassigned_when_production_is_unavailable(tmp_path):
    service = WritingService(tmp_path)
    _, release = _build_release(service)
    service.production_url = "http://127.0.0.1:1"

    with pytest.raises(DomainError) as caught:
        service.handoff_release(release["release_id"])

    assert caught.value.code == "production_unavailable"
    restored = service.get_release(release["release_id"])
    assert restored["production_run_id"] is None
    assert restored["manifest"]["release_id"] == release["release_id"]


def test_every_frozen_gate_must_still_be_a_passed_expected_gate(tmp_path):
    service = WritingService(tmp_path)
    _, release = _build_release(service)
    continuity_gate_id = release["manifest"]["gate_snapshot_ids"][0]
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE gates SET status='blocked' WHERE id=?", (continuity_gate_id,)
        )

    _assert_integrity_failure(
        service, release["release_id"], "gate_reference_mismatch"
    )


def test_handoff_builder_defensively_rechecks_inline_text_hash(tmp_path):
    service = WritingService(tmp_path)
    work, release = _build_release(service)
    verified = verify_script_release(
        service.repo, _release_row(service, release["release_id"])
    )
    verified["text"] += "tampered"

    with pytest.raises(DomainError) as caught:
        build_production_handoff(verified, f"{work['title']} · v1")
    assert caught.value.code == "release_integrity_failed"
    assert caught.value.details == {
        "release_id": release["release_id"],
        "reason": "content_hash_mismatch",
    }


def test_http_returns_stable_release_integrity_error(tmp_path):
    service = WritingService(tmp_path / "data")
    _, release = _build_release(service)
    row = _release_row(service, release["release_id"])
    (service.repo.data_dir / row["content_uri"]).write_text("tampered\n", encoding="utf-8")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/releases/{release['release_id']}"
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(url)
        assert caught.value.code == 409
        response = json.loads(caught.value.read().decode("utf-8"))
        assert response["error"] == {
            "code": "release_integrity_failed",
            "message": "发布版本完整性校验失败，系统不会读取或交接损坏内容。",
            "details": {
                "release_id": release["release_id"],
                "reason": "content_hash_mismatch",
            },
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
