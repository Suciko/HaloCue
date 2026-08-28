"""Disposable HaloCue server for Codex in-app Browser acceptance.

The process owns an isolated temporary data directory and prints its URL as one
JSON line before serving. Browser interactions are intentionally kept outside
this fixture so acceptance uses the Codex in-app Browser rather than a second
automation runtime.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="halocue-iab-acceptance-") as data_dir:
        service = WritingService(Path(data_dir))
        service.start()
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), make_handler(service, PROJECT_ROOT / "web")
        )

        def stop_server(*_args: object) -> None:
            server.shutdown()

        signal.signal(signal.SIGINT, stop_server)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop_server)

        provider = service.provider.descriptor()
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}/",
                    "data_dir": data_dir,
                    "provider": provider["provider"],
                    "model": provider["model"],
                    "can_call_model": provider["can_call_model"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
            service.close()


if __name__ == "__main__":
    main()
