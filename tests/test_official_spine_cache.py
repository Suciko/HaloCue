import json
from pathlib import Path

from official_catalog import CatalogBundleLocation
from official_spine_cache import discover_official_spine_sources


def _location(internal_id: str, bundle: str) -> CatalogBundleLocation:
    return CatalogBundleLocation(
        internal_id=internal_id,
        bundle_name=bundle,
        content_hash="hash-" + bundle,
        data_path=Path("cache") / bundle / "hash" / "__data",
    )


def test_discovers_complete_official_spine_source_with_exact_prefab_key(
    tmp_path, monkeypatch
):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "m_InternalIds": [
            "Assets/Addressables/UIs/03_Scenario/02_Character/CharacterSpine_Airi.prefab"
        ]
    }), encoding="utf-8")
    by_suffix = {
        ".skel.bytes": _location(
            "Assets/Addressables/UIs/03_Scenario/02_Character/data/airi_spr.skel.bytes",
            "skeleton",
        ),
        ".atlas.txt": _location(
            "Assets/Addressables/UIs/03_Scenario/02_Character/data/airi_spr.atlas.txt",
            "atlas",
        ),
        ".png": _location(
            "Assets/Addressables/UIs/03_Scenario/02_Character/data/airi_spr.png",
            "texture",
        ),
    }

    def fake_locations(_catalog, _cache, *, internal_predicate):
        return tuple(
            value for suffix, value in by_suffix.items()
            if internal_predicate(value.internal_id)
        )

    monkeypatch.setattr(
        "official_spine_cache.catalog_bundle_locations", fake_locations
    )

    sources, failures = discover_official_spine_sources(catalog, tmp_path / "cache")

    assert failures == ()
    assert len(sources) == 1
    assert sources[0].outfit_key == "CharacterSpine_Airi"
    assert sources[0].spine.endswith("/CharacterSpine_Airi")
    assert sources[0].asset_stem == "airi_spr"


def test_missing_prefab_identity_is_reported_instead_of_invented(
    tmp_path, monkeypatch
):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"m_InternalIds": []}), encoding="utf-8")
    location = _location(
        "Assets/Addressables/UIs/03_Scenario/02_Character/data/unknown_spr.skel.bytes",
        "skeleton",
    )

    monkeypatch.setattr(
        "official_spine_cache.catalog_bundle_locations",
        lambda _catalog, _cache, *, internal_predicate: (
            (location,) if internal_predicate(location.internal_id) else ()
        ),
    )

    sources, failures = discover_official_spine_sources(catalog, tmp_path / "cache")

    assert sources == ()
    assert failures[0]["reason"] == "missing_catalog_component"
    assert failures[0]["expected_outfit_key"] == "CharacterSpine_unknown"
