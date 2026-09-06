from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class KnowledgeDiscoveryProvider(FakeWritingProvider):
    kind = "knowledge-discovery-test"
    is_simulation = False

    def project_commit_revision(self, projection_kind: str, projection_input: dict) -> dict:
        scene_id = projection_input["scene_id"]
        content = {
            "summary": {"text": "终端在口令后亮起。"},
            "search": {"terms": ["终端", "口令", "亮起"]},
            "memory_followup": {"required": True, "scene_id": scene_id},
            "review_followup": {"required": True, "scene_id": scene_id},
        }[projection_kind]
        return {
            "schema_version": "commit-projection-output/1.0",
            "kind": projection_kind,
            "source_revision_id": projection_input["revision_id"],
            "content": content,
        }

    def extract_memory_bundle(self, memory_context: dict) -> dict:
        return {
            "schema_version": "memory-bundle/1.0",
            "summary": "发现一条需要长期维护的正文事实。",
            "items": [],
            "knowledge_suggestions": [
                {
                    "kind": "canon_fact",
                    "text": "旧终端会在正确口令后亮起。",
                    "scope": "work",
                    "confidence_status": "open",
                    "source_block_ids": ["block-action"],
                }
            ],
        }


def saved_scene(service: WritingService):
    work = service.create_work({"title": "Phase 3 资料维护"})
    created = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {
            "expected_version": work["version"],
            "title": "终端亮起",
            "goal": "确认口令是否有效",
        },
    )
    saved = service.save_scene_manuscript(
        work["id"],
        created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "base_revision_id": None,
            "blocks": [
                {
                    "id": "block-action",
                    "type": "action",
                    "speaker": "",
                    "text": "旧终端在正确口令后亮起。",
                }
            ],
        },
    )
    return saved["work"], created["scene_id"], saved["revision_id"]


def test_background_discovery_is_durable_non_blocking_and_requires_acceptance(tmp_path):
    service = WritingService(tmp_path)
    service.provider = KnowledgeDiscoveryProvider()
    work, scene_id, revision_id = saved_scene(service)

    service.run_commit_projection(work["id"], revision_id)
    with service.repo.connect() as connection:
        queued = connection.execute(
            "SELECT status FROM agent_dispatch_jobs WHERE operation='knowledge.discover'"
        ).fetchall()
    assert len(queued) == 1
    assert queued[0]["status"] == "ready"

    while True:
        dispatched = service.agent_dispatcher.run_once()
        assert dispatched["status"] == "succeeded"
        if dispatched["job"]["operation"] == "knowledge.discover":
            break
    discovered = service.get_work(work["id"])
    suggestion = next(
        item
        for item in discovered["proposals"]
        if item["kind"] == "canon_fact" and item["evidence"].get("background_suggestion")
    )
    assert suggestion["status"] == "pending"
    assert suggestion["evidence"]["scene_revision_id"] == revision_id
    assert suggestion["evidence"]["source_block_ids"] == ["block-action"]
    assert not [item for item in discovered["artifacts"] if item["kind"] == "work_canon"]
    assert not [item for item in discovered["proposals"] if item["kind"] == "memory_bundle"]
    run = next(
        item for item in discovered["agent_runs"]
        if item["policy"].get("workflow") == "knowledge.discover"
    )
    assert run["status"] == "completed"
    assert run["policy"]["background_suggestion_ids"] == [suggestion["id"]]

    accepted = service.accept_proposal(
        work["id"],
        suggestion["id"],
        {
            "expected_version": discovered["version"],
            "expected_impact_digest": suggestion["candidate"]["impact_preview"]["digest"],
        },
    )
    canon = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "work_canon")
    assert canon["current_revision"]["content"]["facts"][0]["text"] == "旧终端会在正确口令后亮起。"


def test_background_discovery_reconcile_dedupes_restart_and_new_revision_gets_new_job(tmp_path):
    service = WritingService(tmp_path)
    service.provider = KnowledgeDiscoveryProvider()
    work, scene_id, first_revision_id = saved_scene(service)
    service.run_commit_projection(work["id"], first_revision_id)
    while True:
        dispatched = service.agent_dispatcher.run_once()
        assert dispatched["status"] == "succeeded"
        if dispatched["job"]["operation"] == "knowledge.discover":
            break

    restarted = WritingService(tmp_path)
    restarted.provider = KnowledgeDiscoveryProvider()
    reconciliation = restarted._reconcile_background_knowledge_jobs()
    assert reconciliation["queued_count"] == 0

    latest = restarted.get_work(work["id"])
    changed = restarted.save_scene_manuscript(
        work["id"],
        scene_id,
        {
            "expected_version": latest["version"],
            "expected_base_revision_id": first_revision_id,
            "blocks": [
                {
                    "id": "block-action",
                    "type": "action",
                    "speaker": "",
                    "text": "旧终端在第二条口令后熄灭。",
                }
            ],
        },
    )
    restarted.run_commit_projection(work["id"], changed["revision_id"])
    superseded = [
        item
        for item in changed["work"]["proposals"]
        if item["kind"] == "canon_fact" and item["evidence"].get("background_suggestion")
    ]
    assert superseded and {item["status"] for item in superseded} == {"superseded"}
    with restarted.repo.connect() as connection:
        jobs = connection.execute(
            "SELECT payload_json FROM agent_dispatch_jobs WHERE operation='knowledge.discover'"
        ).fetchall()
    assert len(jobs) == 2


