from __future__ import annotations

import base64
import threading

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class UsageProvider(FakeWritingProvider):
    is_simulation = False
    kind = "usage-test"
    display_name = "Usage test provider"

    def last_usage(self):
        return {
            "input_tokens": 120,
            "output_tokens": 40,
            "cache_read_tokens": 60,
            "cache_write_tokens": 10,
            "estimated_cost": 0.0025,
        }


class ToolFollowupProvider(FakeWritingProvider):
    is_simulation = False
    kind = "tool-followup-test"
    display_name = "Tool follow-up test provider"

    def __init__(self):
        self.contexts = []
        self._usage = {}

    def last_usage(self):
        return dict(self._usage)

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        self.contexts.append(work_context)
        if work_context.get("tool_followup"):
            self._usage = {
                "input_tokens": 30,
                "output_tokens": 20,
                "cache_read_tokens": 5,
                "cache_write_tokens": 2,
                "estimated_cost": 0.002,
            }
            return {
                "text": "已根据实际读取结果完成回复。",
                "questions": ["是否继续整理为候选？"],
                "reasoning_summary": "读取结果显示当前作品还没有正式资料。",
                "ready_for_proposal": False,
            }
        self._usage = {
            "input_tokens": 100,
            "output_tokens": 10,
            "cache_read_tokens": 20,
            "cache_write_tokens": 3,
            "estimated_cost": 0.001,
        }
        return {
            "text": "请求读取作品正式上下文。",
            "questions": [],
            "reasoning_summary": "先读取资料。",
            "ready_for_proposal": False,
            "tool_calls": [{"id": "provider-call-1", "tool": "read_work_context", "arguments": {}}],
        }


class StandardDraftToolProvider(FakeWritingProvider):
    is_simulation = False
    kind = "standard-draft-tool-test"
    display_name = "Standard draft tool test provider"

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        if work_context.get("tool_followup"):
            return {
                "text": "凯伊的人物卡讨论草稿已经准备好。",
                "questions": [],
                "reasoning_summary": "保留 Provider 工具参数中的人物名称。",
                "ready_for_proposal": False,
            }
        return {
            "text": "准备人物卡讨论草稿。",
            "questions": [],
            "reasoning_summary": "先建立讨论草稿，不写入正式人物卡。",
            "ready_for_proposal": False,
            "tool_calls": [
                {
                    "id": "draft-character-1",
                    "tool": "draft_character_card",
                    "arguments": {"name": "凯伊"},
                }
            ],
        }


class InvalidDiscussionProvider(FakeWritingProvider):
    is_simulation = False

    def __init__(self, reply):
        self.reply = reply

    def discuss_work(self, messages: list[dict], work_context: dict):
        return self.reply


class BlockingManagedDraftProvider(FakeWritingProvider):
    is_simulation = False

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def discuss_work(self, messages: list[dict], work_context: dict):
        self.started.set()
        assert self.release.wait(timeout=5)
        return {
            "text": "已形成资料草稿。",
            "questions": [],
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "canon_fact",
                "title": "作品事实",
                "status": "discussion_draft",
                "content": {"text": "旧终端从未联网。"},
            },
        }


def test_agent_usage_is_persisted_and_aggregated(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "用量记录", "idea": "先讨论一台旧终端。"})
    service.provider = UsageProvider()
    thread = work["conversation_threads"][0]

    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "继续检查终端。"},
    )
    assistant = result["work"]["conversation_threads"][0]["messages"][-1]
    assert assistant["input_tokens"] == 120
    assert assistant["output_tokens"] == 40
    assert assistant["cache_read_tokens"] == 60
    assert assistant["estimated_cost"] == pytest.approx(0.0025)

    usage = service.agent_usage(work["id"])
    assert usage["cache_hit_rate"] == pytest.approx(60 / 120, rel=1e-3)
    assert usage["estimated_cost"] == pytest.approx(0.0025)
    assert usage["cost_available"] is True


