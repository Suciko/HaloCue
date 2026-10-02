"""Card assistance reuses durable discussion and human-approved Revisions."""

import copy
import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class CardAssistanceProvider(FakeWritingProvider):
    """Deliberately overbroad synthetic reply to exercise server field limits."""

    def __init__(self):
        self.contexts = []

    def discuss_work(self, messages, work_context):
        self.contexts.append(copy.deepcopy(work_context))
        context = work_context.get("card_assistance") or {}
        kind = context.get("kind", "character_card")
        return {
            "text": "已整理本作调整建议；以下为本地模拟验收，不代表真实模型质量。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": kind,
                "title": context.get("name", "白露"),
                "status": "discussion_draft",
                "summary": "先保持距离，再通过行动建立信任。",
                "content": {
                    "name": "模型不能改名",
                    "role": "在交付档案前先核验老师的来意。",
                    "knowledge_boundary": "不知道尚未披露的门禁密码。",
                    "voice_anchors": ["模型不应替换受保护的声音"],
                    "relationships": [
                        {
                            "target": "老师",
                            "kind": "谨慎合作",
                            "summary": "先核实再信任",
                            "status": "confirmed",
                        }
                    ],
                    "summary": "夜间需要双人确认后才能进入档案室。",
                    "aliases": ["夜间档案室"],
                    "trust_status": "confirmed",
                    "confidence_status": "confirmed",
                    "source_type": "official_reference",
                    "source": "模型编造的来源不得保存",
                    "source_refs": ["模型编造的引用不得保存"],
                },
            },
        }


def make_card_work(service, kind="character_card"):
    work = service.create_work({"title": "定向资料助手 · 隔离验收"})
    if kind == "character_card":
        saved = service.save_character_card(
            work["id"],
            {
                "expected_version": work["version"],
                "name": "白露",
                "source_type": "custom",
                "role": "整理档案",
                "voice_anchors": ["短句，温和但不盲从"],
                "knowledge_boundary": "只知道公开记录",
                "ooc_constraints": ["不替他人决定"],
                "source_refs": ["用户初始设定"],
                "trust_status": "open",
            },
        )
        work = saved["work"]
        artifact = next(item for item in work["artifacts"] if item["kind"] == "character_card")
        target_id = artifact["scope_id"]
        allowed = ["role", "knowledge_boundary"]
    else:
        saved = service.save_world_bible(
            work["id"],
            {
                "expected_version": work["version"],
                "title": "本作世界观",
                "source_type": "custom",
                "entities": [
                    {
                        "id": "world-archive",
                        "name": "档案室",
                        "kind": "place",
                        "summary": "普通工作间",
                        "source": "用户初始设定",
                        "source_type": "custom",
                        "confidence_status": "open",
                    }
                ],
            },
        )
        work = saved["work"]
        artifact = next(item for item in work["artifacts"] if item["kind"] == "world_bible")
        target_id = "world-archive"
        allowed = ["summary", "aliases"]
    context = {
        "schema_version": "card-assistance/1.0",
        "kind": kind,
        "target_id": target_id,
        "base_revision_id": artifact["current_revision_id"],
        "allowed_fields": allowed,
    }
    return work, context


@pytest.fixture
def service(tmp_path):
    instance = WritingService(tmp_path)
    instance.provider = CardAssistanceProvider()
    yield instance
    instance.close()


def discuss(service, work, context):
    thread = work["conversation_threads"][0]
    return service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请按选定范围整理这张卡片，其他字段保持不变。",
            "card_assistance": context,
        },
    )["work"]


def propose(service, work, context):
    thread = work["conversation_threads"][0]
    return service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": work["version"],
            "expected_thread_version": thread["version"],
            "kind": context["kind"],
            "preview_message_id": thread["messages"][-1]["id"],
        },
    )


