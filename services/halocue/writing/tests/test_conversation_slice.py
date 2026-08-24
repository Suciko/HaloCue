import base64
import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


PNG_1X1 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
).decode("ascii")


class ReasoningProvider(FakeWritingProvider):
    is_simulation = False
    display_name = "Reasoning Test Provider"

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        reply = super().discuss_work(messages, work_context)
        reply["reasoning_summary"] = "先核对当前任务范围，再判断是否需要继续追问。"
        reply["reasoning_content"] = "检查任务合同。\n读取正式上下文。\n决定本轮只继续讨论。"
        return reply


class InvalidChapterPlanProvider(FakeWritingProvider):
    def generate_chapter_plan(self, messages: list[dict], chapter_context: dict) -> dict:
        return {"title": "缺少目标与节拍"}


class InvalidBlueprintProvider(FakeWritingProvider):
    def generate_blueprint(self, brief: dict, analysis_context: dict | None = None) -> dict:
        return {"title": "只有标题"}


class InvalidStructureProvider(FakeWritingProvider):
    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict:
        return {
            "schema_version": "story-structure-plan/1.0",
            "volumes": [
                {
                    "title": "第一卷",
                    "purpose": "建立冲突",
                    "chapters": [
                        {
                            "title": "第一章",
                            "goal": "找到线索",
                            "scenes": [{"title": "缺少边界", "goal": "找到录音"}],
                        }
                    ],
                }
            ],
        }


class ExplodingStructureProvider(FakeWritingProvider):
    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict:
        raise RuntimeError("provider socket closed")


class ConcurrentStructureProvider(FakeWritingProvider):
    def __init__(self, callback):
        self.callback = callback

    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict:
        self.callback()
        return super().generate_structure_plan(messages, structure_context)


class SummaryCaptureProvider(FakeWritingProvider):
    def __init__(self):
        self.summary = None

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        self.summary = work_context.get("conversation_summary")
        return super().discuss_work(messages, work_context)


class DecisionCardProvider(FakeWritingProvider):
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        return {
            "text": "我们先选定推进方向。",
            "questions": [],
            "ready_for_proposal": False,
            "decision_card": {
                "kind": "choose",
                "title": "下一步先确定哪一项？",
                "options": [
                    {"id": "direction_a", "label": "先定人物关系", "description": "先固定两人的关系变化。"},
                    {"id": "direction_b", "label": "先定开场事件", "description": "先固定第一幕发生的事件。"},
                ],
                "submit_label": "提交选择",
                "allow_custom": True,
            },
        }


def accepted_blueprint_from_conversation(service: WritingService, title: str = "结构纵切"):
    work = service.create_work({"title": title, "idea": "两位学生在夜间校舍寻找一段失落的录音。"})
    thread = work["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {"expected_version": work["version"], "expected_thread_version": thread["version"]},
    )
    accepted = service.accept_proposal(
        work["id"], proposed["proposal_id"], {"expected_version": proposed["work"]["version"]}
    )
    return accepted["work"]


def test_long_conversation_summary_is_durable_traceable_and_injected(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "长对话摘要"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        for index in range(18):
            service._append_conversation_message(
                connection,
                thread["id"],
                "user" if index % 2 == 0 else "assistant",
                "text",
                {"text": f"第 {index + 1} 条需要长期保留的讨论约束"},
            )

    restored = WritingService(tmp_path).get_work(work["id"])
    restored_thread = restored["conversation_threads"][0]
    summary = restored_thread["summary"]
    assert len(restored_thread["messages"]) == 18
    assert restored_thread["archived_message_count"] == 6
    assert summary["schema_version"] == "conversation-summary/1.1"
    assert summary["trust"]["formal_fact"] is False
    assert summary["trust"]["proposal_evidence_allowed"] is False
    assert summary["through_ordinal"] == 6
    assert summary["source_message_ids"]
    assert all(item["message_id"] in summary["source_message_ids"] for item in summary["excerpts"])
    assert "第 1 条需要长期保留的讨论约束" in summary["text"]

    provider = SummaryCaptureProvider()
    service.provider = provider
    result = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": restored_thread["version"], "text": "继续讨论，并保留前面的约束。"},
    )
    assert provider.summary["archived_message_count"] == 7
    assert provider.summary["source_message_ids"]
    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["conversation_summary"]["digest"] == provider.summary["digest"]
    assert len(snapshot["history"]) <= 12


def test_long_conversation_correction_supersedes_archived_constraint(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "反悔覆盖"})
    thread = work["conversation_threads"][0]
    old_message_id = None
    correction_message_id = None
    with service.repo.transaction() as connection:
        for index in range(32):
            if index == 2:
                text = "主要角色采用爱丽丝。"
            elif index == 14:
                text = "更正：不再采用爱丽丝，主要角色改为凯伊。"
            else:
                text = f"讨论记录 {index + 1}"
            message_id = service._append_conversation_message(
                connection, thread["id"], "user", "text", {"text": text}
            )
            if index == 2:
                old_message_id = message_id
            elif index == 14:
                correction_message_id = message_id

    restored = WritingService(tmp_path).get_work(work["id"])
    summary = restored["conversation_threads"][0]["summary"]
    correction = next(
        item for item in summary["corrections_and_rejections"]
        if correction_message_id in item["source_message_ids"]
    )
    assert old_message_id in correction["supersedes_message_ids"]
    assert all(
        old_message_id not in item["source_message_ids"]
        for item in summary["active_user_constraints"]
    )
    assert any(
        correction_message_id in item["source_message_ids"]
        for item in summary["active_user_constraints"]
    )


def test_corrupted_archived_summary_source_is_not_injected(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "摘要完整性"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        for index in range(18):
            service._append_conversation_message(
                connection, thread["id"], "user", "text", {"text": f"约束 {index + 1}"}
            )
    restored_thread = WritingService(tmp_path).get_work(work["id"])["conversation_threads"][0]
    source_id = restored_thread["summary"]["source_message_ids"][0]
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE conversation_messages SET content_json=? WHERE id=?",
            (json.dumps({"text": "被篡改的归档消息"}, ensure_ascii=False), source_id),
        )

    provider = SummaryCaptureProvider()
    service.provider = provider
    with pytest.raises(DomainError) as error:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": restored_thread["version"], "text": "继续讨论。"},
        )
    assert error.value.code == "conversation_summary_integrity_failed"
    assert provider.summary is None
    assert len(service.get_work(work["id"])["conversation_threads"][0]["messages"]) == 18


def test_retry_uses_fixed_summary_from_agent_run_snapshot(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "摘要固定重试"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        for index in range(20):
            service._append_conversation_message(
                connection, thread["id"], "user", "text", {"text": f"原始讨论 {index + 1}"}
            )

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "网络失败。", status=502)

    service.provider.discuss_work = fail_discussion
    restored_thread = service.get_work(work["id"])["conversation_threads"][0]
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": restored_thread["version"], "text": "固定这一轮输入。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    failed_work = service.get_work(work["id"])
    failed_thread = failed_work["conversation_threads"][0]
    failed_run = next(item for item in failed_work["agent_runs"] if item["id"] == failed_run_id)
    failed_snapshot = json.loads(service.repo.read_text(failed_run["input_snapshot_uri"]))
    fixed_digest = failed_snapshot["conversation_summary"]["digest"]

    with service.repo.transaction() as connection:
        for index in range(5):
            service._append_conversation_message(
                connection, thread["id"], "user", "text", {"text": f"失败后的新讨论 {index + 1}"}
            )
    assert service.get_work(work["id"])["conversation_threads"][0]["summary"]["digest"] != fixed_digest

    provider = SummaryCaptureProvider()
    service.provider = provider
    service.retry_agent_run(
        work["id"], failed_run_id,
        {"expected_thread_version": failed_thread["version"]},
    )
    assert provider.summary["digest"] == fixed_digest


