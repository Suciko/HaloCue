"""Preview manifests follow the configured resource data, not source checkout."""

import json

import pytest

from halocue_production.resource_catalog import ResourceCatalog
from halocue_production.service import ProductionService
from test_service import configured_resource_settings


def manifest(root, name="image.png", content=b"image"):
    folder = root / "out" / "official-previews"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    (folder / "manifest.json").write_text(
        json.dumps({"records": [{"kind": "background", "key": "BG_RainyStation", "path": name}]}),
        encoding="utf-8",
    )
    return folder / name


def test_preview_follows_separate_resource_index(settings, tmp_path):
    (tmp_path / "resources").mkdir(exist_ok=True)
    configured = configured_resource_settings(settings, tmp_path / "resources")
    image = manifest(configured.resource_index.parent)
    catalog = ResourceCatalog(configured.resource_index, legacy_root=configured.legacy_root)
    preview = catalog.preview("backgrounds", "BG_RainyStation")
    assert preview is not None
    assert preview.path == image.resolve()
    service = ProductionService(configured)
    try:
        assert service.resource_preview("backgrounds", "BG_RainyStation").path == image.resolve()
        assert service.adapter.previews.background("BG_RainyStation").path == image.resolve()
    finally:
        service.jobs.close()


def test_legacy_preview_remains_fallback_when_no_resource_manifest(settings, tmp_path):
    (tmp_path / "resources").mkdir(exist_ok=True)
    configured = configured_resource_settings(settings, tmp_path / "resources")
    image = manifest(configured.legacy_root)
    catalog = ResourceCatalog(configured.resource_index, legacy_root=configured.legacy_root)
    assert catalog.preview("backgrounds", "BG_RainyStation").path == image.resolve()


def test_resource_manifest_is_authoritative_and_reloads(settings, tmp_path):
    (tmp_path / "resources").mkdir(exist_ok=True)
    configured = configured_resource_settings(settings, tmp_path / "resources")
    manifest(configured.legacy_root, content=b"legacy")
    image = manifest(configured.resource_index.parent, content=b"resource")
    catalog = ResourceCatalog(configured.resource_index, legacy_root=configured.legacy_root)
    assert catalog.preview("backgrounds", "BG_RainyStation").path == image.resolve()
    (image.parent / "manifest.json").write_text('{"records":[]}', encoding="utf-8")
    assert catalog.preview("backgrounds", "BG_RainyStation") is None