@pytest.mark.parametrize("invalid_reply", [
    {"text": ["错误类型"], "questions": [], "ready_for_proposal": False},
    {"text": "回复", "questions": "不是数组", "ready_for_proposal": False},
    {"text": "回复", "questions": [], "ready_for_proposal": "yes"},
    {"text": "回复", "questions": [], "artifact_preview": {"kind": "unknown"}},
])
def test_invalid_discussion_provider_output_is_persisted_as_failure(tmp_path, invalid_reply):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "讨论输出校验", "idea": "先讨论旧终端。"})
    service.provider = InvalidDiscussionProvider(invalid_reply)
    thread = work["conversation_threads"][0]

    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "继续讨论。"},
        )
    assert failed.value.code == "agent_failed"
    assert failed.value.details["failure"]["code"] == "provider_output_invalid"

    restored = service.get_work(work["id"])
    run = next(item for item in restored["agent_runs"] if item["id"] == failed.value.details["agent_run_id"])
    assert run["status"] == "failed"
    assert run["failure"]["code"] == "provider_output_invalid"
    assert not restored["proposals"]


def test_managed_agent_run_stops_when_permission_is_downgraded_mid_run(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({
        "title": "运行中降权", "idea": "调查旧终端。", "permission_mode": "managed"
    })
    thread = work["conversation_threads"][0]
    provider = BlockingManagedDraftProvider()
    service.provider = provider
    holder = {}

    def run_turn():
        try:
            holder["result"] = service.post_conversation_message(
                work["id"], thread["id"],
                {"expected_thread_version": thread["version"], "text": "整理成事实。"},
            )
        except Exception as exc:
            holder["error"] = exc

    worker = threading.Thread(target=run_turn)
    worker.start()
    assert provider.started.wait(timeout=5)
    running = service.get_work(work["id"])
    current_thread = running["conversation_threads"][0]
    service.update_conversation_settings(
        work["id"], thread["id"],
        {"expected_thread_version": current_thread["version"], "permission_mode": "review", "phase": "discuss"},
    )
    provider.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert isinstance(holder.get("error"), DomainError)
    assert holder["error"].code == "agent_authorization_changed"
    restored = service.get_work(work["id"])
    run = next(item for item in restored["agent_runs"] if item["instruction"] == "整理成事实。")
    assert run["status"] == "cancelled"
    assert run["failure"]["code"] == "agent_authorization_changed"
    assert not restored["proposals"]
    assert not any(message["agent_run_id"] == run["id"] and message["role"] == "assistant"
                   for message in restored["conversation_threads"][0]["messages"])


def test_provider_tool_call_is_dispatched_then_followed_up_in_one_agent_run(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "工具回传", "idea": "先讨论一台旧终端。"})
    provider = ToolFollowupProvider()
    service.provider = provider
    thread = work["conversation_threads"][0]

    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "先检查已有资料再回答。"},
    )

    assert len(provider.contexts) == 2
    assert provider.contexts[0].get("tool_followup") is None
    followup_context = provider.contexts[1]
    assert followup_context["tool_followup"] is True
    assert followup_context["tool_results"] == [{
        "id": "provider-call-1",
        "tool": "read_work_context",
        "status": "succeeded",
        "output": {"artifacts": []},
        "error": None,
    }]

    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"])
    assert run["status"] == "completed"
    assert run["policy"]["usage"] == {
        "input_tokens": 130,
        "output_tokens": 30,
        "cache_read_tokens": 25,
        "cache_write_tokens": 5,
        "estimated_cost": pytest.approx(0.003),
    }
    assert [(item["tool_name"], item["status"]) for item in run["tool_calls"]] == [
        ("read_work_context", "succeeded")
    ]

    current_thread = result["work"]["conversation_threads"][0]
    assistant = current_thread["messages"][-1]
    assert assistant["content"]["text"] == "已根据实际读取结果完成回复。"
    assert assistant["content"]["tool_results"] == followup_context["tool_results"]
    assert assistant["agent_run_id"] == result["agent_run_id"]
    assert assistant["input_tokens"] == 130
    assert assistant["output_tokens"] == 30
    assert assistant["cache_read_tokens"] == 25
    assert assistant["cache_write_tokens"] == 5
    assert assistant["estimated_cost"] == pytest.approx(0.003)


