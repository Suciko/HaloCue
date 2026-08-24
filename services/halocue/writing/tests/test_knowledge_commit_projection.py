from __future__ import annotations

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


PROJECTION_KINDS = {"summary", "search", "memory_followup", "review_followup"}


class ControlledKnowledgeProjectionProvider(FakeWritingProvider):
    kind = "knowledge-commit-projection-test"
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
        return {
            "schema_version": "commit-projection-output/1.0",
            "kind": projection_kind,
            "source_revision_id": projection_input["revision_id"],
            "content": {
                "source_kind": projection_input["artifact_kind"],
                "scope_type": projection_input["scope_type"],
                "scope_id": projection_input["scope_id"],
            },
        }


class CanonProposalProvider(FakeWritingProvider):
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        return {
            "text": "我整理了一条待确认的作品事实。",
            "questions": [],
            "reasoning_summary": "把用户明确说明的联网边界整理成候选。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "canon_fact",
                "title": "旧终端联网边界",
                "status": "discussion_draft",
                "content": {
                    "text": "旧终端从未连接校内网络。",
                    "source_refs": ["用户在作品主对话中明确说明"],
                },
            },
        }


def save_knowledge_revision(service: WritingService, source_kind: str) -> dict:
    work = service.create_work({"title": f"{source_kind} 投影合同"})
    if source_kind == "character_card":
        saved = service.save_character_card(
            work["id"],
            {
                "expected_version": work["version"],
                "card_id": "character-kei",
                "name": "凯伊",
                "role": "负责判断调查风险。",
                "source_type": "custom",
                "source_refs": ["用户确认"],
                "trust_status": "confirmed",
            },
        )
        scope_type, scope_id = "character", saved["card_id"]
    elif source_kind == "world_bible":
        saved = service.save_world_bible(
            work["id"],
            {
                "expected_version": work["version"],
                "title": "本作世界观",
                "source_type": "custom",
                "entities": [
                    {
                        "id": "world-terminal",
                        "name": "旧终端",
                        "kind": "technology",
                        "summary": "只在午夜后响应。",
                        "source": "用户确认",
                        "confidence_status": "confirmed",
                    }
                ],
            },
        )
        scope_type, scope_id = "work", work["id"]
    elif source_kind == "work_canon":
        saved = service.save_work_canon(
            work["id"],
            {
                "expected_version": work["version"],
                "facts": [
                    {
                        "id": "fact-terminal-network",
                        "text": "旧终端从未连接校内网络。",
                        "source": "用户确认",
                        "confidence_status": "confirmed",
                        "scope": "work",
                    }
                ],
            },
        )
        scope_type, scope_id = "work", work["id"]
    else:
        raise AssertionError(f"unsupported source kind: {source_kind}")
    return {
        "work": saved["work"],
        "revision_id": saved["revision_id"],
        "source_kind": source_kind,
        "scope_type": scope_type,
        "scope_id": scope_id,
    }


def projection_items(status: dict) -> dict[str, dict]:
    assert status["schema_version"] == "commit-projection/1.0"
    items = {item["kind"]: item for item in status["items"]}
    assert set(items) == PROJECTION_KINDS
    for item in items.values():
        assert item["status"] in {"pending", "done", "failed", "skipped"}
        if item["status"] == "skipped":
            assert item["decision"]["code"] == "not_applicable"
            assert item["decision"]["reason"]
    return items


def artifact_snapshot(work: dict, source_kind: str, scope_id: str) -> dict:
    artifact = next(
        item
        for item in work["artifacts"]
        if item["kind"] == source_kind and item["scope_id"] == scope_id
    )
    revision = artifact["current_revision"]
    return {
        "artifact_id": artifact["id"],
        "current_revision_id": artifact["current_revision_id"],
        "revision_id": revision["id"],
        "content_hash": revision["content_hash"],
        "content": revision["content"],
        "revision_ids": [item["id"] for item in artifact["revisions"]],
    }


@pytest.mark.parametrize("source_kind", ["character_card", "world_bible", "work_canon"])
def test_formal_knowledge_revision_automatically_ensures_projection(tmp_path, source_kind):
    service = WritingService(tmp_path)
    saved = save_knowledge_revision(service, source_kind)

    status = service.get_commit_projection(
        saved["work"]["id"], saved["revision_id"]
    )
    items = projection_items(status)

    assert status["work_id"] == saved["work"]["id"]
    assert status["revision_id"] == saved["revision_id"]
    assert {item["status"] for item in items.values()} <= {"pending", "skipped"}
    assert items["summary"]["status"] == "pending"
    assert items["search"]["status"] == "pending"


def test_accepted_knowledge_proposal_automatically_ensures_projection(tmp_path):
    service = WritingService(tmp_path)
    service.provider = CanonProposalProvider()
    work = service.create_work({"title": "Proposal 资料投影"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "旧终端从未连接校内网络。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "canon_fact",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    accepted = service.accept_proposal(
        work["id"],
        proposed["proposal_id"],
        {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        },
    )
    canon = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "work_canon")
    revision_id = canon["current_revision_id"]

    status = service.get_commit_projection(work["id"], revision_id)

    assert status["work_id"] == work["id"]
    assert status["revision_id"] == revision_id
    assert set(projection_items(status)) == PROJECTION_KINDS


