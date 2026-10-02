import json
from types import SimpleNamespace

import pytest
from PIL import Image

from halocue_production.service import ProductionService
from halocue_production.errors import ProductionError


@pytest.fixture
def importer(settings, tmp_path, monkeypatch):
    aa = tmp_path / "aa"
    for part in ("projects", "saves", "settings", "overrides/bgs"):
        (aa / part).mkdir(parents=True)
    (aa / "overrides/manifest.json").write_text(
        json.dumps(
            {
                "BgOverrides": [
                    "bgs/BG_Unused.jpg",
                    "bgs/BG_Unused.png",
                    "bgs/BG_Broken.jpg",
                    "bgs/BG_Move.png",
                    "bgs/BG_Move.jpg",
                    "bgs/nested/BG_Move.png",
                    "bgs/BG_OnlyOld.jpg",
                    "bgs/BG_AARegistered.png",
                ]
            }
        ),
        encoding="utf-8",
    )
    service = ProductionService(settings)
    service.configure_aa_workspace({"path": str(aa)})
    builder = SimpleNamespace(
        harvest_bg=lambda _: pytest.fail("Private background history must not be read"),
        harvest_characters=lambda _: [],
        harvest_sounds=lambda _: [],
        harvest_faces_used=lambda _: {},
        harvest_face_capabilities=lambda _: {},
        EMOTICON={},
        EMOTICON_CN={},
        ACTION={},
        ACTION_CN={},
        APPEAR={},
        APPEAR_CN={},
        SHAPE={},
        SHAPE_CN={},
    )
    discovery = SimpleNamespace(
        discover_aa=lambda *args, **kw: SimpleNamespace(resource_cache=None, catalog=None)
    )
    monkeypatch.setattr(
        service.adapter,
        "_legacy_module",
        lambda name: discovery if name == "aa_install_discovery" else builder,
    )
    yield service, aa
    service.jobs.close()


def image(path, color="blue"):
    Image.new("RGB", (64, 36), color).save(path)


def test_import_includes_unused_override_and_preserves_labels_on_repeat(importer):
    service, aa = importer
    image(aa / "overrides/bgs/BG_Unused.jpg")
    first = service.rebuild_resource_index()
    index = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert "BG_Unused" in index["bg"]
    assert first["resource_index"]["background_media"]["ready"] == 1
    assert service.resource_preview("backgrounds", "BG_Unused").path.is_file()
    index["bg_label"] = {"BG_Unused": {"label": "中文背景", "time": "白天"}}
    service.settings.resource_index.write_text(json.dumps(index), encoding="utf-8")
    second = service.rebuild_resource_index()
    after = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert after["bg"]["BG_Unused"] == index["bg"]["BG_Unused"]
    assert after["bg_label"]["BG_Unused"]["label"] == "中文背景"
    assert second["resource_index"]["background_media"]["ready"] == 1
    manifest = json.loads(
        (service.settings.resource_index.parent / "out/official-previews/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert len([r for r in manifest["records"] if r["kind"] == "background"]) == 1


def test_reimport_reports_deleted_and_corrupt_images_without_stale_preview(importer):
    service, aa = importer
    source = aa / "overrides/bgs/BG_Unused.png"
    image(source)
    service.rebuild_resource_index()
    source.unlink()
    (aa / "overrides/bgs/BG_Broken.jpg").write_bytes(b"not an image")
    result = service.rebuild_resource_index()
    data = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert data["background_media"]["BG_Unused"]["status"] == "missing"
    assert data["background_media"]["BG_Broken"]["status"] == "unreadable"
    assert result["resource_index"]["background_media"]["ready"] == 0
    assert not service.list_resources("backgrounds", query="Unused")["items"][0][
        "preview_available"
    ]
    with pytest.raises(ProductionError):
        service.resource_preview("backgrounds", "BG_Broken")


def test_failed_publish_keeps_previous_index_and_settings(importer, monkeypatch):
    service, aa = importer
    image(aa / "overrides/bgs/BG_Unused.png")
    service.rebuild_resource_index()
    before_path = service.settings.resource_index
    before = before_path.read_bytes()

    def failed(_):
        raise OSError("test disk failure")

    monkeypatch.setattr(service.settings_store, "save", failed)
    with pytest.raises((OSError, ProductionError)):
        service.rebuild_resource_index()
    assert service.settings.resource_index == before_path
    assert before_path.read_bytes() == before


def test_import_follows_moved_file_and_rejects_duplicate_stems(importer):
    service, aa = importer
    root = aa / "overrides/bgs"
    image(root / "BG_Move.png")
    service.rebuild_resource_index()
    (root / "nested").mkdir()
    (root / "BG_Move.png").rename(root / "nested/BG_Move.png")
    service.rebuild_resource_index()
    data = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert (
        data["background_media"]["BG_Move"]["source_relative"] == "overrides/bgs/nested/BG_Move.png"
    )
    assert service.resource_preview("backgrounds", "BG_Move").path.is_file()
    image(root / "BG_Move.jpg", "red")
    service.rebuild_resource_index()
    data = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert data["background_media"]["BG_Move"]["status"] == "ambiguous"
    with pytest.raises(ProductionError):
        service.resource_preview("backgrounds", "BG_Move")


def test_import_reads_database_labels_and_scene_annotations(importer):
    import sqlite3

    service, aa = importer
    image(aa / "overrides/bgs/BG_Unused.jpg")
    db = service.settings.legacy_root / "aa_assets.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS bg (name TEXT, label TEXT, place TEXT, time TEXT, mood TEXT, tags TEXT)"
        )
        con.execute(
            "INSERT INTO bg(name,label,place,time,mood,tags) VALUES ('BG_Unused','数据库中文名','教室','白天','','')"
        )
    service.rebuild_resource_index()
    assert (
        service.list_resources("backgrounds", query="数据库中文名")["items"][0]["key"]
        == "BG_Unused"
    )


def test_workspace_switch_does_not_reuse_previous_override_catalogue(importer, tmp_path):
    service, aa = importer
    image(aa / "overrides/bgs/BG_OnlyOld.jpg")
    service.rebuild_resource_index()
    second = tmp_path / "second"
    for part in ("projects", "saves", "settings", "overrides"):
        (second / part).mkdir(parents=True)
    service.configure_aa_workspace({"path": str(second)})
    service.rebuild_resource_index()
    data = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert "BG_OnlyOld" not in data["bg"]


def test_import_reuses_official_cache_with_registered_identity(importer):
    service, aa = importer
    (aa / "aa_resources.json").write_text(json.dumps({"bg": {"BG_History": 42}}), encoding="utf-8")
    root = aa / "halocue-official-previews"
    root.mkdir()
    image(root / "history.png")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [{"kind": "background", "key": "BG_History", "path": "history.png"}],
            }
        ),
        encoding="utf-8",
    )
    service.rebuild_resource_index()
    assert service.resource_preview("backgrounds", "BG_History").path.is_file()
    assert service.adapter.previews.background("BG_History").path.is_file()
    assert (
        json.loads(service.settings.resource_index.read_text(encoding="utf-8"))["bg"]["BG_History"]
        == 42
    )


