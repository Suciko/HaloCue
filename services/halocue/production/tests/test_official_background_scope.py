import json
from dataclasses import replace

import pytest

from halocue_production.background_library import BackgroundLibraryScope
from halocue_production.errors import ProductionError
from halocue_production.resource_catalog import ResourceCatalog
from halocue_production.service import ProductionService
from test_service import configured_resource_settings


def test_shared_official_sources_exclude_private_history(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    aa = tmp_path / "aa"
    cache = aa / "halocue-official-previews"
    cache.mkdir(parents=True)
    (cache / "official.png").write_bytes(b"official")
    (cache / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [{"kind": "background", "key": "BG_Official", "path": "official.png"}],
            }
        ),
        encoding="utf-8",
    )
    shared = aa / "overrides"
    (shared / "bgs").mkdir(parents=True)
    (shared / "bgs/pack-cg.jpg").write_bytes(b"official-pack")
    (shared / "manifest.json").write_text(
        json.dumps(
            {"BgOverrides": ["bgs/pack-cg.jpg", "bgs/BG_ExplicitPrivate.jpg", "../BG_Escape.jpg"]}
        ),
        encoding="utf-8",
    )
    resources = {
        "bg": {
            key: i
            for i, key in enumerate(
                [
                    "BG_Official",
                    "pack-cg",
                    "BG_ExplicitPrivate",
                    "00000-private",
                    "BG_Private",
                    "BG_Escape",
                ]
            )
        },
        "bg_label": {"BG_ExplicitPrivate": {"source_kind": "project_import"}},
    }
    configured.resource_index.write_text(json.dumps(resources), encoding="utf-8")
    for area in ("projects", "saves"):
        path = aa / area / "old-story/bgs/BG_Private.png"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"private")
    assert BackgroundLibraryScope(aa, configured.resource_index).visible_keys(resources) == {
        "BG_Official",
        "pack-cg",
    }
    catalog = ResourceCatalog(configured.resource_index, aa, configured.legacy_root)
    assert {row["key"] for row in catalog.list("backgrounds")["items"]} == {
        "BG_Official",
        "pack-cg",
    }
    service = ProductionService(replace(configured, aa_data=aa))
    try:
        created = service.create_run(
            {"project": "scope", "source": {"kind": "inline", "text": "## 教室\n旁白: 测试。\n"}}
        )
        run = created["run"]["run_id"]
        frozen = service.adapter._draft_resources(service._run(run).draft_token)
        assert set(frozen["bg"]) == {"BG_Official", "pack-cg"}
        scene = next(card for card in created["draft"]["cards"] if card["kind"] == "scene")
        with pytest.raises(ProductionError):
            service.resolve_background_request(
                run,
                scene["card_id"],
                {
                    "background_key": "BG_Private",
                    "expected_draft_version": created["draft"]["draft_version"],
                },
            )
        for filters in ({}, {"scope": "library"}, {"scope": "library", "ready": "true"}):
            assert {
                row["key"]
                for row in service.list_run_resources(run, "backgrounds", filters=filters)["items"]
            } == {"BG_Official", "pack-cg"}
        assert (
            service.list_run_resources(
                run, "backgrounds", query="private", filters={"scope": "library"}
            )["total"]
            == 0
        )
    finally:
        service.jobs.close()


def test_frozen_task_preview_survives_global_catalogue_change(settings, tmp_path):
    configured = configured_resource_settings(settings, tmp_path)
    folder = tmp_path / "out/official-previews"
    folder.mkdir(parents=True)
    image = folder / "station.png"
    image.write_bytes(b"frozen-preview")
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "records": [
                    {"kind": "background", "key": key, "path": "station.png"}
                    for key in ("BG_RainyStation", "BG_NotFrozen")
                ]
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(configured)
    try:
        created = service.create_run(
            {
                "project": "frozen",
                "source": {
                    "kind": "inline",
                    "text": "## 车站\n@bg BG_RainyStation\n旁白: 测试。\n",
                },
            }
        )
        run = created["run"]["run_id"]
        configured.resource_index.write_text(json.dumps({"bg": {"BG_Black": 1}}), encoding="utf-8")
        assert (
            service.run_resource_preview(run, "backgrounds", "BG_RainyStation").path
            == image.resolve()
        )
        with pytest.raises(ProductionError):
            service.run_resource_preview(run, "backgrounds", "BG_NotFrozen")
    finally:
        service.jobs.close()
