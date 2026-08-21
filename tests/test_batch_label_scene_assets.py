import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

import batch_label_scene_assets
from batch_label_scene_assets import (
    _label_status,
    discover_scene_targets,
    materialize_official_popup_previews,
    select_target_shard,
)


def _image(path: Path, color) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), color).save(path)
    return path


def test_inventory_combines_official_backgrounds_extra_backgrounds_and_popups(tmp_path):
    preview = tmp_path / "previews"
    official = _image(preview / "backgrounds" / "official.webp", (1, 2, 3))
    manifest = preview / "manifest.json"
    manifest.write_text(json.dumps({"records": [{
        "kind": "background", "key": "BG_Official",
        "path": official.relative_to(preview).as_posix(),
    }]}), encoding="utf-8")
    official_popup = _image(preview / "popups" / "popup.webp", (2, 3, 4))
    popup_manifest = preview / "popup-manifest.json"
    popup_manifest.write_text(json.dumps({"records": [{
        "kind": "popup", "key": "Popup_Official",
        "path": official_popup.relative_to(preview).as_posix(),
    }]}), encoding="utf-8")
    overrides = tmp_path / "overrides"
    _image(overrides / "bgs" / "BG_Extra.png", (4, 5, 6))
    _image(overrides / "popups" / "Event01.png", (7, 8, 9))

    targets, stats = discover_scene_targets(
        official_manifest=manifest, official_popup_manifest=popup_manifest,
        override_roots=[overrides],
    )

    assert {(row.resource_channel, row.asset_key) for row in targets} == {
        ("background", "BG_Official"),
        ("background", "BG_Extra"),
        ("popup", "Popup_Official"),
        ("popup", "Event01"),
    }
    assert stats["by_source_kind"] == {"official_base": 2, "extra_pack": 2}


def test_materializes_official_popup_bundle_outside_aa_and_reuses_manifest(
    tmp_path, monkeypatch,
):
    bundle = tmp_path / "aa-cache" / "__data"
    bundle.parent.mkdir()
    bundle.write_bytes(b"bundle")
    location = SimpleNamespace(
        bundle_name="popup-bundle", content_hash="version-hash", data_path=bundle,
    )
    calls = []

    monkeypatch.setattr(
        batch_label_scene_assets,
        "catalog_bundle_locations",
        lambda *_args, **_kwargs: (location,),
    )

    def loader(_path):
        calls.append(_path)
        return [SimpleNamespace(
            name="Popup01", image=Image.new("RGB", (64, 36), "navy")
        )]

    monkeypatch.setattr(batch_label_scene_assets, "_default_bundle_loader", loader)
    output = tmp_path / "owned-cache"

    first = materialize_official_popup_previews(
        tmp_path / "catalog.json", tmp_path / "aa-cache", output
    )
    second = materialize_official_popup_previews(
        tmp_path / "catalog.json", tmp_path / "aa-cache", output
    )
    manifest = json.loads(first.read_text(encoding="utf-8"))

    assert first == second
    assert calls == [bundle]
    assert manifest["records"][0]["key"] == "Popup01"
    assert (output / manifest["records"][0]["path"]).is_file()


def test_inventory_deduplicates_identical_copies_but_reports_same_key_conflicts(tmp_path):
    overrides = tmp_path / "overrides"
    original = _image(overrides / "bgs" / "BG_CS_Test.png", (1, 1, 1))
    duplicate = overrides / "bgs" / "CS" / "BG_CS_Test.png"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(original.read_bytes())
    _image(overrides / "bgs" / "other" / "BG_CS_Test.jpg", (9, 9, 9))

    targets, stats = discover_scene_targets(
        official_manifest=None, override_roots=[overrides]
    )

    assert len(targets) == 2
    assert stats["physical_files"] == 3
    assert stats["duplicate_copy_count"] == 1
    assert stats["identity_conflict_count"] == 1
    assert any(
        target.source_category == "AA/bgs/CS" for target in targets
    )


def test_scene_target_shards_are_disjoint_and_complete(tmp_path):
    overrides = tmp_path / "overrides"
    for index in range(7):
        _image(overrides / "bgs" / f"BG_{index}.png", (index, 0, 0))
    targets = discover_scene_targets(
        official_manifest=None, override_roots=[overrides]
    )[0]

    shards = [
        select_target_shard(targets, shard_count=3, shard_index=index)
        for index in range(3)
    ]

    assert [len(shard) for shard in shards] == [3, 2, 2]
    assert {target.item_id for shard in shards for target in shard} == {
        target.item_id for target in targets
    }


def test_unknown_main_category_stays_candidate_even_with_high_confidence():
    labels = {
        "confidence": 0.99,
        "visual_kind": "cg",
        "main_category": "unknown",
        "setting_scope": "generic",
        "reuse_scope": "generic",
    }

    assert _label_status(labels, 0.75) == "candidate"
    assert _label_status({**labels, "main_category": "event"}, 0.75) == "ready"
