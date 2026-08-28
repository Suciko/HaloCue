# -*- coding: utf-8 -*-
"""Headless WebGL renderer for official Spine 3.8 and 4.2 face animations.

AA's native bundles are Spine 3.8 while current official override bundles are
Spine 4.2. Both are rendered with matching local web runtimes in Chromium, so
batch labeling does not depend on a licensed Spine editor installation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageChops, ImageStat

from asset_validation import _atlas_page_path, _atlas_pages, _read_atlas_lines
from spine_face_renderer import RenderedFace, crop_face_previews


HERE = Path(__file__).resolve().parent
RUNTIME_38 = HERE / "js" / "spine-webgl-3.8.95.js"
RUNTIME_42 = (
    HERE / "js" / "spine-webgl-4.2.119.min.js"
)
# 4.2 runtimes are backward compatible within the same major/minor line.  A
# recent patch is required because referenceScale was added after early 4.2
# runtime packages but is present in the game's 4.2.33 binary exports.
_WEB_RENDER_PROFILES = {
    "3.8": "spine-webgl-3.8.95-face-v3-tight-diff-crop-pma",
    "4.2": "spine-webgl-4.2.119-face-v3-tight-diff-crop-pma",
}
_VERSION_RE = re.compile(rb"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)")


@dataclass(frozen=True)
class WebRenderReport:
    signature: str
    cache_dir: Path
    faces: tuple[RenderedFace, ...]
    cached: bool
    animation_names: tuple[str, ...]
    missing_face_ids: tuple[str, ...] = ()


def detect_spine_version(path: str | Path) -> str:
    """Read the embedded editor version without parsing the binary skeleton."""
    match = _VERSION_RE.search(Path(path).read_bytes())
    return match.group(1).decode("ascii") if match else ""


def _version_family(version: str) -> str:
    for family in ("3.8", "4.2"):
        if str(version or "").startswith(family):
            return family
    raise ValueError(f"Unsupported Spine web version: {version or 'unknown'}")


def runtime_for_spine_version(version: str) -> Path:
    return RUNTIME_42 if _version_family(version) == "4.2" else RUNTIME_38


def _data_uri(path: Path, *, mime: str | None = None) -> str:
    content_type = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _atlas_uses_pma(atlas: Path, family: str) -> bool:
    if family == "3.8":
        # AA's 3.8 textures are straight-alpha files whose transparent edge
        # RGB must be premultiplied at upload time to avoid white fringes.
        return True
    text = atlas.read_text(encoding="utf-8-sig", errors="replace")
    return bool(re.search(
        r"(?:^|\n)\s*pma:\s*true\s*(?:\n|$)", text, re.IGNORECASE
    ))


def _texture_requires_neutral_tint(pages: Sequence[tuple[str, Path]]) -> bool:
    """Detect grayscale exports whose game-runtime tint would crush contrast."""
    try:
        for _, path in pages:
            image = Image.open(path).convert("RGB")
            red, green, blue = image.split()
            chroma = ImageChops.lighter(
                ImageChops.difference(red, green),
                ImageChops.lighter(
                    ImageChops.difference(green, blue),
                    ImageChops.difference(red, blue),
                ),
            )
            if ImageStat.Stat(chroma).mean[0] >= 1.0:
                return False
        return True
    except (OSError, ValueError):
        return False


def _bundle_files(source_dir: str | Path) -> tuple[Path, Path, list[tuple[str, Path]]]:
    source = Path(source_dir).resolve()
    skeletons = sorted(source.glob("*.skel"))
    atlases = sorted(source.glob("*.atlas"))
    if len(skeletons) != 1 or len(atlases) != 1:
        raise ValueError(
            "A renderable Spine bundle must contain exactly one .skel and one .atlas"
        )
    atlas = atlases[0]
    pages: list[tuple[str, Path]] = []
    for name in _atlas_pages(_read_atlas_lines(atlas)):
        resolved = _atlas_page_path(source, name)
        if resolved is None or not resolved.is_file():
            raise FileNotFoundError(f"Spine atlas texture not found: {name}")
        pages.append((name.replace("\\", "/"), resolved))
    if not pages:
        fallback = source / f"{atlas.stem}.png"
        if not fallback.is_file():
            raise FileNotFoundError(f"Spine atlas has no resolvable texture pages: {atlas}")
        pages.append((fallback.name, fallback))
    return skeletons[0], atlas, pages


def web_bundle_signature(source_dir: str | Path) -> str:
    skeleton, atlas, pages = _bundle_files(source_dir)
    family = _version_family(detect_spine_version(skeleton))
    digest = hashlib.sha256(_WEB_RENDER_PROFILES[family].encode("ascii"))
    for path in (skeleton, atlas, *(item[1] for item in pages)):
        digest.update(path.name.encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _is_visible_web_render(path: str | Path) -> bool:
    """Validate WebGL output while allowing sparse transparent portraits."""
    try:
        image = Image.open(path).convert("RGBA")
        image.load()
    except (OSError, ValueError):
        return False
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= 24 else 0)
    bbox = mask.getbbox()
    if not bbox or ImageStat.Stat(mask).sum[0] / 255 < 1000:
        return False
    visible = image.crop(bbox)
    visible_mask = mask.crop(bbox)
    rgb = visible.convert("RGB")
    red, green, blue = rgb.split()
    chroma = ImageChops.difference(red, green)
    chroma = ImageChops.lighter(chroma, ImageChops.difference(green, blue))
    chroma = ImageChops.lighter(chroma, ImageChops.difference(red, blue))
    return (
        ImageStat.Stat(chroma, mask=visible_mask).mean[0] >= 2.0
        or ImageStat.Stat(rgb.convert("L"), mask=visible_mask).stddev[0] >= 12.0
    )


def _load_cached_report(
    cache_dir: Path,
    *,
    signature: str,
    face_ids: Sequence[str],
    render_profile: str,
) -> WebRenderReport | None:
    manifest = cache_dir / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (
        data.get("signature") != signature
        or data.get("render_profile") != render_profile
        or data.get("face_ids") != list(face_ids)
    ):
        return None
    portraits = cache_dir / "portraits"
    heads = cache_dir / "heads"
    faces = tuple(
        RenderedFace(face_id, portraits / f"{face_id}.png", heads / f"{face_id}.png")
        for face_id in face_ids
    )
    if not all(
        face.head_path.is_file()
        and face.portrait_path.is_file()
        and _is_visible_web_render(face.portrait_path)
        for face in faces
    ):
        return None
    return WebRenderReport(
        signature=signature,
        cache_dir=cache_dir,
        faces=faces,
        cached=True,
        animation_names=tuple(str(x) for x in data.get("animation_names") or []),
        missing_face_ids=tuple(str(x) for x in data.get("missing_face_ids") or []),
    )


_PAGE_HTML = """<!doctype html><meta charset=\"utf-8\">
<style>html,body{margin:0;background:transparent}canvas{display:block}</style>
<canvas id=\"face\" width=\"2048\" height=\"2048\"></canvas>"""


