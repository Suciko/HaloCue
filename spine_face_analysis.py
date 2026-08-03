# -*- coding: utf-8 -*-
"""Background-safe orchestration for rendering and labeling custom Spine faces."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from spine_face_labeler import (
    label_face_images,
    make_contact_sheet,
    persist_visual_face_labels,
)
from spine_face_renderer import render_face_variations
from spine_semantic_faces import extract_semantic_face_combinations


ProgressCallback = Callable[[str, str, int | None, int | None], None]


def make_variant_key(ident: str, spine_signature: str, outfit_key: str, face_id: str) -> str:
    """生成结合 ident + spine_signature + outfit_key + face_id 的变体隔离键。"""
    return f"{ident}:{spine_signature[:16]}:{outfit_key}:{face_id}"


def resolve_spine_cli(
    explicit: str | Path | None = None,
    *,
    config_path: str | Path | None = None,
) -> Path | None:
    """Find Spine CLI without baking one user's installation into the program."""
    candidates: list[Path] = []
    if explicit and str(explicit).strip():
        candidates.append(Path(explicit).expanduser())
    environment = os.environ.get("SPINE_CLI", "").strip()
    if environment:
        candidates.append(Path(environment).expanduser())

    config = (
        Path(config_path)
        if config_path is not None
        else Path(__file__).with_name("aa_config.json")
    )
    if config.is_file():
        try:
            loaded = json.loads(config.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                configured = str(loaded.get("spine_cli") or "").strip()
                if configured:
                    candidates.append(Path(configured).expanduser())
        except (OSError, ValueError, TypeError):
            pass

    # Common portable and installed locations. These are discovery candidates,
    # not a required hard-coded location.
    candidates.extend(
        [
            Path(r"E:\Spine3.8.75\Spine.com"),
            Path(r"C:\Spine3.8.75\Spine.com"),
            Path(r"C:\Program Files\Spine\Spine.com"),
        ]
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _notify(
    callback: ProgressCallback | None,
    phase: str,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if callback:
        callback(phase, message, current, total)


def _semantic_hints(source_dir: Path) -> dict[str, dict]:
    skeletons = sorted(source_dir.glob("*.skel"))
    if len(skeletons) != 1:
        return {}
    try:
        return extract_semantic_face_combinations(skeletons[0])
    except (OSError, ValueError):
        return {}


def _existing_visual_ids(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    model: str,
) -> set[str]:
    rows = con.execute(
        """
        SELECT face_id FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND model=?
        """,
        (ident, spine_signature, outfit_key, model),
    ).fetchall()
    return {str(row["face_id"]) for row in rows}


def analyze_character_faces(
    con,
    *,
    source_dir: str | Path,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    spine_cli: str | Path,
    cache_root: str | Path,
    provider=None,
    force_vision: bool = False,
    progress: ProgressCallback | None = None,
    workers: int = 2,
) -> dict:
    """Render all real numbered faces and optionally add visual semantic labels."""
    source = Path(source_dir).resolve()
    _notify(progress, "rendering", "正在渲染人物表情差分")

    def report_render_progress(face_id: str, current: int, total: int) -> None:
        _notify(
            progress,
            "rendering",
            f"正在渲染表情 {face_id}（{current} / {total}）",
            current,
            total,
        )

    report = render_face_variations(
        source,
        spine_cli=spine_cli,
        cache_root=cache_root,
        workers=workers,
        progress=report_render_progress,
    )
    face_ids = {face.face_id for face in report.faces}
    semantic_hints = _semantic_hints(source)
    semantic_faces = []
    for face_id in sorted(face_ids):
        hint = semantic_hints.get(face_id) or {}
        primary = str(hint.get("primary_emotion") or "").strip()
        labels = [
            str(label).strip()
            for label in hint.get("semantic_labels") or []
            if str(label).strip()
        ]
        if primary or labels:
            semantic_faces.append(
                {
                    "face_id": face_id,
                    "primary_emotion": primary or labels[0],
                    "semantic_labels": labels or [primary],
                }
            )
    _notify(
        progress,
        "rendered",
        f"已渲染 {len(report.faces)} 个表情差分",
        len(report.faces),
        len(report.faces),
    )

    contact_sheet = make_contact_sheet(
        report.faces, report.cache_dir / "contact-sheet.jpg"
    )
    result = {
        "ok": True,
        "rendered_count": len(report.faces),
        "render_cache": str(report.cache_dir),
        "render_cached": bool(report.cached),
        "contact_sheet": str(contact_sheet),
        "vision_status": "skipped_missing_key",
        "labeled_count": 0,
        "semantic_faces": semantic_faces,
    }
    if provider is None:
        _notify(
            progress,
            "complete",
            "渲染完成；未配置模型密钥，已保留语义命名解析结果",
            len(report.faces),
            len(report.faces),
        )
        return result

    model = str(getattr(provider, "model", "") or "unknown")
    existing = _existing_visual_ids(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
        model=model,
    )
    if not force_vision and face_ids and face_ids.issubset(existing):
        result.update(vision_status="cached", labeled_count=len(face_ids), model=model)
        _notify(
            progress,
            "complete",
            f"已复用 {len(face_ids)} 个视觉表情标注",
            len(face_ids),
            len(face_ids),
        )
        return result

    _notify(
        progress,
        "labeling",
        f"正在使用 {model} 按九宫格批次识别表情",
        0,
        len(report.faces),
    )

    def report_label_progress(
        completed: int,
        total: int,
        completed_batches: int,
        reviewed: int,
    ) -> None:
        detail = f"完成 {completed_batches} 个九宫格批次"
        if reviewed:
            detail += f"，单项复核 {reviewed} 个"
        _notify(
            progress,
            "labeling",
            f"AI 已识别 {completed} / {total} 个表情（{detail}）",
            completed,
            total,
        )

    labels = label_face_images(
        provider,
        report.faces,
        semantic_hints=semantic_hints,
        progress=report_label_progress,
    )
    persist_visual_face_labels(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
        model=model,
        labels=labels,
    )
    result.update(
        vision_status="labeled",
        labeled_count=len(labels),
        model=model,
    )
    _notify(
        progress,
        "complete",
        f"已写入 {len(labels)} 个视觉表情标注",
        len(labels),
        len(report.faces),
    )
    return result
