"""Discussion recovery and author-requested reuse of curated references."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from halocue_writing.bundled_character_catalog import BundledCharacterCatalog
from halocue_writing.discussion_response import recover_discussion_text
from halocue_writing.providers import FakeWritingProvider, LLMCallResult, LLMWritingProvider
from halocue_writing.service import WritingService
from test_character_card_import import formal_card


REPLY = {
    "text": "方向已经清楚，可以写这一场。",
    "questions": ["结尾停在她睡着了吗？"],
    "decision_card": None,
    "reasoning_summary": "人物与结束边界已明确。",
    "ready_for_proposal": True,
    "ready_to_organize": False,
    "next_step": "structure",
}


@pytest.mark.parametrize(
    "wrapper",
    ["{}", "```json\n{}\n```", "先保留对白。\n```json\n{}\n```\n结尾保持简短。", "说明：\n{}"],
)
def test_mixed_discussion_is_public_fields_not_raw_json(wrapper):
    source = wrapper.format(json.dumps(REPLY, ensure_ascii=False))
    recovered = recover_discussion_text(source)
    assert REPLY["text"] in recovered["text"]
    assert recovered["questions"] == REPLY["questions"]
    assert '"ready_for_proposal"' not in recovered["text"]
    assert recovered["ready_for_proposal"] is False
    if source.startswith("先保留"):
        assert "先保留对白。" in recovered["text"]
        assert "结尾保持简短。" in recovered["text"]


def test_recovery_does_not_execute_embedded_tools_or_convert_code_samples():
    source = json.dumps({**REPLY, "tool_calls": [{"tool": "organize_current_plan"}]})
    assert "tool_calls" not in recover_discussion_text(source)
    assert recover_discussion_text('示例：{"text":"value"}') is None
    assert recover_discussion_text(source + "\n" + source) is None
    assert recover_discussion_text('```json\n{"text":"没写完", "questions":[') is None


def test_provider_recovers_mixed_answer_and_service_recovers_nested_text(monkeypatch):
    source = "开始写作前，先确认结尾。\n```json\n" + json.dumps(REPLY, ensure_ascii=False) + "\n```"
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        provider, "_call_llm", lambda *args, **kwargs: LLMCallResult(source, "", (), None)
    )
    reply = provider.discuss_work([], {})
    assert reply["questions"] == REPLY["questions"]
    nested = WritingService._validate_discussion_reply({"text": source, "questions": []})
    assert nested["questions"] == REPLY["questions"]
    assert '"text"' not in nested["text"]


class QuietProvider(FakeWritingProvider):
    def discuss_work(self, messages, context):
        self.context = context
        return {"text": "我们按这个方向继续。", "questions": [], "ready_for_proposal": False}


class ChapterOrganizer(QuietProvider):
    def __init__(self, chapter_id):
        self.chapter_id = chapter_id

    def discuss_work(self, messages, context):
        if context.get("tool_followup"):
            return {"text": "章节安排会在当前构思对话中交给你核对。", "questions": []}
        return {
            "text": "我来整理本章细纲。",
            "questions": [],
            "tool_calls": [
                {"tool": "organize_current_plan", "arguments": {"chapter_id": self.chapter_id}}
            ],
        }

    def generate_chapter_plan(self, messages, context):
        self.chapter_messages = messages
        self.chapter_context = context
        return {
            "schema_version": "chapter-plan/1.0",
            "title": "夜间活动室细纲",
            "chapter_goal": "找到提示灯的回应规律。",
            "beats": ["两人核对夜间活动室的记录。", "提示灯第一次回应，两人停下观察。"],
            "continuity_notes": ["结尾只保留第一次回应，不添加反派。"],
        }


@pytest.mark.parametrize(
    "outcome", ["cancel", "authorization_change", "invalid_output", "provider_error"]
)
def test_deferred_chapter_result_is_fenced_and_finishes_on_failure(tmp_path, outcome):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from test_scene_conversation_harness import create_ready_scene

    service = WritingService(tmp_path / "data")
    work_id, _scene_id, work = create_ready_scene(service)
    started, release = Event(), Event()

    class DelayedOrganizer(ChapterOrganizer):
        def generate_chapter_plan(self, messages, context):
            started.set()
            assert release.wait(timeout=15)
            if outcome == "invalid_output":
                return {}
            if outcome == "provider_error":
                raise RuntimeError("synthetic planning failure")
            return super().generate_chapter_plan(messages, context)

    service.provider = DelayedOrganizer(work["chapters"][0]["id"])
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(send, service, work, "整理这一章的细纲。")
            try:
                assert started.wait(timeout=5)
                current = service.get_work(work_id)
                run_id = current["conversation_threads"][0]["messages"][-1]["agent_run_id"]
                run = next(item for item in current["agent_runs"] if item["id"] == run_id)
                assert run["status"] == "running"
                if outcome == "cancel":
                    service.cancel_agent_run(work_id, run["id"])
                elif outcome == "authorization_change":
                    thread = current["conversation_threads"][0]
                    service.update_conversation_thread(
                        work_id,
                        thread["id"],
                        {
                            "expected_thread_version": thread["version"],
                            "permission_mode": "managed",
                        },
                    )
            finally:
                release.set()
            if outcome == "provider_error":
                with pytest.raises(RuntimeError, match="synthetic planning failure"):
                    future.result(timeout=10)
            else:
                future.result(timeout=10)
        final = service.get_agent_run(work_id, run["id"])
        assert final["status"] == (
            "cancelled" if outcome in {"cancel", "authorization_change"} else "failed"
        )
        assert final["finished_at"]
        assert not any(
            item["kind"] == "chapter_plan" for item in service.get_work(work_id)["proposals"]
        )
    finally:
        release.set()
        service.close()


def make_catalog(root):
    root.mkdir()
    for name, aliases in [
        ("空崎日奈", ["日奈", "Hina"]),
        ("天雨亚子", ["亚子", "Ako"]),
        ("一之濑明日奈", ["明日奈", "Asuna"]),
    ]:
        (root / f"{name}.json").write_text(
            json.dumps(formal_card(name, aliases), ensure_ascii=False), encoding="utf-8"
        )
    return BundledCharacterCatalog(root)


@pytest.fixture
def prepared(tmp_path):
    service = WritingService(tmp_path / "data")
    service.bundled_characters = make_catalog(tmp_path / "cards")
    service.provider = QuietProvider()
    work = service.create_work({"title": "讨论引用资料验收"})
    yield service, work
    service.close()


def send(service, work, text):
    thread = work["conversation_threads"][0]
    return service.post_conversation_message(
        work["id"], thread["id"], {"expected_thread_version": thread["version"], "text": text}
    )["work"]


def cards(work):
    return [artifact for artifact in work["artifacts"] if artifact["kind"] == "character_card"]


def test_mentions_import_before_model_context_once_and_survive_restart(prepared):
    service, work = prepared
    updated = send(service, work, "想写日奈和亚子的日常，老师不出场。")
    assert {card["current_revision"]["content"]["name"] for card in cards(updated)} == {
        "空崎日奈",
        "天雨亚子",
    }
    receipt = updated["conversation_threads"][0]["messages"][-1]["content"]["character_resolution"]
    import jsonschema

    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/contracts/character-reference-resolution-1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(receipt, schema)
    assert len(receipt["added"]) == 2
    assert service.provider.context["character_resolution"] == receipt
    assert all(card["current_revision"]["content"]["ba_profile"] for card in cards(updated))
    ids = [card["current_revision_id"] for card in cards(updated)]
    repeated = send(service, updated, "日奈和亚子继续在办公室聊天。")
    assert [card["current_revision_id"] for card in cards(repeated)] == ids
    assert not repeated["proposals"]
    assert not any(card["kind"] == "scene_script" for card in repeated["artifacts"])
    service.close()
    fresh = WritingService(service.repo.data_dir)
    try:
        assert [card["current_revision_id"] for card in cards(fresh.get_work(work["id"]))] == ids
    finally:
        fresh.close()


def test_continue_backfills_original_author_mentions_from_an_older_work(prepared, tmp_path):
    service, work = prepared
    catalog = service.bundled_characters
    service.bundled_characters = BundledCharacterCatalog(tmp_path / "unavailable-old-pack")
    old = send(service, work, "日奈和亚子在办公室。")
    assert not cards(old)
    service.bundled_characters = catalog
    updated = send(service, old, "继续")
    assert {card["current_revision"]["content"]["name"] for card in cards(updated)} == {"空崎日奈", "天雨亚子"}
    assert len(service.provider.context["character_resolution"]["added"]) == 2


def test_existing_custom_and_archived_cards_are_not_overwritten(prepared):
    service, work = prepared
    work = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "name": "日奈",
            "source_type": "custom",
            "source_refs": ["作者确认"],
            "voice_anchors": ["作者自定义语气"],
        },
    )["work"]
    original = cards(work)[0]
    updated = send(service, work, "写日奈的日常。")
    assert cards(updated)[0]["current_revision_id"] == original["current_revision_id"]
    archived = service.archive_character_card(
        work["id"], original["scope_id"], {"expected_version": updated["version"]}
    )["work"]
    updated = send(service, archived, "日奈这次不出场。")
    assert cards(updated)[0]["current_revision"]["content"]["status"] == "archived"
    updated = send(service, updated, "日奈改为出场。")
    receipt = updated["conversation_threads"][0]["messages"][-1]["content"]["character_resolution"]
    assert receipt["blocked"] and not receipt["added"]


def test_full_name_overlap_exclusions_and_ambiguous_aliases(prepared):
    service, _work = prepared
    catalog = service.bundled_characters
    result = catalog.resolve_mentions("明日奈出场，不要写日奈。亚子不出场。")
    assert [item["name"] for item in result["matches"]] == ["一之濑明日奈"]
    assert not catalog.resolve_mentions("Hinata doesn't refer to HinaX")["matches"]
    path = catalog.root / "另一位日奈.json"
    path.write_text(
        json.dumps(formal_card("另一位日奈", ["日奈"]), ensure_ascii=False), encoding="utf-8"
    )
    result = catalog.resolve_mentions("日奈和亚子在办公室。")
    assert len(result["ambiguous"]) == 1
    assert [item["name"] for item in result["matches"]] == ["天雨亚子"]


def test_missing_pack_is_reported_and_old_author_mentions_can_resume(prepared, tmp_path):
    service, work = prepared
    catalog = service.bundled_characters
    service.bundled_characters = BundledCharacterCatalog(tmp_path / "missing")
    updated = send(service, work, "想写日奈和亚子的日常。")
    assert not cards(updated)
    assert not updated["conversation_threads"][0]["messages"][-1]["content"][
        "character_resolution"
    ]["available"]
    service.bundled_characters = catalog
    updated = send(service, updated, "现在开始写正文。")
    assert len(cards(updated)) == 2


def test_automatically_imported_profiles_satisfy_runtime_character_readiness(prepared):
    service, work = prepared
    work = send(service, work, "写日奈和亚子的短日常。")
    work = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "两人在办公室聊一件小事。",
            "mode": "bond_short",
            "characters": ["日奈", "亚子"],
        },
    )["work"]
    work = service.generate_blueprint(work["id"], {"expected_version": work["version"]})["work"]
    created = service.create_chapter(
        work["id"], {"expected_version": work["version"], "title": "午后"}
    )
    scene = service.create_scene(
        work["id"],
        created["chapter_id"],
        {
            "expected_version": created["work"]["version"],
            "title": "办公室",
            "location": "风纪委员会办公室",
            "goal": "以一件日常小事收束",
            "stop_boundary": "日奈睡着后结束",
        },
    )
    context = service.assemble_context(work["id"], scene["scene_id"])
    assert not context["readiness"]["missing_runtime_character_cards"]
    assert {card["name"] for card in context["runtime_character_cards"]} == {"空崎日奈", "天雨亚子"}
    assert context["readiness"]["real_ba_writing"] == "ready_for_provider"


def test_next_step_is_optional_and_only_known_actions_are_accepted():
    from halocue_writing.errors import DomainError

    assert (
        WritingService._validate_discussion_reply({"text": "继续讨论", "next_step": None})[
            "next_step"
        ]
        is None
    )
    for action in ("organize", "review", "structure", "draft"):
        assert (
            WritingService._validate_discussion_reply({"text": "可以继续", "next_step": action})[
                "next_step"
            ]
            == action
        )
    for invalid in ("http://example.invalid", "delete", {}, True):
        with pytest.raises(DomainError, match="下一步"):
            WritingService._validate_discussion_reply({"text": "可以继续", "next_step": invalid})


def test_scene_inherits_selected_ideation_and_can_retrieve_originals_after_restart(tmp_path):
    from halocue_writing.agent_tools import ToolExecutionContext
    from halocue_writing.errors import DomainError
    from test_scene_conversation_harness import create_ready_scene

    service = WritingService(tmp_path / "data")
    service.provider = QuietProvider()
    work_id, scene_id, work = create_ready_scene(service)
    work = send(service, work, "结尾停在提示灯第一次回应，不要添加反派。")
    source = next(item for item in work["conversation_threads"] if item["scope_type"] == "work")
    source_message = next(item for item in source["messages"] if item["role"] == "user")
    foreign = service.create_work({"title": "其他作品"})
    foreign = send(service, foreign, "这是另一作品，不能带入。")
    with pytest.raises(DomainError, match="承接"):
        service.create_conversation_thread(
            work_id,
            {
                "expected_version": work["version"],
                "scope_type": "scene",
                "scope_id": scene_id,
                "discussion_source_thread_id": foreign["conversation_threads"][0]["id"],
            },
        )
    created = service.create_conversation_thread(
        work_id,
        {
            "expected_version": work["version"],
            "scope_type": "scene",
            "scope_id": scene_id,
            "discussion_source_thread_id": source["id"],
        },
    )
    target = next(
        item
        for item in created["work"]["conversation_threads"]
        if item["id"] == created["thread_id"]
    )
    service.post_conversation_message(
        work_id,
        target["id"],
        {
            "expected_thread_version": target["version"],
            "text": "沿用前面的要求，先讨论本场节奏，不要写正文。",
        },
    )
    continuation = service.provider.context["scene_conversation_context"]["discussion_continuation"]
    import jsonschema

    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/contracts/discussion-continuation-1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(continuation, schema)
    jsonschema.validate(
        target["messages"][-1]["content"]["discussion_source"], schema["$defs"]["source_link"]
    )
    assert continuation["thread_id"] == source["id"]
    assert source_message["content"]["text"] in [
        item["text"] for item in continuation["recent_messages"]
    ]
    assert all(
        item["id"] != foreign["conversation_threads"][0]["messages"][0]["id"]
        for item in continuation["recent_messages"]
    )
    with service.repo.transaction() as connection:
        tool_context = ToolExecutionContext(
            connection, service, work_id, target["id"], "scene", scene_id, "review"
        )
        result = service.agent_tools.execute(
            tool_context,
            "read_conversation_history",
            {"message_id": source_message["id"], "length": 8},
        )
        assert result.status == "succeeded"
        assert result.output["text"] == source_message["content"]["text"][:8]
        foreign_result = service.agent_tools.execute(
            tool_context,
            "read_conversation_history",
            {"message_id": foreign["conversation_threads"][0]["messages"][0]["id"]},
        )
        assert foreign_result.status == "failed"
    service.close()
    restored = WritingService(tmp_path / "data")

    class DraftCapturingProvider(QuietProvider):
        def generate_scene(self, context):
            self.draft_context = context
            return super().generate_scene(context)

    restored.provider = DraftCapturingProvider()
    target = next(
        item
        for item in restored.get_work(work_id)["conversation_threads"]
        if item["id"] == target["id"]
    )
    restored.post_conversation_message(
        work_id,
        target["id"],
        {"expected_thread_version": target["version"], "text": "仍然先讨论节奏，不要写正文。"},
    )
    assert (
        restored.provider.context["scene_conversation_context"]["discussion_continuation"][
            "thread_id"
        ]
        == source["id"]
    )
    current = restored.get_work(work_id)
    target = next(item for item in current["conversation_threads"] if item["id"] == target["id"])
    result = restored.generate_scene_proposal_from_conversation(
        work_id,
        target["id"],
        {
            "expected_version": current["version"],
            "expected_thread_version": target["version"],
            "instruction": "现在按构思里保留的边界起草这一场。",
        },
    )
    assert (
        restored.provider.draft_context["scene_conversation_context"]["discussion_continuation"][
            "thread_id"
        ]
        == source["id"]
    )
    assert any(
        item["id"] == result["proposal_id"] and item["status"] == "pending"
        for item in result["work"]["proposals"]
    )
    assert not result["work"]["chapters"][0]["scenes"][0]["current_revision_id"]
    restored.close()


def test_ideation_can_organize_chapter_and_outline_syncs_without_overwriting_edits(tmp_path):
    from test_scene_conversation_harness import create_ready_scene

    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service, title="夜间活动室")
    chapter_id = work["chapters"][0]["id"]
    service.provider = QuietProvider()
    work = send(service, work, "结尾只保留第一次回应，不添加反派。")
    service.provider = ChapterOrganizer(chapter_id)
    result = service.post_conversation_message(
        work_id,
        work["conversation_threads"][0]["id"],
        {
            "expected_thread_version": work["conversation_threads"][0]["version"],
            "task_scope": {"surface": "work"},
            "text": "把夜间调查这一章整理成细纲。",
        },
    )
    pending = result["work"]
    proposal = next(
        item for item in pending["proposals"] if item["id"] == result["auto_proposal_id"]
    )
    assert proposal["kind"] == "chapter_plan" and proposal["scope_id"] == chapter_id
    assert proposal["candidate"]["source_thread_id"] == work["conversation_threads"][0]["id"]
    assert any("不添加反派" in item["text"] for item in service.provider.chapter_messages)
    assert not any(item["kind"] == "chapter_plan" for item in pending["artifacts"])
    accepted = service.accept_proposal(
        work_id, proposal["id"], {"expected_version": pending["version"]}
    )["work"]
    outline = service.authoring.get_outline(work_id)
    doc = next(item for item in outline["documents"] if item["scope_id"] == chapter_id)
    assert "找到提示灯的回应规律" in doc["text"]
    assert "不添加反派" in doc["adopted_text"]
    saved = service.authoring.save_outline(
        work_id,
        {
            "expected_version": accepted["version"],
            "scope_type": "chapter",
            "scope_id": chapter_id,
            "expected_base_revision_id": None,
            "text": "手写精修：保持短促对白。",
        },
    )["work"]
    service.provider = ChapterOrganizer(chapter_id)
    second = send(service, saved, "再整理这章的承接。")
    next_proposal = next(
        item
        for item in second["proposals"]
        if item["kind"] == "chapter_plan" and item["status"] == "pending"
    )
    service.accept_proposal(work_id, next_proposal["id"], {"expected_version": second["version"]})
    doc = next(
        item
        for item in service.authoring.get_outline(work_id)["documents"]
        if item["scope_id"] == chapter_id
    )
    assert doc["text"] == "手写精修：保持短促对白。"
    assert doc["source_changed"]
    assert service.get_work(work_id)["chapters"][0]["scenes"][0]["id"] == scene_id
    assert not service.get_work(work_id)["chapters"][0]["scenes"][0]["current_revision_id"]
    service.close()


def test_organize_chapter_tool_rejects_foreign_and_other_chapter_targets(tmp_path):
    from halocue_writing.agent_tools import ToolExecutionContext
    from test_scene_conversation_harness import create_ready_scene

    service = WritingService(tmp_path)
    work_id, _scene_id, work = create_ready_scene(service)
    foreign = service.create_work({"title": "其他作品"})
    with service.repo.connect() as connection:
        context = ToolExecutionContext(
            connection=connection,
            service=service,
            work_id=work_id,
            thread_id=work["conversation_threads"][0]["id"],
            scope_type="work",
            scope_id=work_id,
            permission_mode="review",
        )
        result = service.agent_tools.execute(
            context, "organize_current_plan", {"chapter_id": foreign["chapters"][0]["id"]}
        )
        assert result.status == "failed"
        assert "不属于当前作品" in result.error["message"]
        context.scope_type = "chapter"
        context.scope_id = "another-chapter"
        result = service.agent_tools.execute(
            context, "organize_current_plan", {"chapter_id": work["chapters"][0]["id"]}
        )
        assert result.status == "failed"
        assert "不能整理其他章节" in result.error["message"]
    service.close()
