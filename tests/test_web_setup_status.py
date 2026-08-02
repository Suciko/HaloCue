import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import assetdb
import webui


class ActiveProfileStore:
    def active_profile(self):
        return {
            "id": "profile-1",
            "name": "日常标注模型",
            "model": "vision-model",
            "secret_status": "saved",
        }


def test_setup_status_reports_readiness_without_secret_fields(
    tmp_path,
    monkeypatch,
):
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    database = tmp_path / "assets.db"
    assetdb.connect(database).close()
    monkeypatch.setitem(webui.CFG, "aa_data", str(data))
    monkeypatch.setattr(webui, "DB", str(database))
    monkeypatch.setattr(
        webui,
        "MODEL_PROFILES",
        ActiveProfileStore(),
    )

    status = webui.setup_status()

    assert status["aa"] == {
        "connected": True,
        "path": str(data),
    }
    assert status["database"]["ready"] is True
    assert status["model"] == {
        "configured": True,
        "name": "日常标注模型",
        "model": "vision-model",
    }
    assert status["entry_file"] == "启动AA自动写剧本.cmd"
    serialized = json.dumps(status, ensure_ascii=False).lower()
    assert "api_key" not in serialized
    assert "secret_status" not in serialized


def test_setup_status_is_available_over_local_http(
    tmp_path,
    monkeypatch,
):
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    database = tmp_path / "assets.db"
    assetdb.connect(database).close()
    monkeypatch.setitem(webui.CFG, "aa_data", str(data))
    monkeypatch.setattr(webui, "DB", str(database))
    monkeypatch.setattr(
        webui,
        "MODEL_PROFILES",
        ActiveProfileStore(),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/setup/status"
        ) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["aa"]["connected"] is True
        assert payload["model"]["configured"] is True
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

