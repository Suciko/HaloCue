import json

from halocue_production.service import ProductionService
from halocue_production.name_baseline import CharacterNameBaseline
from halocue_production.automatic_resources import background_match, character_match
from test_service import configured_resource_settings


def test_bundled_aliases_search_without_machine_baseline(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    index["characters"] = [
        {"identifier": "ako", "name": "亞子", "spine": "CharacterSpine_ako", "faces": ["00"]}
    ]
    configured.resource_index.write_text(json.dumps(index), encoding="utf-8")
    service = ProductionService(configured)
    assert service.list_resources("characters", query="亚子")["items"][0]["identifier"] == "ako"
    created = service.create_run(
        {"project": "aliases", "source": {"kind": "inline", "text": "亚子：咖啡。"}}
    )
    assert (
        service.list_run_resources(created["run"]["run_id"], "characters", query="天雨亚子")[
            "items"
        ][0]["identifier"]
        == "ako"
    )
    assert CharacterNameBaseline().resolve(index["characters"][0])["source_name"] == "亞子"


def test_requested_auto_match_preserves_ambiguity_and_authored_background(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    index["characters"] = [
        {"identifier": "ako", "name": "亞子", "spine": "CharacterSpine_ako", "faces": ["00"]},
        {"identifier": "hina-a", "name": "日奈", "spine": "hina-a", "faces": ["00"]},
        {"identifier": "hina-b", "name": "日奈", "spine": "hina-b", "faces": ["00"]},
    ]
    index["bg_label"] = {"BG_Classroom": {"label": "教室", "place": "教室"}}
    configured.resource_index.write_text(json.dumps(index), encoding="utf-8")
    source = "## 教室\n亚子：咖啡。\n日奈：嗯。\n## 车站\n@bg BG_RainyStation\n亚子：到了。"
    service = ProductionService(configured)
    created = service.create_run(
        {
            "project": "automatic",
            "auto_match_resources": True,
            "source": {"kind": "inline", "text": source},
        }
    )
    draft = created["draft"]
    assert draft["cast"]["cast"]["亚子"]["id"] == "ako"
    assert draft["cast"]["cast"].get("日奈", {}).get("kind", "unset") == "unset"
    keys = [
        c["current"]["arg"]
        for c in draft["cards"]
        if c["kind"] == "dir" and c["current"].get("cmd") == "bg"
    ]
    assert keys == ["BG_Classroom", "BG_RainyStation"]
    assert all(c["review_state"] != "approved" for c in draft["cards"])
    version = draft["draft_version"]
    again = service.adapter.match_missing_resources(draft["draft_token"])
    assert again["draft_version"] == version


def test_background_annotations_join_case_without_changing_aa_identity(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    index["bg_label"] = {"BG_Classroom": {"label": "Classroom"}}
    index["scene_labels"] = {
        "background": {
            "bg_classroom": {
                "label": "放学后的教室",
                "place": "教室",
                "category_path_cn": "校园 / 教室",
                "time": "day",
            }
        }
    }
    configured.resource_index.write_text(json.dumps(index), encoding="utf-8")
    service = ProductionService(configured)
    created = service.create_run(
        {
            "project": "labels",
            "auto_match_resources": True,
            "source": {"kind": "inline", "text": "## 教室\n亚子：咖啡。"},
        }
    )
    result = service.list_run_resources(
        created["run"]["run_id"], "backgrounds", query="放学", filters={"category": "校园"}
    )
    assert result["total"] == 1
    assert result["items"][0]["key"] == "BG_Classroom"
    assert result["items"][0]["name"] == "放学后的教室"
    assert any(c["current"].get("arg") == "BG_Classroom" for c in created["draft"]["cards"])
    assert created["draft"]["background_resources"]["BG_Classroom"]["name"] == "放学后的教室"
    reloaded = service.run_detail(created["run"]["run_id"])["draft"]
    assert reloaded["background_resources"]["BG_Classroom"]["name"] == "放学后的教室"


def test_automatic_match_does_not_infer_from_dialogue_or_conflicting_time():
    scene = {"card_id": "scene-1", "kind": "scene", "current": {"title": "夜间教室"}}
    candidates = [{"key": "BG_Classroom", "name": "教室", "place": "教室", "time": "day"}]
    assert background_match([scene], scene, candidates) is None
    scene["current"]["title"] = "开场"
    dialogue = {
        "card_id": "say-1",
        "kind": "say",
        "current": {"speaker": "亚子", "text": "去教室。"},
    }
    assert background_match([scene, dialogue], scene, candidates) is None


def test_frozen_location_exact_match_keeps_time_conflict_guard():
    scene = {"card_id": "s1", "kind": "scene", "current": {"title": "咖啡误会 · 教室"}}
    candidate = {"key": "BG_Classroom", "name": "教室", "place": "教室", "time": "day"}
    assert background_match([scene], scene, [candidate])["key"] == "BG_Classroom"
    scene["current"]["title"] = "夜间的咖啡误会 · 教室"
    assert background_match([scene], scene, [candidate]) is None


def test_automatic_narrator_mapping_does_not_approve_cards(settings, tmp_path):
    service = ProductionService(configured_resource_settings(settings, tmp_path))
    created = service.create_run({"project": "narrator", "auto_match_resources": True,
        "source": {"kind": "inline", "text": "## 开场\n旁白：门开了。"}})
    draft = created["draft"]
    assert draft["cast"]["cast"]["旁白"]["kind"] == "narrator"
    assert all(card["review_state"] != "approved" for card in draft["cards"])
    assert service.adapter.match_missing_resources(draft["draft_token"])["draft_version"] == draft["draft_version"]


def test_plain_outfit_prefill_is_unique_and_never_confuses_shared_alias():
    rows = [
        {"identifier": "ako", "name": "亚子", "spine": "CharacterSpine_ako"},
        {"identifier": "ako-dress", "name": "亚子", "spine": "CharacterSpine_ako_dress"},
    ]
    assert character_match("亚子", rows)["identifier"] == "ako"
    rows.append({"identifier": "ako-copy", "name": "亚子", "spine": "CharacterSpine_ako"})
    assert character_match("亚子", rows) is None


def test_regional_hina_spelling_uses_exact_official_skeleton_alias():
    baseline = CharacterNameBaseline()
    raw = {
        "identifier": "hina",
        "name": "陽奈",
        "spine": "UIs/03_Scenario/02_Character/CharacterSpine_hina",
    }
    row = baseline.decorate(raw)
    assert "日奈" in row["aliases"]
    assert row["name"] == "陽奈"
    assert character_match("日奈", [row])["identifier"] == "hina"
    raw["user_custom"] = True
    assert "日奈" not in baseline.resolve(raw)["aliases"]


def test_exact_character_name_ranks_ahead_of_substring(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    index = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    index["characters"] = [
        {"identifier": "asuna", "name": "明日奈", "spine": "CharacterSpine_asuna"},
        {"identifier": "hina", "name": "陽奈", "spine": "CharacterSpine_hina"},
    ]
    configured.resource_index.write_text(json.dumps(index), encoding="utf-8")
    service = ProductionService(configured)
    assert service.list_resources("characters", query="日奈")["items"][0]["identifier"] == "hina"
    created = service.create_run(
        {"project": "priority", "source": {"kind": "inline", "text": "日奈：嗯。"}}
    )
    assert (
        service.list_run_resources(created["run"]["run_id"], "characters", query="日奈")["items"][
            0
        ]["identifier"]
        == "hina"
    )


def test_background_alias_keys_with_same_image_are_not_ambiguous():
    scene = {"card_id": "scene-1", "kind": "scene", "current": {"title": "教室"}}
    rows = [
        {"key": key, "aa_hash": "same-image", "name": "教室", "place": "教室"}
        for key in ("BG_Classroom", "bg_classroom")
    ]
    assert background_match([scene], scene, rows)["key"] == "BG_Classroom"
    rows[1]["aa_hash"] = "different-image"
    assert background_match([scene], scene, rows) is None


def test_imported_background_keeps_authors_chinese_label(settings):
    from test_custom_asset_library import image_bytes

    service = ProductionService(settings)
    created = service.create_run(
        {"project": "custom-name", "source": {"kind": "inline", "text": "旁白：测试。"}}
    )
    upload = service.upload_asset(filename="blue-stage.png", content=image_bytes("#305080"))
    registered = service.register_task_asset(
        created["run"]["run_id"],
        {
            "kind": "background",
            "upload_token": upload["upload_token"],
            "labels": {"label": "作者自定义舞台"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    assert registered["asset"]["name"] == "作者自定义舞台"
    assert service.task_assets(created["run"]["run_id"])["items"][0]["name"] == "作者自定义舞台"
    service.jobs.close()
