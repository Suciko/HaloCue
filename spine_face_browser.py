"""Persistence helpers for face previews rendered by the local WebGL page.

The page owns rendering because both WebView2 and Android WebView already
provide WebGL.  The server only exposes the registered Spine bundle and
validates the PNGs sent back by that page.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

from PIL import Image

import assetdb
import spine_face_labeler
from spine_face_renderer import RenderedFace, crop_face_previews
from spine_semantic_faces import extract_semantic_face_combinations


_VERSION_RE = re.compile(rb"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")
_HEAD_PREVIEW_SIZE = 768


def bundle_files(source_dir: str | Path) -> tuple[Path, Path, Path]:
    root = Path(source_dir).resolve()
    skeletons = sorted(root.glob("*.skel"))
    atlases = sorted(root.glob("*.atlas"))
    if len(skeletons) != 1 or len(atlases) != 1:
        raise ValueError("Spine bundle must contain exactly one .skel and one .atlas")
    return root, skeletons[0], atlases[0]


def detect_spine_version(path: str | Path) -> str:
    match = _VERSION_RE.search(Path(path).read_bytes())
    return match.group(1).decode("ascii") if match else ""


def atlas_texture_files(root: Path, atlas: Path) -> list[tuple[str, Path]]:
    """Return every atlas page, restricting paths to the registered bundle."""
    try:
        lines = atlas.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Spine atlas must be UTF-8") from exc
    pages: list[tuple[str, Path]] = []
    for index, raw in enumerate(lines):
        name = raw.strip()
        if not name or ":" in name or raw[0].isspace() or Path(name).name != name:
            continue
        following = next((item.strip() for item in lines[index + 1:] if item.strip()), "")
        if not (following.startswith("size:") or following.startswith("format:")):
            continue
        texture = (root / name).resolve()
        if texture.parent != root or not texture.is_file():
            raise ValueError("Spine atlas texture is missing")
        pages.append((name, texture))
    if not pages:
        raise ValueError("Spine atlas has no texture pages")
    return pages


def render_cache_paths(cache_root: str | Path, spine_signature: str) -> tuple[Path, Path, Path]:
    safe = "".join(ch for ch in str(spine_signature or "unknown") if ch.isalnum() or ch in "-_")
    safe = safe[:96] or "unknown"
    root = Path(cache_root).resolve() / safe
    return root, root / "portraits-browser-v1", root / "heads-browser-v1"


def _semantic_faces(combinations: dict) -> list[dict]:
    return [
        {
            "face_id": face_id,
            "primary_emotion": str(record.get("primary_emotion") or ""),
            "semantic_labels": list(record.get("semantic_labels") or record.get("labels") or []),
            "usage_hint_cn": " / ".join(record.get("semantic_labels") or record.get("labels") or [])[:160],
        }
        for face_id, record in sorted(combinations.items())
    ]


def _saved_face_ids(con, *, ident: str, spine_signature: str, outfit_key: str, heads: Path) -> set[str]:
    saved: set[str] = set()
    for record in spine_face_labeler.list_visual_face_labels(
        con, ident=ident, spine_signature=spine_signature, outfit_key=outfit_key
    ):
        face_id = str(record.get("face_id") or "")
        expected = (heads / f"{face_id}.png").resolve()
        path = Path(str(record.get("head_path") or ""))
        if not face_id or not path.is_file() or path.resolve() != expected:
            continue
        try:
            with Image.open(path) as preview:
                if preview.size == (_HEAD_PREVIEW_SIZE, _HEAD_PREVIEW_SIZE):
                    saved.add(face_id)
        except (OSError, ValueError):
            continue
    return saved


def analyze_browser_faces(
    con,
    *,
    source_dir: str | Path,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    cache_root: str | Path,
    progress=None,
) -> dict:
    """Extract face combinations and report whether the browser must render them."""
    _root, skeleton, _atlas = bundle_files(source_dir)
    if progress:
        progress("parsing", "Reading Spine face combinations", 0, 1)
    combinations = extract_semantic_face_combinations(skeleton)
    if not combinations:
        raise ValueError("No renderable Spine face combinations were found")

    parts, seen = [], set()
    for record in combinations.values():
        for part in record.get("parts") or []:
            key = (part.get("kind"), part.get("raw_name"))
            if key not in seen:
                seen.add(key)
                parts.append(part)
    assetdb.replace_expression_parts(
        con, ident=str(ident), spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""), parts=parts,
    )
    assetdb.replace_semantic_face_evidence(
        con, ident=str(ident), spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""), combinations=combinations,
    )
    con.commit()
    _cache, _portraits, heads = render_cache_paths(cache_root, spine_signature)
    complete = set(combinations).issubset(_saved_face_ids(
        con, ident=str(ident), spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""), heads=heads,
    ))
    if progress:
        progress(
            "complete" if complete else "awaiting_render",
            "Face previews are ready" if complete else "Face combinations found; waiting for local WebGL rendering",
            len(combinations) if complete else 0,
            len(combinations),
        )
    return {
        "ok": True,
        "status": "complete" if complete else "awaiting_render",
        "rendered_count": len(combinations) if complete else 0,
        "semantic_face_count": len(combinations),
        "semantic_faces": _semantic_faces(combinations),
        "vision_status": "cached_browser_render" if complete else "awaiting_browser_render",
    }


def store_browser_rendered_face(
    con,
    *,
    source_dir: str | Path,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    cache_root: str | Path,
    face_id: str,
    png_bytes: bytes,
) -> dict:
    """Validate one WebGL PNG and publish previews once every face is present."""
    _root, skeleton, _atlas = bundle_files(source_dir)
    combinations = extract_semantic_face_combinations(skeleton)
    face_id = str(face_id or "")
    if face_id not in combinations:
        raise ValueError("Unknown Spine face ID")
    if not png_bytes or len(png_bytes) > 6 * 1024 * 1024:
        raise ValueError("Rendered face PNG is empty or too large")
    try:
        source = Image.open(io.BytesIO(png_bytes))
        if source.format != "PNG":
            raise ValueError("Rendered face is not PNG")
        image = source.convert("RGBA")
        image.load()
    except (OSError, ValueError) as exc:
        raise ValueError("Rendered face is not a valid PNG") from exc
    if not (256 <= image.width <= 2048 and 256 <= image.height <= 2048):
        raise ValueError("Rendered face dimensions are invalid")
    if not image.getchannel("A").point(lambda value: 255 if value >= 8 else 0).getbbox():
        raise ValueError("Rendered face is fully transparent")

    _cache, portraits, heads = render_cache_paths(cache_root, spine_signature)
    portraits.mkdir(parents=True, exist_ok=True)
    destination = portraits / f"{face_id}.png"
    temporary = destination.with_suffix(".tmp.png")
    temporary.write_bytes(png_bytes)
    os.replace(temporary, destination)
    expected = sorted(combinations)
    received = []
    for item in expected:
        candidate = portraits / f"{item}.png"
        try:
            with Image.open(candidate) as rendered:
                if rendered.format == "PNG" and rendered.size == image.size:
                    received.append(item)
        except (OSError, ValueError):
            continue
    if len(received) != len(expected):
        return {"ok": True, "complete": False, "received": len(received), "total": len(expected)}

    faces = tuple(RenderedFace(item, portraits / f"{item}.png", heads / f"{item}.png") for item in expected)
    crop_face_previews(faces)
    labels = [
        {
            **item,
            "confidence": 1.0 if item.get("primary_emotion") else 0.5,
            "head_path": str(heads / f"{item['face_id']}.png"),
        }
        for item in _semantic_faces(combinations)
    ]
    persisted = spine_face_labeler.persist_visual_face_labels(
        con, ident=str(ident), spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""), model="spine-semantic", labels=labels,
    )
    return {
        "ok": True, "complete": True, "received": len(received), "total": len(expected),
        "rendered_count": len(faces), "vision_status": "semantic_only", **persisted,
    }