_LOAD_SCRIPT = r"""async (payload) => {
  const previous = window.__halocueSpine;
  if (previous) {
    try { previous.assets.removeAll(); } catch (_) {}
    try { previous.shader.dispose(); } catch (_) {}
    try { previous.batcher.dispose(); } catch (_) {}
    window.__halocueSpine = null;
  }
  const canvas = document.getElementById('face');
  canvas.width = payload.canvasSize;
  canvas.height = payload.canvasSize;
  const gl = canvas.getContext('webgl', {
    alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: true,
    antialias: true
  });
  if (!gl || !window.spine) throw new Error('WebGL or Spine runtime unavailable');
  const is42 = String(payload.spineVersion || '').startsWith('4.2');
  const webgl = is42 ? spine : spine.webgl;
  const Shader = is42 ? spine.Shader : spine.webgl.Shader;
  const assets = new webgl.AssetManager(gl);
  assets.setRawDataURI('skeleton.skel', payload.skeleton);
  assets.setRawDataURI('skeleton.atlas', payload.atlas);
  for (const page of payload.textures) assets.setRawDataURI(page.name, page.uri);
  assets.loadBinary('skeleton.skel');
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, Boolean(payload.pma));
  assets.loadTextureAtlas('skeleton.atlas');
  await new Promise((resolve, reject) => {
    const started = Date.now();
    const poll = () => {
      if (assets.isLoadingComplete()) {
        const errors = assets.getErrors();
        if (errors && Object.keys(errors).length) reject(new Error(JSON.stringify(errors)));
        else resolve();
      } else if (Date.now() - started > 60000) reject(new Error('Spine assets timed out'));
      else requestAnimationFrame(poll);
    };
    poll();
  });
  const atlas = assets.get('skeleton.atlas');
  const loader = new spine.AtlasAttachmentLoader(atlas);
  const binary = new spine.SkeletonBinary(loader);
  const skeletonData = binary.readSkeletonData(assets.get('skeleton.skel'));
  const skeleton = new spine.Skeleton(skeletonData);
  const state = new spine.AnimationState(new spine.AnimationStateData(skeletonData));
  const shader = Shader.newTwoColoredTextured(gl);
  const batcher = new webgl.PolygonBatcher(gl);
  const renderer = new webgl.SkeletonRenderer(gl);
  const mvp = new webgl.Matrix4();
  const animationNames = skeletonData.animations.map((item) => item.name);
  window.__halocueSpine = {canvas, gl, assets, skeleton, state, shader, batcher,
    renderer, mvp, animationNames, Shader, pma: Boolean(payload.pma),
    neutralTint: Boolean(payload.neutralTint)};
  return {animationNames};
}"""


