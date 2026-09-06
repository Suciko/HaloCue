from __future__ import annotations

import http.client
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from .manifest import build_integration_manifest


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _path_is(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def route_request(path: str, referer: str | None = None) -> tuple[str, str]:
    parsed = urlsplit(path)
    request_path = parsed.path
    suffix = f"?{parsed.query}" if parsed.query else ""
    if _path_is(request_path, "/production/api/v1"):
        return "production", request_path.removeprefix("/production") + suffix
    if request_path.startswith("/production/"):
        downstream = "/" + request_path.removeprefix("/production/")
        return "production", downstream + suffix
    if any(_path_is(request_path, prefix) for prefix in ("/api/v1/works", "/api/v1/releases", "/api/v1/official-references")):
        return "writing", request_path + suffix
    if any(_path_is(request_path, prefix) for prefix in ("/api/v1/resources/catalog", "/api/v1/resources/search", "/api/v1/imports")):
        return "writing", request_path + suffix
    if any(_path_is(request_path, prefix) for prefix in ("/api/v1/production-runs", "/api/v1/script-preflight", "/api/v1/jobs", "/api/v1/resources")):
        return "production", request_path + suffix
    if request_path.startswith("/api/v1"):
        referer_path = urlsplit(referer or "").path
        target = "production" if referer_path.startswith("/production/") else "writing"
        return target, request_path + suffix
    return "writing", request_path + suffix


class GatewayHandler(BaseHTTPRequestHandler):
    writing_address: tuple[str, int]
    production_address: tuple[str, int]
    static_dir: Path
    integration_manifest: dict
    server_version = "HaloCueIntegrated/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_local_asset(self, filename: str) -> None:
        path = (self.static_dir / filename).resolve()
        if self.static_dir not in path.parents or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _embed_production_script(body: bytes) -> bytes:
        text = body.decode("utf-8")
        api_marker = (
            'const API_ROOT = location.port === "8891"\n'
            '    ? "http://127.0.0.1:8892/api/v1"\n'
            '    : "/api/v1";'
        )
        selector_marker = (
            'const $ = (selector) => document.querySelector(selector);\n'
            '  const $$ = (selector) => [...document.querySelectorAll(selector)];'
        )
        selector_replacement = (
            'const productionHost = globalThis["document"].querySelector("#productionModule");\n'
            '  const productionRoot = productionHost?.shadowRoot;\n'
            '  if (!productionRoot) throw new Error("AA 制作工作面尚未挂载");\n'
            '  const $ = (selector) => productionRoot.querySelector(selector);\n'
            '  const $$ = (selector) => [...productionRoot.querySelectorAll(selector)];'
        )
        text = text.replace(api_marker, 'const API_ROOT = "/production/api/v1";', 1)
        text = text.replace(selector_marker, selector_replacement, 1)
        text = text.replace("document.querySelectorAll(", "productionRoot.querySelectorAll(")
        text = text.replace("document.querySelector(", "productionRoot.querySelector(")
        text = text.replace("document.addEventListener(", "productionRoot.addEventListener(")
        text = text.replace("document.body.classList.toggle(", "productionHost.classList.toggle(")
        text = text.replace(
            'state.currentRun.source_summary?.dialogue_count || 0',
            '(state.currentRun.source_summary?.speaker_details || []).find((item) => item.speaker === speaker)?.count || 0',
            1,
        )
        return text.encode("utf-8")

    @staticmethod
    def _inject_shell(target: str, downstream_path: str, content_type: str, body: bytes) -> bytes:
        clean_path = downstream_path.split("?", 1)[0]
        if target == "writing" and clean_path == "/production-embed.js" and "javascript" in content_type:
            body = body.replace(
                b'fetch("/production/", { headers: { Accept: "text/html" } })',
                b'fetch("/integration/production-fragment", { headers: { Accept: "text/html", "X-HaloCue-Embed": "production" } })',
                1,
            )
        if target == "production" and clean_path == "/app.js" and "javascript" in content_type:
            # Git on Windows may serve CRLF source to both script variants.
            body = body.replace(b"\r\n", b"\n")
            marker = (
                b'const API_ROOT = location.port === "8891"\n'
                b'    ? "http://127.0.0.1:8892/api/v1"\n'
                b'    : "/api/v1";'
            )
            body = body.replace(marker, b'const API_ROOT = "/production/api/v1";', 1)
        if clean_path not in {"/", "/index.html"} or "text/html" not in content_type:
            return body
        marker = b"</head>"
        if target == "production":
            body = body.replace(b"<body>", b'<body class="halocue-integrated-production">', 1)
            body = body.replace(
                marker,
                b'<link rel="stylesheet" href="integration-shell.css">' + marker,
                1,
            )
            return body.replace(
                b"</body>",
                b'<script src="integration-shell.js"></script></body>',
                1,
            )
        else:
            addition = (
                b'<link rel="stylesheet" href="/integration-shell.css">'
                b'<script src="/integration-shell.js" defer></script>'
            )
        return body.replace(marker, addition + marker, 1)

    def _proxy(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/integration/manifest":
            if self.command != "GET":
                self._send_json(405, {"ok": False, "error": {"code": "method_not_allowed"}})
                return
            self._send_json(200, {"ok": True, "data": self.integration_manifest})
            return
        if parsed.path in {"/production", "/production/", "/production/index.html"}:
            query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "section"]
            location = "/?" + urlencode([("section", "production"), *query])
            self.send_response(308)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parsed.path in {"/integration-shell.js", "/production/integration-shell.js"}:
            self._send_local_asset("integration-shell.js")
            return
        if parsed.path in {"/integration-shell.css", "/production/integration-shell.css"}:
            self._send_local_asset("integration-shell.css")
            return

        internal_production_fragment = parsed.path == "/integration/production-fragment"
        if internal_production_fragment and self.headers.get("X-HaloCue-Embed") != "production":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        embedded_production_script = parsed.path == "/production/app-embedded.js"
        if internal_production_fragment:
            routed_path = "/production/"
        else:
            routed_path = "/production/app.js" if embedded_production_script else self.path
        target, downstream_path = route_request(routed_path, self.headers.get("Referer"))
        address = self.production_address if target == "production" else self.writing_address
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.casefold() not in HOP_BY_HOP_HEADERS | {"host", "content-length"}
        }
        connection = http.client.HTTPConnection(*address, timeout=30)
        try:
            connection.request(self.command, downstream_path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            content_type = response.getheader("Content-Type", "application/octet-stream")
            if not internal_production_fragment:
                response_body = self._inject_shell(target, downstream_path, content_type, response_body)
            if embedded_production_script and response.status == 200:
                response_body = self._embed_production_script(response_body)
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.casefold() in HOP_BY_HOP_HEADERS | {"content-length", "content-security-policy", "x-frame-options"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(response_body)
        except (ConnectionError, TimeoutError, OSError) as exc:
            payload = (f'{{"ok":false,"error":{{"code":"upstream_unavailable","message":"{target} service unavailable","details":{{"type":"{type(exc).__name__}"}}}}}}').encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            connection.close()

    do_GET = _proxy
    do_POST = _proxy
    do_PATCH = _proxy
    do_PUT = _proxy
    do_DELETE = _proxy


def create_gateway(
    host: str,
    port: int,
    *,
    writing_address: tuple[str, int],
    production_address: tuple[str, int],
    static_dir: Path,
    integration_manifest: dict | None = None,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundGatewayHandler",
        (GatewayHandler,),
        {
            "writing_address": writing_address,
            "production_address": production_address,
            "static_dir": static_dir.resolve(),
            "integration_manifest": integration_manifest or build_integration_manifest(),
        },
    )
    return ThreadingHTTPServer((host, port), handler)
