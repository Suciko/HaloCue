from __future__ import annotations

from pathlib import Path
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import pytest
from PIL import Image

from aa_stage_media import (
    StageMediaError,
    detect_spine_version,
    resolve_spine_bundle,
    safe_stage_key,
    spine_family,
)


def _bundle(root: Path, version: bytes = b"spine 4.2.33") -> Path:
    bundle = root / "characters" / "hero"
    bundle.mkdir(parents=True)
    (bundle / "hero.skel").write_bytes(version)
    (bundle / "hero.atlas").write_text(
        "hero.png\nsize:2,2\nfilter:Linear,Linear\nhero-region\nbounds:0,0,2,2\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(bundle / "hero.png")
    return bundle


def test_safe_stage_key_rejects_path_traversal():
    assert safe_stage_key("NP0234_spr") == "NP0234_spr"
    for value in ("", "..", "hero/other", r"hero\other", "hero space"):
        with pytest.raises(StageMediaError):
            safe_stage_key(value)


def test_spine_version_family_supports_both_runtime_generations(tmp_path):
    root38 = _bundle(tmp_path / "v38", b"binary Spine 3.8.96 data")
    root42 = _bundle(tmp_path / "v42", b"binary Spine 4.2.33 data")
    assert detect_spine_version(root38 / "hero.skel") == "3.8.96"
    assert detect_spine_version(root42 / "hero.skel") == "4.2.33"
    assert spine_family("3.8.96") == "3.8"
    assert spine_family("4.2.33") == "4.2"


def test_resolve_spine_bundle_validates_atlas_and_returns_logical_metadata(tmp_path):
    root = _bundle(tmp_path)
    result = resolve_spine_bundle(tmp_path, "hero")
    assert result["root"] == root.resolve()
    assert result["spine_family"] == "4.2"
    assert result["textures"] == (root.resolve() / "hero.png",)


def test_resolve_spine_bundle_rejects_unsupported_version(tmp_path):
    _bundle(tmp_path, b"binary Spine 4.0.00 data")
    with pytest.raises(StageMediaError, match="unsupported Spine"):
        resolve_spine_bundle(tmp_path, "hero")


def test_stage_spine_endpoint_streams_only_the_cached_frame(tmp_path, monkeypatch):
    import webui

    frame = tmp_path / "stage.png"
    frame.write_bytes(b"PNG-FRAME")
    monkeypatch.setattr(webui, "stage_frame_path", lambda *args, **kwargs: frame)
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/resources/stage/spine/frame?key=hero"
        ) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/png"
            assert response.read() == b"PNG-FRAME"
    finally:
        server.shutdown()
        server.server_close()


def test_stage_frame_cache_is_partitioned_by_animation(tmp_path, monkeypatch):
    import aa_stage_media

    source = tmp_path / "source.png"
    source.write_bytes(b"PNG-SOURCE")
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()

    class FakeReport:
        faces = (type("Face", (), {"portrait_path": source})(),)
        animation_names = ("00", "03")
        cache_dir = tmp_path / "renderer-cache"

    class FakeRenderer:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def render(self, _root, *, face_ids, cache_root):
            FakeReport.cache_dir = Path(cache_root) / "bundle-signature"
            FakeReport.cache_dir.mkdir(parents=True, exist_ok=True)
            FakeReport.faces = (type("Face", (), {"portrait_path": source})(),)
            FakeRenderer.requested = face_ids[0]
            return FakeReport()

    monkeypatch.setattr(
        aa_stage_media,
        "resolve_spine_bundle",
        lambda *_args, **_kwargs: {"root": bundle_root, "spine_version": "3.8.96"},
    )
    monkeypatch.setattr(aa_stage_media, "extract_catalog_spine_bundle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(aa_stage_media, "web_bundle_signature", lambda _root: "bundle-signature")
    monkeypatch.setattr(
        __import__("spine_face_web_renderer"), "SpineWebRenderer", FakeRenderer,
    )

    # The fake source is not a real image, so patch the crop operation at the
    # module boundary and only assert the animation-specific output paths.
    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def convert(self, _mode):
            return self

        def getchannel(self, _channel):
            return self

        def getbbox(self):
            return (0, 0, 1, 1)

        def crop(self, _bounds):
            return self

        def save(self, path, _format, **_kwargs):
            Path(path).write_bytes(b"PNG-FRAME")

    monkeypatch.setattr("PIL.Image.open", lambda _path: FakeImage())
    first = aa_stage_media.stage_frame_path(None, "CharacterSpine_aris", animation="00", cache_root=tmp_path)
    second = aa_stage_media.stage_frame_path(None, "CharacterSpine_aris", animation="03", cache_root=tmp_path)
    assert first != second
    assert first.name == "00.png"
    assert second.name == "03.png"


def test_stage_frame_returns_tight_cache_before_starting_webgl(tmp_path, monkeypatch):
    import aa_stage_media

    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    tight = tmp_path / "spine-stage" / "sig" / "stage-frames" / "03.png"
    tight.parent.mkdir(parents=True)
    tight.write_bytes(b"cached")

    monkeypatch.setattr(
        aa_stage_media,
        "resolve_spine_bundle",
        lambda *_args, **_kwargs: {"root": bundle_root, "spine_version": "3.8.96"},
    )
    monkeypatch.setattr(aa_stage_media, "web_bundle_signature", lambda _root: "sig")
    monkeypatch.setattr(
        __import__("spine_face_web_renderer"),
        "SpineWebRenderer",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("renderer must not start")),
    )

    assert aa_stage_media.stage_frame_path(None, "hero", animation="03", cache_root=tmp_path) == tight