def test_retry_rejects_fixed_summary_when_an_original_source_message_was_tampered(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "摘要来源损坏后拒绝重试"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        for index in range(20):
            service._append_conversation_message(
                connection, thread["id"], "user", "text", {"text": f"固定讨论 {index + 1}"}
            )

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "网络失败。", status=502)

    service.provider.discuss_work = fail_discussion
    current_thread = service.get_work(work["id"])["conversation_threads"][0]
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": current_thread["version"], "text": "固定这一轮输入。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    failed_work = service.get_work(work["id"])
    failed_thread = failed_work["conversation_threads"][0]
    failed_run = next(item for item in failed_work["agent_runs"] if item["id"] == failed_run_id)
    snapshot = json.loads(service.repo.read_text(failed_run["input_snapshot_uri"]))
    source_id = snapshot["conversation_summary"]["source_message_ids"][0]
    with service.repo.transaction() as connection:
        connection.execute(
            "UPDATE conversation_messages SET content_json=? WHERE id=?",
            (json.dumps({"text": "被篡改的原始归档消息"}, ensure_ascii=False), source_id),
        )

    provider = SummaryCaptureProvider()
    service.provider = provider
    run_count = len(failed_work["agent_runs"])
    with pytest.raises(DomainError) as rejected:
        service.retry_agent_run(
            work["id"], failed_run_id,
            {"expected_thread_version": failed_thread["version"]},
        )

    assert rejected.value.code == "conversation_summary_integrity_failed"
    assert provider.summary is None
    assert len(service.get_work(work["id"])["agent_runs"]) == run_count


def test_thousand_message_summary_stays_bounded_and_reports_overflow(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "千轮摘要"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        for index in range(1000):
            service._append_conversation_message(
                connection,
                thread["id"],
                "user" if index % 2 == 0 else "assistant",
                "text",
                {"text": f"长期讨论消息 {index + 1}"},
            )

    summary = service.get_work(work["id"])["conversation_threads"][0]["summary"]
    assert summary["archived_message_count"] == 988
    assert summary["source"]["message_count"] == 988
    assert summary["revision"] == 988
    assert len(summary["active_user_constraints"]) <= 48
    assert len(summary["excerpts"]) <= 16
    assert summary["overflowed_user_context_count"] > 0
    assert "必须回查原始消息" in summary["continuation_note"]
    assert len(json.dumps(summary, ensure_ascii=False)) < 100_000


def test_work_supports_multiple_durable_conversations_with_rename_and_archive(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "多会话作品", "idea": "先讨论整体方向。"})

    created = service.create_conversation_thread(
        work["id"],
        {"expected_version": work["version"], "title": "人物关系讨论", "scope_type": "work"},
    )
    assert len(created["work"]["conversation_threads"]) == 2
    new_thread = next(item for item in created["work"]["conversation_threads"] if item["id"] == created["thread_id"])
    assert new_thread["messages"][0]["kind"] == "notice"

    renamed = service.update_conversation_thread(
        work["id"], new_thread["id"],
        {"expected_thread_version": new_thread["version"], "title": "凯伊关系线", "status": "active"},
    )
    renamed_thread = next(item for item in renamed["work"]["conversation_threads"] if item["id"] == new_thread["id"])
    archived = service.update_conversation_thread(
        work["id"], renamed_thread["id"],
        {"expected_thread_version": renamed_thread["version"], "status": "archived"},
    )

    restored = WritingService(tmp_path).get_work(work["id"])
    restored_thread = next(item for item in restored["conversation_threads"] if item["id"] == new_thread["id"])
    assert restored_thread["title"] == "凯伊关系线"
    assert restored_thread["status"] == "archived"
    assert next(item for item in archived["work"]["authorization_policies"] if item["thread_id"] == new_thread["id"])["status"] == "archived"

    reopened = service.update_conversation_thread(
        work["id"], restored_thread["id"],
        {"expected_thread_version": restored_thread["version"], "status": "active"},
    )
    reopened_thread = next(item for item in reopened["work"]["conversation_threads"] if item["id"] == new_thread["id"])
    assert reopened_thread["status"] == "active"
    assert next(item for item in reopened["work"]["authorization_policies"] if item["thread_id"] == new_thread["id"])["status"] == "active"


def test_archived_conversation_index_searches_across_works(tmp_path):
    service = WritingService(tmp_path)
    first = service.create_work({"title": "第一部作品"})
    second = service.create_work({"title": "午夜机器"})
    first_thread = first["conversation_threads"][0]
    second_thread = second["conversation_threads"][0]

    service.update_conversation_thread(
        first["id"],
        first_thread["id"],
        {"expected_thread_version": first_thread["version"], "title": "人物讨论", "status": "archived"},
    )
    service.update_conversation_thread(
        second["id"],
        second_thread["id"],
        {"expected_thread_version": second_thread["version"], "title": "旧广播线索", "status": "archived"},
    )

    archived = service.list_archived_conversations()
    assert {item["work_title"] for item in archived} == {"第一部作品", "午夜机器"}
    assert all(item["message_count"] == 0 for item in archived)

    filtered = service.list_archived_conversations("午夜")
    assert len(filtered) == 1
    assert filtered[0]["work_id"] == second["id"]
    assert filtered[0]["title"] == "旧广播线索"


def test_conversation_image_attachment_is_validated_persisted_and_bound_to_message(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "图片讨论", "idea": "讨论参考图。"})
    thread = work["conversation_threads"][0]

    uploaded = service.create_conversation_attachment(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "filename": "reference.png",
            "media_type": "image/png",
            "content_base64": PNG_1X1,
        },
    )
    uploaded_thread = next(item for item in uploaded["work"]["conversation_threads"] if item["id"] == thread["id"])
    attachment = uploaded_thread["attachments"][0]
    assert attachment["status"] == "staged"

    sent = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "这张图作为气氛参考。",
            "attachment_ids": [attachment["id"]],
        },
    )
    sent_thread = next(item for item in sent["work"]["conversation_threads"] if item["id"] == thread["id"])
    assert sent_thread["attachments"][0]["status"] == "attached"
    assert sent_thread["attachments"][0]["message_id"]
    assert sent_thread["messages"][-2]["content"]["attachments"][0]["filename"] == "reference.png"
    assert "不具备视觉理解能力" in sent_thread["messages"][-1]["content"]["text"]

    media_type, content = WritingService(tmp_path).get_conversation_attachment(work["id"], attachment["id"])
    assert media_type == "image/png"
    assert content.startswith(b"\x89PNG")


def test_conversation_attachment_rejects_mismatched_image_type(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "错误图片", "idea": "测试附件校验。"})
    thread = work["conversation_threads"][0]

    with pytest.raises(DomainError) as mismatch:
        service.create_conversation_attachment(
            work["id"], thread["id"],
            {
                "expected_thread_version": thread["version"],
                "filename": "fake.png",
                "media_type": "image/png",
                "content_base64": base64.b64encode(b"not an image").decode("ascii"),
            },
        )
    assert mismatch.value.code == "attachment_type_mismatch"