@pytest.mark.parametrize("kind", ["character_card", "world_card"])
def test_directed_proposal_locks_identity_sources_and_fields_and_partially_accepts(service, kind):
    work, context = make_card_work(service, kind)
    original = copy.deepcopy(work["artifacts"])
    discussed = discuss(service, work, context)
    assert discussed["artifacts"] == original
    user_message = discussed["conversation_threads"][0]["messages"][-2]
    assert user_message["content"]["card_assistance"]["target_id"] == context["target_id"]
    assert (
        service.provider.contexts[-1]["card_assistance"]["base_revision_id"]
        == context["base_revision_id"]
    )
    result = propose(service, discussed, context)
    proposal = next(
        item for item in result["work"]["proposals"] if item["id"] == result["proposal_id"]
    )
    candidate = proposal["candidate"]
    from test_knowledge_proposal_normalization import assert_knowledge_contract

    assert_knowledge_contract(candidate)
    assert result["work"]["artifacts"] == original
    assert candidate["operation"] == "update"
    assert candidate["scope_id"] == context["target_id"]
    assert candidate["content"]["source_type"] == "custom"
    assert set(item["key"] for item in candidate["field_changes"]) == set(context["allowed_fields"])
    assert "模型编造" not in str(candidate["content"])
    assert candidate["content"]["name"] == ("白露" if kind == "character_card" else "档案室")
    field = context["allowed_fields"][0]
    result = service.accept_proposal(
        work["id"],
        proposal["id"],
        {
            "expected_version": result["work"]["version"],
            "selected_fields": [field],
            "expected_impact_digest": candidate["impact_preview"]["digest"],
        },
    )
    artifact = next(
        item
        for item in result["work"]["artifacts"]
        if item["kind"] == ("character_card" if kind == "character_card" else "world_bible")
    )
    content = artifact["current_revision"]["content"]
    if kind == "world_card":
        content = content["entities"][0]
        assert content["confidence_status"] == "open"
        assert content["aliases"] == []
    else:
        assert content["trust_status"] == "open"
        assert content["voice_anchors"] == ["短句，温和但不盲从"]
        assert content["knowledge_boundary"] == "只知道公开记录"
    assert content[field] == candidate["content"][field]
    assert len(artifact["revisions"]) == 2


@pytest.mark.parametrize("kind", ["character_card", "world_card"])
def test_stale_editor_target_cannot_call_model(service, kind):
    work, context = make_card_work(service, kind)
    context["base_revision_id"] = "revision-old"
    with pytest.raises(DomainError) as error:
        discuss(service, work, context)
    assert error.value.code == "card_assistance_stale"
    assert not service.provider.contexts
    assert service.get_work(work["id"])["conversation_threads"][0]["messages"] == []


def test_rejects_cross_work_targets_and_provenance_permissions(service):
    work, context = make_card_work(service)
    other = service.create_work({"title": "另一个作品"})
    with pytest.raises(DomainError) as error:
        discuss(service, other, context)
    assert error.value.code == "card_assistance_target_missing"
    context["allowed_fields"] = ["source_refs"]
    with pytest.raises(DomainError) as error:
        discuss(service, work, context)
    assert error.value.code == "validation_error"
    assert not service.provider.contexts


def test_rechecks_target_revision_between_discussion_and_proposing(service):
    work, context = make_card_work(service)
    work = discuss(service, work, context)
    current = next(item for item in work["artifacts"] if item["kind"] == "character_card")[
        "current_revision"
    ]["content"]
    saved = service.save_character_card(
        work["id"],
        {
            **current,
            "card_id": context["target_id"],
            "expected_version": work["version"],
            "role": "用户刚刚保存的新设定",
        },
    )["work"]
    with pytest.raises(DomainError) as error:
        propose(service, saved, context)
    assert error.value.code == "card_assistance_stale"
    assert service.get_work(work["id"])["proposals"] == []


def test_no_change_in_allowed_fields_does_not_create_proposal(service):
    work, context = make_card_work(service)
    context["allowed_fields"] = ["ooc_constraints"]
    work = discuss(service, work, context)
    with pytest.raises(DomainError) as error:
        propose(service, work, context)
    assert error.value.code == "card_assistance_no_changes"
    assert service.get_work(work["id"])["proposals"] == []


