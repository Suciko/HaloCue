"""Disposable Browser fixture for one attachment-backed Agent turn."""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from halocue_writing.app import make_handler
from halocue_writing.service import WritingService


def copy_model_settings(source: Path, target: Path) -> None:
    public_config = source / "writing-model.json"
    encrypted_secret = source / "secrets" / "writing-model.dpapi"
    if not public_config.is_file() or not encrypted_secret.is_file():
        raise SystemExit("model settings source is incomplete")
    target.mkdir(parents=True, exist_ok=True)
    (target / "secrets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(public_config, target / public_config.name)
    shutil.copy2(encrypted_secret, target / "secrets" / encrypted_secret.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--model-settings-dir", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="halocue-iab-attachment-") as data_dir_value:
        data_dir = Path(data_dir_value)
        if args.model_settings_dir:
            copy_model_settings(args.model_settings_dir.resolve(), data_dir)
        service = WritingService(data_dir)
        work = service.create_work(
            {
                "title": "附件上下文验收",
                "idea": "只验证用户文档如何进入本轮上下文，不修改正式资料。",
            }
        )
        service.start()
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port),
            make_handler(service, PROJECT_ROOT / "web"),
        )

        def stop_server(*_args: object) -> None:
            server.shutdown()

        signal.signal(signal.SIGINT, stop_server)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, stop_server)
        provider = service.health()["provider"]
        print(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{server.server_port}/?section=works&work_id={work['id']}",
                    "provider": provider.get("display_name"),
                    "is_simulation": provider.get("is_simulation"),
                    "config_revision": provider.get("config_revision"),
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
