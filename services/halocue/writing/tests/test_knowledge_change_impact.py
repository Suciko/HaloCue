"""Durable dependency evidence without model calls, inference or formal writes."""

import copy
import json
from pathlib import Path

import pytest

from halocue_writing.errors import NotFound
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class ImpactProvider(FakeWritingProvider):
    def __init__(self):
        self.review_calls = 0

    def review_scene(self, *args, **kwargs):
        self.review_calls += 1
        return super().review_scene(*args, **kwargs)


def make_impact_work(service):
    service.provider = ImpactProvider()
    work = service.create_work({"title": "资料影响追踪 · 合成验收"})

    def version():
        return service.get_work(work["id"])["version"]

    service.save_brief(
        work["id"],
        {
            "expected_version": version(),
            "idea": "两位档案员检查不同房间",
            "mode": "bond_short",
            "characters": ["白露", "青禾"],
        },
    )
    service.generate_blueprint(work["id"], {"expected_version": version()})
    cards = []
    for name in ["白露", "青禾"]:
        saved = service.save_character_card(
            work["id"],
            {
                "expected_version": version(),
                "name": name,
                "source_type": "custom",
                "role": "核对公开记录",
                "voice_anchors": ["先核对再决定。"],
                "knowledge_boundary": "只知道公开档案",
                "ooc_constraints": ["不替别人决定"],
                "source_refs": ["合成验收设定"],
                "trust_status": "confirmed",
            },
        )
        cards.append(saved["card_id"])
    service.save_world_bible(
        work["id"],
        {
            "expected_version": version(),
            "title": "合成世界",
            "source_type": "custom",
            "entities": [
                {
                    "id": "world-archive",
                    "name": "档案室",
                    "kind": "place",
                    "summary": "白天可以进入",
                    "source": "合成验收设定",
                    "confidence_status": "confirmed",
                },
                {
                    "id": "world-garden",
                    "name": "庭院",
                    "kind": "place",
                    "summary": "开放场所",
                    "source": "合成验收设定",
                    "confidence_status": "confirmed",
                },
            ],
        },
    )
    chapter = service.get_work(work["id"])["chapters"][0]["id"]
    scenes = []
    for index, title in enumerate(["夜访档案室", "档案室的传闻（未选用）", "尚未检查的便条"]):
        saved = service.create_scene(
            work["id"],
            chapter,
            {
                "expected_version": version(),
                "title": title,
                "location": "本作场所",
                "goal": "核对房间出入记录",
            },
        )
        scene_id = saved["scene_id"]
        scenes.append(scene_id)
        service.configure_scene_context(
            work["id"],
            scene_id,
            {
                "expected_version": version(),
                "character_card_ids": [cards[1 if index == 1 else 0]],
                "world_item_ids": ["world-garden" if index == 1 else "world-archive"],
                "reference_file_ids": [],
            },
        )
        service.save_scene_manuscript(
            work["id"],
            scene_id,
            {
                "expected_version": version(),
                "expected_base_revision_id": None,
                "blocks": [
                    {
                        "id": "block-entry",
                        "type": "narration",
                        "text": "窗外的灯还亮着，档案员翻开当天的记录。她决定先核对登记，再决定是否打开房门。",
                    },
                    {
                        "id": "block-reply",
                        "type": "dialogue",
                        "speaker": "青禾" if index == 1 else "白露",
                        "text": "先核对记录吧。",
                    },
                ],
            },
        )
        if index < 2:
            service.review_scene(work["id"], scene_id, {"expected_version": version()})
    return service.get_work(work["id"]), {"cards": cards, "scenes": scenes, "chapter_id": chapter}


def edit_card(service, work_id, card_id, **changes):
    work = service.get_work(work_id)
    artifact = next(
        a for a in work["artifacts"] if a["kind"] == "character_card" and a["scope_id"] == card_id
    )
    return service.save_character_card(
        work_id,
        {
            **artifact["current_revision"]["content"],
            **changes,
            "expected_version": work["version"],
            "card_id": card_id,
        },
    )


def edit_world(service, work_id, entity_id, **changes):
    work = service.get_work(work_id)
    bible = copy.deepcopy(
        next(a for a in work["artifacts"] if a["kind"] == "world_bible")["current_revision"][
            "content"
        ]
    )
    next(item for item in bible["entities"] if item["id"] == entity_id).update(changes)
    return service.save_world_bible(work_id, {**bible, "expected_version": work["version"]})


def row(service, work_id, scene_id):
    return next(
        r
        for r in service.get_knowledge_change_impact(work_id)["scenes"]
        if r["scene_id"] == scene_id
    )


@pytest.fixture
def seeded(tmp_path):
    service = WritingService(tmp_path)
    work, ids = make_impact_work(service)
    yield service, work, ids
    service.close()


def test_saved_changes_map_to_exact_selected_ids_without_writing_or_calling_model(seeded):
    service, work, ids = seeded
    edit_card(service, work["id"], ids["cards"][0], knowledge_boundary="新增：不知道夜间口令")
    edit_world(service, work["id"], "world-archive", summary="夜间需要两人核验")
    before = service.get_work(work["id"])
    calls = service.provider.review_calls
    report = service.get_knowledge_change_impact(work["id"])
    first, second, never = report["scenes"]
    assert first["status"] == "needs_review"
    assert {f["key"] for d in first["dependencies"] for f in d["fields"]} == {
        "knowledge_boundary",
        "summary",
    }
    assert second["status"] == "unchanged"  # Its title contains 档案室, but IDs do not.
    assert never["status"] == "not_reviewed"
    assert service.provider.review_calls == calls
    assert service.get_work(work["id"]) == before
    assert report == service.get_knowledge_change_impact(work["id"])
    from test_agent_presentation import _assert_json_schema_instance

    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/contracts/knowledge-change-impact-1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    _assert_json_schema_instance(report, schema)