_RENDER_SCRIPT = r"""(faceId) => {
  const r = window.__halocueSpine;
  if (!r) throw new Error('Spine bundle was not loaded');
  const {canvas, gl, skeleton, state, shader, batcher, renderer, mvp, Shader} = r;
  skeleton.setToSetupPose();
  state.clearTracks();
  if (r.animationNames.includes(faceId)) state.setAnimation(0, faceId, false);
  else if (faceId !== '00') return {missing: true};
  state.update(0);
  state.apply(skeleton);
  if (r.neutralTint) {
    // Some grayscale exports carry a stale dark slot tint intended for the
    // game's runtime shader, which crushes them to near-black in WebGL.
    if (skeleton.color) skeleton.color.set(1, 1, 1, 1);
    for (const slot of skeleton.slots || []) {
      if (slot.color) slot.color.set(1, 1, 1, 1);
      if (slot.darkColor && slot.darkColor.set) slot.darkColor.set(1, 1, 1, 1);
      const attachment = slot.getAttachment && slot.getAttachment();
      if (attachment && attachment.color && attachment.color.set) {
        attachment.color.set(1, 1, 1, 1);
      }
    }
  }
  try { skeleton.updateWorldTransform(spine.Physics.update); }
  catch (_) { skeleton.updateWorldTransform(); }
  const offset = new spine.Vector2(), size = new spine.Vector2();
  skeleton.getBounds(offset, size, []);
  if (!(size.x > 0 && size.y > 0)) throw new Error('Spine skeleton has empty bounds');
  const scale = Math.max(size.x / canvas.width, size.y / canvas.height) * 1.05 || 1;
  const width = canvas.width * scale, height = canvas.height * scale;
  mvp.ortho2d(offset.x + size.x / 2 - width / 2,
    offset.y + size.y / 2 - height / 2, width, height);
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  shader.bind();
  shader.setUniformi(Shader.SAMPLER, 0);
  shader.setUniform4x4f(Shader.MVP_MATRIX, mvp.values);
  batcher.begin(shader);
  renderer.premultipliedAlpha = r.pma;
  renderer.draw(batcher, skeleton);
  batcher.end();
  shader.unbind();
  gl.finish();
  return {missing: false, png: canvas.toDataURL('image/png')};
}"""


