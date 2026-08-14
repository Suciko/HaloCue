"""Android Spine analysis and persistence for WebGL-rendered face previews."""

import io
import os
import re
from pathlib import Path

from PIL import Image

import assetdb
import spine_face_labeler
from spine_face_renderer import HEAD_PREVIEW_SIZE, RenderedFace, crop_face_previews
from spine_semantic_faces import extract_semantic_face_combinations


_VERSION_RE = re.compile(rb"(?<!\d)(\d+\.\d+\.\d+)(?!\d)")


def make_variant_key(ident: str, spine_signature: str, outfit_key: str, face_id: str) -> str:
    return f"{ident}:{spine_signature[:16]}:{outfit_key}:{face_id}"


def resolve_spine_cli(*args, **kwargs):
    return None


def bundle_files(source_dir):
    root = Path(source_dir).resolve()
    skeletons = sorted(root.glob("*.skel"))
    atlases = sorted(root.glob("*.atlas"))
    if len(skeletons) != 1 or len(atlases) != 1:
        raise ValueError("Android Spine rendering requires one .skel and one .atlas file")
    return root, skeletons[0], atlases[0]


def detect_spine_version(path):
    match = _VERSION_RE.search(Path(path).read_bytes())
    return match.group(1).decode("ascii") if match else ""


def atlas_texture_file(root, atlas):
    """Resolve the atlas page declaration without confusing an avatar PNG for a texture."""
    try:
        lines = atlas.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Spine atlas is not UTF-8") from exc
    page_name = next((line.strip() for line in lines if line.strip()), "")
    if not page_name or Path(page_name).name != page_name or not page_name.casefold().endswith(".png"):
        raise ValueError("Spine atlas texture declaration is invalid")
    texture = (root / page_name).resolve()
    if texture.parent != root or not texture.is_file():
        raise ValueError("Spine atlas texture is missing")
    return texture


def atlas_texture_files(root, atlas):
    lines = atlas.read_text(encoding="utf-8-sig").splitlines()
    pages = []
    for index, line in enumerate(lines):
        name = line.strip()
        if not name or ":" in name or line[0].isspace():
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


def render_cache_paths(cache_root, spine_signature):
    signature = str(spine_signature or "unknown")
    safe = "".join(ch for ch in signature if ch.isalnum() or ch in "-_")[:96] or "unknown"
    root = Path(cache_root).resolve() / safe
    return root, root / "portraits-browser-v3", root / "heads-browser-v3"


def _semantic_faces(combinations):
    rows = []
    for face_id, record in combinations.items():
        labels = list(record.get("semantic_labels") or record.get("labels") or [])
        rows.append({
            "face_id": face_id,
            "primary_emotion": str(record.get("primary_emotion") or ""),
            "semantic_labels": labels,
            "usage_hint_cn": "、".join(labels)[:160],
        })
    return rows


def _saved_face_ids(con, *, ident, spine_signature, outfit_key, expected_heads=None):
    records = spine_face_labeler.list_visual_face_labels(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
    )
    saved = set()
    for record in records:
        face_id = str(record.get("face_id"))
        path = Path(str(record.get("head_path") or ""))
        if expected_heads is not None:
            expected = (Path(expected_heads) / f"{face_id}.png").resolve()
            if path.resolve() != expected:
                continue
        if not path.is_file():
            continue
        try:
            with Image.open(path) as preview:
                if preview.size != (HEAD_PREVIEW_SIZE, HEAD_PREVIEW_SIZE):
                    continue
        except (OSError, ValueError):
            continue
        saved.add(face_id)
    return saved


def analyze_character_faces(
    con,
    *,
    source_dir,
    ident,
    spine_signature="",
    outfit_key="",
    cache_root=None,
    progress=None,
    **_kwargs,
):
    """Parse face semantics, then report whether WebGL previews are still needed."""
    _root, skeleton, _atlas = bundle_files(source_dir)
    if progress:
        progress("parsing", "正在解析 Spine 表情元数据", 0, 1)
    combinations = extract_semantic_face_combinations(skeleton)
    parts = []
    seen = set()
    for record in combinations.values():
        for part in record.get("parts") or []:
            key = (part.get("kind"), part.get("raw_name"))
            if key not in seen:
                seen.add(key)
                parts.append(part)
    assetdb.replace_expression_parts(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
        parts=parts,
    )
    assetdb.replace_semantic_face_evidence(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
        combinations=combinations,
    )
    con.commit()
    expected_heads = (
        render_cache_paths(cache_root, spine_signature)[2]
        if cache_root is not None
        else None
    )
    saved = _saved_face_ids(
        con,
        ident=ident,
        spine_signature=spine_signature,
        outfit_key=outfit_key,
        expected_heads=expected_heads,
    )
    complete = set(combinations).issubset(saved)
    if progress:
        progress(
            "complete" if complete else "awaiting_render",
            f"已加载 {len(combinations)} 张表情预览"
            if complete
            else f"已识别 {len(combinations)} 个表情组合，等待生成预览",
            len(combinations) if complete else 0,
            len(combinations),
        )
    return {
        "ok": True,
        "status": "complete" if complete else "awaiting_render",
        "rendered_count": len(combinations) if complete else 0,
        "refreshed_preview_count": 0,
        "labeled_count": len(combinations) if complete else 0,
        "semantic_face_count": len(combinations),
        "semantic_source": next(iter(combinations.values()), {}).get("source", ""),
        "semantic_faces": _semantic_faces(combinations),
        "vision_status": "cached_android_render" if complete else "awaiting_android_render",
    }


