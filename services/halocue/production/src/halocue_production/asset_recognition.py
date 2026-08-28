from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .errors import ProductionError


RECOGNITION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "scene_type": {"type": "string"},
        "time_of_day": {"type": "string"},
        "mood": {"type": "string"},
        "expression_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "face_id": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["face_id", "label"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "summary", "tags", "scene_type", "time_of_day", "mood", "expression_suggestions"],
    "additionalProperties": False,
}


def _jpeg(path: Path) -> bytes:
    try:
        with Image.open(path) as image:
            image.thumbnail((1280, 1280))
            if image.mode in {"RGBA", "LA"}:
                canvas = Image.new("RGB", image.size, "white")
                canvas.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
                image = canvas
            else:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
    except (OSError, ValueError) as exc:
        raise ProductionError("asset_recognition_preview_invalid", "素材预览无法转换为视觉输入", status=422) from exc


def _image_sources(source: Path, kind: str) -> list[Path]:
    if kind in {"background", "cg"} and source.is_file():
        return [source]
    if kind != "character" or not source.is_dir():
        return []
    images = [*source.rglob("*.png"), *source.rglob("*.jpg"), *source.rglob("*.jpeg")]
    images.sort(key=lambda path: (
        "avatar" not in path.name.casefold() and "portrait" not in path.name.casefold(),
        "face" not in path.name.casefold(),
        path.stat().st_size if path.is_file() else 0,
        path.name.casefold(),
    ))
    return images[:4]


def recognize(provider: Any, *, source: Path, kind: str, metadata: dict[str, Any], filename: str) -> dict[str, Any]:
    if kind == "sound":
        raise ProductionError(
            "asset_recognition_media_unsupported",
            "当前 Provider 协议尚不支持音频内容识别；音效仍可按技术参数登记",
            status=409,
        )
    sources = _image_sources(source, kind)
    if not sources:
        raise ProductionError(
            "asset_recognition_preview_missing",
            "没有找到可供 AI 查看的人物头像、贴图或图片预览",
            status=422,
        )
    images = [(path.name, _jpeg(path)) for path in sources]
    face_ids = [str(value) for value in (metadata.get("faces") or []) if str(value).strip()][:80]
    system = (
        "You are a production asset cataloger. Analyze only the supplied images and metadata. "
        "Return a concise JSON proposal. Do not claim to have rendered Spine animation. "
        "For character bundles, expression_suggestions may only use supplied face_ids; leave it empty when the texture does not prove semantics."
    )
    user = (
        f"Asset kind: {kind}\nFilename: {filename}\n"
        f"Deterministic metadata: width={metadata.get('width')}, height={metadata.get('height')}, "
        f"spine_version={metadata.get('spine_version')}, face_ids={face_ids}.\n"
        "Propose a Chinese title, factual visual summary, searchable tags, scene type, time of day, mood, and conservative expression labels."
    )
    try:
        raw = provider.complete_json_vision(system, images, user, RECOGNITION_SCHEMA)
    except ProductionError:
        raise
    except Exception as exc:
        raise ProductionError(
            str(getattr(exc, "code", "asset_recognition_failed")),
            str(exc),
            status=502,
            details={"model": str(getattr(exc, "model", "") or "")},
        ) from exc
    allowed_faces = set(face_ids)
    expressions = []
    for item in raw.get("expression_suggestions") or []:
        if not isinstance(item, dict):
            continue
        face_id = str(item.get("face_id") or "").strip()
        label = str(item.get("label") or "").strip()
        if face_id in allowed_faces and label:
            expressions.append({"face_id": face_id, "label": label[:80]})
    candidate = {
        "title": str(raw.get("title") or "").strip()[:160],
        "summary": str(raw.get("summary") or "").strip()[:800],
        "tags": list(dict.fromkeys(str(value).strip() for value in (raw.get("tags") or []) if str(value).strip()))[:16],
        "scene_type": str(raw.get("scene_type") or "").strip()[:80],
        "time_of_day": str(raw.get("time_of_day") or "").strip()[:80],
        "mood": str(raw.get("mood") or "").strip()[:80],
        "expression_suggestions": expressions,
    }
    return {
        "schema_version": "custom-asset-recognition/1.0",
        "state": "proposal",
        "candidate": candidate,
        "evidence": {
            "scope": "avatar_and_texture_preview" if kind == "character" else "uploaded_image",
            "image_count": len(images),
            "spine_animation_rendered": False,
        },
        "provider": str(getattr(provider, "name", "")),
        "model": str(getattr(provider, "model", "")),
        "usage": dict(getattr(provider, "stats", {}) or {}),
    }
