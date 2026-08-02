from pathlib import Path

import pytest

import aapaths
from aa_resource_cache import (
    detect_resource_cache,
    inspect_cached_bundle,
    iter_cached_bundles,
)


def test_iter_cached_bundles_recognizes_unity_cache_layout(tmp_path):
    data = tmp_path / "outer" / "inner" / "__data"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"UnityFS" + b"\0" * 16)

    bundles = list(iter_cached_bundles(tmp_path))

    assert len(bundles) == 1
    assert bundles[0].data_path == data
    assert bundles[0].outer_hash == "outer"
    assert bundles[0].content_hash == "inner"


def test_iter_cached_bundles_ignores_non_unity_data(tmp_path):
    data = tmp_path / "outer" / "inner" / "__data"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"not a bundle")

    assert list(iter_cached_bundles(tmp_path)) == []


def test_detect_resource_cache_uses_workspace_sibling(tmp_path):
    workspace = tmp_path / "存储文件"
    data = workspace / "data"
    (data / "projects").mkdir(parents=True)
    cache = tmp_path / "资源文件"
    cache.mkdir()

    layout = detect_resource_cache(aa_data=data)

    assert layout.cache_root == cache
    assert layout.source == "workspace sibling"


def test_aapaths_reads_existing_user_settings(tmp_path):
    settings = tmp_path / "data" / "settings"
    settings.mkdir(parents=True)
    (settings / "user_settings.json").write_text(
        '{"workspacePath":"D:/AA-workspace","cachePath":""}',
        encoding="utf-8",
    )

    value = aapaths._read_settings(tmp_path / "data")

    assert value["workspacePath"] == "D:/AA-workspace"


@pytest.mark.skipif(
    not Path(r"E:\AzureArchive\资源文件").is_dir(),
    reason="本机没有 AA 官方资源缓存",
)
def test_real_cache_contains_known_flatdata_bundle():
    path = Path(
        r"E:\AzureArchive\资源文件"
        r"\ea8d917a0a8fcbb8fb1c32ba2344dae0"
        r"\c3860ed9fa93838ab03502ae50de75c3"
        r"\__data"
    )

    info = inspect_cached_bundle(path)

    assert info.type_counts["TextAsset"] == 352
    assert "scenariobgeffectexceltable" in info.asset_names
