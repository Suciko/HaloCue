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