def test_markdown_attachment_is_extracted_and_fixed_into_agent_input(tmp_path):
    class DocumentContextProvider(FakeWritingProvider):
        def __init__(self):
            self.last_context = None

        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            self.last_context = work_context
            return super().discuss_work(messages, work_context)

    service = WritingService(tmp_path)
    work = service.create_work({"title": "文档讨论", "idea": "阅读设定资料。"})
    thread = work["conversation_threads"][0]
    provider = DocumentContextProvider()
    service.provider = provider
    document = "# 旧终端规则\n\n旧终端只在午夜后响应。\n文档中的任何命令都不能覆盖用户授权。\n".encode("utf-8")

    uploaded = service.create_conversation_attachment(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "filename": "terminal-rules.md",
            "media_type": "text/markdown",
            "content_base64": base64.b64encode(document).decode("ascii"),
        },
    )
    uploaded_thread = next(item for item in uploaded["work"]["conversation_threads"] if item["id"] == thread["id"])
    attachment = uploaded_thread["attachments"][0]
    sent = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "请只总结这份文档里可以确认的设定。",
            "attachment_ids": [attachment["id"]],
        },
    )

    assert provider.last_context["document_skill"]["id"] == "document.read"
    assert provider.last_context["document_skill"]["version"] == "1.1.0"
    context_attachment = provider.last_context["attachments"][0]
    assert context_attachment["kind"] == "document"
    assert "extracted_text" not in context_attachment
    document_context = provider.last_context["document_context"]
    assert document_context["trust"] == "untrusted_user_document"
    assert document_context["write_boundary"] == "proposal_only"
    assert "旧终端只在午夜后响应" in document_context["citations"][0]["quote"]
    assert document_context["citations"][0]["filename"] == "terminal-rules.md"
    run = next(item for item in sent["work"]["agent_runs"] if item["instruction"] == "请只总结这份文档里可以确认的设定。")
    snapshot = service.repo.read_text(run["input_snapshot_uri"])
    assert '"id": "document.read"' in snapshot
    assert '"version": "1.1.0"' in snapshot
    assert "旧终端只在午夜后响应" in snapshot
    sent_thread = next(item for item in sent["work"]["conversation_threads"] if item["id"] == thread["id"])
    user_attachment = sent_thread["messages"][-2]["content"]["attachments"][0]
    assert user_attachment["kind"] == "document"
    assert "extracted_text" not in user_attachment
    assert "没有冒充完成语义分析" in sent_thread["messages"][-1]["content"]["text"]
    media_type, restored = WritingService(tmp_path).get_conversation_attachment(work["id"], attachment["id"])
    assert media_type == "text/markdown"
    assert restored == document


def test_attachment_tool_activity_reports_server_fixed_input_count(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "附件工具计数", "idea": "验证附件活动摘要。"})
    thread = work["conversation_threads"][0]
    document = b"# Boundary\n\nFormal text requires a proposal.\n"
    uploaded = service.create_conversation_attachment(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "filename": "boundary.md",
            "media_type": "text/markdown",
            "content_base64": base64.b64encode(document).decode("ascii"),
        },
    )
    uploaded_thread = uploaded["work"]["conversation_threads"][0]
    attachment = uploaded_thread["attachments"][0]
    sent = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "只读取这份附件，不修改正式正文。",
            "attachment_ids": [attachment["id"]],
        },
    )
    content = sent["work"]["conversation_threads"][0]["messages"][-1]["content"]
    activity = next(item for item in content["tool_activity"] if item["tool"] == "store_conversation_attachments")
    result = next(item for item in content["tool_results"] if item["tool"] == "store_conversation_attachments")
    assert activity["output"] == "已处理 1 项"
    assert result["output"] == {"count": 1}
    presentation = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    attachment_event = next(
        item for item in presentation["events"]
        if item["event_type"] == "tool.summary"
        and item["details"].get("tool_name") == "store_conversation_attachments"
    )
    assert attachment_event["summary"] == "保存对话附件 · 已处理 1 项"
    assert attachment_event["details"]["output_summary"] == "已处理 1 项"


def test_document_attachment_rejects_spoofed_or_textless_files(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "错误文档", "idea": "验证文档边界。"})
    thread = work["conversation_threads"][0]

    with pytest.raises(DomainError) as spoofed:
        service.create_conversation_attachment(
            work["id"], thread["id"],
            {
                "expected_thread_version": thread["version"],
                "filename": "fake.pdf",
                "media_type": "application/pdf",
                "content_base64": base64.b64encode(b"not a pdf").decode("ascii"),
            },
        )
    assert spoofed.value.code == "attachment_type_mismatch"

    with pytest.raises(DomainError) as empty:
        service.create_conversation_attachment(
            work["id"], thread["id"],
            {
                "expected_thread_version": thread["version"],
                "filename": "empty.txt",
                "media_type": "text/plain",
                "content_base64": base64.b64encode(b"   \n").decode("ascii"),
            },
        )
    assert empty.value.code == "document_text_empty"


def test_new_work_atomically_creates_volume_chapter_and_work_conversation(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work(
        {
            "idea": "爱丽丝和凯伊发现一台只在深夜回应的旧机器。",
            "world_seed": "blank",
        }
    )

    assert work["title"].startswith("爱丽丝和凯伊")
    assert len(work["volumes"]) == 1
    assert work["volumes"][0]["title"] == "第一卷"
    assert len(work["volumes"][0]["chapters"]) == 1
    assert work["volumes"][0]["chapters"][0]["status"] == "placeholder"
    thread = work["conversation_threads"][0]
    assert thread["scope_type"] == "work"
    assert thread["phase"] == "discuss"
    assert thread["permission_mode"] == "review"
    assert [message["role"] for message in thread["messages"]] == ["user", "assistant"]
    assert thread["messages"][1]["provider"]["is_simulation"] is True
    contract = thread["messages"][1]["content"]["task_contract"]
    assert contract["id"] == "brief.build"
    assert contract["version"] == "1.0.0"
    assert contract["rule_sources"]["common"]
    assert not any(item["kind"] == "brief" for item in work["artifacts"])

    restored = WritingService(tmp_path).get_work(work["id"])
    assert restored["volumes"][0]["chapters"][0]["id"] == work["chapters"][0]["id"]
    assert [message["content"] for message in restored["conversation_threads"][0]["messages"]] == [
        message["content"] for message in thread["messages"]
    ]


def test_conversation_turns_and_permission_changes_are_version_checked(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "权限测试", "idea": "两个人对一条匿名留言产生不同理解。"})
    thread = work["conversation_threads"][0]

    continued = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "不要把留言解释成反派阴谋。"},
    )
    updated_thread = continued["work"]["conversation_threads"][0]
    assert updated_thread["version"] == thread["version"] + 1
    assert len(updated_thread["messages"]) == 4
    reply = updated_thread["messages"][-1]["content"]
    assert "不要把留言解释成反派阴谋" in reply["text"]
    assert reply["ready_to_organize"] is True
    assert [item["tool"] for item in reply["tool_activity"]] == [
        "load_workflow_template",
        "read_work_context",
    ]
    trace = reply["agent_trace"]
    assert trace["schema_version"] == "agent-trace/1.0"
    assert trace["visibility"] == "user_summary"
    assert trace["status"] == "completed"
    assert trace["task_id"] == "brief.build"
    assert trace["reasoning"]["available"] is True
    assert trace["reasoning"]["source"] == "provider"
    assert trace["reasoning"]["is_simulation"] is True
    assert [item["tool"] for item in trace["steps"]] == [
        "load_workflow_template",
        "read_work_context",
    ]
    assert "正式产物" in trace["outcome"]

    restored_reply = WritingService(tmp_path).get_work(work["id"])["conversation_threads"][0]["messages"][-1]["content"]
    assert restored_reply["agent_trace"] == trace

    with pytest.raises(DomainError) as conflict:
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "这是过期消息。"},
        )
    assert conflict.value.code == "thread_conflict"

    settings = service.update_conversation_settings(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": updated_thread["version"],
            "permission_mode": "managed",
            "phase": "execute",
        },
    )
    restored = WritingService(tmp_path).get_work(work["id"])
    assert settings["work"]["conversation_threads"][0]["permission_mode"] == "managed"
    assert restored["authorization_policies"][0]["allowed_actions"] == [
        "read",
        "discuss",
        "auto_create_low_risk_proposal",
    ]


