# -*- coding: utf-8 -*-
"""背景、音效和 Spine 资源的纯验证逻辑；本模块不写 AA 工作区。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Iterable

from PIL import Image

from aa_project_assets import validate_windows_path_component
from asset_models import AssetCandidate, ValidationIssue, ValidationResult
from tables import bg_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _name_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _name_issue(stem: str, existing_names: Iterable[str]) -> ValidationIssue | None:
    if not stem.strip():
        return ValidationIssue("empty_name", "素材文件名去扩展名后不能为空")
    wanted = _name_key(stem)
    for existing in existing_names:
        if _name_key(str(existing)) == wanted:
            return ValidationIssue(
                "name_conflict",
                f"素材名 {stem!r} 与当前作用域中的 {existing!r} 冲突",
            )
    return None


def validate_background(
    source_path: str | Path,
    *,
    existing_names: Iterable[str] = (),
) -> ValidationResult:
    path = Path(source_path)
    issues: list[ValidationIssue] = []
    name_issue = _name_issue(path.stem, existing_names)
    if name_issue:
        issues.append(name_issue)
    if not path.is_file():
        issues.append(ValidationIssue("file_missing", f"背景文件不存在：{path}"))
        return ValidationResult(None, tuple(issues))

    try:
        with Image.open(path) as image:
            image.load()
            width, height, mode = image.width, image.height, image.mode
            fmt = image.format
            has_icc = bool(image.info.get("icc_profile"))
    except Exception as exc:
        issues.append(ValidationIssue("image_unreadable", f"无法读取背景图片：{exc}"))
        return ValidationResult(None, tuple(issues))

    if mode not in {"RGB", "RGBA"}:
        issues.append(
            ValidationIssue(
                "unsupported_color_mode",
                f"AA 自定义背景当前只验证 RGB/RGBA，实际为 {mode}",
            )
        )
    if (fmt or "").upper() not in {"PNG", "JPEG"}:
        issues.append(
            ValidationIssue(
                "unsupported_image_format",
                f"AA 自定义背景当前只验证 PNG/JPEG，实际为 {fmt or '未知'}",
            )
        )

    candidate = AssetCandidate(
        kind="background",
        source_path=path.resolve(),
        stem=path.stem,
        aa_key=int(bg_id(path.stem)),
        sha256=_sha256(path),
        metadata={
            "width": width,
            "height": height,
            "mode": mode,
            "format": fmt,
            "has_icc_profile": has_icc,
        },
    )
    return ValidationResult(candidate, tuple(issues))


def _find_ffprobe(explicit: str | Path | None) -> str | None:
    if explicit:
        p = Path(explicit)
        return str(p) if p.is_file() else None
    found = shutil.which("ffprobe")
    if found:
        return found
    bundled = Path(r"E:\ffmpeg\bin\ffprobe.exe")
    return str(bundled) if bundled.is_file() else None


def validate_sound(
    source_path: str | Path,
    *,
    existing_names: Iterable[str] = (),
    ffprobe_path: str | Path | None = None,
) -> ValidationResult:
    path = Path(source_path)
    issues: list[ValidationIssue] = []
    name_issue = _name_issue(path.stem, existing_names)
    if name_issue:
        issues.append(name_issue)
    if not path.is_file():
        issues.append(ValidationIssue("file_missing", f"音效文件不存在：{path}"))
        return ValidationResult(None, tuple(issues))

    probe = _find_ffprobe(ffprobe_path)
    if not probe:
        issues.append(ValidationIssue("probe_unavailable", "找不到 ffprobe，无法验证音频"))
        return ValidationResult(None, tuple(issues))
    command = [
        probe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,sample_fmt,bits_per_sample:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        payload = json.loads(proc.stdout)
        stream = payload["streams"][0]
    except Exception as exc:
        issues.append(ValidationIssue("audio_unreadable", f"ffprobe 无法读取音频：{exc}"))
        return ValidationResult(None, tuple(issues))

    codec = str(stream.get("codec_name") or "")
    sample_rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)
    bits = int(stream.get("bits_per_sample") or 0)
    sample_fmt = str(stream.get("sample_fmt") or "")
    duration = float(payload.get("format", {}).get("duration") or 0)
    if (
        path.suffix.casefold() != ".wav"
        or codec != "pcm_s16le"
        or bits != 16
        or sample_fmt != "s16"
    ):
        issues.append(
            ValidationIssue(
                "transcode_required",
                "首版安装只接受 PCM signed 16-bit WAV；请先转码",
            )
        )

    candidate = AssetCandidate(
        kind="sound",
        source_path=path.resolve(),
        stem=path.stem,
        aa_key=path.stem,
        sha256=_sha256(path),
        metadata={
            "codec": codec,
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_fmt": sample_fmt,
            "bits_per_sample": bits,
            "duration": duration,
        },
    )
    return ValidationResult(candidate, tuple(issues))


def _spine_base(source: Path) -> tuple[Path | None, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    if source.is_dir():
        skels = sorted(source.glob("*.skel"))
        if len(skels) != 1:
            issues.append(
                ValidationIssue(
                    "skel_count",
                    f"骨骼目录必须正好包含一个 .skel，实际为 {len(skels)}",
                )
            )
            return None, issues
        return skels[0].with_suffix(""), issues
    if source.suffix.casefold() == ".skel":
        return source.with_suffix(""), issues
    return source, issues


def _atlas_pages(lines: list[str]) -> list[str]:
    pages: list[str] = []
    for index, line in enumerate(lines):
        if not line or line[0].isspace() or ":" in line:
            continue
        following = ""
        for other in lines[index + 1 :]:
            if other:
                following = other.strip()
                break
        if following.startswith("size:") or following.startswith("format:"):
            pages.append(line.strip())
    return pages


def _read_atlas_lines(path: Path) -> list[str]:
    """Decode Spine atlas text from encodings commonly used on Windows."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported atlas text encoding")