def test_draft_round_trips_but_unselected_unsaved_fields_are_not_saved(service):
    work, context = make_card_work(service)
    context["allowed_fields"] = ["role"]
    context["draft"] = {
        "role": "用户未保存的职责",
        "voice": "用户未保存的声音",
        "source": "尚未核对的出处",
    }
    work = discuss(service, work, context)
    assert service.provider.contexts[-1]["card_assistance"]["draft"] == context["draft"]
    result = propose(service, work, context)
    candidate = next(p for p in result["work"]["proposals"] if p["id"] == result["proposal_id"])[
        "candidate"
    ]
    assert [item["key"] for item in candidate["field_changes"]] == ["role"]
    assert candidate["content"]["voice_anchors"] == ["短句，温和但不盲从"]
    assert candidate["content"]["source_refs"] == ["用户初始设定"]
    # Pinning survives a service reload; it is not frontend-only transient state.
    with service.repo.connect() as connection:
        message = connection.execute(
            "SELECT content_json FROM conversation_messages WHERE role='user' AND thread_id=?",
            (work["conversation_threads"][0]["id"],),
        ).fetchone()
    assert json.loads(message["content_json"])["card_assistance"]["draft"] == context["draft"]


@pytest.mark.parametrize("kind", ["character_card", "world_card"])
def test_saved_identity_does_not_require_a_model_generated_title(service, monkeypatch, kind):
    work, context = make_card_work(service, kind)
    original = service.provider.discuss_work

    def missing_title(messages, work_context):
        reply = original(messages, work_context)
        reply["artifact_preview"]["title"] = "待命名世界观"
        return reply

    monkeypatch.setattr(service.provider, "discuss_work", missing_title)
    result = propose(service, discuss(service, work, context), context)
    candidate = next(p for p in result["work"]["proposals"] if p["id"] == result["proposal_id"])[
        "candidate"
    ]
    assert candidate["scope_id"] == context["target_id"]
    assert candidate["content"]["name"] == ("白露" if kind == "character_card" else "档案室")


def test_world_assistance_preserves_collection_source_and_import_metadata(service):
    work, context = make_card_work(service, "world_card")
    bible = next(a for a in work["artifacts"] if a["kind"] == "world_bible")["current_revision"][
        "content"
    ]
    bible["source_type"] = "official_reference"
    bible["entities"][0]["source_type"] = "official_reference"
    bible["import_metadata"] = {"import_id": "synthetic-import", "source_hash": "synthetic-hash"}
    saved = service.save_world_bible(work["id"], {**bible, "expected_version": work["version"]})
    context["base_revision_id"] = saved["revision_id"]
    result = propose(service, discuss(service, saved["work"], context), context)
    candidate = next(p for p in result["work"]["proposals"] if p["id"] == result["proposal_id"])[
        "candidate"
    ]
    accepted = service.accept_proposal(
        work["id"],
        result["proposal_id"],
        {
            "expected_version": result["work"]["version"],
            "selected_fields": ["summary"],
            "expected_impact_digest": candidate["impact_preview"]["digest"],
        },
    )
    content = next(a for a in accepted["work"]["artifacts"] if a["kind"] == "world_bible")[
        "current_revision"
    ]["content"]
    assert content["source_type"] == "official_reference"
    assert content["import_metadata"] == bible["import_metadata"]
    assert content["entities"][0]["source"] == "用户初始设定"


def test_invalid_world_links_are_rejected_before_creating_a_proposal(service, monkeypatch):
    work, context = make_card_work(service, "world_card")
    context["allowed_fields"] = ["related_world_ids"]
    original = service.provider.discuss_work

    def invalid_link(messages, work_context):
        reply = original(messages, work_context)
        reply["artifact_preview"]["content"]["related_world_ids"] = ["world-does-not-exist"]
        return reply

    monkeypatch.setattr(service.provider, "discuss_work", invalid_link)
    discussed = discuss(service, work, context)
    with pytest.raises(DomainError) as error:
        propose(service, discussed, context)
    assert error.value.code == "validation_error"
    assert service.get_work(work["id"])["proposals"] == []


