"""Resolve and rasterize user-owned Spine stage media.

The public repository stores only the adapter.  Skeletons, atlases, textures,
and rendered frames stay in the user's AA data/cache or HaloCue output cache.
Spine 3.8 and 4.2 are selected from the embedded skeleton version so a scene
can use either generation without relying on a global browser runtime.
"""

from __future__ import annotations

import re
from pathlib import Path


_VERSION_RE = re.compile(rb"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)")
_SUPPORTED_FAMILIES = ("3.8", "4.2")
_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class StageMediaError(ValueError):
    """A user asset cannot be exposed as stage media."""


def safe_stage_key(value: str | None) -> str:
    key = str(value or "").strip()
    if (
        not key
        or key in {".", ".."}
        or not _SAFE_COMPONENT_RE.fullmatch(key)
        or "/" in key
        or "\\" in key
    ):
        raise StageMediaError("stage media key must be one safe path component")
    return key


def detect_spine_version(skeleton: str | Path) -> str:
    """Read the embedded Spine editor version without modifying the bundle."""

    try:
        data = Path(skeleton).read_bytes()
    except OSError as exc:
        raise StageMediaError("stage skeleton is unavailable") from exc
    match = _VERSION_RE.search(data)
    if not match:
        raise StageMediaError("stage skeleton has no detectable Spine version")
    return match.group(1).decode("ascii")


def spine_family(version: str) -> str:
    value = str(version or "")
    for family in _SUPPORTED_FAMILIES:
        if value.startswith(family):
            return family
    raise StageMediaError(f"unsupported Spine version: {value or 'unknown'}")


def _bundle_files(root: Path) -> tuple[Path, Path, tuple[Path, ...]]:
    skeletons = sorted(root.glob("*.skel"))
    atlases = sorted(root.glob("*.atlas"))
    if len(skeletons) != 1 or len(atlases) != 1:
        raise StageMediaError("stage bundle must contain one .skel and one .atlas")
    atlas = atlases[0]
    pages: list[Path] = []
    for line in atlas.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        name = line.strip()
        if not name or ":" in name or name.startswith(("size:", "format:", "filter:", "repeat:", "pma:", "scale:")):
            continue
        candidate = (root / name.replace("\\", "/")).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise StageMediaError("atlas texture escapes the stage bundle") from exc
        if candidate.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        if not candidate.is_file():
            raise StageMediaError(f"atlas texture is unavailable: {name}")
        if candidate not in pages:
            pages.append(candidate)
    if not pages:
        fallback = root / f"{atlas.stem}.png"
        if fallback.is_file():
            pages.append(fallback.resolve())
    if not pages:
        raise StageMediaError("atlas has no resolvable texture page")
    return skeletons[0], atlas, tuple(pages)


def resolve_spine_bundle(overrides: str | Path | None, key: str) -> dict[str, object]:
    """Return a safe, local-only description of ``overrides/characters/<key>``."""

    safe_key = safe_stage_key(key)
    if not overrides:
        raise StageMediaError("AA overrides directory is not configured")
    root = (Path(overrides).expanduser().resolve() / "characters" / safe_key).resolve()
    try:
        root.relative_to(Path(overrides).expanduser().resolve())
    except ValueError as exc:
        raise StageMediaError("stage bundle is outside the overrides directory") from exc
    if not root.is_dir():
        raise StageMediaError("stage bundle directory is unavailable")
    skeleton, atlas, pages = _bundle_files(root)
    version = detect_spine_version(skeleton)
    return {
        "key": safe_key,
        "root": root,
        "skeleton": skeleton,
        "atlas": atlas,
        "textures": pages,
        "spine_version": version,
        "spine_family": spine_family(version),
    }


def _catalog_character_stem(key: str) -> str:
    value = safe_stage_key(key)
    lowered = value.casefold()
    if lowered.startswith("characterspine_"):
        value = value[len("CharacterSpine_"):]
    if value.casefold().endswith("_noweapon"):
        value = value[:-len("_noweapon")]
    if not _SAFE_COMPONENT_RE.fullmatch(value):
        raise StageMediaError("catalog character key is not safe")
    return value.casefold()