def test_standard_draft_tool_arguments_are_not_overwritten_by_empty_preview(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "标准工具参数"})
    service.provider = StandardDraftToolProvider()
    thread = work["conversation_threads"][0]

    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "请讨论凯伊的人物卡。"},
    )

    assistant = result["work"]["conversation_threads"][0]["messages"][-1]
    preview = assistant["content"]["artifact_preview"]
    assert preview["title"] == "凯伊"
    assert preview["content"]["name"] == "凯伊"
    run = next(
        item for item in result["work"]["agent_runs"]
        if item["id"] == result["agent_run_id"]
    )
    draft_call = next(item for item in run["tool_calls"] if item["tool_name"] == "draft_character_card")
    assert draft_call["status"] == "succeeded"


def test_managed_agent_turn_budget_is_enforced_by_backend(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "授权预算", "idea": "讨论开场。", "permission_mode": "managed"})
    thread = work["conversation_threads"][0]
    with service.repo.connect() as connection:
        connection.execute("UPDATE authorization_policies SET max_turns=1 WHERE thread_id=?", (thread["id"],))
        connection.commit()

    with pytest.raises(DomainError) as blocked:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "超出授权轮次。"},
        )
    assert blocked.value.code == "agent_turn_budget_exceeded"
    assert blocked.value.status == 429


@pytest.mark.parametrize(
    ("policy_update", "expected_code"),
    [
        ({"allowed_actions_json": '["read"]'}, "agent_action_denied"),
        ({"expires_at": "2020-01-01T00:00:00+00:00"}, "agent_policy_expired"),
        ({"max_cost": 0.0}, "agent_cost_budget_exceeded"),
    ],
)
def test_agent_authorization_policy_blocks_before_provider_call(
    tmp_path, policy_update, expected_code,
):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "授权边界"})
    thread = work["conversation_threads"][0]
    assignments = ",".join(f"{field}=?" for field in policy_update)
    with service.repo.connect() as connection:
        connection.execute(
            f"UPDATE authorization_policies SET {assignments} WHERE thread_id=?",
            [*policy_update.values(), thread["id"]],
        )
        connection.commit()

    called = False

    def should_not_run(_messages, _context):
        nonlocal called
        called = True
        return {}

    service.provider.discuss_work = should_not_run
    with pytest.raises(DomainError) as blocked:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "继续讨论。"},
        )
    assert blocked.value.code == expected_code
    assert called is False


def test_archived_thread_rejects_agent_turn(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "归档边界"})
    thread = work["conversation_threads"][0]
    archived = service.update_conversation_thread(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "status": "archived"},
    )
    archived_thread = archived["work"]["conversation_threads"][0]

    with pytest.raises(DomainError) as blocked:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": archived_thread["version"], "text": "继续讨论。"},
        )
    assert blocked.value.code == "agent_thread_archived"


def test_retry_reuses_failed_turn_without_consuming_another_turn(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "重试轮次", "permission_mode": "managed"})
    thread = work["conversation_threads"][0]
    with service.repo.connect() as connection:
        connection.execute(
            "UPDATE authorization_policies SET max_turns=1 WHERE thread_id=?",
            (thread["id"],),
        )
        connection.commit()

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "网络失败。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "只运行这一轮。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    restored = service.get_work(work["id"])
    current_thread = restored["conversation_threads"][0]
    user_count = sum(message["role"] == "user" for message in current_thread["messages"])

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work["id"], failed_run_id,
        {"expected_thread_version": current_thread["version"]},
    )
    retried_thread = retried["work"]["conversation_threads"][0]
    assert sum(message["role"] == "user" for message in retried_thread["messages"]) == user_count
    retried_run = next(
        item for item in retried["work"]["agent_runs"]
        if item["id"] == retried["agent_run_id"]
    )
    assert retried_run["policy"]["retry_of"] == failed_run_id


def test_managed_mode_auto_creates_proposal_but_never_accepts_it(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "托管资料", "idea": "调查旧校舍。", "permission_mode": "managed"})
    thread = work["conversation_threads"][0]
    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "请创建《旧校舍》的地点设定：午夜后广播才会工作。"},
    )
    assert result["auto_proposal_id"]
    proposal = next(item for item in result["work"]["proposals"] if item["id"] == result["auto_proposal_id"])
    assert proposal["status"] == "pending"
    assert not any(item["kind"] == "world_bible" for item in result["work"]["artifacts"])


