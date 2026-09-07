"""Adopted prose candidates must become ordinary scene revisions, not orphan artifacts."""

import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.repository import canonical_json
from halocue_writing.service import WritingService
from test_adaptation_integrity import prepared, valid_reply, ReplyProvider


def candidate(service, source, plan, text="老师: 我们进去看看。\n旁白: 门前的灯亮着。\n"):
    service.provider = ReplyProvider(json.dumps(valid_reply(source["chapters"][0], text)))
    return service.adaptations.generate_chapter_candidate(plan["id"], source["chapters"][0]["id"])


def current_scene(service, work_id, scene_id):
    work = service.get_work(work_id)
    return next(
        scene
        for chapter in work["chapters"]
        for scene in chapter["scenes"]
        if scene["id"] == scene_id
    )


def content(service, revision_id):
    with service.repo.connect() as c:
        row = c.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
    return json.loads(service.repo.read_text(row["content_uri"]))


def test_candidate_preview_has_target_but_creates_no_formal_scene(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    generated = candidate(service, source, plan)
    target = generated["candidate"]["target"]
    assert target["scene_id"] is None
    assert target["chapter_id"] == work["chapters"][0]["id"]
    assert not [
        scene for chapter in service.get_work(work["id"])["chapters"] for scene in chapter["scenes"]
    ]
    assert service.get_work(work["id"])["version"] == work["version"]


def test_adoption_creates_normal_scene_revision_and_survives_reload(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    generated = candidate(service, source, plan)
    adopted = service.accept_proposal(
        work["id"], generated["proposal_id"], {"expected_version": work["version"]}
    )
    scene = current_scene(service, work["id"], adopted["scene_id"])
    assert scene["current_revision_id"] == adopted["revision_id"]
    manuscript = content(service, adopted["revision_id"])
    assert manuscript["schema_version"] == "scene-blocks/1.0"
    assert manuscript["text"] == generated["candidate"]["text"]
    artifacts = service.get_work(work["id"])["artifacts"]
    assert any(a["kind"] == "scene_script" and a["scope_id"] == scene["id"] for a in artifacts)
    assert not any(a["kind"] == "adaptation_manuscript" for a in artifacts)
    service.close()
    reopened = WritingService(service.repo.data_dir)
    assert (
        current_scene(reopened, work["id"], scene["id"])["current_revision_id"]
        == adopted["revision_id"]
    )
    reopened.close()


def test_pending_regeneration_cannot_overwrite_manual_edit_to_mapped_scene(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    first = candidate(service, source, plan)
    adopted = service.accept_proposal(
        work["id"], first["proposal_id"], {"expected_version": work["version"]}
    )
    second = candidate(service, source, plan, "老师: 另一个候选。\n")
    edited = service.save_scene_manuscript(
        work["id"],
        adopted["scene_id"],
        {
            "expected_version": adopted["work"]["version"],
            "expected_base_revision_id": adopted["revision_id"],
            "blocks": [
                {
                    "id": "block-manual",
                    "type": "dialogue",
                    "speaker": "老师",
                    "text": "我决定留在这里。",
                }
            ],
        },
    )
    with pytest.raises(DomainError) as rejected:
        service.accept_proposal(
            work["id"], second["proposal_id"], {"expected_version": edited["work"]["version"]}
        )
    assert rejected.value.code == "proposal_superseded"
    assert content(service, edited["revision_id"])["text"] == "老师: 我决定留在这里。\n"
    next_candidate = candidate(service, source, plan)
    assert next_candidate["candidate"]["target"]["base_revision_id"] == edited["revision_id"]
    accepted = service.accept_proposal(
        work["id"],
        next_candidate["proposal_id"],
        {"expected_version": service.get_work(work["id"])["version"]},
    )
    assert accepted["scene_id"] == adopted["scene_id"]


def test_deleted_target_chapter_rejects_candidate_without_partial_scene(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    generated = candidate(service, source, plan)
    with service.repo.transaction() as c:
        c.execute("DELETE FROM chapters WHERE work_id=?", (work["id"],))
    with pytest.raises(DomainError):
        service.accept_proposal(
            work["id"], generated["proposal_id"], {"expected_version": work["version"]}
        )
    with service.repo.connect() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM scenes WHERE work_id=?", (work["id"],)).fetchone()[0]
            == 0
        )
        assert (
            c.execute(
                "SELECT status FROM proposals WHERE id=?", (generated["proposal_id"],)
            ).fetchone()[0]
            == "pending"
        )


def test_acceptance_cannot_redirect_to_unrelated_scene(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    unrelated = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {"expected_version": work["version"], "title": "Unrelated"},
    )
    generated = candidate(service, source, plan)
    with pytest.raises(DomainError) as rejected:
        service.accept_proposal(
            work["id"],
            generated["proposal_id"],
            {
                "expected_version": unrelated["work"]["version"],
                "target_scene_id": unrelated["scene_id"],
            },
        )
    assert rejected.value.code == "adaptation_target_changed"
    assert current_scene(service, work["id"], unrelated["scene_id"])["current_revision_id"] is None


def test_new_adapted_scene_keeps_work_writing_mode(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "忠实改编本章",
            "mode": "main_battle",
            "characters": ["老师"],
        },
    )
    generated = candidate(service, source, plan)
    accepted = service.accept_proposal(
        work["id"], generated["proposal_id"], {"expected_version": brief["work"]["version"]}
    )
    scene = current_scene(service, work["id"], accepted["scene_id"])
    assert scene["contract"]["writing_mode"] == "main_battle"


def legacy_accepted(service, work, source, plan):
    generated = candidate(service, source, plan)
    raw = generated["candidate"]
    with service.repo.transaction() as c:
        chapter = c.execute(
            "SELECT * FROM adaptation_chapters WHERE adaptation_id=?", (plan["id"],)
        ).fetchone()
        artifact = service._artifact(
            c, work["id"], "adaptation_manuscript", "adaptation_chapter", chapter["id"]
        )
        value = {
            key: raw[key]
            for key in (
                "text",
                "source_version_id",
                "source_chapter_id",
                "source_refs",
                "deviations",
                "open_threads",
            )
        }
        value["schema_version"] = "adaptation-manuscript/1.0"
        revision_id = service._add_revision(
            c,
            artifact,
            value,
            "user",
            {"workflow": "legacy-adaptation"},
            schema_version="adaptation-manuscript/1.0",
        )
        c.execute("UPDATE proposals SET status='accepted' WHERE id=?", (generated["proposal_id"],))
        c.execute(
            "UPDATE adaptation_chapters SET status='accepted',candidate_json=? WHERE id=?",
            (canonical_json({**raw, "formal": True, "revision_id": revision_id}), chapter["id"]),
        )
        row = c.execute(
            "SELECT content_uri,content_hash FROM revisions WHERE id=?", (revision_id,)
        ).fetchone()
    return revision_id, row["content_uri"], row["content_hash"]


def test_legacy_adopted_artifact_requires_explicit_promotion_and_preserves_bytes(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    revision_id, uri, digest = legacy_accepted(service, work, source, plan)
    before = (service.repo.data_dir / uri).read_bytes()
    restored = WritingService(service.repo.data_dir)
    assert not [s for c in restored.get_work(work["id"])["chapters"] for s in c["scenes"]]
    request = {
        "expected_version": work["version"],
        "expected_revision_id": revision_id,
        "target_chapter_id": work["chapters"][0]["id"],
    }
    promoted = restored.promote_adaptation_manuscript(
        work["id"], plan["id"], source["chapters"][0]["id"], request
    )
    assert content(restored, promoted["revision_id"])["schema_version"] == "scene-blocks/1.0"
    assert (service.repo.data_dir / uri).read_bytes() == before
    with restored.repo.connect() as c:
        assert (
            c.execute("SELECT content_hash FROM revisions WHERE id=?", (revision_id,)).fetchone()[0]
            == digest
        )
        assert (
            c.execute(
                "SELECT current_revision_id FROM artifacts WHERE kind='adaptation_manuscript'"
            ).fetchone()[0]
            == revision_id
        )
    replay = restored.promote_adaptation_manuscript(
        work["id"], plan["id"], source["chapters"][0]["id"], request
    )
    assert replay["deduplicated"] is True
    assert replay["revision_id"] == promoted["revision_id"]
    assert len([s for c in replay["work"]["chapters"] for s in c["scenes"]]) == 1
    restored.close()


def test_legacy_promotion_needs_an_explicit_owned_target(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    revision_id, _, _ = legacy_accepted(service, work, source, plan)
    with pytest.raises(DomainError):
        service.promote_adaptation_manuscript(
            work["id"],
            plan["id"],
            source["chapters"][0]["id"],
            {"expected_version": work["version"], "expected_revision_id": revision_id},
        )
    other = service.create_work({"title": "other"})
    with pytest.raises(DomainError):
        service.promote_adaptation_manuscript(
            work["id"],
            plan["id"],
            source["chapters"][0]["id"],
            {
                "expected_version": work["version"],
                "expected_revision_id": revision_id,
                "target_chapter_id": other["chapters"][0]["id"],
            },
        )
    assert not [s for c in service.get_work(work["id"])["chapters"] for s in c["scenes"]]


def test_adoption_normalizes_scene_text_and_reports_difference(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    generated = candidate(service, source, plan, "  老师： 我们进去看看。  \n\n")
    accepted = service.accept_proposal(
        work["id"], generated["proposal_id"], {"expected_version": work["version"]}
    )
    manuscript = content(service, accepted["revision_id"])
    assert (
        manuscript["text"]
        == service._scene_text_from_blocks(manuscript["blocks"])
        == "老师: 我们进去看看。\n"
    )
    assert accepted["normalization_changed_text"] is True


def test_old_queued_snapshot_without_target_requires_fresh_generation(tmp_path, monkeypatch):
    from halocue_writing.repository import sha256_text

    service, work, source, plan = prepared(tmp_path)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = service.adaptation_jobs.enqueue(work["id"], plan["id"], source["chapters"][0]["id"])
    with service.repo.transaction() as c:
        run = c.execute("SELECT * FROM agent_runs WHERE id=?", (queued["agent_run_id"],)).fetchone()
        value = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
        value.pop("target")
        raw = canonical_json(value)
        service.repo.atomic_write_text(run["input_snapshot_uri"], raw)
        c.execute("UPDATE agent_runs SET input_digest=? WHERE id=?", (sha256_text(raw), run["id"]))
    service.agent_dispatcher.run_once()
    failed = service.get_agent_run(work["id"], queued["agent_run_id"])
    assert failed["failure"]["code"] == "adaptation_target_confirmation_required"
    assert failed["failure"]["retryable"] is False
    with pytest.raises(DomainError) as rejected:
        service.retry_agent_run(work["id"], queued["agent_run_id"], {})
    assert rejected.value.code == "adaptation_target_confirmation_required"
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0


def test_source_grounded_candidate_cannot_change_its_adaptation_chapter_scope(tmp_path):
    service, work, source, plan = prepared(tmp_path, text="第一章\n门开了。\n第二章\n灯亮了。")
    generated = candidate(service, source, plan)
    other = source["chapters"][1]
    with service.repo.transaction() as c:
        proposal = c.execute(
            "SELECT * FROM proposals WHERE id=?", (generated["proposal_id"],)
        ).fetchone()
        value = json.loads(service.repo.read_text(proposal["candidate_uri"]))
        value["source_chapter_id"] = other["id"]
        value["source_refs"] = [
            {"paragraph_id": other["paragraphs"][0]["id"], "quote": other["paragraphs"][0]["text"]}
        ]
        _, digest = service.repo.atomic_write_text(proposal["candidate_uri"], canonical_json(value))
        evidence = {
            "source_version_id": source["id"],
            "source_chapter_id": other["id"],
            "source_digest": other["content_digest"],
        }
        c.execute(
            "UPDATE proposals SET candidate_hash=?,evidence_json=? WHERE id=?",
            (digest, canonical_json(evidence), proposal["id"]),
        )
    with pytest.raises(DomainError) as rejected:
        service.accept_proposal(
            work["id"], generated["proposal_id"], {"expected_version": work["version"]}
        )
    assert rejected.value.code == "proposal_candidate_invalid"
    assert not [s for c in service.get_work(work["id"])["chapters"] for s in c["scenes"]]


def test_concurrent_acceptance_creates_only_one_scene_revision(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    service, work, source, plan = prepared(tmp_path)
    generated = candidate(service, source, plan)
    other = WritingService(service.repo.data_dir)
    barrier = threading.Barrier(2)

    def accept(instance):
        barrier.wait(3)
        try:
            return instance.accept_proposal(
                work["id"], generated["proposal_id"], {"expected_version": work["version"]}
            )
        except DomainError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(accept, (service, other)))
    assert sum(isinstance(result, dict) for result in results) == 1
    scenes = [s for c in service.get_work(work["id"])["chapters"] for s in c["scenes"]]
    assert len(scenes) == 1
    with service.repo.connect() as c:
        assert (
            c.execute(
                "SELECT COUNT(*) FROM revisions WHERE artifact_id IN (SELECT id FROM artifacts WHERE work_id=? AND kind='scene_script')",
                (work["id"],),
            ).fetchone()[0]
            == 1
        )
    other.close()


def test_explicit_legacy_promotion_is_available_through_http(tmp_path):
    from http.server import ThreadingHTTPServer
    import threading
    from pathlib import Path
    from halocue_writing.app import make_handler
    import urllib.request

    service, work, source, plan = prepared(tmp_path)
    revision_id, _, _ = legacy_accepted(service, work, source, plan)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/works/{work['id']}/adaptations/{plan['id']}/chapters/{source['chapters'][0]['id']}/manuscript:promote"
        request = urllib.request.Request(
            url,
            data=json.dumps(
                {
                    "expected_version": work["version"],
                    "expected_revision_id": revision_id,
                    "target_chapter_id": work["chapters"][0]["id"],
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as reply:
            assert reply.status == 200
            response = json.loads(reply.read())
        assert response["data"]["scene_id"]
        assert (
            current_scene(service, work["id"], response["data"]["scene_id"])["current_revision_id"]
            == response["data"]["revision_id"]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        service.close()


def test_adaptation_detail_exposes_canonical_target_for_legacy_candidate(tmp_path):
    service, work, source, plan = prepared(tmp_path)
    generated = candidate(service, source, plan)
    adopted = service.accept_proposal(
        work["id"], generated["proposal_id"], {"expected_version": work["version"]}
    )
    result = service.adaptations.get(plan["id"])["chapters"][0]
    assert result["resolved_target"]["scene_id"] == adopted["scene_id"]
    assert result["resolved_target"]["base_revision_id"] == adopted["revision_id"]