def test_import_never_probes_or_extracts_game_resources(importer, monkeypatch):
    service, aa = importer
    original = service.adapter._legacy_module

    def allowed(name):
        assert name == "build_index", "AA import must not invoke catalog/cache discovery"
        builder = original(name)

        def forbidden(**kwargs):
            pytest.fail("Game bundle extraction must not run")

        builder.harvest_official_characters = forbidden
        return builder

    monkeypatch.setattr(service.adapter, "_legacy_module", allowed)
    result = service.rebuild_resource_index()
    assert not any(
        "Addressables" in w or "catalog" in w for w in result["resource_index"]["warnings"]
    )


def test_import_uses_aa_exported_index_without_game_catalog(importer):
    service, aa = importer
    exported = {
        "bg": {"BG_AARegistered": 789},
        "characters": [{"identifier": "aa-actor", "name": "AA 已登记角色", "faces": []}],
        "sounds": ["AA_SE"],
        "bg_label": {"BG_AARegistered": {"label": "AA 中文背景"}},
    }
    (aa / "aa_resources.json").write_text(json.dumps(exported), encoding="utf-8")
    image(aa / "overrides/bgs/BG_AARegistered.png")
    service.rebuild_resource_index()
    data = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert data["bg"]["BG_AARegistered"] == 789
    assert data["bg_label"]["BG_AARegistered"]["label"] == "AA 中文背景"
    assert any(r["identifier"] == "aa-actor" for r in data["characters"])
    assert "AA_SE" in data["sounds"]
    (aa / "aa_resources.json").unlink()
    service.rebuild_resource_index()
    data = json.loads(service.settings.resource_index.read_text(encoding="utf-8"))
    assert any(r["identifier"] == "aa-actor" for r in data["characters"])


def test_production_discovery_skips_catalog_and_cache(settings, tmp_path, monkeypatch):
    service = ProductionService(settings)
    aa = tmp_path / "workspace"
    for part in ("projects", "saves", "settings", "overrides"):
        (aa / part).mkdir(parents=True)
    module = service.adapter._modules["aa_install_discovery"]

    def forbidden(*args, **kwargs):
        pytest.fail("Production workspace discovery must not probe game resources")

    monkeypatch.setattr(module, "_catalog_path", forbidden)
    monkeypatch.setattr(module, "_resource_cache", forbidden)
    try:
        environment = service.inspect_aa_environment({"selection": str(aa)})["environment"]
        assert environment["workspace"]["valid"]
        assert environment["aa_resources"]["local_only"]
        assert environment["resource_cache"]["available"] is False
    finally:
        service.jobs.close()


def test_real_aa_import_runs_with_game_module_imports_blocked(settings, tmp_path, monkeypatch):
    import builtins

    service = ProductionService(settings)
    aa = tmp_path / "aa-real-builder"
    for part in ("projects", "saves", "settings", "overrides/bgs"):
        (aa / part).mkdir(parents=True)
    image(aa / "overrides/bgs/BG_Local.jpg")
    (aa / "overrides/manifest.json").write_text(
        json.dumps({"BgOverrides": ["bgs/BG_Local.jpg"]}), encoding="utf-8"
    )
    service.configure_aa_workspace({"path": str(aa)})
    original_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {
            "official_catalog",
            "UnityPy",
            "official_preview_index",
        }, name
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    try:
        result = service.rebuild_resource_index()
        assert result["resource_index"]["backgrounds"] == 1
        assert result["resource_index"]["background_media"]["ready"] == 1
        assert service.resource_preview("backgrounds", "BG_Local").path.is_file()
    finally:
        service.jobs.close()
