"""Initial drafting uses the same authorized Proposal boundary as text edits."""

import json
import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import LLMWritingProvider, LLMCallResult
from halocue_writing.service import WritingService
from first_use_fixture_support import DraftingProvider
from test_scene_conversation_harness import create_ready_scene, create_scene_thread


@pytest.fixture
def ready(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    work, thread = create_scene_thread(service, work_id, scene_id, work)
    yield service, work_id, scene_id, work, thread
    service.close()


def post(service, work_id, scene_id, thread):
    return service.post_conversation_message(
        work_id,
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请起草本场。",
            "task_scope": {"surface": "scene", "scene_id": scene_id},
        },
    )


def test_draft_tool_creates_only_a_proposal_until_explicit_acceptance(ready):
    service, work_id, scene_id, _work, thread = ready
    service.provider = DraftingProvider()
    result = post(service, work_id, scene_id, thread)
    current = result["work"]
    proposal = next(item for item in current["proposals"] if item["kind"] == "scene_script")
    assert proposal["base_revision_id"] is None
    assert proposal["status"] == "pending"
    assert not current["chapters"][0]["scenes"][0]["current_revision_id"]
    assert not any(item["kind"] == "scene_script" for item in current["artifacts"])
    run = service.get_agent_run(work_id, result["agent_run_id"])
    assert run["proposal_id"] == proposal["id"]
    accepted = service.accept_proposal(
        work_id, proposal["id"], {"expected_version": current["version"]}
    )
    assert accepted["work"]["chapters"][0]["scenes"][0]["current_revision_id"]


@pytest.mark.parametrize("kind", ["unknown_speaker", "duplicate"])
def test_invalid_or_multiple_initial_drafts_cannot_create_a_proposal(ready, kind):
    service, work_id, scene_id, _work, thread = ready

    class InvalidDraft(DraftingProvider):
        def discuss_work(self, messages, context):
            reply = super().discuss_work(messages, context)
            if kind == "unknown_speaker":
                reply["tool_calls"][0]["arguments"]["text"] = "未确认角色: 不应进入候选。"
            else:
                reply["tool_calls"] *= 2
            return reply

    service.provider = InvalidDraft()
    with pytest.raises(DomainError):
        post(service, work_id, scene_id, thread)
    assert not service.get_work(work_id)["proposals"]


@pytest.mark.parametrize("change", ["contract", "cancel"])
def test_draft_cannot_commit_after_pinned_input_changes_or_cancellation(ready, change):
    service, work_id, scene_id, _work, thread = ready

    class ChangeDuringFollowup(DraftingProvider):
        is_simulation = False

        def discuss_work(self, messages, context):
            if not context.get("tool_followup"):
                return super().discuss_work(messages, context)
            current = service.get_work(work_id)
            if change == "contract":
                service.update_scene_contract(
                    work_id,
                    scene_id,
                    {
                        "expected_version": current["version"],
                        "title": "新场景设定",
                        "goal": "新的写作目标",
                        "stop_boundary": "新的结束位置",
                    },
                )
            else:
                service.cancel_agent_run(work_id, current["agent_runs"][0]["id"])
            return {"text": "等待核对。", "questions": []}

    service.provider = ChangeDuringFollowup()
    if change == "contract":
        with pytest.raises(DomainError):
            post(service, work_id, scene_id, thread)
    else:
        assert post(service, work_id, scene_id, thread)["cancelled"]
    current = service.get_work(work_id)
    assert not current["proposals"]
    assert not current["chapters"][0]["scenes"][0]["current_revision_id"]


def test_draft_tool_followup_does_not_echo_the_manuscript():
    observed = json.loads(
        LLMWritingProvider._result_content(
            {
                "status": "succeeded",
                "output": {
                    "kind": "scene_draft",
                    "status": "prepared",
                    "text": "私有正文",
                    "reason": "按要求起草",
                },
            }
        )
    )
    assert "text" not in observed["output"]
    assert observed["output"]["status"] == "prepared"


def test_initial_scene_model_receives_drafting_tool_and_direct_execution_prompt(monkeypatch):
    def names(task):
        return {item["name"] for item in LLMWritingProvider._agent_tool_contract(task)}

    assert "propose_scene_draft" in names("scene.draft.generate")
    assert "propose_scene_draft" not in names("scene.draft.rewrite")
    assert "propose_scene_draft" not in names("blueprint.generate")
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    captured = {}
    monkeypatch.setattr(
        provider, "_skill_system_prompt", lambda *args, **kwargs: "Synthetic writing rules"
    )

    def call(system, user, **kwargs):
        captured.update(system=system, tools=kwargs["tools"])
        return LLMCallResult('{"text":"继续讨论。","questions":[]}', "", (), None)

    monkeypatch.setattr(provider, "_call_llm", call)
    provider.discuss_work([], {"task_contract": {"id": "scene.draft.generate"}})
    assert "直接调用 propose_scene_draft" in captured["system"]
    assert "只想讨论" in captured["system"]
    assert "propose_scene_draft" in {item["name"] for item in captured["tools"]}


@pytest.mark.parametrize("state", ["pending", "saved", "discussion"])
def test_draft_tool_cannot_bypass_existing_prose_candidates_or_discussion_only(ready, state):
    service, work_id, scene_id, _work, thread = ready
    service.provider = DraftingProvider()
    if state != "discussion":
        result = post(service, work_id, scene_id, thread)
        current = result["work"]
        if state == "saved":
            service.accept_proposal(
                work_id, current["proposals"][0]["id"], {"expected_version": current["version"]}
            )

    class AlwaysDraft(DraftingProvider):
        def discuss_work(self, messages, context):
            return super().discuss_work(
                messages, {**context, "task_contract": {"id": "scene.draft.generate"}}
            )

    service.provider = AlwaysDraft()
    before = service.get_work(work_id)
    thread = next(item for item in before["conversation_threads"] if item["id"] == thread["id"])
    with pytest.raises(DomainError):
        service.post_conversation_message(
            work_id,
            thread["id"],
            {
                "expected_thread_version": thread["version"],
                "text": "只讨论这场的节奏。",
                "task_scope": {
                    "surface": "scene",
                    "scene_id": scene_id,
                    "discussion_only": state == "discussion",
                },
            },
        )
    after = service.get_work(work_id)
    assert len(after["proposals"]) == len(before["proposals"])
    assert (
        after["chapters"][0]["scenes"][0]["current_revision_id"]
        == before["chapters"][0]["scenes"][0]["current_revision_id"]
    )
