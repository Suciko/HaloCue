"""Lifecycle checks use temporary data and loopback servers, never a real provider."""

import json
import threading

from halocue_integrated.server import IntegratedRuntime


def test_integrated_close_stops_idle_writing_dispatcher(tmp_path):
    resource_index = tmp_path / "resources.json"
    resource_index.write_text(
        json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8"
    )
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=resource_index,
    )
    runtime.start_upstreams()
    gateway_thread = threading.Thread(target=runtime.gateway.serve_forever, daemon=True)
    gateway_thread.start()
    try:
        assert runtime.writing_service.agent_dispatcher.descriptor()["running"] is True
        runtime.close()
        gateway_thread.join(timeout=3)
        assert not gateway_thread.is_alive()
        assert runtime.writing_service.agent_dispatcher.descriptor()["running"] is False
    finally:
        # Also clean up the baseline's leaked worker when the RED assertion fails.
        runtime.writing_service.close()
        if gateway_thread.is_alive():
            runtime.close()
            gateway_thread.join(timeout=3)