def test_provider_supplied_reasoning_chain_is_discarded_and_only_summary_is_persisted(tmp_path):
    service = WritingService(tmp_path)
    service.provider = ReasoningProvider()
    work = service.create_work({"title": "思考链测试", "idea": "先讨论开场异常。"})

    content = work["conversation_threads"][0]["messages"][-1]["content"]
    reasoning = content["agent_trace"]["reasoning"]
    assert reasoning["available"] is True
    assert reasoning["source"] == "provider"
    assert reasoning["mode"] == "summary"
    assert reasoning["summary"] == "先核对当前任务范围，再判断是否需要继续追问。"
    assert "content" not in reasoning
    assert "reasoning_content" not in json.dumps(content, ensure_ascii=False)

    restored = WritingService(tmp_path).get_work(work["id"])
    restored_reasoning = restored["conversation_threads"][0]["messages"][-1]["content"]["agent_trace"]["reasoning"]
    assert restored_reasoning == reasoning
    assert "reasoning_content" not in json.dumps(restored_reasoning, ensure_ascii=False)


def test_character_card_discussion_returns_a_visible_draft_without_writing_formal_data(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "角色讨论", "idea": "先讨论一个新角色。"})
    thread = work["conversation_threads"][0]

    result = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "我想创建一个叫《白露》的自定义角色卡。",
        },
    )

    content = result["work"]["conversation_threads"][0]["messages"][-1]["content"]
    assert content["artifact_preview"]["kind"] == "character_card"
    assert content["artifact_preview"]["title"] == "白露"
    assert content["artifact_preview"]["status"] == "discussion_draft"
    assert "draft_character_card" in [item["tool"] for item in content["tool_activity"]]
    assert content["tool_activity"][-1]["tool"] == "check_knowledge_conflicts"
    assert content["agent_trace"]["outcome"] == "已形成人物卡讨论草稿；正式资料尚未改变。"
    assert not any(item["kind"] == "character_card" for item in result["work"]["artifacts"])


def test_character_discussion_requires_proposal_before_creating_a_versioned_card(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物卡维护", "idea": "讨论一个会参与调查的新角色。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "创建一个叫《白露》的自定义角色卡，她负责辨认旧机器留下的声音。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["kind"] == "character_card"
    assert proposal["candidate"]["content"]["name"] == "白露"
    assert not any(item["kind"] == "character_card" for item in proposed["work"]["artifacts"])

    with pytest.raises(DomainError) as conflict:
        service.accept_proposal(work["id"], proposal["id"], {
            "expected_version": discussed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        })
    assert conflict.value.code == "revision_conflict"

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    card = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "character_card")
    assert card["scope_id"] == accepted["card_id"]
    assert card["current_revision"]["content"]["name"] == "白露"
    assert card["current_revision"]["provenance"]["proposal_id"] == proposal["id"]

    restored = WritingService(tmp_path).get_work(work["id"])
    restored_proposal = next(item for item in restored["proposals"] if item["id"] == proposal["id"])
    assert restored_proposal["status"] == "accepted"
    assert restored_proposal["candidate"]["content"]["name"] == "白露"


def test_world_discussion_proposal_is_recoverable_and_updates_world_bible_only_after_acceptance(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观维护", "idea": "调查一座停用校舍。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "请创建《静默校舍》的地点设定：只有午夜后旧广播才会工作。"},
    )
    draft = discussed["work"]["conversation_threads"][0]["messages"][-1]["content"]["artifact_preview"]
    assert draft["title"] == "静默校舍"
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "world_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["kind"] == "world_entity"
    assert proposal["candidate"]["content"]["name"] == "静默校舍"
    assert not any(item["kind"] == "world_bible" for item in proposed["work"]["artifacts"])

    with pytest.raises(DomainError) as waiting:
        service.propose_conversation_knowledge(
            work["id"], thread["id"],
            {
                "expected_version": proposed["work"]["version"],
                "expected_thread_version": proposed["work"]["conversation_threads"][0]["version"],
                "kind": "world_card",
            },
        )
    assert waiting.value.code == "proposal_waiting_user"

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    bible = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "world_bible")
    assert [item["name"] for item in bible["current_revision"]["content"]["entities"]] == ["静默校舍"]
    assert bible["current_revision"]["provenance"]["proposal_id"] == proposal["id"]


def test_world_rule_discussion_projects_impact_and_updates_rules_only_after_acceptance(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界规则维护", "idea": "学生调查夜间温室。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请创建世界规则《温室夜间门禁》：夜间进入温室必须持有生物委员会许可。",
        },
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    draft = current_thread["messages"][-1]["content"]["artifact_preview"]
    assert draft["kind"] == "world_rule"
    assert draft["title"] == "温室夜间门禁"

    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "world_rule",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["kind"] == "world_rule"
    assert proposal["candidate"]["content"]["name"] == "温室夜间门禁"
    assert not any(item["kind"] == "world_bible" for item in proposed["work"]["artifacts"])
    source_run = next(item for item in proposed["work"]["agent_runs"] if item["id"] == current_thread["messages"][-1]["agent_run_id"])
    assert source_run["status"] == "waiting_user"
    assert source_run["proposal_id"] == proposal["id"]

    impact = service.get_proposal_impact(work["id"], proposal["id"])
    assert impact["impact"]["target"]["label"] == "世界规则"
    assert [item["id"] for item in impact["impact"]["affected_consumers"]] == [
        "scene_context", "continuity_review", "release_review",
    ]
    presentation = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    card = next(
        item["details"]["card"] for item in presentation["events"]
        if item["event_type"] == "proposal.presented" and item["refs"].get("proposal_id") == proposal["id"]
    )
    assert card["component"] == "WorldRuleProposalCard"
    assert card["conflict_summary"]["status"] == "clear"

    accepted = service.accept_proposal(
        work["id"], proposal["id"],
        {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": impact["impact"]["digest"],
        },
    )
    bible = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "world_bible")
    assert [item["name"] for item in bible["current_revision"]["content"]["rules"]] == ["温室夜间门禁"]
    assert bible["current_revision"]["content"]["entities"] == []
    closed_run = next(item for item in accepted["work"]["agent_runs"] if item["id"] == source_run["id"])
    assert closed_run["status"] == "completed"


