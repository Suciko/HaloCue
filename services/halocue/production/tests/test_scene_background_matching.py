"""Scene-specific background advice uses structured evidence, not dialogue guesses."""

import copy
import pytest

from halocue_production.scene_backgrounds import scene_context, assess_background, rank_items
from halocue_production.errors import ProductionError
from test_resource_annotations import adapter_with


def scene_cards(title="社团室 · 深夜 · 室内"):
    return [
        {"card_id": "s1", "kind": "scene", "current": {"title": title}},
        {"card_id": "bg1", "kind": "dir", "current": {"cmd": "bg", "arg": "BG_Day"}},
        {"card_id": "line1", "kind": "line", "current": {"text": "明天下午去操场，别忘了！"}},
        {"card_id": "s2", "kind": "scene", "current": {"title": "操场 白天"}},
    ]


def test_context_uses_heading_not_dialogue_and_does_not_mutate():
    cards = scene_cards()
    before = copy.deepcopy(cards)
    context = scene_context(cards, "s1", {})
    assert context["requirements"] == {"time": "夜间", "space": "室内", "place": "社团室"}
    assert context["current_background"] == "BG_Day"
    assert cards == before


def test_unknown_and_ambiguous_titles_do_not_claim_match():
    context = scene_context(scene_cards("夜间与白天的约定"), "s1", {})
    assert "time" not in context["requirements"]
    assert context["notes"]
    assert assess_background({"key": "BG_X"}, context)["status"] == "unknown"
    assert "time" not in scene_context(scene_cards("birthday party"), "s1", {})["requirements"]


def test_rank_before_pagination_current_conflict_remains_visible():
    context = scene_context(scene_cards(), "s1", {})
    rows = [
        {
            "key": "BG_Day",
            "name": "A",
            "place": "社团室",
            "time": "day",
            "indoor_outdoor": "indoor",
        },
        {"key": "BG_Unknown", "name": "B", "place": "社团室"},
        {
            "key": "BG_Night",
            "name": "Z",
            "place": "社团室",
            "time": "night",
            "indoor_outdoor": "室内",
        },
    ]
    before = copy.deepcopy(rows)
    ranked = rank_items(rows, context)
    assert [row["key"] for row in ranked] == ["BG_Night", "BG_Unknown", "BG_Day"]
    assert ranked[-1]["scene_match"]["current"]
    assert "需要夜间" in ranked[-1]["scene_match"]["conflicts"][0]
    assert ranked[1]["scene_match"]["unknown"]
    assert rows == before


def test_explicit_overrides_and_negative_annotations_are_not_matches():
    context = scene_context(scene_cards(), "s1", {"time": "白天", "space": "室外", "place": "操场"})
    assert context["sources"]["time"] == "本次筛选"
    item = {
        "key": "BG_X",
        "time": "night",
        "place": "社团室",
        "indoor_outdoor": "indoor",
        "avoid_when": "操场 白天 室外",
        "has_fixed_characters": True,
        "dialogue_suitable": False,
    }
    advice = assess_background(item, context)
    assert len(advice["conflicts"]) == 5
    assert advice["matches"] == []


def test_unknown_location_alias_not_falsely_rejected():
    context = scene_context(scene_cards(), "s1", {"place": "游戏开发部活动室"})
    advice = assess_background({"key": "BG_X", "place": "社团室"}, context)
    assert not advice["conflicts"]
    assert advice["unknown"]


def test_scene_id_must_resolve_to_current_scene():
    for value in ["gone", "line1"]:
        with pytest.raises(ProductionError) as error:
            scene_context(scene_cards(), value, {})
        assert error.value.code == "scene_not_found"


def test_adapter_ranks_entire_frozen_catalogue_before_paging():
    resources = {
        "bg": {"BG_Day": 1, "BG_Night": 2},
        "bg_label": {
            "BG_Day": {"label": "A", "place": "社团室", "time": "白天", "indoor_outdoor": "室内"},
            "BG_Night": {"label": "Z", "place": "社团室", "time": "夜晚", "indoor_outdoor": "室内"},
        },
    }
    adapter = adapter_with(resources)
    adapter.draft_detail = lambda token: {"cards": scene_cards()}
    filters = {"scene_card_id": "s1", "scene_time": "深夜"}
    first = adapter.list_draft_resources("token", "backgrounds", limit=1, filters=filters)
    second = adapter.list_draft_resources(
        "token", "backgrounds", offset=1, limit=1, filters=filters
    )
    assert first["items"][0]["key"] == "BG_Night"
    assert second["items"][0]["key"] == "BG_Day"
    assert first["scene_context"]["counts"] == {"match": 1, "unknown": 0, "conflict": 1}
    assert first["total"] == 2
    assert first["frozen"] is True
    assert "scene_context" not in adapter.list_draft_resources("token", "backgrounds")


