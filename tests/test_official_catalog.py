import base64
from pathlib import Path

import pytest


def _encrypt_for_fixture(text, key):
    raw = text.encode("utf-16-le")
    return base64.b64encode(bytes(ch ^ key[i % len(key)] for i, ch in enumerate(raw))).decode("ascii")


def test_decrypts_official_table_text_with_the_character_table_key():
    from official_catalog import CHARACTER_NAME_KEY, decrypt_ba_text

    token = _encrypt_for_fixture("日步美", CHARACTER_NAME_KEY)

    assert decrypt_ba_text(token) == "日步美"


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