def test_failed_agent_run_can_retry_from_persisted_instruction(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Agent 重试", "idea": "讨论广播来源。"})
    thread = work["conversation_threads"][0]

    def fail_discussion(messages, context):
        raise DomainError("writing_provider_failed", "网络失败。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "检查广播来源。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    restored = service.get_work(work["id"])
    current_thread = restored["conversation_threads"][0]
    message_count_before_retry = len(current_thread["messages"])

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work["id"], failed_run_id,
        {"expected_thread_version": current_thread["version"]},
    )
    assert retried["retried_from_agent_run_id"] == failed_run_id
    assert retried["agent_run_id"] != failed_run_id
    retried_thread = retried["work"]["conversation_threads"][0]
    assert len(retried_thread["messages"]) == message_count_before_retry + 1
    retried_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert retried_run["policy"]["retry_of"] == failed_run_id


def test_failed_agent_run_with_missing_snapshot_returns_stable_integrity_error(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "缺失重试快照", "idea": "讨论广播来源。"})
    thread = work["conversation_threads"][0]

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "网络失败。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "检查广播来源。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    restored = service.get_work(work["id"])
    failed_run = next(item for item in restored["agent_runs"] if item["id"] == failed_run_id)
    (service.repo.data_dir / failed_run["input_snapshot_uri"]).unlink()
    current_thread = restored["conversation_threads"][0]

    with pytest.raises(DomainError) as rejected:
        service.retry_agent_run(
            work["id"], failed_run_id,
            {"expected_thread_version": current_thread["version"]},
        )

    assert rejected.value.code == "agent_snapshot_integrity_failed"
    assert rejected.value.details == {"agent_run_id": failed_run_id}
    assert len(service.get_work(work["id"])["agent_runs"]) == len(restored["agent_runs"])


def test_duplicate_canon_fact_is_flagged_and_cannot_be_accepted(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "事实冲突", "idea": "调查一台旧终端。"})
    saved = service.save_work_canon(
        work["id"],
        {"expected_version": work["version"], "facts": [{"id": "fact-existing", "text": "旧终端从未连接校内网络。", "source": "用户设定", "confidence_status": "confirmed"}]},
    )
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "请记录事实：旧终端从未连接校内网络。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "canon_fact",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["risk"] == "high"
    assert proposal["candidate"]["conflicts"][0]["kind"] == "duplicate_canon_fact"

    with pytest.raises(DomainError) as conflict:
        service.accept_proposal(
            work["id"], proposal["id"], {
                "expected_version": proposed["work"]["version"],
                "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            }
        )
    assert conflict.value.code == "knowledge_conflict"


def test_agent_updates_existing_character_card_through_a_revision_proposal(tmp_path):
    class CharacterUpdateProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "我整理了一份凯伊的人物卡更新草稿。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "character_card",
                    "title": "凯伊",
                    "status": "discussion_draft",
                    "content": {
                        "name": "凯伊",
                        "knowledge_boundary": "已经知道旧终端只在午夜后响应。",
                        "ooc_constraints": ["不会在证据不足时断定异常来自敌对行为。"],
                    },
                },
                "tool_activity": [
                    {"tool": "draft_character_card", "label": "生成人物卡更新草稿", "status": "succeeded"}
                ],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物持续维护"})
    saved = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": "负责判断调查风险。",
            "source_type": "custom",
            "source_refs": ["用户初始设定"],
            "trust_status": "confirmed",
        },
    )
    service.provider = CharacterUpdateProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "更新凯伊：她已经确认终端的午夜响应规律。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["candidate"]["operation"] == "update"
    assert proposal["candidate"]["scope_id"] == "character-kei"
    assert proposal["candidate"]["base_revision_id"] == saved["revision_id"]
    assert proposal["candidate"]["conflicts"][0]["blocking"] is False
    changes = {item["field"]: item for item in proposal["candidate"]["field_changes"]}
    assert proposal["candidate"]["schema_version"] == "conversation-knowledge-proposal/1.2"
    assert changes["知情边界"] == {
        "field": "知情边界", "key": "knowledge_boundary", "before": "",
        "after": "已经知道旧终端只在午夜后响应。",
    }
    assert proposal["diff"]["format"] == "knowledge-fields/1.2"
    assert proposal["diff"]["changes"] == proposal["candidate"]["field_changes"]

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    cards = [item for item in accepted["work"]["artifacts"] if item["kind"] == "character_card"]
    assert len(cards) == 1
    assert cards[0]["scope_id"] == "character-kei"
    assert len(cards[0]["revisions"]) == 2
    content = cards[0]["current_revision"]["content"]
    assert content["role"] == "负责判断调查风险。"
    assert content["knowledge_boundary"] == "已经知道旧终端只在午夜后响应。"
    assert content["source_refs"] == ["用户初始设定", f"作品主对话 {thread['id']}"]


