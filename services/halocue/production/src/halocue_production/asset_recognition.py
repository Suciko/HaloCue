from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from typing import Any, Sequence

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

RECOGNITION_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": True,
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


def _image_sources(
    source: Path, kind: str, rendered_sources: Sequence[Path] = ()
) -> list[Path]:
    if kind in {"background", "cg"} and source.is_file():
        return [source]
    if kind != "character" or not source.is_dir():
        return []
    rendered = [Path(path) for path in rendered_sources if Path(path).is_file()]
    if rendered:
        return rendered[:12]
    images = [*source.rglob("*.png"), *source.rglob("*.jpg"), *source.rglob("*.jpeg")]
    images.sort(key=lambda path: (
        "avatar" not in path.name.casefold() and "portrait" not in path.name.casefold(),
        "face" not in path.name.casefold(),
        path.stat().st_size if path.is_file() else 0,
        path.name.casefold(),
    ))
    return images[:4]


def _semantic_face_evidence(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Keep only small, deterministic face hints safe to send with images."""
    raw = metadata.get("semantic_face_combinations")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for face_id, value in sorted(raw.items(), key=lambda item: str(item[0]))[:80]:
        if not isinstance(value, dict):
            continue
        labels = [
            str(item).strip()[:80]
            for item in (value.get("semantic_labels") or value.get("labels") or [])
            if str(item).strip()
        ][:12]
        parts = [
            str(item).strip()[:100]
            for item in (value.get("parts") or [])
            if str(item).strip()
        ][:24]
        result[str(face_id)[:32]] = {
            "primary_emotion": str(value.get("primary_emotion") or "").strip()[:80],
            "semantic_labels": labels,
            "parts": parts,
        }
    return result


def recognize(
    provider: Any,
    *,
    source: Path,
    kind: str,
    metadata: dict[str, Any],
    filename: str,
    rendered_sources: Sequence[Path] = (),
    render_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if kind == "sound":
        raise ProductionError(
            "asset_recognition_media_unsupported",
            "当前 Provider 协议尚不支持音频内容识别；音效仍可按技术参数登记",
            status=409,
        )
    render_evidence = render_evidence if isinstance(render_evidence, dict) else {}
    sources = _image_sources(source, kind, rendered_sources)
    if not sources:
        raise ProductionError(
            "asset_recognition_preview_missing",
            "没有找到可供 AI 查看的人物头像、贴图或图片预览",
            status=422,
        )
    images = [(path.name, _jpeg(path)) for path in sources]
    face_ids = [str(value) for value in (metadata.get("faces") or []) if str(value).strip()][:80]
    semantic_faces = _semantic_face_evidence(metadata) if kind == "character" else {}
    rendered_count = int(render_evidence.get("rendered_animation_count") or 0)
    rendered = kind == "character" and rendered_count > 0
    system = (
        "You are a production asset cataloger. Analyze only the supplied images and metadata. "
        "Return a concise JSON proposal. "
        + (
            "The character images include numbered Spine face animation renderings; use visible differences as visual evidence, but do not infer faces that are not supplied. "
            if rendered
            else "Do not claim to have rendered Spine animation. "
        )
        + "For character bundles, expression_suggestions may only use supplied face_ids; leave it empty when the texture does not prove semantics."
        + " Deterministic skeleton labels are hints, not visual proof; never invent a face ID or claim rendered animation."
    )
    user = (
        f"Asset kind: {kind}\nFilename: {filename}\n"
        f"Deterministic metadata: width={metadata.get('width')}, height={metadata.get('height')}, "
        f"spine_version={metadata.get('spine_version')}, face_ids={face_ids}, "
        f"semantic_face_hints={json.dumps(semantic_faces, ensure_ascii=False, sort_keys=True)}, "
        f"rendered_face_ids={render_evidence.get('rendered_face_ids') or []}.\n"
        "Propose a Chinese title, factual visual summary, searchable tags, scene type, time of day, mood, and conservative expression labels."
    )
    repaired = False
    try:
        raw = provider.complete_json_vision(system, images, user, RECOGNITION_SCHEMA)
    except Exception as exc:
        if str(getattr(exc, "code", "")) != "structured_output_invalid":
            if isinstance(exc, ProductionError):
                raise
            raise ProductionError(
                str(getattr(exc, "code", "asset_recognition_failed")),
                str(exc),
                status=502,
                details={"model": str(getattr(exc, "model", "") or "")},
            ) from exc
        repaired = True
        repair_system = (
            system
            + " The previous JSON was incomplete. Return an object with at least a factual summary; "
            + "leave uncertain optional fields empty and do not invent expression IDs."
        )
        try:
            raw = provider.complete_json_vision(
                repair_system, images, user, RECOGNITION_REPAIR_SCHEMA
            )
        except Exception as repair_exc:
            if isinstance(repair_exc, ProductionError):
                raise
            raise ProductionError(
                str(getattr(repair_exc, "code", "asset_recognition_failed")),
                str(repair_exc),
                status=502,
                details={"model": str(getattr(repair_exc, "model", "") or "")},
            ) from repair_exc
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
        "title": str(raw.get("title") or Path(filename).stem).strip()[:160],
        "summary": str(raw.get("summary") or "模型没有提供可用摘要，请手工补充。").strip()[:800],
        "tags": list(dict.fromkeys(str(value).strip() for value in (raw.get("tags") or []) if str(value).strip()))[:16],
        "scene_type": str(raw.get("scene_type") or "").strip()[:80],
        "time_of_day": str(raw.get("time_of_day") or "").strip()[:80],
        "mood": str(raw.get("mood") or "").strip()[:80],
        "expression_suggestions": expressions,
    }
    evidence = {
        "scope": "rendered_spine_face_preview" if rendered else "avatar_and_texture_preview" if kind == "character" else "uploaded_image",
        "image_count": len(images),
        "validated_face_ids": face_ids if kind == "character" else [],
        "semantic_face_count": len(semantic_faces) if kind == "character" else 0,
        "expression_source": (
            "rendered_spine_preview_and_skeleton_metadata"
            if rendered and semantic_faces
            else "rendered_spine_preview"
            if rendered
            else "skeleton_metadata_and_static_preview"
            if kind == "character" and semantic_faces
            else "atlas_allowlist_and_static_preview"
            if kind == "character"
            else "uploaded_image"
        ),
        "rendered_animation_count": rendered_count,
        "spine_animation_rendered": rendered,
    }
    if rendered:
        evidence.update(
            {
                "rendered_face_ids": [
                    str(value).strip()
                    for value in (render_evidence.get("rendered_face_ids") or [])
                    if str(value).strip()
                ][:80],
                "calibration": list(render_evidence.get("calibration") or [])[:80],
            }
        )
    if repaired:
        evidence["response_repaired"] = True
    return {
        "schema_version": "custom-asset-recognition/1.0",
        "state": "proposal",
        "candidate": candidate,
        "evidence": evidence,
        "provider": str(getattr(provider, "name", "")),
        "model": str(getattr(provider, "model", "")),
        "usage": dict(getattr(provider, "stats", {}) or {}),
    }