def store_browser_rendered_face(
    con,
    *,
    source_dir,
    ident,
    spine_signature,
    outfit_key,
    cache_root,
    face_id,
    png_bytes,
):
    """Validate one browser render and finalize the complete aligned set."""
    _root, skeleton, _atlas = bundle_files(source_dir)
    combinations = extract_semantic_face_combinations(skeleton)
    face_id = str(face_id or "")
    if face_id not in combinations:
        raise ValueError("Unknown Spine face ID")
    if not png_bytes or len(png_bytes) > 6 * 1024 * 1024:
        raise ValueError("Rendered face PNG is empty or too large")
    try:
        source_image = Image.open(io.BytesIO(png_bytes))
        if source_image.format != "PNG":
            raise ValueError("Rendered face is not a PNG")
        image = source_image.convert("RGBA")
        image.load()
    except (OSError, ValueError) as exc:
        raise ValueError("Rendered face is not a valid PNG") from exc
    if not (256 <= image.width <= 2048 and 256 <= image.height <= 2048):
        raise ValueError("Rendered face dimensions are invalid")
    if not image.getchannel("A").point(lambda value: 255 if value >= 8 else 0).getbbox():
        raise ValueError("Rendered face is transparent")

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

    faces = tuple(
        RenderedFace(item, portraits / f"{item}.png", heads / f"{item}.png")
        for item in expected
    )
    crop_face_previews(faces)
    labels = []
    for item in _semantic_faces(combinations):
        labels.append({
            **item,
            "confidence": 1.0 if item.get("primary_emotion") else 0.5,
            "head_path": str(heads / f"{item['face_id']}.png"),
        })
    persisted = spine_face_labeler.persist_visual_face_labels(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
        model="spine-semantic",
        labels=labels,
    )
    return {
        "ok": True,
        "complete": True,
        "received": len(received),
        "total": len(expected),
        "rendered_count": len(faces),
        **persisted,
    }


def label_browser_rendered_faces(
    con,
    *,
    source_dir,
    ident,
    spine_signature,
    outfit_key,
    cache_root,
    provider,
    force_vision=False,
    progress=None,
):
    """Send the completed high-resolution browser renders to the vision model."""
    _root, skeleton, _atlas = bundle_files(source_dir)
    combinations = extract_semantic_face_combinations(skeleton)
    _cache, portraits, heads = render_cache_paths(cache_root, spine_signature)
    faces = tuple(
        RenderedFace(face_id, portraits / f"{face_id}.png", heads / f"{face_id}.png")
        for face_id in sorted(combinations)
    )
    if not faces or any(
        not face.portrait_path.is_file() or not face.head_path.is_file()
        for face in faces
    ):
        raise ValueError("High-resolution browser face renders are incomplete")
    for face in faces:
        try:
            with Image.open(face.head_path) as preview:
                if preview.size != (HEAD_PREVIEW_SIZE, HEAD_PREVIEW_SIZE):
                    raise ValueError("Browser face preview resolution is too low")
        except OSError as exc:
            raise ValueError("Browser face preview is unreadable") from exc

    model = str(getattr(provider, "model", "") or "unknown")
    existing = {
        str(row["face_id"])
        for row in con.execute(
            """
            SELECT face_id FROM face_visual_label
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND model=?
            """,
            (str(ident), str(spine_signature or ""), str(outfit_key or ""), model),
        ).fetchall()
    }
    expected = {face.face_id for face in faces}
    if not force_vision and expected.issubset(existing):
        row = con.execute(
            """
            SELECT COUNT(DISTINCT face_id),MAX(updated_at) FROM face_visual_label
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND model=?
            """,
            (str(ident), str(spine_signature or ""), str(outfit_key or ""), model),
        ).fetchone()
        return {
            "ok": True,
            "status": "complete",
            "vision_status": "cached",
            "labeled_count": len(expected),
            "saved_count": int(row[0] or 0),
            "failed_count": 0,
            "completed_at": str(row[1] or ""),
            "model": model,
        }

    if progress:
        progress("labeling", f"正在使用 {model} 按九宫格批次识别表情", 0, len(faces))

    def report_label_progress(completed, total, completed_batches, reviewed):
        if not progress:
            return
        detail = f"完成 {completed_batches} 个九宫格批次"
        if reviewed:
            detail += f"，单项复核 {reviewed} 个"
        progress(
            "labeling",
            f"AI 已识别 {completed} / {total} 个表情（{detail}）",
            completed,
            total,
        )

    semantic_hints = {
        face_id: {
            **record,
            "labels": list(record.get("semantic_labels") or record.get("labels") or []),
        }
        for face_id, record in combinations.items()
    }
    labels = spine_face_labeler.label_face_images(
        provider,
        faces,
        semantic_hints=semantic_hints,
        progress=report_label_progress,
    )
    if progress:
        progress("persisting", f"正在保存 {len(labels)} 个 AI 表情标注", 0, len(labels))
    saved = spine_face_labeler.persist_visual_face_labels(
        con,
        ident=str(ident),
        spine_signature=str(spine_signature or ""),
        outfit_key=str(outfit_key or ""),
        model=model,
        labels=labels,
    )
    status = "partial" if int(saved.get("failed_count") or 0) else "complete"
    if progress:
        progress(
            status,
            f"AI 已写入 {saved['saved_count']} 个视觉表情标注，{saved['failed_count']} 个失败",
            int(saved["saved_count"]),
            len(faces),
        )
    return {
        "ok": True,
        "status": status,
        "vision_status": "labeled",
        "labeled_count": int(saved.get("saved_count") or 0),
        "model": model,
        **saved,
    }