def test_agent_can_partially_accept_selected_character_update_fields(tmp_path):
    class PartialCharacterProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "我整理了凯伊的两项人物卡更新。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "character_card", "title": "凯伊", "status": "discussion_draft",
                    "content": {
                        "name": "凯伊",
                        "role": "负责判断调查风险，并在证据不足时先停下来。",
                        "knowledge_boundary": "知道旧终端会保存最后一次访问日志。",
                    },
                },
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物部分采纳"})
    saved = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"], "card_id": "character-kei", "name": "凯伊",
            "role": "负责判断调查风险。", "source_type": "custom", "source_refs": ["用户初始设定"],
            "trust_status": "confirmed",
        },
    )
    service.provider = PartialCharacterProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "讨论凯伊的知情边界和职责。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    selected = next(item for item in proposal["candidate"]["field_changes"] if item["key"] == "knowledge_boundary")
    accepted = service.accept_proposal(
        work["id"], proposal["id"],
        {
            "expected_version": proposed["work"]["version"],
            "selected_fields": ["knowledge_boundary"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            "note": "只采用知情边界",
        },
    )
    card = next(item for item in accepted["work"]["artifacts"] if item["scope_id"] == "character-kei")
    content = card["current_revision"]["content"]
    assert content["knowledge_boundary"] == selected["after"]
    assert content["role"] == "负责判断调查风险。"
    assert card["current_revision"]["provenance"]["partial_accept"] is True
    assert card["current_revision"]["provenance"]["applied_fields"] == ["knowledge_boundary"]


def test_document_citations_follow_canon_proposal_into_formal_provenance(tmp_path):
    class DocumentFactProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "文档中有一条可整理的作品事实。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "canon_fact",
                    "title": "作品事实",
                    "status": "discussion_draft",
                    "content": {"text": "旧终端只在午夜后响应。"},
                },
                "tool_activity": [
                    {"tool": "draft_canon_fact", "label": "生成作品事实草稿", "status": "succeeded"}
                ],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "文档事实来源"})
    thread = work["conversation_threads"][0]
    document = "# 终端规则\n\n旧终端只在午夜后响应。\n".encode("utf-8")
    uploaded = service.create_conversation_attachment(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "filename": "terminal-rules.md",
            "media_type": "text/markdown",
            "content_base64": base64.b64encode(document).decode("ascii"),
        },
    )
    uploaded_thread = uploaded["work"]["conversation_threads"][0]
    attachment = uploaded_thread["attachments"][0]
    service.provider = DocumentFactProvider()
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "把旧终端的响应时间整理成事实候选，并保留文档来源。",
            "attachment_ids": [attachment["id"]],
        },
    )
    assistant = discussed["work"]["conversation_threads"][0]["messages"][-1]["content"]
    assert assistant["artifact_preview"]["sources"][0]["filename"] == "terminal-rules.md"

    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "canon_fact",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["evidence"]["document_citations"][0]["chunk_id"].startswith(attachment["id"])
    assert proposal["candidate"]["content"]["source_refs"][0]["filename"] == "terminal-rules.md"

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    canon = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "work_canon")
    fact = canon["current_revision"]["content"]["facts"][0]
    assert "terminal-rules.md" in fact["source"]
    assert fact["source_refs"][0]["paragraph_ids"]
    assert canon["current_revision"]["provenance"]["document_citations"][0]["filename"] == "terminal-rules.md"

    restored = WritingService(tmp_path).get_work(work["id"])
    restored_proposal = next(item for item in restored["proposals"] if item["id"] == proposal["id"])
    restored_canon = next(item for item in restored["artifacts"] if item["kind"] == "work_canon")
    assert restored_proposal["evidence"]["document_citations"] == proposal["evidence"]["document_citations"]
    assert restored_proposal["candidate"]["document_citations"] == proposal["candidate"]["document_citations"]
    assert restored_canon["current_revision"]["provenance"]["document_citations"] == proposal["evidence"]["document_citations"]


