"""Prompt prefix stability, not synthetic claims of remote cache hits."""

import copy
import json

import pytest

from halocue_writing.discussion_prompt import discussion_context_json
from test_provider_tool_calling import FakeHTTPResponse, provider


def context():
    return {
        "work_id": "work-a",
        "idea": "调查旧广播室",
        "task_contract": {
            "id": "chapter.plan",
            "task_scope": {"surface": "scene", "scene_id": "s", "scene_revision_id": "r1"},
            "workflow_state": {"pending_proposal_count": 0},
        },
        "conversation_summary": {"archived_message_count": 1, "text": "旧讨论"},
        "attachments": [{"id": "file-a", "content": "导入剧本片段"}],
        "document_context": {
            "query": "第一轮问题",
            "chunks": [{"citation": "文档第一段", "text": "导入剧本依据"}],
        },
        "scene_conversation_context": {
            "schema_version": "scene-conversation-context/1.0",
            "scene": {"id": "s", "chapter_id": "c", "contract": {"goal": "寻找声音"}},
            "current_manuscript": {"revision_id": "r1", "content": {"text": "原稿"}},
            "confirmed_materials": [
                {
                    "kind": "character_card",
                    "revision_id": "card1",
                    "content": {"name": "角色甲", "voice": "稳定资料" * 1500},
                },
                {"kind": "chapter_plan", "revision_id": "plan1", "content": {"goal": "找出线索"}},
            ],
            "confirmed_references": [{"id": "ref", "content": "原作依据"}],
            "source_revision_ids": ["card1", "plan1", "r1"],
            "write_boundary": "讨论不能直接写回正式正文",
        },
        "future_field": {"z": 3, "a": [2, 1]},
    }


def test_context_layout_is_lossless_deterministic_and_does_not_mutate():
    original = context()
    before = copy.deepcopy(original)
    payload = discussion_context_json(original)
    assert json.loads(payload) == original
    assert original == before

    def reverse_keys(value):
        if isinstance(value, dict):
            return {key: reverse_keys(value[key]) for key in reversed(list(value))}
        if isinstance(value, list):
            return [reverse_keys(item) for item in value]
        return value

    assert discussion_context_json(reverse_keys(original)) == payload
    assert json.loads(payload)["future_field"]["a"] == [2, 1]


@pytest.mark.parametrize("change", ["summary", "retrieval", "attachment", "manuscript", "workflow"])
def test_dynamic_changes_do_not_break_confirmed_material_prefix(change):
    old = context()
    new = copy.deepcopy(old)
    if change == "summary":
        new["conversation_summary"]["text"] = "最新约束：不要结束本场"
    elif change == "retrieval":
        new["document_context"]["chunks"][0]["text"] = "新检索到的导入剧本依据"
    elif change == "attachment":
        new["attachments"].append({"id": "file-b", "content": "新增文档"})
    elif change == "manuscript":
        new["scene_conversation_context"]["current_manuscript"] = {
            "revision_id": "r2",
            "content": {"text": "作者刚写的新正文"},
        }
        new["scene_conversation_context"]["source_revision_ids"][-1] = "r2"
        new["task_contract"]["task_scope"]["scene_revision_id"] = "r2"
    else:
        new["task_contract"]["workflow_state"]["pending_proposal_count"] = 1
    first, second = discussion_context_json(old), discussion_context_json(new)
    boundary = first.index(', "current_manuscript"')
    assert first[:boundary] == second[:boundary]
    assert first != second
    assert json.loads(second) == new


def test_scope_and_material_changes_are_never_hidden():
    original = context()
    for key, value in [("work_id", "other-work"), ("idea", "另一份原稿")]:
        changed = copy.deepcopy(original)
        changed[key] = value
        assert discussion_context_json(changed) != discussion_context_json(original)
    changed = copy.deepcopy(original)
    changed["scene_conversation_context"]["scene"]["id"] = "other-scene"
    changed["scene_conversation_context"]["confirmed_materials"][0]["content"]["name"] = "角色乙"
    assert json.loads(discussion_context_json(changed)) == changed


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_actual_http_body_has_stable_context_and_reports_only_real_usage(monkeypatch, protocol):
    captured = []
    response_text = json.dumps(
        {"text": "离线验收回复", "questions": [], "ready_for_proposal": False}, ensure_ascii=False
    )

    def transport(request, **kwargs):
        captured.append(json.loads(request.data))
        if protocol == "anthropic":
            return FakeHTTPResponse({"content": [{"type": "text", "text": response_text}]})
        return FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", transport)
    instance = provider(protocol, "https://local-fixture.invalid/v1")
    first = context()
    first["conversation_summary"] = {"archived_message_count": 0}
    second = copy.deepcopy(first)
    second["conversation_summary"] = {"archived_message_count": 8, "text": "多轮讨论后的新约束"}
    instance.discuss_work([{"role": "user", "text": "先讨论目标"}], first)
    instance.discuss_work([{"role": "user", "text": "保留刚写的正文，补充后续"}], second)
    systems = [
        body["system"][0]["text"] if protocol == "anthropic" else body["messages"][0]["content"]
        for body in captured
    ]
    assert systems[0] == systems[1]
    user = captured[-1]["messages"][0 if protocol == "anthropic" else 1]["content"]
    rendered, history = user.removeprefix("作品上下文: ").split("\n历史消息:\n", 1)
    assert json.loads(rendered) == second
    assert history == "user: 保留刚写的正文，补充后续"
    assert instance.last_usage()["cache_status"] == "unknown"
    assert instance.last_usage()["usage_status"] == "not_reported"


