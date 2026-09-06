from __future__ import annotations

import argparse
import os
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

from .gateway import create_gateway
from .manifest import build_integration_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
WRITING_ROOT = WORKSPACE_ROOT / "writing"
PRODUCTION_ROOT = WORKSPACE_ROOT / "production"
REPOSITORY_ROOT = PROJECT_ROOT.parents[2]
for source_root in (WRITING_ROOT / "src", PRODUCTION_ROOT / "src"):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from halocue_production.app import create_server as create_production_server  # noqa: E402
from halocue_production.config import Settings  # noqa: E402
from halocue_writing.app import make_handler  # noqa: E402
from halocue_writing.service import WritingService  # noqa: E402

from .production_assets import IntegratedProductionService  # noqa: E402


class IntegratedRuntime:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        writing_data_dir: Path,
        production_data_dir: Path,
        resource_index: Path | None = None,
    ) -> None:
        settings = Settings.from_env(host="127.0.0.1", port=0, data_dir=production_data_dir)
        if resource_index is not None:
            settings = replace(settings, resource_index=resource_index.resolve())
        self.production_service = IntegratedProductionService(settings)
        self.production_server = create_production_server(self.production_service, "127.0.0.1", 0)
        production_address = ("127.0.0.1", self.production_server.server_port)

        self.writing_service = WritingService(writing_data_dir, f"http://127.0.0.1:{self.production_server.server_port}")
        writing_handler = make_handler(self.writing_service, WRITING_ROOT / "web")
        self.writing_server = ThreadingHTTPServer(("127.0.0.1", 0), writing_handler)
        writing_address = ("127.0.0.1", self.writing_server.server_port)

        self.gateway = create_gateway(
            host,
            port,
            writing_address=writing_address,
            production_address=production_address,
            static_dir=PROJECT_ROOT / "static",
            integration_manifest=build_integration_manifest(
                started_at=datetime.now(timezone.utc).isoformat()
            ),
        )
        self._threads = [
            threading.Thread(target=self.production_server.serve_forever, name="halocue-production", daemon=True),
            threading.Thread(target=self.writing_server.serve_forever, name="halocue-writing", daemon=True),
        ]

    @property
    def port(self) -> int:
        return self.gateway.server_port

    def start_upstreams(self) -> None:
        for thread in self._threads:
            thread.start()

    def close(self, *, stop_gateway: bool = True) -> None:
        if stop_gateway:
            self.gateway.shutdown()
        self.gateway.server_close()
        self.writing_server.shutdown()
        self.writing_server.server_close()
        self.production_server.shutdown()
        self.production_server.server_close()
        self.production_service.jobs.close()
        for thread in self._threads:
            thread.join(timeout=3)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="HaloCue 1.0 integrated writing and AA production runtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument("--writing-data-dir")
    parser.add_argument("--production-data-dir")
    args = parser.parse_args(argv)
    default_data_root = REPOSITORY_ROOT / ".halocue" / "integrated"
    writing_data = Path(
        args.writing_data_dir
        or os.getenv("HALOCUE_WRITING_DATA_DIR")
        or default_data_root / "writing"
    ).resolve()
    production_data = Path(
        args.production_data_dir
        or os.getenv("HALOCUE_DATA_DIR")
        or default_data_root / "production"
    ).resolve()
    runtime = IntegratedRuntime(
        host=args.host,
        port=args.port,
        writing_data_dir=writing_data,
        production_data_dir=production_data,
    )
    runtime.start_upstreams()
    print(f"HaloCue 1.0: http://{args.host}:{runtime.port}/", flush=True)
    print(f"AA production: http://{args.host}:{runtime.port}/production/", flush=True)
    try:
        runtime.gateway.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close(stop_gateway=False)


if __name__ == "__main__":
    main()