def test_agent_updates_existing_world_entity_without_duplicating_its_stable_id(tmp_path):
    class WorldUpdateProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "我整理了旧终端世界观条目的更新草稿。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "world_card",
                    "title": "旧终端",
                    "status": "discussion_draft",
                    "content": {
                        "name": "旧终端",
                        "summary": "只在午夜后响应，并保留最后一次访问日志。",
                    },
                },
                "tool_activity": [
                    {"tool": "draft_world_card", "label": "生成世界观更新草稿", "status": "succeeded"}
                ],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观持续维护"})
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
                    "source": "用户初始设定",
                    "confidence_status": "confirmed",
                }
            ],
        },
    )
    service.provider = WorldUpdateProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "补充旧终端会保存最后一次访问日志。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "world_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["candidate"]["operation"] == "update"
    assert proposal["candidate"]["scope_id"] == "world-terminal"

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    bible = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "world_bible")
    entities = bible["current_revision"]["content"]["entities"]
    assert len(entities) == 1
    assert entities[0]["id"] == "world-terminal"
    assert entities[0]["kind"] == "technology"
    assert entities[0]["summary"] == "只在午夜后响应，并保留最后一次访问日志。"


def test_multiple_character_alias_matches_remain_blocking_until_target_is_chosen(tmp_path):
    class AmbiguousCharacterProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "这个别名同时命中了两张人物卡，需要先选择目标。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "character_card",
                    "title": "小雪",
                    "status": "discussion_draft",
                    "content": {"name": "小雪", "knowledge_boundary": "知道终端的响应时间。"},
                },
                "tool_activity": [
                    {"tool": "draft_character_card", "label": "生成人物卡更新草稿", "status": "succeeded"}
                ],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "别名歧义"})
    first = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-snow-a",
            "name": "白雪",
            "aliases": ["小雪"],
            "source_type": "custom",
            "source_refs": ["用户设定 A"],
            "trust_status": "confirmed",
        },
    )
    second = service.save_character_card(
        work["id"],
        {
            "expected_version": first["work"]["version"],
            "card_id": "character-snow-b",
            "name": "雪乃",
            "aliases": ["小雪"],
            "source_type": "custom",
            "source_refs": ["用户设定 B"],
            "trust_status": "confirmed",
        },
    )
    service.provider = AmbiguousCharacterProvider()
    thread = second["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "更新小雪的知情边界。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["risk"] == "high"
    assert {item["existing_id"] for item in proposal["candidate"]["conflicts"]} == {
        "character-snow-a", "character-snow-b",
    }
    assert all(item["blocking"] is True for item in proposal["candidate"]["conflicts"])
    assert all(item["resolution"] == "choose_existing_target" for item in proposal["candidate"]["conflicts"])

    with pytest.raises(DomainError) as conflict:
        service.accept_proposal(
            work["id"], proposal["id"], {
                "expected_version": proposed["work"]["version"],
                "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            }
        )
    assert conflict.value.code == "knowledge_conflict"


def test_character_update_does_not_erase_existing_fields_with_empty_values(tmp_path):
    class SparseCharacterUpdateProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "只补充知情边界，其余空字段不代表删除。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "character_card",
                    "title": "凯伊",
                    "status": "discussion_draft",
                    "content": {
                        "name": "凯伊",
                        "role": "",
                        "voice_anchors": [],
                        "relationships": [],
                        "knowledge_boundary": "已经知道旧终端只在午夜后响应。",
                    },
                },
                "tool_activity": [
                    {"tool": "draft_character_card", "label": "生成人物卡增量更新", "status": "succeeded"}
                ],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物增量合并"})
    saved = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": "负责判断调查风险。",
            "voice_anchors": ["结论简短，先给行动建议。"],
            "relationships": [{"target": "爱丽丝", "kind": "同伴", "summary": "共同调查终端。"}],
            "source_type": "custom",
            "source_refs": ["用户初始设定"],
            "trust_status": "confirmed",
        },
    )
    service.provider = SparseCharacterUpdateProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "补充凯伊当前知道的终端规律。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    candidate = proposal["candidate"]["content"]
    assert candidate["role"] == "负责判断调查风险。"
    assert candidate["voice_anchors"] == ["结论简短，先给行动建议。"]
    assert candidate["relationships"][0]["target"] == "爱丽丝"

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    card = next(item for item in accepted["work"]["artifacts"] if item["scope_id"] == "character-kei")
    content = card["current_revision"]["content"]
    assert content["role"] == "负责判断调查风险。"
    assert content["voice_anchors"] == ["结论简短，先给行动建议。"]
    assert content["relationships"][0]["target"] == "爱丽丝"
    assert content["knowledge_boundary"] == "已经知道旧终端只在午夜后响应。"