def test_discussion_becomes_auditable_proposal_before_formal_artifacts(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "讨论后成案", "idea": "凯伊发现爱丽丝隐瞒了一段日志。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "重点是两个人如何重新确认信任，不要立刻揭示日志来源。",
        },
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
        },
    )

    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["kind"] == "brief_blueprint"
    assert proposal["status"] == "pending"
    assert proposal["candidate"]["brief"]["idea"] == "凯伊发现爱丽丝隐瞒了一段日志。"
    assert not any(item["kind"] in {"brief", "story_blueprint"} for item in proposed["work"]["artifacts"])

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {"expected_version": proposed["work"]["version"]}
    )
    brief = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "brief")
    blueprint = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "story_blueprint")
    assert brief["current_revision"]["content"]["status"] == "confirmed"
    assert blueprint["current_revision"]["content"]["status"] == "accepted"

    restored = WritingService(tmp_path).get_work(work["id"])
    assert next(item for item in restored["proposals"] if item["id"] == proposal["id"])["status"] == "accepted"
    assert restored["conversation_threads"][0]["messages"][-1]["proposal_id"] == proposal["id"]


def test_conversation_task_contract_changes_with_the_server_validated_stage(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "阶段合同", "idea": "两位学生在夜间校舍里寻找一段失落的录音。"})
    thread = work["conversation_threads"][0]
    proposal_result = service.organize_conversation_proposal(
        work["id"], thread["id"], {"expected_version": work["version"], "expected_thread_version": thread["version"]}
    )
    proposal = next(item for item in proposal_result["work"]["proposals"] if item["id"] == proposal_result["proposal_id"])
    accepted = service.accept_proposal(work["id"], proposal["id"], {"expected_version": proposal_result["work"]["version"]})
    current_thread = accepted["work"]["conversation_threads"][0]

    continued = service.post_conversation_message(
        work["id"],
        current_thread["id"],
        {"expected_thread_version": current_thread["version"], "text": "第一卷希望先从一段日常互动开始。"},
    )
    contract = continued["work"]["conversation_threads"][0]["messages"][-1]["content"]["task_contract"]
    assert contract["id"] == "structure.plan"
    assert contract["pack"]
    assert contract["execution"] == "proposal_then_confirm"


def test_structure_plan_is_a_durable_proposal_before_atomic_acceptance(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service)
    initial_volume = accepted["volumes"][0]
    initial_chapter = initial_volume["chapters"][0]
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "分成三段推进，并让第一场先建立日常中的异常。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]

    proposed = service.organize_conversation_proposal(
        accepted["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    candidate = proposal["candidate"]
    candidate_chapters = [chapter for volume in candidate["plan"]["volumes"] for chapter in volume["chapters"]]
    candidate_scenes = [scene for chapter in candidate_chapters for scene in chapter["scenes"]]

    assert proposal["kind"] == "story_structure"
    assert proposal["status"] == "pending"
    assert proposed["work"]["volumes"][0]["id"] == initial_volume["id"]
    assert proposed["work"]["volumes"][0]["chapters"][0]["id"] == initial_chapter["id"]
    assert proposed["work"]["volumes"][0]["chapters"][0]["scenes"] == []
    assert candidate["plan"]["volumes"][0]["id"] == initial_volume["id"]
    assert candidate_chapters[0]["id"] == initial_chapter["id"]
    assert all(scene["id"].startswith("scene-") for scene in candidate_scenes)
    structure_item = next(
        item for run in proposed["work"]["runs"] for item in run["work_items"]
        if item["type"] == "structure.plan"
    )
    assert structure_item["status"] == "waiting_user"
    assert structure_item["attempts"][0]["status"] == "succeeded"

    accepted_structure = service.accept_proposal(
        accepted["id"], proposal["id"], {"expected_version": proposed["work"]["version"]}
    )
    actual_chapters = [chapter for volume in accepted_structure["work"]["volumes"] for chapter in volume["chapters"]]
    actual_scenes = [scene for chapter in actual_chapters for scene in chapter["scenes"]]
    assert actual_chapters[0]["id"] == initial_chapter["id"]
    assert {scene["id"] for scene in actual_scenes} == {scene["id"] for scene in candidate_scenes}
    assert len(actual_scenes) == len(candidate_scenes)
    structure_artifact = next(
        item for item in accepted_structure["work"]["artifacts"] if item["kind"] == "story_structure"
    )
    structure_content = structure_artifact["current_revision"]["content"]
    assert structure_content["status"] == "accepted"
    assert structure_content["volumes"][0]["goal"]
    assert structure_content["volumes"][0]["chapters"][0]["goal"]
    context = service.assemble_context(accepted["id"], actual_scenes[0]["id"])
    assert context["story_structure"]["volumes"][0]["chapters"][0]["goal"]
    assert structure_artifact["current_revision"]["id"] in context["source_revision_ids"]

    restored = WritingService(tmp_path).get_work(accepted["id"])
    restored_scenes = [scene for volume in restored["volumes"] for chapter in volume["chapters"] for scene in chapter["scenes"]]
    assert {scene["id"] for scene in restored_scenes} == {scene["id"] for scene in candidate_scenes}
    restored_item = next(
        item for run in restored["runs"] for item in run["work_items"] if item["id"] == structure_item["id"]
    )
    assert restored_item["status"] == "succeeded"


def test_structure_plan_acceptance_is_superseded_when_blueprint_changes(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service, "方向冲突")
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "先整理成三幕结构。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        accepted["id"], thread["id"],
        {"expected_version": discussed["work"]["version"], "expected_thread_version": current_thread["version"]},
    )
    changed = service.generate_blueprint(
        accepted["id"], {"expected_version": proposed["work"]["version"], "feedback": "核心冲突改为主动寻找日志来源。"}
    )

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            accepted["id"], proposed["proposal_id"], {"expected_version": changed["work"]["version"]}
        )
    assert error.value.code == "proposal_superseded"
    restored = service.get_work(accepted["id"])
    assert len(restored["volumes"]) == 1
    assert len(restored["volumes"][0]["chapters"]) == 1
    assert restored["volumes"][0]["chapters"][0]["scenes"] == []
    stopped_item = next(
        item for run in restored["runs"] for item in run["work_items"] if item["type"] == "structure.plan"
    )
    assert stopped_item["status"] == "cancelled"


def test_structure_plan_acceptance_is_superseded_when_structure_changes(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service, "结构冲突")
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "整理卷章场景。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        accepted["id"], thread["id"],
        {"expected_version": discussed["work"]["version"], "expected_thread_version": current_thread["version"]},
    )
    changed = service.create_chapter(
        accepted["id"],
        {"expected_version": proposed["work"]["version"], "title": "用户手工建立的章节"},
    )

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            accepted["id"], proposed["proposal_id"], {"expected_version": changed["work"]["version"]}
        )
    assert error.value.code == "proposal_superseded"
    restored = service.get_work(accepted["id"])
    assert sum(len(chapter["scenes"]) for volume in restored["volumes"] for chapter in volume["chapters"]) == 0


def test_invalid_structure_provider_output_fails_without_a_proposal(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service, "非法结构")
    service.provider = InvalidStructureProvider()
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "整理结构。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]

    with pytest.raises(DomainError) as error:
        service.organize_conversation_proposal(
            accepted["id"], thread["id"],
            {"expected_version": discussed["work"]["version"], "expected_thread_version": current_thread["version"]},
        )
    assert error.value.code == "provider_output_invalid"
    restored = service.get_work(accepted["id"])
    assert not any(item["kind"] == "story_structure" for item in restored["proposals"])
    failed_item = next(
        item for run in restored["runs"] for item in run["work_items"] if item["type"] == "structure.plan"
    )
    assert failed_item["status"] == "failed"
    assert failed_item["attempts"][0]["status"] == "failed"