def extract_catalog_spine_bundle(
    catalog: str | Path | None,
    resource_cache: str | Path | None,
    key: str,
    cache_root: str | Path,
) -> dict[str, object]:
    """Materialize one authorized local catalog Spine bundle into user cache."""

    if not catalog or not resource_cache:
        raise StageMediaError("AA catalog and resource cache are not configured")
    stem = _catalog_character_stem(key)
    try:
        from official_catalog import catalog_bundle_locations
        import UnityPy

        main_rows = catalog_bundle_locations(
            catalog,
            resource_cache,
            internal_predicate=lambda value: value.casefold().endswith(
                f"/characters_assets_{stem}all.bundle"
            ),
        )
        atlas_rows = catalog_bundle_locations(
            catalog,
            resource_cache,
            internal_predicate=lambda value: value.casefold().endswith(
                f"/{stem}_spr.atlas.txt"
            ),
        )
    except Exception as exc:
        raise StageMediaError("AA catalog cannot resolve the Spine bundle") from exc
    if not main_rows or main_rows[0].data_path is None or not atlas_rows or atlas_rows[0].data_path is None:
        raise StageMediaError(f"AA Spine bundle is not cached: {key}")

    root = Path(cache_root).expanduser().resolve() / "catalog-spine" / stem
    skeleton_path = root / f"{stem}_spr.skel"
    atlas_path = root / f"{stem}_spr.atlas"
    texture_path = root / f"{stem}_spr.png"
    if not (skeleton_path.is_file() and atlas_path.is_file() and texture_path.is_file()):
        main_env = UnityPy.load(str(main_rows[0].data_path))
        atlas_env = UnityPy.load(str(atlas_rows[0].data_path))
        skeleton_asset = None
        texture_asset = None
        atlas_asset = None
        for obj in main_env.objects:
            try:
                asset = obj.read()
            except Exception:
                continue
            name = str(getattr(asset, "m_Name", "") or "")
            if obj.type.name == "TextAsset" and name.casefold() == f"{stem}_spr.skel":
                skeleton_asset = asset
            elif obj.type.name == "Texture2D" and name.casefold() == f"{stem}_spr":
                texture_asset = asset
        for obj in atlas_env.objects:
            if obj.type.name != "TextAsset":
                continue
            try:
                asset = obj.read()
            except Exception:
                continue
            if str(getattr(asset, "m_Name", "") or "").casefold() == f"{stem}_spr.atlas":
                atlas_asset = asset
                break
        if skeleton_asset is None or texture_asset is None or atlas_asset is None:
            raise StageMediaError(f"AA Spine assets are incomplete: {key}")
        root.mkdir(parents=True, exist_ok=True)
        skeleton_path.write_bytes(
            str(skeleton_asset.m_Script).encode("utf-8", errors="surrogateescape")
        )
        atlas_text = str(atlas_asset.m_Script).replace("\r", "")
        atlas_path.write_text(atlas_text, encoding="utf-8")
        texture_asset.image.save(texture_path, "PNG")
    version = detect_spine_version(skeleton_path)
    return {
        "key": key,
        "root": root,
        "skeleton": skeleton_path,
        "atlas": atlas_path,
        "textures": (texture_path,),
        "spine_version": version,
        "spine_family": spine_family(version),
    }


def stage_background_from_catalog(
    catalog: str | Path | None,
    cache_root: str | Path,
    key: str,
    *,
    resource_cache: str | Path | None,
) -> Path | None:
    """Extract one full-resolution official background into user cache.

    This is intentionally lazy and never writes to the repository.  A missing
    UnityPy installation or uncached bundle simply returns ``None``.
    """

    safe_key = safe_stage_key(key)
    if not catalog or not resource_cache:
        return None
    try:
        from official_catalog import catalog_bundle_locations
        import UnityPy
        from PIL import Image

        locations = catalog_bundle_locations(
            catalog,
            resource_cache,
            internal_predicate=lambda value: safe_key.casefold() in value.casefold()
            and value.casefold().endswith(".bundle"),
        )
    except Exception:
        return None
    if not locations or locations[0].data_path is None:
        return None
    output = Path(cache_root).expanduser().resolve() / "backgrounds" / f"{safe_key}.png"
    if output.is_file():
        return output
    try:
        environment = UnityPy.load(str(locations[0].data_path))
        for obj in environment.objects:
            if obj.type.name not in {"Texture2D", "Sprite"}:
                continue
            asset = obj.read()
            if str(getattr(asset, "m_Name", "") or "").casefold() != safe_key.casefold() and safe_key.casefold() not in str(getattr(asset, "m_Name", "") or "").casefold():
                continue
            image = getattr(asset, "image", None)
            if image is None:
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            image.convert("RGB").save(output, "PNG")
            return output
    except Exception:
        return None
    return None


def stage_frame_path(
    overrides: str | Path | None,
    key: str,
    *,
    animation: str = "00_default",
    cache_root: str | Path,
    catalog: str | Path | None = None,
    resource_cache: str | Path | None = None,
) -> Path:
    """Render/cache a transparent stage frame through the matching WebGL runtime."""

    try:
        bundle = resolve_spine_bundle(overrides, key)
    except StageMediaError:
        bundle = extract_catalog_spine_bundle(catalog, resource_cache, key, cache_root)
    animation_name = str(animation or "00_default").strip() or "00_default"
    # AA descriptors use the semantic default name; the renderer's face
    # contract uses the first numeric animation as its stable alias.
    if animation_name == "00_default":
        animation_name = "00"
    if not _SAFE_COMPONENT_RE.fullmatch(animation_name):
        raise StageMediaError("animation must be one safe path component")
    from spine_face_web_renderer import SpineWebRenderer

    cache_dir = Path(cache_root).expanduser().resolve() / "spine-stage"
    renderer = SpineWebRenderer(
        spine_version=str(bundle["spine_version"]),
        canvas_size=2048,
        headless=True,
    )
    try:
        with renderer:
            report = renderer.render(
                Path(bundle["root"]),
                face_ids=(animation_name,),
                cache_root=cache_dir,
            )
    except Exception as exc:
        raise StageMediaError(f"Spine stage frame rendering failed: {exc}") from exc
    if not report.faces:
        available = ",".join(report.animation_names[:20])
        raise StageMediaError(
            f"Spine animation not found: {animation_name}; available={available}"
        )
    source = report.faces[0].portrait_path
    tight = report.cache_dir / "stage.png"
    if not tight.is_file():
        try:
            from PIL import Image

            with Image.open(source).convert("RGBA") as image:
                alpha = image.getchannel("A")
                bounds = alpha.getbbox()
                if not bounds:
                    raise StageMediaError("Spine stage frame has no visible pixels")
                image.crop(bounds).save(tight, "PNG", optimize=True)
        except StageMediaError:
            raise
        except Exception as exc:
            raise StageMediaError(f"Unable to crop Spine stage frame: {exc}") from exc
    return tight