def test_character_update_proposal_is_superseded_by_a_newer_card_revision(tmp_path):
    class CharacterUpdateProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "形成凯伊的更新草稿。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "character_card",
                    "title": "凯伊",
                    "status": "discussion_draft",
                    "content": {"name": "凯伊", "knowledge_boundary": "知道午夜响应规律。"},
                },
                "tool_activity": [{"tool": "draft_character_card", "status": "succeeded"}],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物并发修订"})
    saved = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"], "card_id": "character-kei", "name": "凯伊",
            "role": "调查风险。", "source_type": "custom", "source_refs": ["初始设定"],
            "trust_status": "confirmed",
        },
    )
    service.provider = CharacterUpdateProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "补充凯伊的知情边界。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    newer = service.save_character_card(
        work["id"],
        {
            "expected_version": proposed["work"]["version"], "card_id": "character-kei", "name": "凯伊",
            "role": "已经由用户改为现场指挥。", "source_type": "custom", "source_refs": ["用户并发修订"],
            "trust_status": "confirmed",
        },
    )

    with pytest.raises(DomainError) as superseded:
        service.accept_proposal(
            work["id"], proposal["id"], {
                "expected_version": newer["work"]["version"],
                "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            }
        )
    assert superseded.value.code == "proposal_superseded"
    restored = service.get_work(work["id"])
    assert next(item for item in restored["proposals"] if item["id"] == proposal["id"])["status"] == "superseded"


def test_world_update_proposal_is_superseded_by_a_newer_world_revision(tmp_path):
    class WorldUpdateProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "形成旧终端的更新草稿。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "world_card",
                    "title": "旧终端",
                    "status": "discussion_draft",
                    "content": {"name": "旧终端", "summary": "午夜后响应并保存日志。"},
                },
                "tool_activity": [{"tool": "draft_world_card", "status": "succeeded"}],
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观并发修订"})
    original_entity = {
        "id": "world-terminal", "name": "旧终端", "kind": "technology",
        "summary": "只在午夜后响应。", "source": "初始设定", "confidence_status": "confirmed",
    }
    saved = service.save_world_bible(
        work["id"],
        {"expected_version": work["version"], "title": "本作世界观", "source_type": "custom", "entities": [original_entity]},
    )
    service.provider = WorldUpdateProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "补充旧终端保存日志。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "world_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    newer = service.save_world_bible(
        work["id"],
        {
            "expected_version": proposed["work"]["version"], "title": "本作世界观", "source_type": "custom",
            "entities": [{**original_entity, "summary": "用户已改为黄昏后响应。", "source": "用户并发修订"}],
        },
    )

    with pytest.raises(DomainError) as superseded:
        service.accept_proposal(
            work["id"], proposal["id"], {
                "expected_version": newer["work"]["version"],
                "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            }
        )
    assert superseded.value.code == "proposal_superseded"
    restored = service.get_work(work["id"])
    assert next(item for item in restored["proposals"] if item["id"] == proposal["id"])["status"] == "superseded"


def test_second_service_does_not_reclassify_unleased_agent_run(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "重启恢复"})
    snapshot_uri, digest = service.repo.atomic_write_text(
        "agent-runs/agent-interrupted/input.json", '{"schema_version":"conversation-agent-input/1.0"}\n'
    )
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "agent-interrupted", work["id"], "work", work["id"], "继续讨论",
                "running", "{}", snapshot_uri, digest, None, None,
                "2026-08-15T00:00:00+00:00", None,
            ),
        )

    restored = WritingService(tmp_path).get_work(work["id"])
    run = next(item for item in restored["agent_runs"] if item["id"] == "agent-interrupted")
    assert run["status"] == "running"
    assert run["failure"] is None