_PART_KIND_KEYWORDS = (
    ("eyes", ("眼",)),
    ("brows", ("眉",)),
    ("mouth", ("嘴", "唇")),
    ("blush", ("脸红",)),
    ("tear", ("泪",)),
)


def _expression_part_kind(name: str) -> str:
    component_name = re.split(r"[（(]", name, maxsplit=1)[0]
    for kind, keywords in _PART_KIND_KEYWORDS:
        if any(keyword in component_name for keyword in keywords):
            return kind
    return "unknown"


def extract_expression_capabilities(atlas_lines: list[str]) -> dict[str, object]:
    """Extract safe face candidates and optional semantic part hints from an atlas.

    Numeric ``NN_*`` region names are only candidates: AA still has to observe or
    verify a faceId before a model may emit it. Semantic parts intentionally have
    no faceId because a modular Spine file does not prove an AA face mapping.
    """
    pages = set(_atlas_pages(atlas_lines))
    faces: set[str] = set()
    parts: list[dict[str, object]] = []
    seen_parts: set[str] = set()
    for line in atlas_lines:
        raw_name = line.strip()
        if not raw_name or line[:1].isspace() or ":" in raw_name or raw_name in pages:
            continue
        numeric = re.match(r"^(\d{2})(?:_|$)", raw_name)
        if numeric:
            faces.add(numeric.group(1))
        labels = []
        for group in re.findall(r"[（(]([^（）()]*)[）)]", raw_name):
            for value in re.split(r"[、，,]", group):
                value = value.strip()
                if value and value not in labels:
                    labels.append(value)
        if labels and raw_name not in seen_parts:
            seen_parts.add(raw_name)
            parts.append({
                "kind": _expression_part_kind(raw_name),
                "raw_name": raw_name,
                "labels": labels,
                "source": "atlas_semantic",
            })
    if faces:
        mode = "numbered_composite"
    elif parts:
        mode = "semantic_modular"
    else:
        mode = "opaque_custom"
    return {"faces": sorted(faces), "parts": parts, "mode": mode}


