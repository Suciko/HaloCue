from halocue_writing.agent_tools import ToolExecutionContext
from halocue_writing.providers import FakeWritingProvider, LLMWritingProvider
from halocue_writing.service import WritingService


def context_for(service, connection, work_id, thread_id):
    return ToolExecutionContext(
        connection=connection,
        service=service,
        work_id=work_id,
        thread_id=thread_id,
        scope_type="work",
        scope_id=work_id,
        permission_mode="review",
        history=[],
    )


def test_required_tool_strings_reject_empty_and_null_values(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "工具校验"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        context = context_for(service, connection, work["id"], thread["id"])
        empty = service.agent_tools.execute(context, "draft_character_card", {"name": ""})
        null = service.agent_tools.execute(context, "draft_world_card", {"name": None})

    assert empty.status == "failed"
    assert empty.error["code"] == "tool_invalid_arguments"
    assert "不能为空" in empty.error["message"]
    assert null.status == "failed"
    assert null.error["code"] == "tool_invalid_arguments"


def test_tool_schema_rejects_unknown_properties_and_invalid_enum(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "工具枚举"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        context = context_for(service, connection, work["id"], thread["id"])
        extra = service.agent_tools.execute(
            context, "draft_canon_fact", {"text": "终端未联网。", "silent_write": True}
        )
        invalid = service.agent_tools.execute(
            context, "create_knowledge_proposal", {"kind": "unknown"}
        )

    assert extra.status == "failed"
    assert "未声明参数" in extra.error["message"]
    assert invalid.status == "failed"
    assert "允许值" in invalid.error["message"]


def test_tool_dispatch_enforces_allowed_actions(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "工具授权"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        context = context_for(service, connection, work["id"], thread["id"])
        context.allowed_actions = frozenset({"read"})
        denied = service.agent_tools.execute(
            context, "draft_character_card", {"name": "凯伊"}
        )
        allowed = service.agent_tools.execute(context, "read_work_context", {})

    assert denied.status == "denied"
    assert denied.error["code"] == "permission_denied"
    assert allowed.status == "succeeded"


def test_provider_contract_exposes_structured_character_and_world_draft_fields():
    tools = {item["name"]: item["input_schema"] for item in LLMWritingProvider._agent_tool_contract()}

    character = tools["draft_character_card"]
    assert {
        "canonical_name", "aliases", "role", "voice_anchors", "knowledge_boundary",
        "ooc_constraints", "relationships", "source_refs", "source_type", "trust_status",
    } <= set(character["properties"])
    relationship = character["properties"]["relationships"]["items"]
    assert relationship["required"] == ["target"]
    assert relationship["additionalProperties"] is False
    assert relationship["properties"]["status"]["enum"] == [
        "confirmed", "inferred", "open", "conflict",
    ]

    world = tools["draft_world_card"]
    assert {
        "kind", "aliases", "source", "source_refs", "source_type", "confidence_status",
        "scope", "participants", "related_world_ids",
    } <= set(world["properties"])
    assert "technology" in world["properties"]["kind"]["enum"]
    assert world["additionalProperties"] is False


def test_character_draft_handler_preserves_all_declared_structured_content(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物草稿字段"})
    thread = work["conversation_threads"][0]
    arguments = {
        "name": "凯伊",
        "canonical_name": "ケイ",
        "aliases": ["Key"],
        "summary": "负责核对异常日志。",
        "role": "调查搭档",
        "voice_anchors": ["先确认记录。"],
        "knowledge_boundary": "知道终端午夜响应，但不知道操作者。",
        "ooc_constraints": ["证据不足时不会直接指控。"],
        "relationships": [{
            "target": "爱丽丝", "kind": "搭档", "summary": "共同调查。", "status": "open",
        }],
        "source_refs": ["用户本轮说明"],
        "source_type": "custom",
        "trust_status": "inferred",
    }
    with service.repo.transaction() as connection:
        result = service.agent_tools.execute(
            context_for(service, connection, work["id"], thread["id"]),
            "draft_character_card",
            arguments,
        )

    assert result.status == "succeeded"
    assert result.output["title"] == "凯伊"
    assert result.output["status"] == "discussion_draft"
    assert result.output["content"] == arguments


def test_world_draft_handler_preserves_all_declared_structured_content(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观草稿字段"})
    thread = work["conversation_threads"][0]
    arguments = {
        "name": "旧终端",
        "kind": "technology",
        "summary": "只在午夜后响应。",
        "aliases": ["第三终端"],
        "source": "用户讨论（待确认）",
        "source_refs": ["terminal-rules.md · p000003"],
        "source_type": "custom",
        "confidence_status": "open",
        "scope": "work",
        "participants": ["凯伊", "爱丽丝"],
        "related_world_ids": ["world-observatory"],
    }
    with service.repo.transaction() as connection:
        result = service.agent_tools.execute(
            context_for(service, connection, work["id"], thread["id"]),
            "draft_world_card",
            arguments,
        )

    assert result.status == "succeeded"
    assert result.output["title"] == "旧终端"
    assert result.output["status"] == "discussion_draft"
    assert result.output["content"] == arguments


def test_nested_draft_fields_remain_strictly_validated(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "嵌套字段校验"})
    thread = work["conversation_threads"][0]
    with service.repo.transaction() as connection:
        context = context_for(service, connection, work["id"], thread["id"])
        invalid_relationship = service.agent_tools.execute(
            context,
            "draft_character_card",
            {"name": "凯伊", "relationships": [{"target": "爱丽丝", "secret": True}]},
        )
        invalid_world_kind = service.agent_tools.execute(
            context, "draft_world_card", {"name": "旧终端", "kind": "unknown"}
        )

    assert invalid_relationship.status == "failed"
    assert "未声明参数" in invalid_relationship.error["message"]
    assert invalid_world_kind.status == "failed"
    assert "允许值" in invalid_world_kind.error["message"]


def test_standard_provider_tool_call_keeps_structured_content_in_artifact_preview(tmp_path):
    class StructuredDraftProvider(FakeWritingProvider):
        def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
            return {
                "text": "已生成结构化人物讨论草稿。",
                "questions": [],
                "reasoning_summary": "人物约束仍需用户确认。",
                "ready_for_proposal": False,
                "tool_calls": [{
                    "id": "draft-character-structured",
                    "tool": "draft_character_card",
                    "arguments": {
                        "name": "凯伊",
                        "canonical_name": "ケイ",
                        "aliases": ["Key"],
                        "role": "调查搭档",
                        "voice_anchors": ["先确认记录。"],
                        "knowledge_boundary": "不知道终端操作者。",
                        "ooc_constraints": ["不会无证据指控。"],
                        "relationships": [{"target": "爱丽丝", "kind": "搭档", "status": "open"}],
                        "source_refs": ["用户本轮说明"],
                        "source_type": "custom",
                        "trust_status": "open",
                    },
                }],
            }

    service = WritingService(tmp_path)
    service.provider = StructuredDraftProvider()
    work = service.create_work({"title": "Provider 字段保真", "idea": "讨论凯伊的人物约束。"})
    thread = work["conversation_threads"][0]

    result = service.post_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "整理凯伊的人物卡草稿。"},
    )

    preview = result["work"]["conversation_threads"][0]["messages"][-1]["content"]["artifact_preview"]
    assert preview["content"]["canonical_name"] == "ケイ"
    assert preview["content"]["voice_anchors"] == ["先确认记录。"]
    assert preview["content"]["ooc_constraints"] == ["不会无证据指控。"]
    assert preview["content"]["relationships"] == [
        {"target": "爱丽丝", "kind": "搭档", "status": "open"}
    ]
    assert preview["content"]["source_refs"] == ["用户本轮说明"]
