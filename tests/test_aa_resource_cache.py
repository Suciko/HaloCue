from pathlib import Path

import pytest

import aapaths
from aa_resource_cache import (
    detect_resource_cache,
    inspect_cached_bundle,
    iter_cached_bundles,
    probe_resource_cache,
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


def test_probe_distinguishes_missing_invalid_and_installed(tmp_path):
    missing = probe_resource_cache(tmp_path / "missing")
    invalid_root = tmp_path / "invalid"
    (invalid_root / "a" / "b").mkdir(parents=True)
    (invalid_root / "a" / "b" / "__data").write_bytes(
        b"not-unity"
    )
    valid_root = tmp_path / "valid"
    bundle = valid_root / "outer" / "inner" / "__data"
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b"UnityFS" + b"\0" * 16)

    assert missing.status == "not_installed"
    assert missing.sample_bundle is None
    assert probe_resource_cache(invalid_root).status == "invalid"
    installed = probe_resource_cache(valid_root)
    assert installed.status == "installed"
    assert installed.sample_bundle == bundle


def test_probe_obeys_directory_bounds(tmp_path):
    for index in range(100):
        (tmp_path / f"outer-{index:03}" / "inner").mkdir(
            parents=True
        )

    probe = probe_resource_cache(tmp_path, max_outer=8, max_inner=1)

    assert probe.status == "invalid"
    assert probe.inspected_outer == 8


def test_probe_reports_outer_directories_actually_inspected(tmp_path):
    first = tmp_path / "outer-000" / "inner" / "__data"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"UnityFS")
    (tmp_path / "outer-001" / "inner").mkdir(parents=True)

    probe = probe_resource_cache(tmp_path)

    assert probe.inspected_outer == 1


def test_probe_rejects_non_positive_bounds(tmp_path):
    tmp_path.joinpath("cache").mkdir()

    with pytest.raises(ValueError):
        probe_resource_cache(tmp_path / "cache", max_outer=0)


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