def validate_spine(
    source_path: str | Path,
    *,
    identifier: str,
    existing_identifiers: Iterable[str] = (),
) -> ValidationResult:
    source = Path(source_path)
    issues: list[ValidationIssue] = []
    if not identifier.strip():
        issues.append(
            ValidationIssue("identifier_required", "角色 Identifier 必须由用户填写")
        )
    elif any(_name_key(identifier) == _name_key(x) for x in existing_identifiers):
        issues.append(
            ValidationIssue(
                "identifier_conflict",
                f"角色 Identifier {identifier!r} 已存在于当前作用域",
            )
        )

    if identifier.strip():
        try:
            validate_windows_path_component(identifier, label="character Identifier")
        except ValueError as exc:
            issues.append(ValidationIssue("unsafe_path_component", str(exc)))

    base, base_issues = _spine_base(source)
    issues.extend(base_issues)
    if base is None:
        return ValidationResult(None, tuple(issues))

    skel = Path(str(base) + ".skel")
    atlas = Path(str(base) + ".atlas")
    texture = Path(str(base) + ".png")
    avatar = Path(str(base) + "-avatar.png")
    required = [
        ("skel_missing", skel),
        ("atlas_missing", atlas),
        ("texture_missing", texture),
        ("avatar_missing", avatar),
    ]
    for code, path in required:
        if not path.is_file():
            issues.append(ValidationIssue(code, f"缺少 Spine 文件：{path.name}"))

    lines: list[str] = []
    if atlas.is_file():
        try:
            lines = _read_atlas_lines(atlas)
        except Exception as exc:
            issues.append(ValidationIssue("atlas_unreadable", f"无法读取 atlas：{exc}"))
    pages = _atlas_pages(lines)
    directory_names = {p.name for p in base.parent.iterdir()} if base.parent.is_dir() else set()
    for page in pages:
        if page not in directory_names:
            issues.append(
                ValidationIssue(
                    "atlas_page_missing",
                    f"atlas 引用的贴图不存在或大小写不一致：{page}",
                )
            )

    expression = extract_expression_capabilities(lines)
    faces = expression["faces"]
    version = None
    spine_signature = ""
    semantic_face_combinations = {}
    if skel.is_file():
        skel_bytes = skel.read_bytes()
        spine_signature = hashlib.sha256(skel_bytes).hexdigest()
        match = re.search(rb"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", skel_bytes)
        if match:
            version = match.group(1).decode("ascii")
        try:
            # Imported lazily to keep the lightweight atlas validator free of a
            # binary parser dependency and avoid a module import cycle.
            from spine_semantic_faces import extract_semantic_face_combinations
            semantic_face_combinations = extract_semantic_face_combinations(skel)
        except ValueError:
            semantic_face_combinations = {}

    files = {
        "skel": str(skel.resolve()),
        "atlas": str(atlas.resolve()),
        "texture": str(texture.resolve()),
        "avatar": str(avatar.resolve()),
    }
    digest = hashlib.sha256()
    for path in (skel, atlas, texture, avatar):
        if path.is_file():
            digest.update(path.name.encode("utf-8"))
            digest.update(bytes.fromhex(_sha256(path)))
    candidate = AssetCandidate(
        kind="character",
        source_path=base.parent.resolve(),
        stem=base.name,
        aa_key=identifier,
        sha256=digest.hexdigest(),
        metadata={
            "identifier": identifier,
            "files": files,
            "atlas_pages": pages,
            "faces": faces,
            "expression_parts": expression["parts"],
            "expression_mode": expression["mode"],
            "expression_status": (
                "known" if faces or semantic_face_combinations else "unresolved"
            ),
            "semantic_face_combinations": semantic_face_combinations,
            "semantic_face_count": len(semantic_face_combinations),
            "spine_version": version,
            "spine_signature": spine_signature,
            "outfit_key": base.name,
        },
    )
    return ValidationResult(candidate, tuple(issues))
