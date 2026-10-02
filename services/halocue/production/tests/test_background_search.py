import json

from halocue_production.background_search import background_search_document, background_search_score
from halocue_production.service import ProductionService
from test_service import configured_resource_settings


def test_chinese_keywords_aliases_and_lowercase_aa_ids():
    document = background_search_document(
        {"key": "bg_abydostrainstation_night", "name": "Train Station"}
    )
    for query in ("阿拜多斯", "阿比多斯 夜间", "车站 夜晚", "火车站 深夜", "train_station NIGHT"):
        assert background_search_score(document, query) is not None
    assert background_search_score(document, "车站 白天") is None
    rooftop = background_search_document({"key": "BG_Rooftop_Night", "name": "屋顶 · 夜晚"})
    assert background_search_score(rooftop, "楼顶 夜间") is not None


def test_negative_suitability_notes_do_not_match_search():
    document = background_search_document(
        {
            "key": "BG_BusStation",
            "name": "晴天街道公交车站",
            "tags": ["车站", "白天"],
            "avoid_when": "不适合深夜、恶劣雨雪天气或室内封闭会议场景。",
        }
    )
    assert background_search_score(document, "车站 白天") is not None
    assert background_search_score(document, "车站 夜晚") is None
    assert background_search_score(document, "车站 室内") is None


def test_search_cache_reuses_resource_reads_and_reloads_changed_snapshot(
    settings, tmp_path, monkeypatch
):
    configured = configured_resource_settings(settings, tmp_path)
    payload = json.loads(configured.resource_index.read_text(encoding="utf-8"))
    payload["bg"]["BG_AbydosTrainStation_Night"] = 99
    configured.resource_index.write_text(json.dumps(payload), encoding="utf-8")
    service = ProductionService(configured)
    try:
        created = service.create_run(
            {"project": "search", "source": {"kind": "inline", "text": "## 车站\n旁白: 测试。\n"}}
        )
        run = created["run"]["run_id"]
        token = service._run(run).draft_token
        count = {"reads": 0, "previews": 0}
        original = service.adapter._draft_resources

        def read(token):
            count["reads"] += 1
            return original(token)

        def preview(keys):
            keys = list(keys)
            count["previews"] += len(keys)
            return {key: False for key in keys}

        monkeypatch.setattr(service.adapter, "_draft_resources", read)
        monkeypatch.setattr(service.adapter.previews, "backgrounds_available", preview)
        for query in ("车站 夜间", "阿比多斯 深夜"):
            page = service.list_run_resources(
                run, "backgrounds", query=query, filters={"scope": "library"}
            )
            assert [row["key"] for row in page["items"]] == ["BG_AbydosTrainStation_Night"]
            assert all(not key.startswith("_") for key in page["items"][0])
        assert count == {"reads": 1, "previews": 2}
        path = service.adapter.store.get_draft_path(token) / "resources.json"
        frozen = original(token)
        frozen["bg"]["BG_TrainStation_Night2"] = 100
        path.write_text(json.dumps(frozen), encoding="utf-8")
        assert (
            service.list_run_resources(
                run, "backgrounds", query="车站 夜晚", filters={"scope": "library"}
            )["total"]
            == 2
        )
        assert count["reads"] == 2
    finally:
        service.jobs.close()
