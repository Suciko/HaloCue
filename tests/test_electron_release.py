from pathlib import Path
import io

import pytest

from release_tools.manifest import is_public_source_path
from release_tools.scanner import scan_tree


def test_public_export_includes_host_but_excludes_build_dependencies():
    assert is_public_source_path("apps/desktop-client/electron/main.cjs")
    assert is_public_source_path("apps/desktop-client/electron/boot.js")
    assert is_public_source_path("apps/desktop-client/electron/package-lock.json")
    assert not is_public_source_path("apps/desktop-client/electron/node_modules/electron/index.js")
    assert not is_public_source_path("apps/another-client/private.json")


@pytest.mark.parametrize("name", ["HaloCueBackend.exe", "chrome_elf.dll", "dxcompiler.dll"])
def test_scanner_accepts_only_exact_electron_runtime_locations(tmp_path, name):
    (tmp_path / name).write_bytes(b"MZ synthetic runtime fixture")
    assert scan_tree(tmp_path, mode="public") == ()
    nested = tmp_path / "unreviewed"
    nested.mkdir()
    (nested / name).write_bytes(b"MZ synthetic runtime fixture")
    assert any(f.code == "unexpected-executable" for f in scan_tree(tmp_path, mode="public"))


def test_generated_boot_icon_matches_brand_master():
    root = Path(__file__).resolve().parents[1]
    assert (root / "branding/halocue-icon.svg").read_bytes() == (
        root / "apps/desktop-client/electron/icon.svg"
    ).read_bytes()


def test_writing_favicon_uses_canonical_branding_when_export_has_no_bitmap_copy(tmp_path):
    from services.halocue.runtime_layout import enable_service_imports

    enable_service_imports()
    from halocue_writing.app import WritingRequestHandler

    handler = object.__new__(WritingRequestHandler)
    handler.static_dir = tmp_path
    handler.wfile = io.BytesIO()
    headers = []
    handler._headers = lambda *args: headers.append(args)
    handler._static("/halocue-favicon.png")
    root = Path(__file__).resolve().parents[1]
    assert handler.wfile.getvalue() == (root / "branding/halocue-favicon.png").read_bytes()
    assert headers[0][0:2] == (200, "image/png")


def test_scanner_checks_cjs_contents_for_private_paths(tmp_path):
    (tmp_path / "main.cjs").write_text(
        "const path = '" + "/".join(["C:", "Users", "SomePrivateUser", "Documents"]) + "';",
        encoding="utf-8",
    )
    assert any(f.code == "personal-path" for f in scan_tree(tmp_path, mode="source"))