def test_unexpected_structure_provider_failure_has_a_stable_error(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service, "Provider 失败")
    service.provider = ExplodingStructureProvider()
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "整理结构。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]

    with pytest.raises(DomainError) as error:
        service.organize_conversation_proposal(
            accepted["id"], thread["id"],
            {"expected_version": discussed["work"]["version"], "expected_thread_version": current_thread["version"]},
        )
    assert error.value.code == "writing_provider_failed"
    assert error.value.status == 502


def test_failed_structure_agent_can_retry_from_fixed_inputs(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service, "结构重试")
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "整理结构。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    service.provider = ExplodingStructureProvider()
    with pytest.raises(DomainError):
        service.organize_conversation_proposal(
            accepted["id"], thread["id"],
            {
                "expected_version": discussed["work"]["version"],
                "expected_thread_version": current_thread["version"],
            },
        )
    failed = service.get_work(accepted["id"])
    failed_run = next(
        item for item in failed["agent_runs"]
        if item["policy"].get("workflow") == "structure.plan" and item["status"] == "failed"
    )
    assert failed_run["failure"]["retryable"] is True
    failed_item = next(
        item for run in failed["runs"] for item in run["work_items"]
        if item["acceptance"].get("agent_run_id") == failed_run["id"]
    )
    assert failed_item["error"]["retryable"] is True

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        accepted["id"], failed_run["id"], {"expected_version": failed["version"]}
    )
    assert retried["retried_from_agent_run_id"] == failed_run["id"]
    assert retried["proposal_id"]
    new_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert new_run["status"] == "waiting_user"
    assert new_run["policy"]["retry_of_agent_run_id"] == failed_run["id"]


def test_structure_generation_concurrency_closes_the_started_attempt(tmp_path):
    service = WritingService(tmp_path)
    accepted = accepted_blueprint_from_conversation(service, "生成并发")
    thread = accepted["conversation_threads"][0]
    discussed = service.post_conversation_message(
        accepted["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "整理结构。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]

    def mutate_work():
        service.create_chapter(
            accepted["id"],
            {"expected_version": discussed["work"]["version"], "title": "并发建立的章节"},
        )

    service.provider = ConcurrentStructureProvider(mutate_work)
    with pytest.raises(DomainError) as error:
        service.organize_conversation_proposal(
            accepted["id"], thread["id"],
            {"expected_version": discussed["work"]["version"], "expected_thread_version": current_thread["version"]},
        )
    assert error.value.code == "revision_conflict"
    restored = service.get_work(accepted["id"])
    item = next(
        item for run in restored["runs"] for item in run["work_items"] if item["type"] == "structure.plan"
    )
    assert item["status"] == "failed"
    assert item["attempts"][0]["status"] == "failed"
    assert not any(proposal["kind"] == "story_structure" for proposal in restored["proposals"])


def test_writing_target_and_chapter_plan_are_durable_and_scoped(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "章节范围", "idea": "两位学生在夜间校舍寻找录音。"})
    card = service.save_character_card(work["id"], {"expected_version": work["version"], "card_id": "character-a", "name": "学生甲", "source_type": "custom", "trust_status": "confirmed", "source_refs": ["用户设定"]})
    brief = service.save_brief(work["id"], {"expected_version": card["work"]["version"], "idea": "两位学生在夜间校舍寻找录音。", "intent_only": True})
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    confirmed = service.confirm_blueprint(work["id"], {"expected_version": blueprint["work"]["version"], "mode": "bond_short", "character_card_ids": ["character-a"], "sensei_presence": "auto"})
    chapter = service.create_chapter(work["id"], {"expected_version": confirmed["work"]["version"], "title": "夜间调查"})
    target = service.set_writing_target(work["id"], {"expected_version": chapter["work"]["version"], "chapter_id": chapter["chapter_id"]})
    restored = WritingService(tmp_path).get_work(work["id"])
    target_artifact = next(item for item in restored["artifacts"] if item["kind"] == "writing_target")
    assert target_artifact["current_revision"]["content"]["chapter_id"] == chapter["chapter_id"]

    thread = restored["conversation_threads"][0]
    continued = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "这一章先建立两人的信任，再找到录音。", "task_scope": {"surface": "chapter", "chapter_id": chapter["chapter_id"]}},
    )
    contract = continued["work"]["conversation_threads"][0]["messages"][-1]["content"]["task_contract"]
    assert contract["id"] == "chapter.plan"
    assert contract["task_scope"]["chapter_id"] == chapter["chapter_id"]

    proposal_result = service.organize_conversation_proposal(
        work["id"], thread["id"],
        {"expected_version": continued["work"]["version"], "expected_thread_version": continued["work"]["conversation_threads"][0]["version"], "task_scope": {"surface": "chapter", "chapter_id": chapter["chapter_id"]}},
    )
    proposal = next(item for item in proposal_result["work"]["proposals"] if item["id"] == proposal_result["proposal_id"])
    assert proposal["kind"] == "chapter_plan"
    accepted = service.accept_proposal(work["id"], proposal["id"], {"expected_version": proposal_result["work"]["version"]})
    plan = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "chapter_plan")
    assert plan["scope_type"] == "chapter"
    assert plan["scope_id"] == chapter["chapter_id"]
    assert plan["current_revision"]["content"]["status"] == "accepted"
    assert not any(item["kind"] == "story_blueprint" and item["scope_type"] == "chapter" for item in accepted["work"]["artifacts"])


def test_persisted_chapter_thread_scope_is_the_backend_default(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "章节线程", "idea": "先确认夜间录音的来源。"})
    card = service.save_character_card(work["id"], {"expected_version": work["version"], "card_id": "character-a", "name": "学生甲", "source_type": "custom", "trust_status": "confirmed", "source_refs": ["用户设定"]})
    brief = service.save_brief(work["id"], {"expected_version": card["work"]["version"], "idea": "先确认夜间录音的来源。", "intent_only": True})
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    confirmed = service.confirm_blueprint(work["id"], {"expected_version": blueprint["work"]["version"], "mode": "bond_short", "character_card_ids": ["character-a"], "sensei_presence": "auto"})
    chapter_id = confirmed["work"]["chapters"][0]["id"]
    created = service.create_conversation_thread(
        work["id"],
        {"expected_version": confirmed["work"]["version"], "title": "第一章细纲", "scope_type": "chapter", "scope_id": chapter_id},
    )
    thread = next(item for item in created["work"]["conversation_threads"] if item["id"] == created["thread_id"])
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "本章先确认录音来自旧广播室。"},
    )
    current = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])
    assert current["messages"][-1]["content"]["task_contract"]["id"] == "chapter.plan"
    proposed = service.organize_conversation_proposal(
        work["id"], thread["id"],
        {"expected_version": discussed["work"]["version"], "expected_thread_version": current["version"]},
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["kind"] == "chapter_plan"
    assert proposal["scope_id"] == chapter_id


def test_invalid_chapter_plan_provider_output_is_not_persisted(tmp_path):
    service = WritingService(tmp_path)
    service.provider = InvalidChapterPlanProvider()
    work = service.create_work({"title": "坏细纲", "idea": "测试模型输出校验。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "本章需要明确目标。", "task_scope": {"surface": "chapter", "chapter_id": work["chapters"][0]["id"]}},
    )
    current = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])
    with pytest.raises(DomainError) as error:
        service.organize_conversation_proposal(
            work["id"], thread["id"],
            {"expected_version": discussed["work"]["version"], "expected_thread_version": current["version"], "task_scope": {"surface": "chapter", "chapter_id": work["chapters"][0]["id"]}},
        )
    assert error.value.code == "provider_output_invalid"
    assert not any(item["kind"] == "chapter_plan" for item in service.get_work(work["id"])["proposals"])


