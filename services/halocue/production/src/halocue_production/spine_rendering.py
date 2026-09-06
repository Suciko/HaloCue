from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from .errors import ProductionError


def _legacy_module(name: str, legacy_root: Path):
    root = str(legacy_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module(name)


def _config_paths(legacy_root: Path, data_dir: Path) -> tuple[Path, ...]:
    return (
        legacy_root / "aa_config.json",
        data_dir / "aa_config.json",
        data_dir / "settings.json",
    )


def resolve_cli(*, legacy_root: Path, data_dir: Path) -> Path | None:
    """Resolve the local Spine CLI without exposing its path to the browser."""
    explicit = os.environ.get("HALOCUE_SPINE_CLI", "").strip() or os.environ.get(
        "SPINE_CLI", ""
    ).strip()
    try:
        analysis = _legacy_module("spine_face_analysis", legacy_root)
        return analysis.resolve_spine_cli(
            explicit=explicit or None,
            config_path=legacy_root / "aa_config.json",
            fallback_config_paths=_config_paths(legacy_root, data_dir),
        )
    except (ImportError, OSError, ValueError, TypeError):
        return None


def capability(*, legacy_root: Path, data_dir: Path) -> dict[str, Any]:
    cli = resolve_cli(legacy_root=legacy_root, data_dir=data_dir)
    return {
        "state": "available" if cli else "not_configured",
        "requires_explicit_opt_in": True,
        "supported_kinds": ["character"],
        "evidence_only": True,
        "reason": None if cli else "spine_cli_not_configured",
    }


def _bundle_root(source: Path) -> Path:
    bundles = [
        skeleton.parent
        for skeleton in source.rglob("*.skel")
        if skeleton.with_suffix(".atlas").is_file()
    ]
    if len(bundles) != 1:
        raise ProductionError(
            "asset_spine_bundle_ambiguous",
            "角色 ZIP 中必须只有一组可渲染的 Spine 骨骼和 atlas",
            status=422,
        )
    return bundles[0]


def render_preview(
    *,
    source: Path,
    legacy_root: Path,
    data_dir: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Render numbered faces into the isolated production data directory.

    The returned paths are internal handoff data. They are never serialized to
    the browser or copied into a frozen release; the caller only persists the
    count, IDs, and calibration status as recognition evidence.
    """
    cli = resolve_cli(legacy_root=legacy_root, data_dir=data_dir)
    if cli is None:
        raise ProductionError(
            "asset_spine_render_not_configured",
            "尚未配置 Spine 命令行程序；可以关闭“先渲染表情”并继续静态识别",
            status=409,
            details={"evidence_only": True},
        )
    try:
        renderer = _legacy_module("spine_face_renderer", legacy_root)
        bundle = _bundle_root(source)
        cache_root = data_dir / "spine-render-cache"
        report = renderer.render_face_variations(
            bundle,
            spine_cli=cli,
            cache_root=cache_root,
            workers=1,
        )
    except ProductionError:
        raise
    except FileNotFoundError as exc:
        raise ProductionError(
            "asset_spine_render_not_configured",
            "Spine 命令行程序不可用；可以关闭“先渲染表情”并继续静态识别",
            status=409,
            details={"evidence_only": True},
        ) from exc
    except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
        raise ProductionError(
            "asset_spine_render_failed",
            "Spine 表情预览生成失败；请检查骨骼版本或关闭渲染后重试",
            status=422,
            details={"type": type(exc).__name__, "evidence_only": True},
        ) from exc

    faces = list(getattr(report, "faces", ()) or ())
    sources = [
        Path(str(getattr(face, "head_path", "") or getattr(face, "portrait_path", "")))
        for face in faces
    ]
    sources = [path for path in sources if path.is_file()]
    if not sources:
        raise ProductionError(
            "asset_spine_render_empty",
            "Spine 没有生成可供模型查看的表情预览；请关闭渲染后重试",
            status=422,
            details={"evidence_only": True},
        )
    return {
        "_sources": sources,
        "rendered_face_ids": [str(getattr(face, "face_id", "")) for face in faces],
        "rendered_animation_count": len(faces),
        "spine_animation_rendered": True,
        "expression_source": "rendered_spine_preview",
        "calibration": list(getattr(report, "calibration", ()) or ()),
        "render_cache": str(getattr(report, "cache_dir", "")),
        "render_cached": bool(getattr(report, "cached", False)),
        "metadata_spine_version": str(metadata.get("spine_version") or ""),
    }
