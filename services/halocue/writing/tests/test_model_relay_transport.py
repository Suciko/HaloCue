"""Loopback relay rejects anonymous Python transport headers, not model credentials."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from halocue_writing.model_settings import WritingModelSettings
from halocue_writing.providers import LLMWritingProvider


@pytest.fixture
def relay():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, body):
            agent = self.headers.get("User-Agent", "")
            calls.append((self.path, agent))
            accepted = agent == "HaloCue/1.0"
            data = json.dumps(
                body if accepted else {"error": {"message": "error code: 1010"}}
            ).encode()
            self.send_response(200 if accepted else 403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.respond({"data": [{"id": "relay-fixture"}]})

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            assert data["model"] == "relay-fixture"
            self.respond(
                {
                    "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                    "content": [{"type": "text", "text": "OK"}],
                    "stop_reason": "end_turn",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_relay_discovery_test_activation_and_actual_call_use_application_headers(
    tmp_path, relay, protocol
):
    base_url, calls = relay
    config = {"provider": protocol, "base_url": base_url, "model": "relay-fixture", "timeout": 10}
    settings = WritingModelSettings(tmp_path)
    assert settings.fetch_models(config) == ["relay-fixture"]
    assert settings.test_connection(config)["model"] == "relay-fixture"
    assert settings.activate(config)["model"]["configured"] is True
    restored = settings.get_credentials()
    assert LLMWritingProvider(restored)._call_llm("Be concise.", "Reply OK.").text == "OK"
    assert len(calls) == 4
    assert all(agent == "HaloCue/1.0" for _, agent in calls)


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
def test_actual_writing_request_independently_supports_relay(relay, protocol):
    base_url, _ = relay
    provider = LLMWritingProvider(
        {"provider": protocol, "base_url": base_url, "model": "relay-fixture", "timeout": 10}
    )
    assert provider._call_llm("Be concise.", "Reply OK.").text == "OK"
