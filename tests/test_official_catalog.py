import base64
import json
import struct
from pathlib import Path

import pytest


def _entry_data(*rows):
    raw = bytearray(struct.pack("<I", len(rows)))
    for row in rows:
        raw.extend(struct.pack("<7i", *row))
    return base64.b64encode(raw).decode("ascii")


def _extra_data(*options):
    raw = bytearray()
    offsets = []
    for option in options:
        offsets.append(len(raw))
        encoded = json.dumps(option).encode("utf-16-le")
        raw.extend(struct.pack("<I", len(encoded)))
        raw.extend(encoded)
    return base64.b64encode(raw).decode("ascii"), offsets


def _bucket_data(*buckets):
    raw = bytearray(struct.pack("<I", len(buckets)))
    for index, entries in enumerate(buckets):
        raw.extend(struct.pack("<ii", index * 4, len(entries)))
        for entry in entries:
            raw.extend(struct.pack("<i", entry))
    return base64.b64encode(raw).decode("ascii")


def _write_catalog_fixture(path):
    background_id = (
        "Assets/AddressableResources/UIs/"
        "03_Scenario/01_Background/BG_Classroom.jpg"
    )
    avatar_bundle_id = (
        "Assets/AddressableResources/UIs/"
        "01_Common/01_Character/avatars_assets_all.bundle"
    )
    extra, offsets = _extra_data(
        {"m_BundleName": "outer-avatar", "m_Hash": "content-avatar"},
        {"m_BundleName": "outer-audio", "m_Hash": "content-audio"},
        {"m_BundleName": "outer-bg", "m_Hash": "content-bg"},
    )
    catalog = {
        "m_InternalIds": [
            background_id,
            avatar_bundle_id,
            "Assets/Audio/voice_assets_all.bundle",
            "Assets/Background/background_assets_all.bundle",
        ],
        "m_EntryDataString": _entry_data(
            (0, 0, 3, 0, 0, 0, 0),
            (1, 0, -1, 0, offsets[0], 0, 0),
            (2, 0, -1, 0, offsets[1], 0, 0),
            (3, 0, -1, 0, offsets[2], 0, 0),
        ),
        "m_ExtraDataString": extra,
    }
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return background_id, avatar_bundle_id


def _encrypt_for_fixture(text, key):
    raw = text.encode("utf-16-le")
    return base64.b64encode(bytes(ch ^ key[i % len(key)] for i, ch in enumerate(raw))).decode("ascii")


def test_decrypts_official_table_text_with_the_character_table_key():
    from official_catalog import CHARACTER_NAME_KEY, decrypt_ba_text

    token = _encrypt_for_fixture("日步美", CHARACTER_NAME_KEY)

    assert decrypt_ba_text(token) == "日步美"


def test_catalog_resolves_asset_and_bundle_internal_ids(tmp_path):
    from official_catalog import catalog_bundle_locations

    catalog_path = tmp_path / "catalog.json"
    background_id, avatar_bundle_id = _write_catalog_fixture(catalog_path)
    cache_root = tmp_path / "cache"
    background_data = cache_root / "outer-bg" / "content-bg" / "__data"
    background_data.parent.mkdir(parents=True)
    background_data.write_bytes(b"UnityFS")
    avatar_data = (
        cache_root / "outer-avatar" / "content-avatar" / "__data"
    )
    avatar_data.parent.mkdir(parents=True)
    avatar_data.write_bytes(b"UnityFS")

    backgrounds = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: (
            "/01_background/" in value.casefold()
        ),
    )
    avatars = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: value.casefold().endswith(
            "/avatars_assets_all.bundle"
        ),
    )

    assert [
        (row.internal_id, row.bundle_name, row.content_hash)
        for row in backgrounds
    ] == [(background_id, "outer-bg", "content-bg")]
    assert backgrounds[0].data_path == background_data
    assert avatars[0].internal_id == avatar_bundle_id
    assert avatars[0].data_path == avatar_data


def test_catalog_uses_only_one_unambiguous_cached_version(tmp_path):
    from official_catalog import catalog_bundle_locations

    catalog_path = tmp_path / "catalog.json"
    _write_catalog_fixture(catalog_path)
    cache_root = tmp_path / "cache"
    fallback = cache_root / "outer-bg" / "downloaded-version" / "__data"
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b"UnityFS")

    rows = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: (
            "/01_background/" in value.casefold()
        ),
    )
    assert rows[0].data_path == fallback

    second = cache_root / "outer-bg" / "older-version" / "__data"
    second.parent.mkdir(parents=True)
    second.write_bytes(b"UnityFS")
    ambiguous = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: (
            "/01_background/" in value.casefold()
        ),
    )
    assert ambiguous[0].data_path is None


