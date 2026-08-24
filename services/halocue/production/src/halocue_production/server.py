from __future__ import annotations

import argparse

from .app import create_server
from .config import Settings
from .service import ProductionService


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="HaloCue 1.0 production backend")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    settings = Settings.from_env(host=args.host, port=args.port, data_dir=args.data_dir)
    service = ProductionService(settings)
    server = create_server(service, settings.host, settings.port)
    print(f"HaloCue production API: http://{settings.host}:{server.server_port}/api/v1/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.jobs.close()


if __name__ == "__main__":
    main()

