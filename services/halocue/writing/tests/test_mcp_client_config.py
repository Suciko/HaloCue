import json
import tomllib
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import pytest

from halocue_writing.app import make_handler
from halocue_writing.mcp_client_config import client_profile
from test_external_agents import ROOT, exchange as external_exchange

exchange = external_exchange


def test_native_configs_preserve_windows_unicode_and_argument_boundaries():
    server = {
        "command": 'C:\\工具 😀\\Python "preview"\\python.exe',
        "args": ["D:\\Alice's 工作区\\bridge.py", "--connection", "D:\\连接\\one.json"],
        "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    }
    config = {"mcpServers": {"halocue": server}}
    codex = client_profile(config, "codex")
    assert tomllib.loads(codex["text"])["mcp_servers"]["halocue"] == server
    claude = client_profile(config, "claude-code")
    assert json.loads(claude["text"])["mcpServers"]["halocue"] == server
    # Both clients use the identical executable, argument vector and environment.
    assert server == config["mcpServers"]["halocue"]


def test_client_profile_http_keeps_generic_config_and_private_credentials(exchange):
    service, payload, _ = exchange
    state = service.mcp_workspace.connect({"work_ids": [payload["work_id"]]})
    private = json.loads(service.mcp_workspace._connection_path(state["connection_id"]).read_text())
    http = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, ROOT / "services/halocue/writing/web")
    )
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{http.server_port}"

    def fetch(**query):
        return json.load(
            urlopen(endpoint + "/api/v1/mcp/config?" + urlencode({"endpoint": endpoint, **query}))
        )["data"]

    try:
        config = fetch()
        assert set(config) == {"mcpServers"}
        for client in ["codex", "claude-code", "generic"]:
            profile = fetch(client=client)
            assert private["token"] not in json.dumps(profile)
            parsed = (
                tomllib.loads(profile["text"]) if client == "codex" else json.loads(profile["text"])
            )
            servers = parsed["mcp_servers" if client == "codex" else "mcpServers"]
            assert servers["halocue"] == config["mcpServers"]["halocue"]
        with pytest.raises(HTTPError) as error:
            fetch(client="unsupported")
        assert error.value.code == 400
        assert service.mcp_workspace.status()["connection_id"] == state["connection_id"]
    finally:
        http.shutdown()
        http.server_close()
        thread.join()