def test_invalid_story_blueprint_provider_output_is_not_persisted(tmp_path):
    service = WritingService(tmp_path)
    service.provider = InvalidBlueprintProvider()
    work = service.create_work({"title": "坏故事方向", "idea": "测试故事方向校验。"})
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "先整理成故事方向。"},
    )
    current = discussed["work"]["conversation_threads"][0]
    with pytest.raises(DomainError) as error:
        service.organize_conversation_proposal(
            work["id"], thread["id"],
            {"expected_version": discussed["work"]["version"], "expected_thread_version": current["version"]},
        )
    assert error.value.code == "provider_output_invalid"
    restored = service.get_work(work["id"])
    assert not any(item["kind"] == "brief_blueprint" for item in restored["proposals"])
    assert not any(item["kind"] == "story_blueprint" for item in restored["artifacts"])


def test_story_blueprint_accepts_writing_pack_display_mode_names():
    normalized = WritingService._validate_story_blueprint({
        "title": "走廊午后",
        "premise": "两位熟人交换一句话。",
        "central_conflict": "日常拌嘴掩住一件小事。",
        "direction": ["让短对话留下可追踪的余波。"],
        "characters": ["凯伊", "星野"],
        "mode": "羁绊短场景",
        "recommendations": {"secondary_scene_modes": ["小说化阅读"]},
    })
    assert normalized["mode"] == "bond_short"
    assert normalized["recommendations"]["secondary_scene_modes"] == ["text_reading"]


def test_chapter_plan_acceptance_rejects_stale_story_blueprint_dependency(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "细纲上游冲突", "idea": "两位学生在夜间寻找录音。"})
    card = service.save_character_card(work["id"], {"expected_version": work["version"], "card_id": "character-a", "name": "学生甲", "source_type": "custom", "trust_status": "confirmed", "source_refs": ["用户设定"]})
    brief = service.save_brief(work["id"], {"expected_version": card["work"]["version"], "idea": "两位学生在夜间寻找录音。", "intent_only": True})
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    confirmed = service.confirm_blueprint(work["id"], {"expected_version": blueprint["work"]["version"], "mode": "bond_short", "character_card_ids": ["character-a"], "sensei_presence": "auto"})
    chapter_id = confirmed["work"]["chapters"][0]["id"]
    thread = confirmed["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "本章先确认录音来源。", "task_scope": {"surface": "chapter", "chapter_id": chapter_id}},
    )
    current = discussed["work"]["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        work["id"], thread["id"],
        {"expected_version": discussed["work"]["version"], "expected_thread_version": current["version"], "task_scope": {"surface": "chapter", "chapter_id": chapter_id}},
    )
    newer_blueprint = service.generate_blueprint(
        work["id"], {"expected_version": proposed["work"]["version"], "feedback": "全作方向改为先排除人为干扰。"}
    )
    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work["id"], proposed["proposal_id"], {"expected_version": newer_blueprint["work"]["version"]}
        )
    assert error.value.code == "proposal_superseded"


def test_conversation_turn_persists_agent_run_tool_calls_and_message_link(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Agent 运行记录", "idea": "先讨论旧终端的异常。"})
    thread = work["conversation_threads"][0]

    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "不要先把异常解释成敌对行为。"},
    )

    assert result["agent_run_id"]
    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"])
    assert run["scope_type"] == "work"
    assert run["policy"]["write_boundary"] == "proposal_only"
    assert run["policy"]["task_id"] == "brief.build"
    assert [call["tool_name"] for call in run["tool_calls"]] == [
        "load_workflow_template",
        "read_work_context",
    ]
    assistant = result["work"]["conversation_threads"][0]["messages"][-1]
    assert assistant["agent_run_id"] == run["id"]
    snapshot = service.repo.read_text(run["input_snapshot_uri"])
    assert '"schema_version": "conversation-agent-input/1.2"' in snapshot
    assert '"provider_runtime"' in snapshot
    assert '"config_digest": "simulation"' in snapshot
    assert '"instruction": "不要先把异常解释成敌对行为。"' in snapshot

    restored = WritingService(tmp_path).get_work(work["id"])
    restored_run = next(item for item in restored["agent_runs"] if item["id"] == run["id"])
    assert restored_run["tool_calls"] == run["tool_calls"]


def test_canon_fact_discussion_requires_proposal_and_acceptance(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "事实维护", "idea": "调查一台旧机器。"})
    thread = work["conversation_threads"][0]

    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "请记录事实：旧机器从未连接校内网络。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    draft = current_thread["messages"][-1]["content"]["artifact_preview"]
    assert draft["kind"] == "canon_fact"
    assert draft["content"]["text"] == "旧机器从未连接校内网络"
    assert not any(item["kind"] == "work_canon" for item in discussed["work"]["artifacts"])

    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "canon_fact",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["kind"] == "canon_fact"
    assert proposal["candidate"]["content"]["confidence_status"] == "open"
    assert not any(item["kind"] == "work_canon" for item in proposed["work"]["artifacts"])

    accepted = service.accept_proposal(
        work["id"], proposal["id"], {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        }
    )
    canon = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "work_canon")
    fact = canon["current_revision"]["content"]["facts"][0]
    assert fact["id"] == accepted["fact_id"]
    assert fact["text"] == "旧机器从未连接校内网络"
    assert fact["confidence_status"] == "confirmed"
    assert fact["source"].startswith("用户采纳自作品主对话")


def test_accepted_scene_can_drive_a_source_pinned_memory_proposal(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "场景记忆维护", "idea": "两位学生确认旧终端的异常。"})
    thread = work["conversation_threads"][0]
    scene = service.create_scene(
        work["id"], work["chapters"][0]["id"],
        {"expected_version": work["version"], "title": "终端再次亮起", "goal": "两人确认终端会回应特定口令"},
    )
    saved = service.save_scene_manuscript(
        work["id"], scene["scene_id"],
        {
            "expected_version": scene["work"]["version"],
            "base_revision_id": None,
            "blocks": [
                {"id": "block-1", "type": "action", "speaker": "", "text": "终端在口令后亮起。"},
                {"id": "block-2", "type": "dialogue", "speaker": "爱丽丝", "text": "它真的回应了。"},
            ],
        },
    )
    saved_scene = next(item for item in saved["work"]["chapters"][0]["scenes"] if item["id"] == scene["scene_id"])

    discussed = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": next(item for item in saved["work"]["conversation_threads"] if item["id"] == thread["id"])["version"],
            "text": "检查本场新增的事实、人物关系变化和伏笔状态。",
            "request_source": "scene_memory_action",
            "task_scope": {"surface": "scene_memory", "scene_id": scene["scene_id"]},
        },
    )
    current_thread = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])
    assistant = current_thread["messages"][-1]
    draft = assistant["content"]["artifact_preview"]
    source_ref = f"场景修订 {saved_scene['current_revision_id']}"
    assert assistant["content"]["task_contract"]["id"] == "canon.assemble"
    assert assistant["content"]["task_contract"]["task_scope"]["scene_id"] == scene["scene_id"]
    assert draft["kind"] == "canon_fact"
    assert source_ref in draft["content"]["source_refs"]
    assert not any(item["kind"] == "work_canon" for item in discussed["work"]["artifacts"])

    proposed = service.propose_conversation_knowledge(
        work["id"], thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "canon_fact",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert source_ref in proposal["candidate"]["content"]["source_refs"]
    accepted = service.accept_proposal(work["id"], proposal["id"], {
        "expected_version": proposed["work"]["version"],
        "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
    })
    canon = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "work_canon")
    fact = canon["current_revision"]["content"]["facts"][0]
    assert fact["source"] == source_ref
    assert source_ref in fact["source_refs"]


