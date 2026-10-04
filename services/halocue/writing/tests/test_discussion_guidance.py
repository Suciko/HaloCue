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