class SpineWebRenderer:
    """Reuse one local Chromium instance across many official skeletons."""

    def __init__(
        self,
        *,
        runtime_path: str | Path | None = None,
        spine_version: str = "4.2",
        canvas_size: int = 2048,
        headless: bool = True,
    ) -> None:
        self.version_family = _version_family(spine_version)
        self.runtime_path = Path(
            runtime_path or runtime_for_spine_version(spine_version)
        ).resolve()
        self.canvas_size = max(512, int(canvas_size))
        self.headless = bool(headless)
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "SpineWebRenderer":
        if not self.runtime_path.is_file():
            raise FileNotFoundError(
                f"Spine 4.2 web runtime not found: {self.runtime_path}\n"
                "请先双击“安装Spine网页渲染运行时.cmd”，阅读并接受官方许可证。"
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 Playwright；请先运行 python -m pip install playwright，"
                "再运行 playwright install chromium"
            ) from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--enable-webgl", "--ignore-gpu-blocklist", "--use-angle=swiftshader"],
        )
        self._page = self._browser.new_page(
            viewport={"width": self.canvas_size, "height": self.canvas_size}
        )
        self._page.set_content(_PAGE_HTML)
        self._page.add_script_tag(path=str(self.runtime_path))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = self._browser = self._playwright = None

    def render(
        self,
        source_dir: str | Path,
        *,
        face_ids: Iterable[str],
        cache_root: str | Path,
        force: bool = False,
        progress=None,
    ) -> WebRenderReport:
        if self._page is None:
            raise RuntimeError("SpineWebRenderer must be used as a context manager")
        requested = tuple(sorted(dict.fromkeys(str(item) for item in face_ids)))
        if not requested:
            raise ValueError("No face IDs were requested")
        skeleton, atlas, texture_pages = _bundle_files(source_dir)
        version = detect_spine_version(skeleton)
        family = _version_family(version)
        if family != self.version_family:
            raise ValueError(
                f"Web renderer loaded Spine {self.version_family} runtime for {version} data"
            )
        render_profile = _WEB_RENDER_PROFILES[family]
        signature = web_bundle_signature(source_dir)
        cache_dir = Path(cache_root).resolve() / signature
        if not force:
            cached = _load_cached_report(
                cache_dir, signature=signature, face_ids=requested,
                render_profile=render_profile,
            )
            if cached is not None:
                return cached

        portraits = cache_dir / "portraits"
        heads = cache_dir / "heads"
        portraits.mkdir(parents=True, exist_ok=True)
        heads.mkdir(parents=True, exist_ok=True)
        payload = {
            "canvasSize": self.canvas_size,
            "spineVersion": version,
            "pma": _atlas_uses_pma(atlas, family),
            "neutralTint": _texture_requires_neutral_tint(texture_pages),
            "skeleton": _data_uri(skeleton, mime="application/octet-stream"),
            "atlas": _data_uri(atlas, mime="text/plain;charset=utf-8"),
            "textures": [
                {"name": name, "uri": _data_uri(path)}
                for name, path in texture_pages
            ],
        }
        loaded = self._page.evaluate(_LOAD_SCRIPT, payload)
        animation_names = tuple(str(x) for x in loaded.get("animationNames") or [])
        rendered: list[RenderedFace] = []
        missing: list[str] = []
        total = len(requested)
        for index, face_id in enumerate(requested, start=1):
            if progress:
                progress(face_id, index - 1, total)
            result = self._page.evaluate(_RENDER_SCRIPT, face_id)
            if result.get("missing"):
                missing.append(face_id)
                continue
            encoded = str(result.get("png") or "").partition(",")[2]
            if not encoded:
                raise RuntimeError(f"Browser returned no PNG for face {face_id}")
            portrait = portraits / f"{face_id}.png"
            portrait.write_bytes(base64.standard_b64decode(encoded))
            if not _is_visible_web_render(portrait):
                raise RuntimeError(
                    f"Spine face {face_id} rendered without visible texture; "
                    f"diagnostic PNG kept at {portrait}; animations="
                    f"{','.join(animation_names[:20])}"
                )
            rendered.append(
                RenderedFace(face_id, portrait, heads / f"{face_id}.png")
            )
            if progress:
                progress(face_id, index, total)

        cropped = tuple(crop_face_previews(rendered, size=768))
        # Force Pillow to verify every saved head before publishing the cache.
        for face in cropped:
            with Image.open(face.head_path) as image:
                image.verify()
        manifest = {
            "signature": signature,
            "render_profile": render_profile,
            "spine_version": version,
            "face_ids": list(requested),
            "rendered_face_ids": [face.face_id for face in cropped],
            "missing_face_ids": missing,
            "animation_names": list(animation_names),
        }
        (cache_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return WebRenderReport(
            signature=signature,
            cache_dir=cache_dir,
            faces=cropped,
            cached=False,
            animation_names=animation_names,
            missing_face_ids=tuple(missing),
        )

    def animation_names(self, source_dir: str | Path) -> tuple[str, ...]:
        """Load one matching 3.8/4.2 bundle and return its animation names."""
        if self._page is None:
            raise RuntimeError("SpineWebRenderer must be used as a context manager")
        skeleton, atlas, texture_pages = _bundle_files(source_dir)
        version = detect_spine_version(skeleton)
        family = _version_family(version)
        if family != self.version_family:
            raise ValueError(
                f"Web renderer loaded Spine {self.version_family} runtime for {version} data"
            )
        loaded = self._page.evaluate(_LOAD_SCRIPT, {
            "canvasSize": self.canvas_size,
            "spineVersion": version,
            "pma": _atlas_uses_pma(atlas, family),
            "skeleton": _data_uri(skeleton, mime="application/octet-stream"),
            "atlas": _data_uri(atlas, mime="text/plain;charset=utf-8"),
            "textures": [
                {"name": name, "uri": _data_uri(path)}
                for name, path in texture_pages
            ],
        })
        return tuple(str(item) for item in loaded.get("animationNames") or [])