def test_http_scene_advice_uses_current_cards_and_stays_read_only(settings, tmp_path):
    import json
    from dataclasses import replace
    from services.halocue.production.tests.test_http_api import api, request

    path = tmp_path / "resources.json"
    path.write_text(
        json.dumps(
            {
                "bg": {"BG_Day": 1, "BG_Night": 2},
                "sounds": [],
                "characters": [],
                "enums": {"emoticon": {}, "action": {}},
                "bg_label": {
                    "BG_Day": {"label": "A", "time": "白天"},
                    "BG_Night": {"label": "Z", "time": "夜晚"},
                },
            }
        ),
        encoding="utf-8",
    )
    with api(replace(settings, resource_index=path)) as base:
        status, _, created = request(
            base,
            "/api/v1/production-runs",
            {
                "project": "synthetic-scene-match",
                "source": {"kind": "inline", "text": "## 深夜\n@bg BG_Day\n旁白: 明天去操场。\n"},
            },
            "POST",
        )
        assert status == 201
        run_id = created["run"]["run_id"]
        scene = next(card for card in created["draft"]["cards"] if card["kind"] == "scene")
        endpoint = f"/api/v1/production-runs/{run_id}"
        status, _, ranked = request(
            base, endpoint + "/resources/backgrounds?scene_card_id=" + scene["card_id"] + "&limit=1"
        )
        assert status == 200
        assert ranked["items"][0]["key"] == "BG_Night"
        assert ranked["scene_context"]["requirements"] == {"time": "夜间"}
        assert ranked["scene_context"]["current_background"] == "BG_Day"
        status, _, invalid = request(
            base, endpoint + "/resources/backgrounds?scene_card_id=missing"
        )
        assert status == 404
        assert invalid["error"]["code"] == "scene_not_found"
        _, _, after = request(base, endpoint)
        assert after["draft"] == created["draft"]


def test_existing_background_uses_validated_resolution_and_preserves_identity(settings, tmp_path):
    from services.halocue.production.tests.test_service import configured_resource_settings
    from services.halocue.production.tests.test_http_api import api, request

    with api(configured_resource_settings(settings, tmp_path)) as base:
        _, _, created = request(
            base,
            "/api/v1/production-runs",
            {
                "project": "synthetic-background-replacement",
                "source": {
                    "kind": "inline",
                    "text": "## 社团室\n@bg BG_Classroom\n旁白: 保持这句原文。\n",
                },
            },
            "POST",
        )
        cards = created["draft"]["cards"]
        bg = next(card for card in cards if card["kind"] == "dir")
        line = next(card for card in cards if card["kind"] == "line")
        endpoint = f"/api/v1/production-runs/{created['run']['run_id']}/cards/"
        version = created["draft"]["draft_version"]
        payload = {
            "action": "select",
            "background_key": "BG_RainyStation",
            "expected_draft_version": version,
        }
        status, _, invalid_target = request(
            base, endpoint + line["card_id"] + "/background-resolution", payload, "POST"
        )
        assert status == 409
        status, _, missing = request(
            base,
            endpoint + bg["card_id"] + "/background-resolution",
            {**payload, "background_key": "BG_NotFrozen"},
            "POST",
        )
        assert status == 404
        status, _, updated = request(
            base, endpoint + bg["card_id"] + "/background-resolution", payload, "POST"
        )
        assert status == 200
        same = next(card for card in updated["draft"]["cards"] if card["card_id"] == bg["card_id"])
        assert same["current"] == {"cmd": "bg", "arg": "BG_RainyStation"}
        assert same["review_state"] == "pending"
        assert (
            next(card for card in updated["draft"]["cards"] if card["kind"] == "line")["current"]
            == line["current"]
        )
        status, _, stale = request(
            base, endpoint + bg["card_id"] + "/background-resolution", payload, "POST"
        )
        assert status == 409
        assert stale["error"]["code"] == "revision_conflict"


def test_ambiguous_candidate_time_and_weather_shorthand():
    context = scene_context(scene_cards(), "s1", {"weather": "雨"})
    assert context["requirements"]["weather"] == "雨天"
    advice = assess_background(
        {"key": "BG_Mixed", "time": "白天 / 夜间", "weather": "rain"}, context
    )
    assert "天气：雨天" in advice["matches"]
    assert "时间：夜间" not in advice["matches"]
    assert any("多个标记" in message for message in advice["unknown"])