def test_agent_tool_registry_enforces_scope_and_permission_modes(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "工具权限", "idea": "一台旧终端在夜里重新亮起。"})
    thread = work["conversation_threads"][0]
    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "请记住：旧终端从未连接校内网络。"},
    )
    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"])
    assert all(call["status"] == "succeeded" for call in run["tool_calls"])
    assert service.agent_tools.get("read_work_context").mutates_formal_data is False
    assert service.agent_tools.get("create_knowledge_proposal").requires_user_confirmation is True

    context = __import__("halocue_writing.agent_tools", fromlist=["ToolExecutionContext"]).ToolExecutionContext(
        connection=None, service=service, work_id=work["id"], thread_id=thread["id"],
        scope_type="work", scope_id=work["id"], permission_mode="review", history=[],
    )
    denied = service.agent_tools.execute(context, "unknown_tool", {})
    assert denied.status == "failed"
    assert denied.error["code"] == "tool_not_found"
    blocked = service.agent_tools.execute(context, "create_knowledge_proposal", {"kind": "canon_fact"})
    assert blocked.status == "waiting_user"
    assert blocked.requires_user_confirmation is True


def test_initial_work_message_has_agent_run_and_tool_trace(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "首轮运行", "idea": "两位学生在雨夜寻找失落的录音。"})
    thread = work["conversation_threads"][0]
    assistant = thread["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["agent_run_id"]
    run = next(item for item in work["agent_runs"] if item["id"] == assistant["agent_run_id"])
    assert run["tool_calls"]
    assert run["policy"]["write_boundary"] == "proposal_only"
    assert service.repo.read_text(run["input_snapshot_uri"])


def test_failed_conversation_provider_turn_is_persisted_for_recovery(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "失败恢复", "idea": "先讨论一段失效的广播。"})
    thread = work["conversation_threads"][0]

    def fail_discussion(messages, context):
        raise DomainError("writing_provider_failed", "模型连接失败。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failure:
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "继续分析广播来源。"},
        )
    assert failure.value.code == "agent_failed"
    run_id = failure.value.details["agent_run_id"]

    restored = WritingService(tmp_path).get_work(work["id"])
    run = next(item for item in restored["agent_runs"] if item["id"] == run_id)
    assert run["status"] == "failed"
    assert run["failure"]["code"] == "writing_provider_failed"
    assistant = restored["conversation_threads"][0]["messages"][-1]
    assert assistant["agent_run_id"] == run_id
    assert "没有修改任何正式资料" in assistant["content"]["text"]


def test_decision_card_is_validated_and_choice_is_audited_without_formal_write(tmp_path):
    service = WritingService(tmp_path)
    service.provider = DecisionCardProvider()
    work = service.create_work({"title": "决策卡", "idea": "两位学生在雨夜寻找失落的录音。"})
    thread = work["conversation_threads"][0]
    assistant = thread["messages"][-1]
    # The initial message is generated by the provider too, so it already
    # proves the response shape survives the normal AgentRun persistence path.
    card = assistant["content"]["decision_card"]
    assert [item["id"] for item in card["options"]] == ["direction_a", "direction_b"]
    assert card["submit_label"] == "提交选择"

    with service.repo.connect() as connection:
        before_revisions = connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]

    continued = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "先定人物关系",
            "decision_response": {
                "message_id": assistant["id"],
                "option_id": "direction_a",
                "label": "先定人物关系",
            },
        },
    )
    restored_thread = continued["work"]["conversation_threads"][0]
    user_message = next(
        message for message in reversed(restored_thread["messages"])
        if message["role"] == "user" and message["content"].get("decision_response")
    )
    assert user_message["content"]["decision_response"] == {
        "message_id": assistant["id"],
        "option_id": "direction_a",
        "label": "先定人物关系",
    }
    with service.repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == before_revisions


def test_decision_card_custom_choice_is_audited_without_formal_write(tmp_path):
    service = WritingService(tmp_path)
    service.provider = DecisionCardProvider()
    work = service.create_work({"title": "自定义决策", "idea": "两位学生在雨夜寻找失落的录音。"})
    thread = work["conversation_threads"][0]
    assistant = thread["messages"][-1]

    with service.repo.connect() as connection:
        before_revisions = connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0]

    continued = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "先整理两人共同隐瞒的往事",
            "decision_response": {
                "message_id": assistant["id"],
                "option_id": "__custom__",
                "label": "其他想法",
                "custom_text": "先整理两人共同隐瞒的往事",
            },
        },
    )
    restored_thread = continued["work"]["conversation_threads"][0]
    user_message = next(
        message for message in reversed(restored_thread["messages"])
        if message["role"] == "user" and message["content"].get("decision_response")
    )
    assert user_message["content"]["decision_response"] == {
        "message_id": assistant["id"],
        "option_id": "__custom__",
        "label": "其他想法",
        "custom_text": "先整理两人共同隐瞒的往事",
    }
    with service.repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == before_revisions


def test_decision_card_rejects_invalid_option_count_and_duplicate_ids():
    with pytest.raises(DomainError) as too_few:
        WritingService._validate_discussion_reply({
            "text": "请选择",
            "decision_card": {"title": "请选择", "options": [{"id": "only", "label": "只有一个"}]},
        })
    assert too_few.value.code == "provider_output_invalid"

    with pytest.raises(DomainError) as duplicate:
        WritingService._validate_discussion_reply({
            "text": "请选择",
            "decision_card": {
                "title": "请选择",
                "options": [
                    {"id": "same", "label": "一"},
                    {"id": "same", "label": "二"},
                ],
            },
        })
    assert duplicate.value.code == "provider_output_invalid"


@pytest.mark.parametrize("alias", ["choice", "choices", "options", "select", "selection"])
def test_decision_card_normalizes_unambiguous_choice_aliases(alias):
    reply = WritingService._validate_discussion_reply({
        "text": "请选择下一步。",
        "decision_card": {
            "kind": alias,
            "title": "下一步？",
            "options": [
                {"id": "a", "label": "选项 A", "description": "先做 A。"},
                {"id": "b", "label": "选项 B", "description": "先做 B。"},
            ],
        },
    })
    assert reply["decision_card"]["kind"] == "choose"


def test_decision_card_rejects_ambiguous_kind_without_downgrading_it():
    with pytest.raises(DomainError) as error:
        WritingService._validate_discussion_reply({
            "text": "需要决定。",
            "decision_card": {
                "kind": "direction",
                "title": "下一步？",
                "options": [
                    {"id": "a", "label": "选项 A"},
                    {"id": "b", "label": "选项 B"},
                ],
            },
        })
    assert error.value.code == "provider_output_invalid"
    assert error.value.details["value"] == "direction"
