from __future__ import annotations

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


PROJECTION_KINDS = {"summary", "search", "memory_followup", "review_followup"}


class ControlledCommitProjectionProvider(FakeWritingProvider):
    kind = "commit-projection-test"
    is_simulation = False

    def __init__(self, *, fail_kinds: set[str] | None = None):
        self.fail_kinds = set(fail_kinds or set())
        self.calls: list[str] = []

    def project_commit_revision(self, projection_kind: str, projection_input: dict) -> dict:
        self.calls.append(projection_kind)
        if projection_kind in self.fail_kinds:
            raise DomainError(
                "commit_projection_failed",
                f"{projection_kind} 测试投影失败。",
                status=502,
                details={"projection_kind": projection_kind},
            )
        revision_id = projection_input["revision_id"]
        outputs = {
            "summary": {"text": "旧终端在口令后亮起。"},
            "search": {"terms": ["旧终端", "口令", "亮起"]},
            "memory_followup": {"required": True, "scene_id": projection_input["scene_id"]},
            "review_followup": {"required": True, "scene_id": projection_input["scene_id"]},
        }
        return {
            "schema_version": "commit-projection-output/1.0",
            "kind": projection_kind,
            "source_revision_id": revision_id,
            "content": outputs[projection_kind],
        }


def committed_scene(service: WritingService, *, text: str = "旧终端在口令后亮起。"):
    work = service.create_work({"title": "CommitProjection 合同"})
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
                    "text": text,
                }
            ],
        },
    )
    return saved["work"], created["scene_id"], saved["revision_id"]


def projection_items(status: dict) -> dict[str, dict]:
    assert status["schema_version"] == "commit-projection/1.0"
    items = {item["kind"]: item for item in status["items"]}
    assert set(items) == PROJECTION_KINDS
    assert all(item["status"] in {"pending", "done", "failed", "skipped"} for item in items.values())
    return items


def current_scene_revision(work: dict, scene_id: str) -> dict:
    scene = next(
        scene
        for chapter in work["chapters"]
        for scene in chapter["scenes"]
        if scene["id"] == scene_id
    )
    artifact = next(
        artifact
        for artifact in work["artifacts"]
        if artifact["kind"] == "scene_script" and artifact["scope_id"] == scene_id
    )
    return {
        "scene_revision_id": scene["current_revision_id"],
        "revision_id": artifact["current_revision"]["id"],
        "content_hash": artifact["current_revision"]["content_hash"],
        "content": artifact["current_revision"]["content"],
        "history_ids": [revision["id"] for revision in artifact["revisions"]],
    }


def test_committed_revision_registers_four_pending_projection_items(tmp_path):
    service = WritingService(tmp_path)
    work, _scene_id, revision_id = committed_scene(service)

    ensured = service.ensure_commit_projection(work["id"], revision_id)
    status = service.get_commit_projection(work["id"], revision_id)
    items = projection_items(status)

    assert status["work_id"] == work["id"]
    assert status["id"] == ensured["id"]
    assert status["revision_id"] == revision_id
    assert status["status"] == "pending"
    assert {item["status"] for item in items.values()} == {"pending"}
    assert {item["attempt_count"] for item in items.values()} == {0}


def test_ensure_and_run_same_revision_twice_are_idempotent(tmp_path):
    service = WritingService(tmp_path)
    provider = ControlledCommitProjectionProvider()
    service.provider = provider
    work, _scene_id, revision_id = committed_scene(service)

    first_ensure = service.ensure_commit_projection(work["id"], revision_id)
    second_ensure = service.ensure_commit_projection(work["id"], revision_id)
    assert first_ensure["id"] == second_ensure["id"]
    assert {item["attempt_count"] for item in projection_items(second_ensure).values()} == {0}

    first = service.run_commit_projection(work["id"], revision_id)
    first_items = projection_items(first)
    second = service.run_commit_projection(work["id"], revision_id)
    second_items = projection_items(second)

    assert first["id"] == second["id"]
    assert first["status"] == second["status"] == "completed"
    assert {kind: item["id"] for kind, item in first_items.items()} == {
        kind: item["id"] for kind, item in second_items.items()
    }
    assert {kind: item["attempt_count"] for kind, item in second_items.items()} == {
        kind: 1 for kind in PROJECTION_KINDS
    }
    assert len(provider.calls) == 4
    assert set(provider.calls) == PROJECTION_KINDS


def test_one_projection_failure_keeps_other_outputs_and_never_rewrites_revision(tmp_path):
    service = WritingService(tmp_path)
    provider = ControlledCommitProjectionProvider(fail_kinds={"search"})
    service.provider = provider
    work, scene_id, revision_id = committed_scene(service)
    service.ensure_commit_projection(work["id"], revision_id)
    source_before = current_scene_revision(work, scene_id)

    status = service.run_commit_projection(work["id"], revision_id)
    items = projection_items(status)
    source_after = current_scene_revision(service.get_work(work["id"]), scene_id)

    assert status["status"] == "partial"
    assert items["search"]["status"] == "failed"
    assert items["search"]["error"]["code"] == "commit_projection_failed"
    assert {
        kind: items[kind]["status"]
        for kind in PROJECTION_KINDS - {"search"}
    } == {
        kind: "done" for kind in PROJECTION_KINDS - {"search"}
    }
    assert all(items[kind]["output_ref"] for kind in PROJECTION_KINDS - {"search"})
    assert source_after == source_before


