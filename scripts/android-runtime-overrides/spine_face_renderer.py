"""Android helpers for browser-rendered Spine face previews."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops

from android_runtime_guard import unavailable


HEAD_PREVIEW_SIZE = 768
_FACE_ZONE_RATIO = 0.25
_FACE_CHANGE_ZONE_RATIO = 0.48


@dataclass(frozen=True)
class RenderedFace:
    face_id: str
    portrait_path: Path
    head_path: Path


def _square_box(center_x, center_y, side):
    side = max(1, round(side))
    left = round(center_x - side / 2)
    top = round(center_y - side / 2)
    return left, top, left + side, top + side


def _upper_alpha_crop(image):
    alpha_bbox = image.getchannel("A").point(
        lambda value: 255 if value >= 8 else 0
    ).getbbox()
    if not alpha_bbox:
        raise ValueError("Rendered portrait is empty")
    left, top, right, bottom = _face_alpha_bbox(image, alpha_bbox)
    side = max(right - left, bottom - top)
    side = max(side, round((right - left) * 1.12))
    return _square_box((left + right) / 2, top + side * 0.48, side)


def _face_alpha_bbox(image, alpha_bbox=None):
    """Estimate the head zone from the upper portrait, ignoring lower props."""
    alpha_bbox = alpha_bbox or image.getchannel("A").point(
        lambda value: 255 if value >= 8 else 0
    ).getbbox()
    if not alpha_bbox:
        raise ValueError("Rendered portrait is empty")
    _, top, _, bottom = alpha_bbox
    zone_bottom = top + max(1, round((bottom - top) * _FACE_ZONE_RATIO))
    mask = image.getchannel("A").point(lambda value: 255 if value >= 8 else 0)
    zone_bbox = mask.crop((0, top, image.width, min(image.height, zone_bottom))).getbbox()
    if not zone_bbox:
        return alpha_bbox
    return (zone_bbox[0], top + zone_bbox[1], zone_bbox[2], top + zone_bbox[3])


def derive_shared_face_crop(paths):
    """Find one image-driven crop shared by an aligned expression set."""
    paths = tuple(paths)
    if not paths:
        raise ValueError("No usable rendered portraits")
    try:
        first = Image.open(paths[0]).convert("RGBA")
        first.load()
    except (OSError, ValueError) as exc:
        raise ValueError("No usable rendered portraits") from exc
    if not first.getchannel("A").getbbox():
        raise ValueError("No usable rendered portraits")
    fallback = _upper_alpha_crop(first)
    if len(paths) < 2:
        return fallback
    width, height = first.size
    scale = min(1.0, 384 / max(width, height))
    analysis_size = (max(1, round(width * scale)), max(1, round(height * scale)))

    def flattened(image):
        if image.size != analysis_size:
            image = image.resize(analysis_size, Image.Resampling.LANCZOS)
        background = Image.new("RGBA", analysis_size, (224, 226, 230, 255))
        background.alpha_composite(image)
        return background.convert("RGB")

    base = flattened(first)
    difference = Image.new("L", analysis_size, 0)
    for path in paths[1:]:
        try:
            image = Image.open(path).convert("RGBA")
            image.load()
        except (OSError, ValueError):
            continue
        if image.size != first.size:
            return fallback
        difference = ImageChops.lighter(
            difference, ImageChops.difference(base, flattened(image)).convert("L")
        )
    changed = difference.point(lambda value: 255 if value >= 12 else 0).getbbox()
    if not changed:
        return fallback
    scale_x, scale_y = width / analysis_size[0], height / analysis_size[1]
    left, top, right, bottom = (
        changed[0] * scale_x,
        changed[1] * scale_y,
        changed[2] * scale_x,
        changed[3] * scale_y,
    )
    first_alpha = first.getchannel("A").point(
        lambda value: 255 if value >= 8 else 0
    ).getbbox()
    if first_alpha:
        zone_bottom = first_alpha[1] + round((first_alpha[3] - first_alpha[1]) * _FACE_CHANGE_ZONE_RATIO)
        top = max(top, first_alpha[1])
        bottom = min(bottom, zone_bottom)
    if bottom <= top:
        return fallback
    fallback_side = fallback[2] - fallback[0]
    side = max(fallback_side, (right - left) * 1.5, (bottom - top) * 1.35)
    side = min(side, fallback_side * 1.55)
    fallback_center_x = (fallback[0] + fallback[2]) / 2
    fallback_center_y = (fallback[1] + fallback[3]) / 2
    center_x = min(max((left + right) / 2, fallback_center_x - side * 0.25), fallback_center_x + side * 0.25)
    center_y = min(max((top + bottom) / 2, fallback_center_y - side * 0.25), fallback_center_y + side * 0.25)
    return _square_box(center_x, center_y, side)


def _crop_with_transparent_padding(image, box):
    left, top, right, bottom = box
    side = right - left
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    source_box = (max(0, left), max(0, top), min(image.width, right), min(image.height, bottom))
    if source_box[2] > source_box[0] and source_box[3] > source_box[1]:
        canvas.alpha_composite(
            image.crop(source_box), (source_box[0] - left, source_box[1] - top)
        )
    return canvas


def crop_face_previews(faces, *, size=HEAD_PREVIEW_SIZE):
    """Write aligned head previews from browser-rendered full portraits."""
    ordered = tuple(faces)
    if not ordered:
        return ()
    dimensions = []
    for face in ordered:
        with Image.open(face.portrait_path) as image:
            dimensions.append(image.size)
    if all(dimensions[index] == dimensions[0] for index in range(1, len(dimensions))):
        boxes = [derive_shared_face_crop([face.portrait_path for face in ordered])] * len(ordered)
    else:
        boxes = []
        for face in ordered:
            with Image.open(face.portrait_path) as source:
                image = source.convert("RGBA")
                image.load()
            boxes.append(_upper_alpha_crop(image))

    def write_preview(face, box):
        with Image.open(face.portrait_path) as source:
            image = source.convert("RGBA")
            image.load()
        preview = _crop_with_transparent_padding(image, box).resize(
            (size, size), Image.Resampling.LANCZOS
        )
        face.head_path.parent.mkdir(parents=True, exist_ok=True)
        preview.save(face.head_path, format="PNG", compress_level=1)

    with ThreadPoolExecutor(max_workers=min(2, len(ordered))) as executor:
        list(executor.map(lambda pair: write_preview(*pair), zip(ordered, boxes)))
    return ordered


def render_face_variations(*args, **kwargs):
    unavailable("spine_rendering")
