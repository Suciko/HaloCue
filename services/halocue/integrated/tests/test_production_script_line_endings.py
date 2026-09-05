import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from halocue_integrated.gateway import create_gateway


SCRIPT = """(() => {
  const API_ROOT = location.port === "8891"
    ? "http://127.0.0.1:8892/api/v1"
    : "/api/v1";
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  document.addEventListener("click", () => {});
})();
"""


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("asset", ["app.js", "app-embedded.js"])
def test_production_script_http_rewrite_is_independent_of_checkout_line_endings(
    tmp_path,
    newline,
    asset,
):
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            body = SCRIPT.replace("\n", newline).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    address = ("127.0.0.1", upstream.server_port)
    gateway = create_gateway(
        "127.0.0.1",
        0,
        writing_address=address,
        production_address=address,
        static_dir=tmp_path,
    )
    servers = (upstream, gateway)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{gateway.server_port}/production/{asset}",
            timeout=5,
        ) as response:
            text = response.read().decode("utf-8")
        assert 'const API_ROOT = "/production/api/v1";' in text
        if asset == "app-embedded.js":
            assert "const productionRoot = productionHost?.shadowRoot;" in text
            assert 'productionRoot.addEventListener("click"' in text
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
