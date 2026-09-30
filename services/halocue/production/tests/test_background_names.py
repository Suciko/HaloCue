from halocue_production.background_names import background_display_name
from halocue_production.service import ProductionService
from test_service import configured_resource_settings


def test_core_official_backgrounds_have_chinese_display_names():
    assert background_display_name("BG_GameDevRoom", {"label": "Game Dev Room"}) == "游戏开发部活动室"
    assert background_display_name("BG_MainOffice_Night", {"label": "Main Office"}) == "主办公室 · 夜晚"
    assert background_display_name("BG_RainyStation", {"label": "Rainy Station", "place": "车站"}) == "车站"


def test_resource_catalog_exposes_chinese_name_and_preserves_key(settings, tmp_path):
    service = ProductionService(configured_resource_settings(settings, tmp_path))
    try:
        item = next(
            row for row in service.list_resources("backgrounds")["items"]
            if row["key"] == "BG_Classroom"
        )
        assert item["name"] == "教室"
        assert item["name_zh_cn"] == "教室"
        assert item["key"] == "BG_Classroom"
    finally:
        service.jobs.close()
