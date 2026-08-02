# -*- coding: utf-8 -*-
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
import webui
from webui import H, build_csp_headers


HERE = Path(__file__).resolve().parent.parent


def test_csp_and_security_headers():
    headers = build_csp_headers()
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]

    # 包含严格 CSP 约束，无 'unsafe-inline'
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "'unsafe-inline'" not in csp

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("Referrer-Policy") == "no-referrer"


def test_static_runtime_files_have_safe_mime_headers_and_reject_traversal():
    """The browser must be able to load modules without exposing adjacent files."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/js/app.js") as response:
            assert response.headers["Content-Type"].startswith("application/javascript")
            assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        with urlopen(base + "/css/layout.css") as response:
            assert response.headers["Content-Type"].startswith("text/css")
        with pytest.raises(HTTPError) as blocked:
            urlopen(base + "/js/../ui.html")
        assert blocked.value.code == 404
        for unsafe_path in ("/css/%2e%2e/ui.html", "/js/%2e%2e/webui.py", "/css/app.js"):
            with pytest.raises(HTTPError) as unsafe:
                urlopen(base + unsafe_path)
            assert unsafe.value.code == 404
        for wrong_extension in ("/js/app.txt", "/css/layout.js"):
            with pytest.raises(HTTPError) as unsafe:
                urlopen(base + wrong_extension)
            assert unsafe.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_static_routes_do_not_serve_real_wrong_extension_files(tmp_path, monkeypatch):
    """Allowlisting must hold even if an adjacent unexpected file exists."""
    (tmp_path / "js").mkdir(); (tmp_path / "css").mkdir()
    (tmp_path / "js" / "secret.txt").write_text("do not leak", encoding="utf-8")
    (tmp_path / "css" / "secret.js").write_text("do not leak", encoding="utf-8")
    monkeypatch.setattr(webui, "HERE", str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        for path in ("/js/secret.txt", "/css/secret.js"):
            with pytest.raises(HTTPError) as blocked:
                urlopen(base + path)
            assert blocked.value.code == 404
            assert b"do not leak" not in blocked.value.read()
    finally:
        server.shutdown(); server.server_close()


def test_asset_workbench_scripts_are_external_and_avoid_inline_execution():
    html = (HERE / "ui.html").read_text(encoding="utf-8")
    scripts = (
        "library_preview.js",
        "library_transfer.js",
        "library_copies.js",
        "library.js",
    )
    for script in scripts:
        assert f'<script src="/js/{script}"></script>' in html
        source = (HERE / "js" / script).read_text(encoding="utf-8")
        assert "innerHTML" not in source
        assert "eval(" not in source
    assert "onclick=" not in html
    assert "onchange=" not in html