def test_bound_workspace_preview_cache_fills_missing_index_preview(settings, tmp_path):
    from halocue_production.resource_previews import ResourcePreviewCatalog

    resources_dir = tmp_path / "resources"
    resources_dir.mkdir()
    configured = configured_resource_settings(settings, resources_dir)
    index_preview = manifest(configured.resource_index.parent, name="index-only.png")
    workspace_cache = configured.resource_index.parent / "aa" / "halocue-official-previews"
    workspace_image = workspace_cache / "backgrounds" / "workspace.webp"
    workspace_image.parent.mkdir(parents=True)
    workspace_image.write_bytes(b"workspace-preview")
    (workspace_cache / "manifest.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "kind": "background",
                        "key": "BG_WorkspaceCache",
                        "path": "backgrounds/workspace.webp",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    aa_data = configured.resource_index.parent / "aa"
    catalog = ResourcePreviewCatalog(configured.legacy_root, aa_data, configured.resource_index)

    assert catalog.background("BG_RainyStation").path == index_preview.resolve()
    assert catalog.background("BG_WorkspaceCache").path == workspace_image.resolve()


def test_background_preview_does_not_scan_private_story_history(tmp_path):
    from halocue_production.resource_previews import ResourcePreviewCatalog

    aa_root = tmp_path / "aa"
    for area in ("projects", "saves"):
        image = aa_root / area / "history" / "bgs" / "BG_Private.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"private-story-art")
    catalog = ResourcePreviewCatalog(tmp_path / "legacy", aa_root)
    assert catalog.background("BG_Private") is None


@pytest.mark.parametrize("bad_path", ["../../../outside.png", "absolute"])
def test_external_preview_paths_remain_blocked(settings, tmp_path, bad_path):
    (tmp_path / "resources").mkdir(exist_ok=True)
    configured = configured_resource_settings(settings, tmp_path / "resources")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    image = manifest(configured.resource_index.parent)
    path = str(outside) if bad_path == "absolute" else bad_path
    (image.parent / "manifest.json").write_text(
        json.dumps({"records": [{"kind": "background", "key": "BG_RainyStation", "path": path}]}),
        encoding="utf-8",
    )
    catalog = ResourceCatalog(configured.resource_index, legacy_root=configured.legacy_root)
    assert catalog.preview("backgrounds", "BG_RainyStation") is None


def test_background_preview_resolves_configured_workspace_overrides(tmp_path):
    from halocue_production.resource_previews import ResourcePreviewCatalog

    root = tmp_path / "aa"
    folder = root / "overrides" / "bgs"
    folder.mkdir(parents=True)
    image = folder / "BG_Extra.jpg"
    image.write_bytes(b"synthetic-image")
    catalog = ResourcePreviewCatalog(tmp_path / "legacy", root)
    assert catalog.background("BG_Extra").path == image.resolve()
    assert catalog.background("../BG_Extra") is None
    assert catalog.background(str(image.with_suffix(""))) is None
    assert catalog.background("BG_Missing") is None


def test_background_override_wins_over_cached_official_image(tmp_path):
    from halocue_production.resource_previews import ResourcePreviewCatalog

    manifest(tmp_path, name="cached.jpg")
    folder = tmp_path / "aa" / "overrides" / "bgs"
    folder.mkdir(parents=True)
    image = folder / "BG_RainyStation.png"
    image.write_bytes(b"synthetic-override")
    catalog = ResourcePreviewCatalog(tmp_path, tmp_path / "aa")
    assert catalog.background("BG_RainyStation").path == image.resolve()


def test_cached_preview_detects_removed_image_and_new_override(tmp_path):
    from halocue_production.resource_previews import ResourcePreviewCatalog

    cached_image = manifest(tmp_path, name="cached.jpg")
    folder = tmp_path / "aa" / "overrides" / "bgs"
    folder.mkdir(parents=True)
    catalog = ResourcePreviewCatalog(tmp_path, tmp_path / "aa")
    assert catalog.background("BG_RainyStation").path == cached_image.resolve()
    override = folder / "BG_RainyStation.png"
    override.write_bytes(b"new-override")
    assert catalog.background("BG_RainyStation").path == override.resolve()
    override.unlink()
    cached_image.unlink()
    assert catalog.background("BG_RainyStation") is None


def test_concurrent_thumbnails_parse_manifest_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from time import sleep
    from halocue_production.resource_previews import ResourcePreviewCatalog

    manifest(tmp_path)
    original = Path.read_text
    reads = []

    def read(path, *args, **kwargs):
        if path.name == "manifest.json":
            reads.append(path)
            sleep(0.01)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    catalog = ResourcePreviewCatalog(tmp_path, None)
    with ThreadPoolExecutor(max_workers=8) as pool:
        previews = list(pool.map(catalog.background, ["BG_RainyStation"] * 16))
    assert all(preview is not None for preview in previews)
    assert len(reads) == 1


def test_character_preview_resolves_bound_workspace_avatar_override(tmp_path):
    aa_root = tmp_path / "aa"
    spine = r"characters\NP0172_spr\NP0172_spr"
    image = aa_root / "overrides" / "characters" / "NP0172_spr" / "NP0172_spr-avatar.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"synthetic-avatar")
    index = tmp_path / "aa_resources.json"
    index.write_text(
        json.dumps({"characters": [{"identifier": "白子（一年级）", "spine": spine, "faces": []}]}),
        encoding="utf-8",
    )

    catalog = ResourceCatalog(index, aa_data=aa_root, legacy_root=tmp_path / "legacy")

    assert catalog.list("characters", query="白子")["items"][0]["preview_available"] is True
    assert catalog.preview("characters", "白子（一年级）").path == image.resolve()


def test_character_avatar_override_rejects_path_traversal(tmp_path):
    from halocue_production.resource_previews import ResourcePreviewCatalog

    aa_root = tmp_path / "aa"
    escaped = aa_root / "outside-avatar.png"
    escaped.parent.mkdir(parents=True)
    escaped.write_bytes(b"must-not-be-served")
    catalog = ResourcePreviewCatalog(tmp_path / "legacy", aa_root)

    assert catalog.avatar(avatar_key="", spine=r"..\outside") is None