def test_catalog_resolves_real_addressables_dependency_bucket(tmp_path):
    from official_catalog import catalog_bundle_locations

    asset_id = "Assets/Addressables/UIs/03_Scenario/02_Character/Hero.bytes"
    bundle_id = "Assets/Bundles/hero_assets.bundle"
    extra, offsets = _extra_data(
        {"m_BundleName": "outer-hero", "m_Hash": "content-hero"}
    )
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps({
        "m_InternalIds": [asset_id, bundle_id],
        "m_EntryDataString": _entry_data(
            (0, 0, 4, 0, -1, 0, 0),
            (1, 0, -1, 0, offsets[0], 0, 0),
        ),
        "m_BucketDataString": _bucket_data((), (), (), (), (1,)),
        "m_ExtraDataString": extra,
    }), encoding="utf-8")
    cache_root = tmp_path / "cache"
    data = cache_root / "outer-hero" / "content-hero" / "__data"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"UnityFS")

    rows = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: value.endswith("Hero.bytes"),
    )

    assert [(row.internal_id, row.bundle_name, row.data_path) for row in rows] == [
        (asset_id, "outer-hero", data)
    ]


def test_catalog_decodes_large_binary_sections_once(tmp_path, monkeypatch):
    import official_catalog

    catalog_path = tmp_path / "catalog.json"
    _write_catalog_fixture(catalog_path)
    calls = 0
    original = official_catalog.base64.b64decode

    def counted_decode(value):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(
        official_catalog.base64,
        "b64decode",
        counted_decode,
    )

    official_catalog.catalog_bundle_locations(
        catalog_path,
        tmp_path / "cache",
        internal_predicate=lambda value: True,
    )

    assert calls == 2


@pytest.mark.skipif(
    not Path(r"E:\AzureArchive\资源文件\ea8d917a0a8fcbb8fb1c32ba2344dae0\c3860ed9fa93838ab03502ae50de75c3\__data").is_file(),
    reason="本机没有 AA FlatData 缓存",
)
def test_reads_traditional_name_and_native_id_from_real_character_table():
    from official_catalog import read_character_table_bundle

    rows = read_character_table_bundle(
        Path(r"E:\AzureArchive\资源文件\ea8d917a0a8fcbb8fb1c32ba2344dae0\c3860ed9fa93838ab03502ae50de75c3\__data")
    )

    hifumi = next(row for row in rows if row["identifier"] == "히후미")
    assert hifumi["name"] == "日步美"
    assert hifumi["club"] == "補課部"
    assert hifumi["spine"] == "UIs/03_Scenario/02_Character/CharacterSpine_hihumi"


@pytest.mark.skipif(
    not Path(r"E:\AzureArchive\资源文件").is_dir(),
    reason="本机没有 AA 官方资源缓存",
)
def test_locates_character_table_bundle_from_the_addressables_catalog():
    from official_catalog import locate_character_table_bundle

    path = locate_character_table_bundle(
        Path(r"E:\AzureArchive_084\AzureArchive_Data\StreamingAssets\aa\catalog.json"),
        Path(r"E:\AzureArchive\资源文件"),
    )

    assert path == Path(
        r"E:\AzureArchive\资源文件"
        r"\ea8d917a0a8fcbb8fb1c32ba2344dae0"
        r"\c3860ed9fa93838ab03502ae50de75c3\__data"
    )


@pytest.mark.skipif(
    not Path(r"E:\AzureArchive\资源文件\ea8d917a0a8fcbb8fb1c32ba2344dae0\c3860ed9fa93838ab03502ae50de75c3\__data").is_file(),
    reason="本机没有 AA FlatData 缓存",
)
def test_matches_observed_native_variant_id_to_its_traditional_label():
    from official_catalog import read_character_table_bundle, select_native_characters

    rows = read_character_table_bundle(
        Path(r"E:\AzureArchive\资源文件\ea8d917a0a8fcbb8fb1c32ba2344dae0\c3860ed9fa93838ab03502ae50de75c3\__data")
    )
    selected = select_native_characters(rows, ["아리스N"])

    aris = next(row for row in selected if row["identifier"] == "아리스N")
    assert aris["name"] == "愛麗絲"
    assert aris["club"] == "遊戲開發部"
    assert aris["spine"] == "UIs/03_Scenario/02_Character/CharacterSpine_aris_noweapon"
    assert aris["source"] == "official_flatdata"


@pytest.mark.skipif(
    not Path(r"E:\AzureArchive\资源文件").is_dir(),
    reason="本机没有 AA 官方资源缓存",
)
def test_build_index_harvests_official_native_records_with_observed_variant_ids():
    from build_index import harvest_official_characters

    records = harvest_official_characters(
        cache_root=Path(r"E:\AzureArchive\资源文件"),
        catalog_path=Path(r"E:\AzureArchive_084\AzureArchive_Data\StreamingAssets\aa\catalog.json"),
        observed_identifiers=["아리스N"],
    )

    assert any(record["identifier"] == "아리스N" and record["name"] == "愛麗絲"
               for record in records)
