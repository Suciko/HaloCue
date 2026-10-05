"""Ordinary chat stays tool-free; only real requests produce tool receipts."""

from pathlib import Path

from halocue_writing.agent_tools import ToolExecutionResult
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService
from test_discussion_guidance import QuietProvider, make_catalog, send


class LookupThenDraft(QuietProvider):
    is_simulation = False

    def __init__(self, service):
        self.service = service
        self.rounds = []

    def discuss_work(self, messages, context):
        self.rounds.append(context)
        if not context.get("tool_followup"):
            return {
                "text": "看看本作人物。",
                "questions": [],
                "tool_calls": [
                    {
                        "id": "lookup",
                        "tool": "search_character_cards",
                        "arguments": {"query": ""},
                    }
                ],
            }
        current = self.service.get_work(context["work_id"])["agent_runs"][0]
        assert current["status"] == "running"
        assert current["tool_calls"]  # Visible before the next model reply.
        if context["tool_round"] == 1:
            return {
                "text": "整理一个原创人物草稿。",
                "questions": [],
                "tool_calls": [
                    {
                        "id": "draft",
                        "tool": "draft_character_card",
                        "arguments": {"name": "测试角色", "summary": "弄错了值班时间。"},
                    }
                ],
            }
        return {"text": "人物草稿准备好了，可以继续讨论她的反应。", "questions": []}


def test_plain_reply_does_not_execute_or_invent_tools(tmp_path):
    service = WritingService(tmp_path)
    service.provider = QuietProvider()
    work = send(service, service.create_work({"title": "普通对话"}), "这个笑点挺好，就保留吧。")
    reply = work["conversation_threads"][0]["messages"][-1]
    run = service.get_agent_run(work["id"], reply["agent_run_id"])
    assert run["tool_calls"] == []
    assert reply["content"]["tool_activity"] == []
    assert reply["content"]["agent_trace"]["steps"] == []
    service.close()


def test_simulation_does_not_force_context_reads(tmp_path):
    service = WritingService(tmp_path)
    service.provider = FakeWritingProvider()
    work = send(service, service.create_work({"title": "模拟对话"}), "先随便聊聊。")
    reply = work["conversation_threads"][0]["messages"][-1]
    assert service.get_agent_run(work["id"], reply["agent_run_id"])["tool_calls"] == []
    service.close()


def test_character_preparation_is_a_receipt_not_an_agent_tool(tmp_path):
    service = WritingService(tmp_path / "data")
    service.bundled_characters = make_catalog(tmp_path / "cards")
    service.provider = QuietProvider()
    work = send(service, service.create_work({"title": "人物准备"}), "日奈和亚子闹了个小误会。")
    reply = work["conversation_threads"][0]["messages"][-1]
    assert {item["name"] for item in reply["content"]["character_resolution"]["added"]} == {
        "空崎日奈",
        "天雨亚子",
    }
    assert service.get_agent_run(work["id"], reply["agent_run_id"])["tool_calls"] == []
    work = send(service, work, "让日奈和亚子继续聊。")
    receipt = work["conversation_threads"][0]["messages"][-1]["content"]["character_resolution"]
    assert not receipt["added"]
    assert len(receipt["reused"]) == 2
    service.close()


def test_tool_result_is_classified_and_summarized_without_json():
    result = ToolExecutionResult(
        "search_bundled_character_metadata",
        "succeeded",
        "raw description",
        {
            "items": [{"name": "空崎日奈"}, {"name": "天雨亚子"}],
            "private_path": "C:/private/cards.json",
        },
    )
    activity = result.activity()
    assert activity["category"] == "人物资料"
    assert activity["label"] == "查找随包人物参考"
    assert "2" in activity["output"] and "空崎日奈" in activity["output"]
    assert "private_path" not in activity["output"]
    failed = ToolExecutionResult(
        "search_character_cards", "failed", "raw", error={"message": "人物索引暂不可用"}
    ).activity()
    assert failed["error"]["message"] == "人物索引暂不可用"


def test_lookup_can_be_followed_by_draft_and_results_are_visible_mid_turn(tmp_path):
    service = WritingService(tmp_path)
    provider = LookupThenDraft(service)
    service.provider = provider
    work = send(
        service,
        service.create_work({"title": "按需工具链"}),
        "查下本作人物，再整理一个原创人物卡草稿。",
    )
    reply = work["conversation_threads"][0]["messages"][-1]
    assert len(provider.rounds) == 3
    assert "人物草稿准备好了" in reply["content"]["text"]
    run = service.get_agent_run(work["id"], reply["agent_run_id"])
    assert [item["tool_name"] for item in run["tool_calls"]] == [
        "search_character_cards",
        "draft_character_card",
        "check_knowledge_conflicts",
    ]
    assert len({item["id"] for item in run["tool_calls"]}) == 3
    service.close()


def test_discussion_loads_creative_guidance_instead_of_generation_sop(tmp_path):
    service = WritingService(tmp_path)
    from halocue_writing.workflow_pack import DISCUSSION_RULE_SOURCE

    discussion = service.ba_skill.required_paths(
        "main_battle", True, task_id="scene.draft.generate", output_mode="discussion_json"
    )
    assert discussion == ["SKILL.md", DISCUSSION_RULE_SOURCE]
    manuscript = service.ba_skill.required_paths(
        "main_battle", True, task_id="scene.draft.generate", output_mode="official_script"
    )
    assert "agents/writer.md" in manuscript
    assert "knowledge/老师在场规则.md" in manuscript
    assert DISCUSSION_RULE_SOURCE in service.ba_skill._pack_paths()
    service.close()


def test_real_prompt_keeps_author_genre_and_allows_lookup_then_writing(monkeypatch, tmp_path):
    from halocue_writing.ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
    from halocue_writing.providers import LLMCallResult, LLMWritingProvider
    from halocue_writing.repository import Repository

    source = Path(__file__).resolve().parents[1] / "skill" / "ba-writing"
    provider = LLMWritingProvider({"provider": "openai", "model": "acceptance"})
    registry = BaWritingSkillRegistry(source)
    assert registry.materialize(Repository(tmp_path))["status"] == "ready"
    provider.prompt_assembler = BaWritingPromptAssembler(registry)
    captured = []

    def call(system_prompt, user_prompt, **kwargs):
        captured.append(system_prompt)
        return LLMCallResult('{"text":"先写这个误会。","questions":[]}', "", (), None)

    monkeypatch.setattr(provider, "_call_llm", call)
    provider.discuss_work(
        [{"role": "user", "text": "想写一个轻松的 IF 小误会。"}],
        {
            "task_contract": {"id": "scene.draft.generate"},
            "scene_contract": {"has_sensei": True},
            "rules": {"mode_key": "main_battle"},
        },
    )
    prompt = captured[0]
    assert "OC、IF" in prompt
    assert '"questions": []' in prompt
    assert "同一轮可以先检索" in prompt
    assert "准备正文修改时，可以请求下一轮相应工具" in prompt
    assert "缺一项不得写正文" not in prompt
    assert "第一优先：主线" not in prompt
    assert "只有确实缺少另一项已提供的只读资料" not in prompt
