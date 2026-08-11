"""Run the Android WebView page on localhost for desktop narrow-screen preview."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import android_exports
import android_web_server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=str(Path.cwd() / ".preview-workspace"),
        help="workspace used by the local preview server",
    )
    parser.add_argument("--session", default="desktop-preview")
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    android_exports.set_backend_for_tests(android_exports.PreviewExportBackend(workspace))
    try:
        result = android_web_server.start(str(workspace), args.session)
        print(result["url"], flush=True)
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        android_web_server.stop()
        android_exports.set_backend_for_tests(None)


if __name__ == "__main__":
    main()
