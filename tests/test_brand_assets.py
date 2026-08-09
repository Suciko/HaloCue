from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.request import urlopen

from PIL import Image

import brand_provenance
import webui


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"


def corner_points(image):
    width, height = image.size
    return ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))


def test_brand_master_is_transparent_and_square():
    image = Image.open(BRANDING / "halocue-icon.png")

    assert image.mode == "RGBA"
    assert image.size == (1024, 1024)
    assert all(image.getpixel(point)[3] == 0 for point in corner_points(image))
    assert image.getchannel("A").getbbox() is not None


def test_windows_icon_contains_required_sizes():
    image = Image.open(BRANDING / "halocue.ico")

    assert {
        (16, 16), (24, 24), (32, 32), (48, 48),
        (64, 64), (128, 128), (256, 256),
    } <= set(image.info["sizes"])


def test_favicon_is_transparent_rgba_at_64_pixels():
    image = Image.open(BRANDING / "halocue-favicon.png")

    assert image.mode == "RGBA"
    assert image.size == (64, 64)
    assert all(image.getpixel(point)[3] == 0 for point in corner_points(image))


def test_public_branding_assets_have_no_local_path_metadata():
    for asset in (
        BRANDING / "halocue-icon.png",
        BRANDING / "halocue-favicon.png",
        BRANDING / "halocue.ico",
    ):
        image = Image.open(asset)
        metadata = repr(image.info).casefold()
        assert ":\\" not in metadata
        assert "/users/" not in metadata
        assert "/home/" not in metadata


def test_content_identity_check_detects_a_renamed_reference(tmp_path, monkeypatch):
    reference_bytes = b"external halo reference fixture"
    reference_copy = tmp_path / "unrelated-filename.png"
    reference_copy.write_bytes(reference_bytes)
    monkeypatch.setattr(
        brand_provenance,
        "EXTERNAL_REFERENCE_SHA256",
        frozenset({brand_provenance.sha256_bytes(reference_bytes)}),
    )

    assert brand_provenance.external_reference_matches(tmp_path) == [
        reference_copy
    ]


def test_external_reference_manifest_contains_sha256_values_only():
    manifest = ROOT / "branding" / "excluded-reference-sha256.txt"
    values = manifest.read_text(encoding="ascii").splitlines()

    assert values
    assert all(brand_provenance.is_sha256(value) for value in values)
    assert len(values) == len(set(values))


def test_repository_contains_no_external_reference_asset_by_content_identity():
    assert brand_provenance.external_reference_matches(ROOT) == []


def test_favicon_is_served_as_the_allowlisted_brand_asset():
    expected = (BRANDING / "halocue-favicon.png").read_bytes()
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/branding/halocue-favicon.png"
        ) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "image/png"
            assert response.read() == expected
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