def test_retry_runs_only_failed_projection_items(tmp_path):
    service = WritingService(tmp_path)
    failing = ControlledCommitProjectionProvider(fail_kinds={"memory_followup"})
    service.provider = failing
    work, _scene_id, revision_id = committed_scene(service)
    service.ensure_commit_projection(work["id"], revision_id)
    partial = service.run_commit_projection(work["id"], revision_id)
    before = projection_items(partial)
    done_attempts = {
        kind: before[kind]["attempt_count"]
        for kind in PROJECTION_KINDS - {"memory_followup"}
    }
    recovered = ControlledCommitProjectionProvider()
    service.provider = recovered

    retried = service.retry_commit_projection(work["id"], revision_id)
    after = projection_items(retried)

    assert retried["status"] == "completed"
    assert recovered.calls == ["memory_followup"]
    assert after["memory_followup"]["attempt_count"] == 2
    assert {
        kind: after[kind]["attempt_count"]
        for kind in PROJECTION_KINDS - {"memory_followup"}
    } == done_attempts


def test_pending_and_failed_projection_state_survives_service_restart(tmp_path):
    service = WritingService(tmp_path)
    provider = ControlledCommitProjectionProvider(fail_kinds={"review_followup"})
    service.provider = provider
    work, _scene_id, revision_id = committed_scene(service)
    service.ensure_commit_projection(work["id"], revision_id)
    partial = service.run_commit_projection(
        work["id"], revision_id, projection_kinds=["summary", "review_followup"]
    )
    before = projection_items(partial)
    assert before["summary"]["status"] == "done"
    assert before["review_followup"]["status"] == "failed"
    assert before["search"]["status"] == "pending"
    assert before["memory_followup"]["status"] == "pending"

    restarted = WritingService(tmp_path)
    restored = restarted.get_commit_projection(work["id"], revision_id)
    after = projection_items(restored)

    assert restored["id"] == partial["id"]
    assert {
        kind: item["status"] for kind, item in after.items()
    } == {
        kind: item["status"] for kind, item in before.items()
    }
    assert after["review_followup"]["error"] == before["review_followup"]["error"]

    recovered = ControlledCommitProjectionProvider()
    restarted.provider = recovered
    retried = restarted.retry_commit_projection(work["id"], revision_id)
    retry_items = projection_items(retried)
    assert recovered.calls == ["review_followup"]
    assert retry_items["review_followup"]["status"] == "done"
    assert retry_items["search"]["status"] == "pending"
    assert retry_items["memory_followup"]["status"] == "pending"

    resumed = restarted.run_commit_projection(work["id"], revision_id)
    assert resumed["status"] == "completed"
    assert len(recovered.calls[1:]) == 2
    assert set(recovered.calls[1:]) == {"search", "memory_followup"}


def test_skipped_projection_is_auditable_and_not_executed(tmp_path):
    service = WritingService(tmp_path)
    provider = ControlledCommitProjectionProvider()
    service.provider = provider
    work, _scene_id, revision_id = committed_scene(service)
    service.ensure_commit_projection(work["id"], revision_id)

    skipped = service.skip_commit_projection(
        work["id"],
        revision_id,
        "review_followup",
        reason="本次仅保存草稿，不进行审查。",
    )
    items = projection_items(skipped)
    completed = service.run_commit_projection(work["id"], revision_id)
    completed_items = projection_items(completed)

    assert items["review_followup"]["status"] == "skipped"
    assert items["review_followup"]["decision"]["reason"] == "本次仅保存草稿，不进行审查。"
    assert completed_items["review_followup"]["status"] == "skipped"
    assert "review_followup" not in provider.calls


def test_projection_state_is_isolated_between_scene_revisions(tmp_path):
    service = WritingService(tmp_path)
    provider = ControlledCommitProjectionProvider()
    service.provider = provider
    work, scene_id, first_revision_id = committed_scene(service)
    service.ensure_commit_projection(work["id"], first_revision_id)
    first = service.run_commit_projection(
        work["id"], first_revision_id, projection_kinds=["summary"]
    )
    scene = next(
        scene
        for chapter in work["chapters"]
        for scene in chapter["scenes"]
        if scene["id"] == scene_id
    )
    changed = service.save_scene_manuscript(
        work["id"],
        scene_id,
        {
            "expected_version": work["version"],
            "expected_base_revision_id": scene["current_revision_id"],
            "blocks": [
                {
                    "id": "block-action",
                    "type": "action",
                    "speaker": "",
                    "text": "旧终端没有回应第二次口令。",
                }
            ],
        },
    )
    second_revision_id = changed["revision_id"]
    service.ensure_commit_projection(work["id"], second_revision_id)

    second = service.get_commit_projection(work["id"], second_revision_id)
    restored_first = service.get_commit_projection(work["id"], first_revision_id)
    first_items = projection_items(restored_first)
    second_items = projection_items(second)

    assert second["id"] != first["id"]
    assert second["revision_id"] != first["revision_id"]
    assert first_items["summary"]["status"] == "done"
    assert second_items["summary"]["status"] == "pending"
    assert {item["status"] for item in second_items.values()} == {"pending"}