def test_tool_followup_does_not_rewrite_system_prefix(monkeypatch):
    from halocue_writing.providers import LLMCallResult, ProviderUsageSnapshot

    instance = provider("openai", "https://local-fixture.invalid/v1")
    captured = []

    def call(system, user, **kwargs):
        captured.append((system, user, kwargs))
        return LLMCallResult(
            '{"text":"完成","questions":[],"ready_for_proposal":false}',
            "",
            (),
            ProviderUsageSnapshot(),
        )

    monkeypatch.setattr(instance, "_call_llm", call)
    original = context()
    instance.discuss_work([], original)
    followup = {
        **original,
        "tool_followup": True,
        "tool_results": [{"tool": "read_work", "result": {"text": "实际返回"}}],
    }
    instance.discuss_work([], followup)
    assert captured[0][0] == captured[1][0]
    assert captured[1][2]["tool_results"] == followup["tool_results"]
    assert "实际返回" in captured[1][1]


def test_saved_manual_revision_is_fresh_on_next_discussion_and_snapshot(tmp_path):
    from halocue_writing.service import WritingService
    from test_scene_conversation_harness import (
        CapturingProvider,
        create_ready_scene,
        create_scene_thread,
    )

    service = WritingService(tmp_path)
    captured = CapturingProvider()
    service.provider = captured
    work_id, scene_id, work = create_ready_scene(service)
    saved = service.save_scene_manuscript(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "base_revision_id": None,
            "blocks": [{"id": "block-1", "type": "narration", "text": "原稿：终端灯亮了一次。"}],
        },
    )
    current, thread = create_scene_thread(service, work_id, scene_id, saved["work"])
    first = service.post_conversation_message(
        work_id,
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "先讨论这段原稿，不要改写。",
        },
    )
    before = captured.discussion_contexts[-1]
    old_revision = before["scene_conversation_context"]["current_manuscript"]["revision_id"]
    revised = service.save_scene_manuscript(
        work_id,
        scene_id,
        {
            "expected_version": first["work"]["version"],
            "expected_base_revision_id": old_revision,
            "blocks": [
                {"id": "block-1", "type": "narration", "text": "新稿：终端灯熄灭，窗外传来敲击声。"}
            ],
        },
    )
    next_thread = next(
        item for item in revised["work"]["conversation_threads"] if item["id"] == thread["id"]
    )
    second = service.post_conversation_message(
        work_id,
        thread["id"],
        {
            "expected_thread_version": next_thread["version"],
            "text": "我手写更新了正文，请基于新稿讨论后续。",
        },
    )
    after = captured.discussion_contexts[-1]
    manuscript = after["scene_conversation_context"]["current_manuscript"]
    assert manuscript["revision_id"] != old_revision
    assert "新稿：终端灯熄灭" in json.dumps(manuscript["content"], ensure_ascii=False)
    assert "原稿：终端灯亮" not in json.dumps(manuscript["content"], ensure_ascii=False)
    assert after["task_contract"]["task_scope"]["scene_revision_id"] == manuscript["revision_id"]
    assert manuscript["revision_id"] in after["scene_conversation_context"]["source_revision_ids"]
    assert old_revision not in after["scene_conversation_context"]["source_revision_ids"]
    assert (
        before["scene_conversation_context"]["confirmed_materials"]
        == after["scene_conversation_context"]["confirmed_materials"]
    )
    old_json, new_json = discussion_context_json(before), discussion_context_json(after)
    boundary = old_json.index(', "current_manuscript"')
    assert old_json[:boundary] == new_json[:boundary]
    assert json.loads(new_json) == after
    run = next(
        item for item in second["work"]["agent_runs"] if item["id"] == second["agent_run_id"]
    )
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["scene_conversation_context"]["current_manuscript"] == manuscript
    assert any(
        item["kind"] == "story_blueprint"
        for item in after["scene_conversation_context"]["confirmed_materials"]
    )
    assert second["work"]["proposals"] == revised["work"]["proposals"]
