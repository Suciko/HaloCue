# -*- coding: utf-8 -*-
"""Render and prepare visual evidence for Spine face animations.

The module keeps source bundles read-only.  Slow editor exports are cached by
the content signature of the ``.skel``, ``.atlas`` and texture PNG files.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from PIL import Image, ImageChops, ImageStat

from spine_semantic_faces import extract_semantic_face_combinations


_SOURCE_SUFFIXES = {".skel", ".atlas", ".png"}
_FRAME_SUFFIX = re.compile(r"_(\d+)\.png$", re.IGNORECASE)
_RENDER_PROFILE = "restore-region-attachment-size-v4"
_HEAD_PREVIEW_SIZE = 768


@dataclass(frozen=True)
class RenderedFace:
    face_id: str
    portrait_path: Path
    head_path: Path


@dataclass(frozen=True)
class RenderReport:
    signature: str
    cache_dir: Path
    faces: tuple[RenderedFace, ...]
    cached: bool


def discover_renderable_face_ids(combinations: Mapping[str, Mapping]) -> list[str]:
    """Return every two-digit animation that can be visually inspected.

    ``99`` is sometimes treated conservatively by the script allowlist until
    AA has observed it, but it is still a real Spine animation and must be
    rendered so a user can verify and label it.
    """
    return sorted(
        face_id
        for face_id in combinations
        if re.fullmatch(r"\d{2}", face_id)
    )


def extend_face_animation_duration(
    skeleton_json: dict,
    face_ids: Sequence[str],
    *,
    duration: float = 8,
) -> None:
    """Add an invisible root hold so zero-length faces can finish loading textures."""
    bones = skeleton_json.get("bones") or []
    if not bones:
        raise ValueError("Spine JSON has no root bone")
    root_name = str(bones[0].get("name") or "")
    if not root_name:
        raise ValueError("Spine JSON root bone has no name")
    animations = skeleton_json.get("animations") or {}
    for face_id in face_ids:
        animation = animations.get(face_id)
        if not isinstance(animation, dict):
            continue
        root = (
            animation.setdefault("bones", {})
            .setdefault(root_name, {})
        )
        translate = root.setdefault("translate", [])
        if not any(float(frame.get("time") or 0) >= duration for frame in translate):
            translate.append({"time": duration})


def bundle_signature(source_dir: str | Path) -> str:
    """Hash every Spine source file without changing or copying the bundle."""
    root = Path(source_dir)
    files = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in _SOURCE_SUFFIXES
        ),
        key=lambda path: path.name,
    )
    if not any(path.suffix.lower() == ".skel" for path in files):
        raise ValueError(f"Spine bundle has no .skel file: {root}")
    if not any(path.suffix.lower() == ".atlas" for path in files):
        raise ValueError(f"Spine bundle has no .atlas file: {root}")
    if not any(path.suffix.lower() == ".png" for path in files):
        raise ValueError(f"Spine bundle has no texture PNG: {root}")

    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def sanitize_spine_output(output: str) -> str:
    """Remove private license data and harmless Java preference warnings."""
    clean: list[str] = []
    registry_continuation = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Licensed to:"):
            continue
        if "WindowsPreferences" in line:
            registry_continuation = True
            continue
        if line.startswith("WARNING: Could not create windows registry node"):
            registry_continuation = True
            continue
        if line.startswith("WARNING: Trying to recreate Windows registry node"):
            registry_continuation = True
            continue
        if registry_continuation and (
            "RegCreateKeyEx" in line
            or "WindowsRegOpenKey" in line
            or line.startswith("WARNING: Could not open windows registry node")
        ):
            continue
        registry_continuation = False
        clean.append(line)
    return "\n".join(clean)


def select_final_frame(directory: str | Path) -> Path:
    """Choose the last numeric frame produced by a Spine PNG sequence."""
    candidates: list[tuple[int, Path]] = []
    for path in Path(directory).glob("*.png"):
        match = _FRAME_SUFFIX.search(path.name)
        if match:
            candidates.append((int(match.group(1)), path))
    if not candidates:
        raise FileNotFoundError(f"No numbered Spine PNG frames in {directory}")
    return max(candidates, key=lambda item: item[0])[1]


def is_textured_render(source: str | Path) -> bool:
    """Reject empty/white silhouettes caused by incomplete editor texture load."""
    try:
        image = Image.open(source).convert("RGBA")
        image.load()
    except (OSError, ValueError):
        # A timed-out Spine process may leave a PNG header or partial IDAT
        # stream behind.  Existing does not mean complete.
        return False
    alpha = image.getchannel("A")
    bbox = alpha.point(lambda value: 255 if value >= 24 else 0).getbbox()
    if not bbox:
        return False
    visible_alpha = alpha.crop(bbox)
    alpha_stat = ImageStat.Stat(visible_alpha)
    if alpha_stat.extrema[0][1] < 240 or alpha_stat.mean[0] < 100:
        return False
    visible = image.crop(bbox)
    opaque_mask = visible.getchannel("A").point(lambda value: 255 if value >= 24 else 0)
    rgb = visible.convert("RGB")

    # A real portrait contains both luminance and colour variation.  White
    # silhouettes have essentially no channel separation or spatial variance.
    r, g, b = rgb.split()
    chroma = ImageChops.difference(r, g)
    chroma = ImageChops.lighter(chroma, ImageChops.difference(g, b))
    chroma = ImageChops.lighter(chroma, ImageChops.difference(r, b))
    chroma_stat = ImageStat.Stat(chroma, mask=opaque_mask)
    luminance_stat = ImageStat.Stat(rgb.convert("L"), mask=opaque_mask)
    return chroma_stat.mean[0] >= 2.0 or luminance_stat.stddev[0] >= 12.0


def crop_head_preview(
    source: str | Path,
    output: str | Path,
    *,
    size: int = _HEAD_PREVIEW_SIZE,
) -> Path:
    """Crop the upper portrait region into a square transparent preview."""
    image = Image.open(source).convert("RGBA")
    alpha_bbox = image.getchannel("A").point(
        lambda value: 255 if value >= 8 else 0
    ).getbbox()
    if not alpha_bbox:
        raise ValueError(f"Rendered portrait is empty: {source}")

    left, top, right, bottom = alpha_bbox
    visible_width = right - left
    visible_height = bottom - top
    head_height = max(1, round(visible_height * 0.34))
    crop_side = max(visible_width, head_height)
    center_x = (left + right) / 2
    crop_left = round(center_x - crop_side / 2)
    crop_top = top
    crop_right = crop_left + crop_side
    crop_bottom = crop_top + crop_side

    canvas = Image.new("RGBA", (crop_side, crop_side), (0, 0, 0, 0))
    source_box = (
        max(0, crop_left),
        max(0, crop_top),
        min(image.width, crop_right),
        min(image.height, crop_top + head_height),
    )
    piece = image.crop(source_box)
    canvas.alpha_composite(
        piece,
        (
            source_box[0] - crop_left,
            source_box[1] - crop_top,
        ),
    )
    preview = canvas.resize((size, size), Image.Resampling.LANCZOS)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    preview.save(destination, format="PNG", optimize=True)
    return destination


def restore_region_attachment_images(
    skeleton_json: dict,
    images_dir: str | Path,
) -> list[dict]:
    """Restore unpacked atlas regions to their Spine attachment dimensions.

    Spine's atlas unpacker writes packed pixels (for example 269x127), while
    region attachments retain their authoring dimensions (for example
    414x195).  Reimporting those packed pixels as loose images makes the face
    parts about 35% too small.  Mesh attachments are deliberately untouched:
    their UVs and vertices, rather than region width/height, define geometry.
    """
    root = Path(images_dir)
    expected_by_path: dict[str, tuple[int, int]] = {}

    skins = skeleton_json.get("skins") or []
    if isinstance(skins, dict):
        skin_records = skins.values()
    else:
        skin_records = skins

    for skin in skin_records:
        if not isinstance(skin, dict):
            continue
        attachments = skin.get("attachments")
        if not isinstance(attachments, dict):
            # Spine 3.7 and earlier JSON may store the slot map directly
            # under the skin name.
            attachments = {
                key: value
                for key, value in skin.items()
                if key != "name"
            }
        for slot in attachments.values():
            if not isinstance(slot, dict):
                continue
            for attachment_name, attachment in slot.items():
                if not isinstance(attachment, dict):
                    continue
                if attachment.get("type", "region") != "region":
                    continue
                width = round(float(attachment.get("width") or 0))
                height = round(float(attachment.get("height") or 0))
                if width <= 0 or height <= 0:
                    continue
                raw_path = str(
                    attachment.get("path")
                    or attachment.get("name")
                    or attachment_name
                ).replace("\\", "/")
                relative = Path(raw_path)
                if relative.suffix.lower() != ".png":
                    relative = relative.with_suffix(".png")
                normalized = relative.as_posix()
                expected = (width, height)
                previous = expected_by_path.get(normalized)
                if previous is not None and previous != expected:
                    raise ValueError(
                        "Spine region is used with conflicting attachment sizes: "
                        f"{normalized} is both {previous} and {expected}"
                    )
                expected_by_path[normalized] = expected

    restored: list[dict] = []
    for normalized, expected in expected_by_path.items():
        image_path = root / Path(normalized)
        if not image_path.is_file():
            continue
        with Image.open(image_path) as source:
            source.load()
            actual = source.size
            if actual == expected:
                continue
            resized = source.convert("RGBA").resize(
                expected,
                Image.Resampling.LANCZOS,
            )
        resized.save(image_path, format="PNG", optimize=True)
        restored.append(
            {
                "path": normalized,
                "from": list(actual),
                "to": list(expected),
            }
        )
    return restored


def _run_spine(
    command: Sequence[str],
    *,
    timeout_seconds: int | float = 120,
) -> str:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        parts = []
        for value in (exc.stdout, exc.stderr):
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if value:
                parts.append(str(value))
        detail = sanitize_spine_output("\n".join(parts))
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(
            f"Spine command timed out after {timeout_seconds:g} seconds{suffix}"
        ) from exc
    combined = sanitize_spine_output(
        "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    )
    if completed.returncode:
        raise RuntimeError(combined or f"Spine exited with code {completed.returncode}")
    return combined


def _export_settings(
    *,
    project: Path,
    output: Path,
    animation: str,
    compression: int,
) -> dict:
    return {
        "class": "com.esotericsoftware.spine.editor.export.ExportSettings$ExportPng",
        "name": "PNG",
        "project": project.as_posix(),
        "output": output.as_posix(),
        "exportType": "animation",
        "skeletonType": "current",
        "animationType": "single",
        "animation": animation,
        "skinType": "current",
        "skinNone": False,
        "maxBounds": True,
        "renderImages": True,
        "renderBones": False,
        "renderOthers": False,
        "linearFiltering": True,
        "scale": 100,
        "fitWidth": 0,
        "fitHeight": 0,
        "enlarge": False,
        "fps": 1,
        "lastFrame": True,
        "rangeStart": -1,
        "rangeEnd": -1,
        "pad": True,
        "msaa": 4,
        "compression": compression,
        "open": False,
    }


def _json_export_settings() -> dict:
    return {
        "class": "com.esotericsoftware.spine.editor.export.ExportSettings$ExportJson",
        "name": "JSON",
        "extension": ".json",
        "format": "JSON",
        "prettyPrint": True,
        "nonessential": True,
        "cleanUp": False,
        "warnings": True,
        "open": False,
    }


def _prepare_warmed_project(
    *,
    execute: Callable[[Sequence[str]], str],
    cli: Path,
    project: Path,
    work: Path,
    face_ids: Sequence[str],
) -> Path:
    # v4 restores atlas-unpacked region images both when creating and reusing
    # the warmed project.  A repeat unpack must never shrink the loose images.
    # Keep the version in the filename so a malformed warmed project cannot
    # silently survive the renderer correction.
    warmed = work / "render-warmup-v4.spine"
    patched = work / "render-warmup-v4.json"
    if warmed.exists() and patched.exists():
        cached_data = json.loads(patched.read_text(encoding="utf-8"))
        restore_region_attachment_images(cached_data, work)
        return warmed
    export_dir = work / f"json-export-{len(list(work.glob('json-export-*'))):03d}"
    export_dir.mkdir(parents=True, exist_ok=False)
    settings = work / "json-export-settings.json"
    settings.write_text(
        json.dumps(_json_export_settings(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    execute(
        [
            str(cli),
            "--update",
            "3.8.75",
            "--input",
            str(project),
            "--output",
            str(export_dir),
            "--export",
            str(settings),
        ]
    )
    exported = sorted(export_dir.glob("*.json"))
    if len(exported) != 1:
        raise RuntimeError(
            f"Expected one exported Spine JSON, found {len(exported)} in {export_dir}"
        )
    data = json.loads(exported[0].read_text(encoding="utf-8"))
    data.setdefault("skeleton", {})["images"] = work.as_posix()
    restore_region_attachment_images(data, work)
    all_numbered = [
        name
        for name in (data.get("animations") or {})
        if re.fullmatch(r"\d{2}", name)
    ]
    extend_face_animation_duration(data, all_numbered, duration=8)
    patched.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    execute(
        [
            str(cli),
            "--update",
            "3.8.75",
            "--input",
            str(patched),
            "--output",
            str(warmed),
            "--import",
            project.stem,
        ]
    )
    return warmed


def _load_cached_report(
    cache_dir: Path, signature: str, face_ids: Sequence[str]
) -> RenderReport | None:
    manifest = cache_dir / "manifest.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        data.get("signature") != signature
        or data.get("face_ids") != list(face_ids)
        or data.get("render_profile") != _RENDER_PROFILE
    ):
        return None
    faces = tuple(
        RenderedFace(
            face_id=face_id,
            portrait_path=cache_dir / "portraits-v4" / f"{face_id}.png",
            head_path=cache_dir / "heads-v4" / f"{face_id}.png",
        )
        for face_id in face_ids
    )
    if not all(
        face.portrait_path.exists()
        and face.head_path.exists()
        and is_textured_render(face.portrait_path)
        for face in faces
    ):
        return None
    return RenderReport(
        signature=signature,
        cache_dir=cache_dir,
        faces=faces,
        cached=True,
    )


def render_face_variations(
    source_dir: str | Path,
    *,
    spine_cli: str | Path,
    cache_root: str | Path,
    face_ids: Sequence[str] | None = None,
    runner: Callable[[Sequence[str]], str] | None = None,
    workers: int = 1,
    command_timeout_seconds: int | float = 120,
    progress: Callable[[str, int, int], None] | None = None,
) -> RenderReport:
    """Render numbered expressions without modifying the source Spine bundle."""
    source = Path(source_dir).resolve()
    cli = Path(spine_cli).resolve()
    execute = runner or (
        lambda command: _run_spine(
            command, timeout_seconds=command_timeout_seconds
        )
    )
    if runner is None and not cli.is_file():
        raise FileNotFoundError(f"Spine command line executable not found: {cli}")

    skeletons = sorted(source.glob("*.skel"))
    atlases = sorted(source.glob("*.atlas"))
    if len(skeletons) != 1 or len(atlases) != 1:
        raise ValueError(
            "A renderable Spine bundle must contain exactly one .skel and one .atlas"
        )
    signature = bundle_signature(source)
    if face_ids is None:
        combinations = extract_semantic_face_combinations(skeletons[0])
        selected_ids = discover_renderable_face_ids(combinations)
    else:
        selected_ids = sorted(dict.fromkeys(str(item) for item in face_ids))
    if not selected_ids:
        raise ValueError("No renderable numbered face animations were found")
    if workers < 1:
        raise ValueError("workers must be at least 1")

    cache_dir = Path(cache_root).resolve() / signature
    cached = _load_cached_report(cache_dir, signature, selected_ids)
    if cached:
        return cached

    work = cache_dir / "work"
    unpacked = work / "images"
    work.mkdir(parents=True, exist_ok=True)
    unpacked.mkdir(parents=True, exist_ok=True)
    execute(
        [
            str(cli),
            "--update",
            "3.8.75",
            "--input",
            str(source),
            "--output",
            str(unpacked),
            "--unpack",
            str(atlases[0]),
        ]
    )

    skeleton_copy = work / skeletons[0].name
    shutil.copy2(skeletons[0], skeleton_copy)
    for image in unpacked.rglob("*.png"):
        relative = image.relative_to(unpacked)
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image, destination)

    project = work / "source-project-v1.spine"
    if not project.exists():
        execute(
            [
                str(cli),
                "--update",
                "3.8.75",
                "--input",
                str(skeleton_copy),
                "--output",
                str(project),
                "--import",
                skeletons[0].stem,
            ]
        )
    project = _prepare_warmed_project(
        execute=execute,
        cli=cli,
        project=project,
        work=work,
        face_ids=selected_ids,
    )

    portraits = cache_dir / "portraits-v4"
    heads = cache_dir / "heads-v4"
    settings_dir = work / "settings"
    portraits.mkdir(parents=True, exist_ok=True)
    heads.mkdir(parents=True, exist_ok=True)
    settings_dir.mkdir(parents=True, exist_ok=True)
    def render_one(face_id: str) -> RenderedFace:
        portrait = portraits / f"{face_id}.png"
        head = heads / f"{face_id}.png"
        if portrait.exists() and head.exists() and is_textured_render(portrait):
            return RenderedFace(
                face_id=face_id, portrait_path=portrait, head_path=head
            )
        animation = "Idle_01" if face_id == "00" else face_id
        accepted: Path | None = None
        last_error: Exception | None = None
        for attempt, compression in enumerate((1, 9), start=1):
            raw_dir = work / "raw" / face_id / f"attempt-{attempt}"
            raw_dir.mkdir(parents=True, exist_ok=True)
            output = raw_dir / "face"
            settings = settings_dir / f"{face_id}-attempt-{attempt}.json"
            settings.write_text(
                json.dumps(
                    _export_settings(
                        project=project,
                        output=output,
                        animation=animation,
                        compression=compression,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            try:
                execute(
                    [
                        str(cli),
                        "--update",
                        "3.8.75",
                        "--input",
                        str(project),
                        "--output",
                        str(output),
                        "--export",
                        str(settings),
                    ]
                )
                final_frame = select_final_frame(raw_dir)
            except (RuntimeError, FileNotFoundError) as exc:
                last_error = exc
                # Spine 3.8 occasionally finishes writing the complete PNG
                # sequence but leaves its command-line process alive.  A
                # timeout is still required, yet a valid final frame should
                # be retained instead of paying for another full export.
                try:
                    final_frame = select_final_frame(raw_dir)
                except FileNotFoundError:
                    continue
                if is_textured_render(final_frame):
                    accepted = final_frame
                    break
                continue
            if is_textured_render(final_frame):
                accepted = final_frame
                break
        if accepted is None:
            suffix = f": {last_error}" if last_error else ""
            raise RuntimeError(
                f"Spine face {face_id} remained an untextured silhouette after retry"
                f"{suffix}"
            )
        shutil.copy2(accepted, portrait)
        crop_head_preview(portrait, head)
        return RenderedFace(
            face_id=face_id, portrait_path=portrait, head_path=head
        )

    total = len(selected_ids)
    if workers == 1:
        rendered = []
        for index, face_id in enumerate(selected_ids):
            if progress:
                progress(face_id, index, total)
            rendered.append(render_one(face_id))
            if progress:
                progress(face_id, index + 1, total)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(render_one, face_id): face_id
                for face_id in selected_ids
            }
            completed = []
            for future in as_completed(futures):
                face_id = futures[future]
                completed.append(future.result())
                if progress:
                    progress(face_id, len(completed), total)
            rendered = sorted(completed, key=lambda face: selected_ids.index(face.face_id))

    (cache_dir / "manifest.json").write_text(
        json.dumps(
            {
                "signature": signature,
                "face_ids": selected_ids,
                "spine_version": "3.8.75",
                "render_profile": _RENDER_PROFILE,
                "head_preview_size": _HEAD_PREVIEW_SIZE,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return RenderReport(
        signature=signature,
        cache_dir=cache_dir,
        faces=tuple(rendered),
        cached=False,
    )