def test_knowledge_projection_ensure_is_idempotent(tmp_path):
    service = WritingService(tmp_path)
    saved = save_knowledge_revision(service, "character_card")

    first = service.ensure_commit_projection(saved["work"]["id"], saved["revision_id"])
    second = service.ensure_commit_projection(saved["work"]["id"], saved["revision_id"])

    assert first["id"] == second["id"]
    assert {
        kind: item["id"] for kind, item in projection_items(first).items()
    } == {
        kind: item["id"] for kind, item in projection_items(second).items()
    }


def test_knowledge_projection_failure_does_not_pollute_formal_revision(tmp_path):
    service = WritingService(tmp_path)
    saved = save_knowledge_revision(service, "world_bible")
    before = artifact_snapshot(saved["work"], saved["source_kind"], saved["scope_id"])
    provider = ControlledKnowledgeProjectionProvider(fail_kinds={"search"})
    service.provider = provider

    result = service.run_commit_projection(saved["work"]["id"], saved["revision_id"])
    items = projection_items(result)
    after = artifact_snapshot(
        service.get_work(saved["work"]["id"]), saved["source_kind"], saved["scope_id"]
    )

    assert items["search"]["status"] == "failed"
    assert items["search"]["error"]["code"] == "commit_projection_failed"
    assert all(
        item["status"] in {"done", "skipped"}
        for kind, item in items.items()
        if kind != "search"
    )
    assert after == before


def test_restart_recovers_knowledge_projection_and_retry_runs_only_failed(tmp_path):
    service = WritingService(tmp_path)
    saved = save_knowledge_revision(service, "work_canon")
    failing = ControlledKnowledgeProjectionProvider(fail_kinds={"summary"})
    service.provider = failing
    partial = service.run_commit_projection(saved["work"]["id"], saved["revision_id"])
    before = projection_items(partial)
    assert before["summary"]["status"] == "failed"

    restarted = WritingService(tmp_path)
    restored = restarted.get_commit_projection(saved["work"]["id"], saved["revision_id"])
    assert {
        kind: item["status"] for kind, item in projection_items(restored).items()
    } == {
        kind: item["status"] for kind, item in before.items()
    }
    recovered = ControlledKnowledgeProjectionProvider()
    restarted.provider = recovered

    retried = restarted.retry_commit_projection(saved["work"]["id"], saved["revision_id"])
    after = projection_items(retried)

    assert recovered.calls == ["summary"]
    assert after["summary"]["status"] == "done"
    assert {
        kind: after[kind]["attempt_count"]
        for kind in PROJECTION_KINDS - {"summary"}
    } == {
        kind: before[kind]["attempt_count"]
        for kind in PROJECTION_KINDS - {"summary"}
    }


def test_knowledge_projection_state_is_isolated_across_revisions(tmp_path):
    service = WritingService(tmp_path)
    saved = save_knowledge_revision(service, "character_card")
    provider = ControlledKnowledgeProjectionProvider()
    service.provider = provider
    first = service.run_commit_projection(
        saved["work"]["id"], saved["revision_id"], projection_kinds=["summary"]
    )
    revised = service.save_character_card(
        saved["work"]["id"],
        {
            "expected_version": saved["work"]["version"],
            "card_id": saved["scope_id"],
            "name": "凯伊",
            "role": "负责判断调查风险，并在证据不足时暂停结论。",
            "source_type": "custom",
            "source_refs": ["用户确认", "第二次修订"],
            "trust_status": "confirmed",
        },
    )
    second = service.get_commit_projection(saved["work"]["id"], revised["revision_id"])
    restored_first = service.get_commit_projection(saved["work"]["id"], saved["revision_id"])

    assert first["id"] != second["id"]
    assert projection_items(restored_first)["summary"]["status"] == "done"
    assert projection_items(second)["summary"]["status"] == "pending"
    assert restored_first["revision_id"] == saved["revision_id"]
    assert second["revision_id"] == revised["revision_id"]


def test_start_reconciles_legacy_current_knowledge_revision_once(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "旧资料投影补登记"})
    with service.repo.transaction() as connection:
        artifact = service._artifact(
            connection, work["id"], "character_card", "character", "character-legacy"
        )
        revision_id = service._add_revision(
            connection,
            artifact,
            {
                "name": "旧人物卡",
                "role": "服务升级前已经存在。",
                "source_refs": ["旧版本用户确认"],
                "source_type": "custom",
                "trust_status": "confirmed",
            },
            "user",
            {"workflow": "legacy.fixture"},
        )
    assert service.repo.get_commit_projection(
        work_id=work["id"], revision_id=revision_id
    ) is None

    first_start = service.start()
    second_start = service.start()
    projection = service.get_commit_projection(work["id"], revision_id)
    with service.repo.connect() as connection:
        job_count = connection.execute(
            """SELECT COUNT(*) FROM agent_dispatch_jobs
               WHERE operation='commit.projection' AND payload_json LIKE ?""",
            (f'%"revision_id":"{revision_id}"%',),
        ).fetchone()[0]
    service.close()

    assert first_start["commit_projection_reconciliation"]["registered_count"] == 1
    assert second_start["commit_projection_reconciliation"] == first_start[
        "commit_projection_reconciliation"
    ]
    assert projection["source"]["kind"] == "character_card"
    assert job_count == 1
