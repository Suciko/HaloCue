"""Load isolated data defaults even when integrated pyproject is the pytest root."""

import sys
import json
import threading
import random
import socket
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.halocue._test_support import (  # noqa: E402,F401
    isolated_legacy_root,
    isolated_production_defaults,
)

for context in ("writing", "production", "integrated"):
    sys.path.insert(0, str(REPOSITORY_ROOT / "services" / "halocue" / context / "src"))

from halocue_integrated.server import IntegratedRuntime  # noqa: E402


@pytest.fixture
def runtime(tmp_path):
    # Windows can allocate port 0 below 10000, including Chromium-blocked ports.
    # Pick an available high port for the browser-facing gateway only.
    gateway_port = None
    for _ in range(100):
        candidate = random.SystemRandom().randrange(20000, 60000)
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            gateway_port = candidate
            break
    assert gateway_port is not None, "No available browser-safe test port"
    resource_index = tmp_path / "resources.json"
    resource_index.write_text(
        json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8"
    )
    instance = IntegratedRuntime(
        host="127.0.0.1",
        port=gateway_port,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=resource_index,
        legacy_root=tmp_path,
    )
    instance.start_upstreams()
    gateway = threading.Thread(target=instance.gateway.serve_forever, daemon=True)
    gateway.start()
    try:
        yield instance
    finally:
        instance.close()
        gateway.join(timeout=3)
