"""Own the integrated runtime for the desktop and headless release entry."""

import json
import os
from pathlib import Path
import threading
import signal
import secrets

from halocue_meta import APP_ID, DISPLAY_NAME, VERSION
from services.halocue.runtime_layout import enable_service_imports, integrated_data_root


def run_integrated(
    *, aa_data=None, port=8770, no_browser=False, ready_file=None, webview_module=None
):
    enable_service_imports()
    from halocue_integrated.server import IntegratedRuntime
    from runtime_layout import LAYOUT, prepare_user_state

    prepare_user_state(LAYOUT)

    data = integrated_data_root()
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=port,
        writing_data_dir=Path(os.getenv("HALOCUE_WRITING_DATA_DIR") or data / "writing"),
        production_data_dir=Path(os.getenv("HALOCUE_DATA_DIR") or data / "production"),
        aa_data=Path(aa_data) if aa_data else None,
        legacy_root=LAYOUT.user_data_root,
        resource_index=LAYOUT.resource_index_path if LAYOUT.resource_index_path.is_file() else None,
    )
    runtime.start_upstreams()
    shutdown_token = secrets.token_urlsafe(32) if no_browser and ready_file else None
    runtime.gateway.shutdown_token = shutdown_token
    gateway = threading.Thread(target=runtime.gateway.serve_forever, daemon=True)
    gateway.start()
    url = f"http://127.0.0.1:{runtime.port}"
    interrupted = threading.Event()
    previous_handler = None
    if no_browser and hasattr(signal, "SIGBREAK"):
        previous_handler = signal.signal(signal.SIGBREAK, lambda *_: interrupted.set())
    try:
        if ready_file:
            target = Path(ready_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(
                    {
                        "app_id": APP_ID,
                        "version": VERSION,
                        "url": url,
                        "pid": os.getpid(),
                        "host": "127.0.0.1",
                        "port": runtime.port,
                        "shutdown_token": shutdown_token,
                        "interface": "integrated",
                    }
                ),
                encoding="utf-8",
            )
        if no_browser:
            while gateway.is_alive() and not interrupted.is_set():
                gateway.join(timeout=0.5)
        else:
            if webview_module is None:
                import webview as webview_module
            webview_module.create_window(
                DISPLAY_NAME,
                url,
                width=1360,
                height=860,
                min_size=(960, 640),
                background_color="#f4f7fb",
            )
            webview_module.start(gui="edgechromium", debug=False)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.close()
        gateway.join(timeout=3)
        if ready_file:
            Path(ready_file).unlink(missing_ok=True)
        if previous_handler is not None:
            signal.signal(signal.SIGBREAK, previous_handler)
    return 0
