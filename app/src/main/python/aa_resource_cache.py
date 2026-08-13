# -*- coding: utf-8 -*-
"""只读识别 AA 使用的 Unity Addressables 官方资源缓存。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal


@dataclass(frozen=True)
class CachedBundle:
    data_path: Path
    outer_hash: str
    content_hash: str


@dataclass(frozen=True)
class ResourceCacheLayout:
    cache_root: Path
    catalog_paths: tuple[Path, ...]
    source: str


@dataclass(frozen=True)
class BundleInspection:
    type_counts: dict[str, int]
    asset_names: tuple[str, ...]


@dataclass(frozen=True)
class ResourceCacheProbe:
    status: Literal["installed", "not_installed", "invalid"]
    sample_bundle: Path | None
    inspected_outer: int
    issue: str


def _is_unityfs(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(7) == b"UnityFS"
    except OSError:
        return False


def _bounded_directories(root: Path, limit: int) -> list[Path]:
    selected: list[Path] = []
    try:
        children = root.iterdir()
        for child in children:
            if child.is_dir():
                selected.append(child)
                if len(selected) == limit:
                    break
    except OSError:
        return []
    return sorted(selected, key=lambda path: path.name.casefold())


def probe_resource_cache(
    cache_root: str | Path | None,
    *,
    max_outer: int = 64,
    max_inner: int = 4,
) -> ResourceCacheProbe:
    """Quickly validate an AA cache without scanning bundle contents."""
    if max_outer <= 0 or max_inner <= 0:
        raise ValueError("resource probe bounds must be positive")
    if cache_root is None:
        return ResourceCacheProbe(
            "not_installed", None, 0, "未配置 AA 官方资源目录"
        )
    root = Path(cache_root)
    if not root.is_dir():
        return ResourceCacheProbe(
            "not_installed", None, 0, "AA 官方资源目录不存在"
        )

    outer_directories = _bounded_directories(root, max_outer)
    inspected_outer = 0
    for outer in outer_directories:
        inspected_outer += 1
        for content in _bounded_directories(outer, max_inner):
            data_path = content / "__data"
            if data_path.is_file() and _is_unityfs(data_path):
                return ResourceCacheProbe(
                    "installed",
                    data_path,
                    inspected_outer,
                    "",
                )
    return ResourceCacheProbe(
        "invalid",
        None,
        inspected_outer,
        "目录中没有找到有效的 AA UnityFS 缓存项",
    )


def iter_cached_bundles(cache_root: str | Path) -> Iterator[CachedBundle]:
    """遍历 ``<outer>/<content>/__data``，只返回 UnityFS bundle。"""
    root = Path(cache_root)
    if not root.is_dir():
        return
    for outer in root.iterdir():
        if not outer.is_dir():
            continue
        for content in outer.iterdir():
            if not content.is_dir():
                continue
            data = content / "__data"
            if data.is_file() and _is_unityfs(data):
                yield CachedBundle(data, outer.name, content.name)


def detect_resource_cache(
    *,
    aa_data: str | Path | None = None,
    explicit_cache: str | Path | None = None,
    aa_install: str | Path | None = None,
) -> ResourceCacheLayout:
    """定位缓存根目录及可用 Addressables catalog，不写任何文件。"""
    candidates: list[tuple[Path, str]] = []
    if explicit_cache:
        candidates.append((Path(explicit_cache).expanduser().resolve(), "explicit"))
    if aa_data:
        data = Path(aa_data).expanduser().resolve()
        workspace = data.parent
        candidates.append((workspace.parent / "资源文件", "workspace sibling"))

    cache_root = next((p for p, _ in candidates if p.is_dir()), None)
    source = next((s for p, s in candidates if p == cache_root), None)
    if cache_root is None or source is None:
        raise FileNotFoundError("找不到 AA 官方资源缓存；请显式指定资源文件目录")

    catalogs: list[Path] = []
    if aa_install:
        bundled = (
            Path(aa_install)
            / "AzureArchive_Data"
            / "StreamingAssets"
            / "aa"
            / "catalog.json"
        )
        if bundled.is_file():
            catalogs.append(bundled)
    return ResourceCacheLayout(cache_root, tuple(catalogs), source)


def inspect_cached_bundle(data_path: str | Path) -> BundleInspection:
    """用 UnityPy 读取一个 bundle 的对象类型和资源名。"""
    import UnityPy

    env = UnityPy.load(str(data_path))
    types: Counter[str] = Counter()
    names: list[str] = []
    for obj in env.objects:
        types[obj.type.name] += 1
        try:
            name = getattr(obj.read(), "m_Name", None)
        except Exception:
            name = None
        if name:
            names.append(str(name))
    return BundleInspection(dict(types), tuple(names))