@pytest.mark.parametrize(
    "draft", [{"role": {"unexpected": "object"}}, {"role": "x" * 60001}, {"unknown": "field"}]
)
def test_invalid_draft_is_rejected_before_calling_model(service, draft):
    work, context = make_card_work(service)
    context["draft"] = draft
    with pytest.raises(DomainError) as error:
        discuss(service, work, context)
    assert error.value.code == "validation_error"
    assert not service.provider.contexts


def test_queued_stale_context_has_actionable_error_and_does_not_create_a_job(service):
    work, context = make_card_work(service)
    context["base_revision_id"] = "revision-old"
    thread = work["conversation_threads"][0]
    with pytest.raises(DomainError) as error:
        service.enqueue_conversation_message(
            work["id"],
            thread["id"],
            {
                "expected_thread_version": thread["version"],
                "text": "调整职责",
                "card_assistance": context,
            },
        )
    assert error.value.code == "card_assistance_stale"
    assert error.value.status == 409
    with service.repo.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM agent_dispatch_jobs WHERE operation='conversation.message'"
            ).fetchone()[0]
            == 0
        )
    assert not service.provider.contexts


def test_redirect_retains_card_scope_and_invalid_redirect_does_not_cancel(service):
    import threading
    import time
    from test_agent_async import BlockingProvider, wait_for_terminal

    work, context = make_card_work(service)
    provider = BlockingProvider()
    service.provider = provider
    thread = work["conversation_threads"][0]
    queued = service.enqueue_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "先调整职责",
            "card_assistance": context,
        },
    )
    run_id = queued["agent_run_id"]
    worker = None
    try:
        assert provider.started.wait(timeout=2)
        current_thread = service.get_work(work["id"])["conversation_threads"][0]
        request = {
            "expected_thread_version": current_thread["version"],
            "text": "补充：更谨慎些",
            "idempotency_key": "card-redirect",
        }
        with pytest.raises(DomainError) as error:
            service.redirect_agent_run(
                work["id"],
                run_id,
                {
                    **request,
                    "idempotency_key": "invalid-card-redirect",
                    "card_assistance": {**context, "base_revision_id": "revision-old"},
                },
            )
        assert error.value.code == "card_assistance_stale"
        assert service.get_agent_run(work["id"], run_id)["status"] == "running"
        result = {}

        def redirect():
            try:
                result.update(
                    service.redirect_agent_run(
                        work["id"], run_id, {**request, "card_assistance": context}
                    )
                )
            except Exception as exc:
                result["error"] = exc

        worker = threading.Thread(target=redirect)
        worker.start()
        deadline = time.monotonic() + 2
        while (
            time.monotonic() < deadline
            and service.get_agent_run(work["id"], run_id)["status"] != "cancelled"
        ):
            time.sleep(0.01)
        assert service.get_agent_run(work["id"], run_id)["status"] == "cancelled"
        provider.release.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert "error" not in result, result.get("error")
        replacement = wait_for_terminal(service, work["id"], result["agent_run_id"])
        snapshot = json.loads(service.repo.read_text(replacement["input_snapshot_uri"]))
        assert snapshot["card_assistance"]["target_id"] == context["target_id"]
        assert snapshot["card_assistance"]["allowed_fields"] == context["allowed_fields"]
        messages = service.get_work(work["id"])["conversation_threads"][0]["messages"]
        redirected = next(m for m in messages if m["content"].get("redirect_of") == run_id)
        assert (
            redirected["content"]["card_assistance"]["base_revision_id"]
            == context["base_revision_id"]
        )
    finally:
        provider.release.set()
        if worker:
            worker.join(timeout=5)
