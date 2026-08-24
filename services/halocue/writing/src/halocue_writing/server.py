from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer
from pathlib import Path

from .app import make_handler
from .service import WritingService


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--data-dir")
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    repository_root = project_root.parents[2]
    default_data_dir = repository_root / ".halocue" / "writing"
    data_dir = Path(
        args.data_dir
        or os.environ.get("HALOCUE_WRITING_DATA_DIR")
        or default_data_dir
    )
    production_url = os.environ.get("HALOCUE_PRODUCTION_URL", "http://127.0.0.1:8892")
    service = WritingService(data_dir, production_url)
    service.start()
    handler = make_handler(service, project_root / "web")
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"HaloCue Writing: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
