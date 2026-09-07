from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

from halocue_production.app import create_server
from halocue_production.service import ProductionService


@contextmanager
def api(settings):
    service = ProductionService(settings)
    server = create_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        service.jobs.close()
        thread.join(timeout=2)


def request(base: str, path: str, payload=None, method="GET"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), json.loads(error.read())