def test_rechecking_uses_latest_saved_cards_without_rewriting_manuscript(seeded):
    service, work, ids = seeded
    edit_card(service, work["id"], ids["cards"][0], role="核验来意后再开放记录")
    assert row(service, work["id"], ids["scenes"][0])["status"] == "needs_review"
    before = service.get_work(work["id"])
    service.review_scene(work["id"], ids["scenes"][0], {"expected_version": before["version"]})
    assert row(service, work["id"], ids["scenes"][0])["status"] == "unchanged"
    after = service.get_work(work["id"])
    assert before["artifacts"] == after["artifacts"]


@pytest.mark.parametrize("change", [{"trust_status": "open"}, {"status": "archived"}])
def test_unavailable_selected_card_is_not_presented_as_current(seeded, change):
    service, work, ids = seeded
    edit_card(service, work["id"], ids["cards"][0], **change)
    item = next(
        d
        for d in row(service, work["id"], ids["scenes"][0])["dependencies"]
        if d["kind"] == "character_card"
    )
    assert item["status"] == "unavailable"
    assert item["available"] is False


def test_unrelated_world_revision_does_not_invalidate_the_selected_card(seeded):
    service, work, ids = seeded
    edit_world(service, work["id"], "world-garden", summary="庭院新增了一座喷泉")
    assert row(service, work["id"], ids["scenes"][0])["status"] == "unchanged"
    assert row(service, work["id"], ids["scenes"][1])["status"] == "needs_review"


def test_removed_and_added_dependencies_are_explained(seeded):
    service, work, ids = seeded
    service.configure_scene_context(
        work["id"],
        ids["scenes"][0],
        {
            "expected_version": work["version"],
            "character_card_ids": [ids["cards"][1]],
            "world_item_ids": ["world-garden"],
            "reference_file_ids": [],
        },
    )
    item = row(service, work["id"], ids["scenes"][0])
    assert {d["status"] for d in item["dependencies"]} == {"removed", "added"}
    assert "scene_contract_changed" in item["reasons"]


def test_corrupt_latest_review_does_not_fall_back_to_clean_status(seeded):
    service, work, ids = seeded
    report = row(service, work["id"], ids["scenes"][0])
    run = service.get_agent_run(work["id"], report["baseline"]["run_id"])
    service.repo.atomic_write_text(run["input_snapshot_uri"], "{}")
    result = row(service, work["id"], ids["scenes"][0])
    assert result["status"] == "baseline_unavailable"
    assert all(d["status"] == "baseline_unavailable" for d in result["dependencies"])


def test_report_is_work_scoped_and_survives_service_reopen(seeded, tmp_path):
    service, work, ids = seeded
    other = service.create_work({"title": "空作品"})
    assert service.get_knowledge_change_impact(other["id"])["scenes"] == []
    with pytest.raises(NotFound):
        service.get_knowledge_change_impact("work-does-not-exist")
    before = service.get_knowledge_change_impact(work["id"])
    service.close()
    reopened = WritingService(tmp_path)
    try:
        assert reopened.get_knowledge_change_impact(work["id"]) == before
    finally:
        reopened.close()


def test_same_display_name_never_substitutes_another_card_id(seeded):
    service, work, ids = seeded
    edit_card(service, work["id"], ids["cards"][1], name="白露", role="另一个同名人物的新职责")
    first = row(service, work["id"], ids["scenes"][0])
    assert first["status"] == "unchanged"
    assert {d["target_id"] for d in first["dependencies"] if d["kind"] == "character_card"} == {
        ids["cards"][0]
    }
    assert row(service, work["id"], ids["scenes"][1])["status"] == "needs_review"


def test_archived_world_card_and_new_manuscript_require_recheck(seeded):
    service, work, ids = seeded
    edit_world(service, work["id"], "world-archive", status="archived")
    first = row(service, work["id"], ids["scenes"][0])
    assert (
        next(d for d in first["dependencies"] if d["kind"] == "world_card")["status"]
        == "unavailable"
    )
    current = service.get_work(work["id"])
    script = next(
        a
        for a in current["artifacts"]
        if a["kind"] == "scene_script" and a["scope_id"] == ids["scenes"][1]
    )
    blocks = copy.deepcopy(script["current_revision"]["content"]["blocks"])
    blocks[0]["text"] += "她又等了片刻。"
    service.save_scene_manuscript(
        work["id"],
        ids["scenes"][1],
        {
            "expected_version": current["version"],
            "expected_base_revision_id": script["current_revision_id"],
            "blocks": blocks,
        },
    )
    second = row(service, work["id"], ids["scenes"][1])
    assert second["changed_count"] == 0
    assert second["reasons"] == ["manuscript_changed"]
    assert second["status"] == "needs_review"


def test_legacy_scope_is_explicitly_labeled_not_name_search_through_manuscript(seeded):
    service, work, ids = seeded
    saved = service.create_scene(
        work["id"],
        ids["chapter_id"],
        {"expected_version": work["version"], "title": "旧作品兼容场景"},
    )
    scene = row(service, work["id"], saved["scene_id"])
    assert scene["selection_mode"] == "legacy"
    assert scene["status"] == "not_reviewed"
    assert len(scene["dependencies"]) == 4
    assert {d["basis"] for d in scene["dependencies"]} == {"legacy_selection"}


def test_materializing_empty_optional_world_ids_is_not_a_knowledge_change(seeded):
    service, work, ids = seeded
    edit_world(service, work["id"], "world-archive", participant_character_ids=[])
    assert row(service, work["id"], ids["scenes"][0])["status"] == "unchanged"