def test_artifact_revision_comparison_is_scoped_read_only_and_integrity_checked(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "修订比较"})
    first = service.save_work_canon(
        work["id"],
        {
            "expected_version": work["version"],
            "facts": [
                {
                    "id": "fact-terminal",
                    "text": "终端保持熄灭。",
                    "source": "用户确认",
                    "confidence_status": "confirmed",
                    "scope": "work",
                }
            ],
        },
    )
    second = service.save_work_canon(
        work["id"],
        {
            "expected_version": first["work"]["version"],
            "facts": [
                {
                    "id": "fact-terminal",
                    "text": "终端会在口令后亮起。",
                    "source": "场景修订",
                    "confidence_status": "confirmed",
                    "scope": "work",
                }
            ],
        },
    )
    canon = next(item for item in second["work"]["artifacts"] if item["kind"] == "work_canon")
    before = canon["revisions"][-1]
    current_id = canon["current_revision_id"]

    comparison = service.compare_artifact_revisions(
        work["id"], canon["id"], before["id"]
    )
    assert comparison["schema_version"] == "artifact-revision-comparison/1.0"
    assert comparison["comparison_digest"].startswith("sha256:")
    assert not comparison["comparison_digest"].startswith("sha256:sha256:")
    assert comparison["to_revision"]["id"] == current_id
    assert comparison["change_counts"]["replace"] >= 1
    text_change = next(item for item in comparison["changes"] if item["path"].endswith("/text"))
    assert text_change["path"] == "/facts/fact-terminal/text"
    assert text_change["subject"] == "终端会在口令后亮起。"
    assert text_change["before"] == "终端保持熄灭。"
    assert text_change["after"] == "终端会在口令后亮起。"
    restored_canon = next(
        item for item in service.get_work(work["id"])["artifacts"]
        if item["id"] == canon["id"]
    )
    assert restored_canon["current_revision_id"] == current_id

    other = service.create_work({"title": "另一个作品"})
    with pytest.raises(DomainError) as cross_work:
        service.compare_artifact_revisions(other["id"], canon["id"], before["id"])
    assert cross_work.value.code == "not_found"

    with service.repo.connect() as connection:
        content_uri = connection.execute(
            "SELECT content_uri FROM revisions WHERE id=?", (before["id"],)
        ).fetchone()["content_uri"]
    (tmp_path / content_uri).write_text("{}\n", encoding="utf-8")
    with pytest.raises(DomainError) as corrupted:
        service.compare_artifact_revisions(work["id"], canon["id"], before["id"])
    assert corrupted.value.code == "revision_integrity_failed"


def test_artifact_revision_comparison_http_contract_and_against_query(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "修订比较 HTTP"})
    first = service.save_work_canon(
        work["id"],
        {
            "expected_version": work["version"],
            "facts": [
                {
                    "id": "fact-gate",
                    "text": "温室夜间关闭。",
                    "source": "用户确认",
                    "confidence_status": "confirmed",
                    "scope": "work",
                }
            ],
        },
    )
    second = service.save_work_canon(
        work["id"],
        {
            "expected_version": first["work"]["version"],
            "facts": [
                {
                    "id": "fact-gate",
                    "text": "温室夜间关闭，但教师可临时授权。",
                    "source": "场景修订",
                    "confidence_status": "confirmed",
                    "scope": "work",
                }
            ],
        },
    )
    canon = next(item for item in second["work"]["artifacts"] if item["kind"] == "work_canon")
    first_revision_id = canon["revisions"][-1]["id"]
    current_revision_id = canon["current_revision_id"]

    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/v1"

    def get_json(url: str):
        try:
            with urllib.request.urlopen(url) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    try:
        comparison_url = (
            f"{base}/works/{work['id']}/artifacts/{canon['id']}"
            f"/revisions/{first_revision_id}/compare"
        )
        status, response = get_json(comparison_url)
        assert status == 200
        assert response["ok"] is True
        assert response["data"]["from_revision"]["id"] == first_revision_id
        assert response["data"]["to_revision"]["id"] == current_revision_id
        assert response["data"]["change_counts"]["replace"] >= 1
        assert response["data"]["changes"][0]["path"] == "/facts/fact-gate/source"
        assert {item["subject"] for item in response["data"]["changes"]} == {
            "温室夜间关闭，但教师可临时授权。"
        }

        query = urllib.parse.urlencode({"against": first_revision_id})
        status, reverse_response = get_json(
            comparison_url.replace(
                f"/revisions/{first_revision_id}/compare",
                f"/revisions/{current_revision_id}/compare?{query}",
            )
        )
        assert status == 200
        assert reverse_response["data"]["from_revision"]["id"] == current_revision_id
        assert reverse_response["data"]["to_revision"]["id"] == first_revision_id

        status, missing = get_json(
            comparison_url.replace(first_revision_id, "revision-does-not-exist")
        )
        assert status == 404
        assert missing == {
            "ok": False,
            "error": {
                "code": "not_found",
                "message": "revision 不存在。",
                "details": {"resource": "revision", "id": "revision-does-not-exist"},
            },
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
