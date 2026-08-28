from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from halocue_writing.ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
from halocue_writing.providers import FakeWritingProvider, LLMWritingProvider
from halocue_writing.repository import Repository


def _prompt_assembler(tmp_path: Path) -> BaWritingPromptAssembler:
    registry = BaWritingSkillRegistry()
    registry.materialize(Repository(tmp_path / "prompt-runtime"))
    return BaWritingPromptAssembler(registry)


def _provider(
    protocol: str,
    base_url: str,
    prompt_assembler: BaWritingPromptAssembler,
    **overrides,
) -> LLMWritingProvider:
    return LLMWritingProvider(
        {
            "provider": protocol,
            "base_url": base_url,
            "model": "local-contract-model",
            "api_key": "local-test-key",
            "max_tokens": 1024,
            **overrides,
        },
        prompt_assembler,
    )


def _protocol_server(protocol: str):
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": body,
            })
            call_number = len(requests)
            reply = json.dumps(
                {
                    "text": f"第 {call_number} 次本地协议响应。",
                    "questions": [],
                    "reasoning_summary": "只公开可验证的简短判断摘要。",
                    "ready_for_proposal": False,
                },
                ensure_ascii=False,
            )
            if protocol == "anthropic":
                payload = {
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 20,
                        "cache_read_input_tokens": 0 if call_number == 1 else 80,
                        "cache_creation_input_tokens": 32 if call_number == 1 else 0,
                    },
                    "content": [{"type": "text", "text": reply}],
                }
            else:
                payload = {
                    "usage": {
                        "prompt_tokens": 180,
                        "completion_tokens": 20,
                        "prompt_tokens_details": {
                            "cached_tokens": 0 if call_number == 1 else 80,
                        },
                    },
                    "choices": [{"message": {"role": "assistant", "content": reply}}],
                }
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, requests


def test_fake_provider_declares_no_real_runtime_capabilities():
    descriptor = FakeWritingProvider().descriptor()

    assert descriptor["is_simulation"] is True
    assert descriptor["capabilities"] == {
        "schema_version": "provider-capabilities/1.0",
        "usage": {"support": "unsupported", "source": "no_model_call"},
        "cache": {"support": "unsupported", "mode": "none"},
        "reasoning_summary": {
            "support": "unsupported",
            "mode": "none",
            "hidden_chain_exposed": False,
        },
    }
    assert FakeWritingProvider().last_usage() == {}


def test_cache_observation_distinguishes_unsupported_unknown_miss_and_hit(tmp_path):
    assembler = _prompt_assembler(tmp_path)
    unsupported = _provider(
        "openai", "http://provider.invalid/v1", assembler, cache_support="unsupported"
    )
    unknown = _provider("openai", "http://provider.invalid/v1", assembler)

    assert unsupported._capture_usage({"usage": {"prompt_tokens": 20}}).cache_status == "unsupported"
    assert unknown._capture_usage({"usage": {"prompt_tokens": 20}}).cache_status == "unknown"
    assert unknown._capture_usage({
        "usage": {"prompt_tokens": 20, "prompt_tokens_details": {"cached_tokens": 0}}
    }).cache_status == "supported_miss"
    assert unknown._capture_usage({
        "usage": {"prompt_tokens": 20, "prompt_tokens_details": {"cached_tokens": 12}}
    }).cache_status == "supported_hit"
    flat = unknown._capture_usage({
        "usage": {
            "prompt_tokens": 20,
            "prompt_cache_hit_tokens": 12,
            "prompt_cache_miss_tokens": 8,
        }
    })
    assert flat.cache_status == "supported_hit"
    assert flat.cache_read_tokens == 12
    assert flat.input_tokens == 20
    missing = unknown._capture_usage({})
    assert missing.usage_status == "not_reported"
    assert missing.cache_status == "unknown"


def test_openai_compatible_local_protocol_exercises_real_http_and_cache_observation(tmp_path):
    server, thread, requests = _protocol_server("openai")
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    provider = _provider(
        "openai", base_url, _prompt_assembler(tmp_path), cache_support="supported"
    )
    try:
        first = provider.discuss_work([], {"work_id": "work-local-openai"})
        first_usage = provider.last_usage()
        second = provider.discuss_work([], {"work_id": "work-local-openai"})
        second_usage = provider.last_usage()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert first["reasoning_summary"] == "只公开可验证的简短判断摘要。"
    assert second["text"].startswith("第 2 次")
    assert [item["path"] for item in requests] == [
        "/v1/chat/completions", "/v1/chat/completions",
    ]
    assert requests[0]["headers"]["authorization"] == "Bearer local-test-key"
    assert requests[0]["body"]["messages"][0]["role"] == "system"
    assert first_usage["usage_status"] == "reported"
    assert first_usage["cache_status"] == "supported_miss"
    assert second_usage["cache_status"] == "supported_hit"
    capabilities = provider.descriptor()["capabilities"]
    assert capabilities["usage"]["support"] == "supported"
    assert capabilities["cache"] == {
        "support": "supported",
        "mode": "provider_managed",
        "observation_values": [
            "unsupported", "unknown", "supported_miss", "supported_hit",
        ],
    }
    assert capabilities["reasoning_summary"]["support"] == "supported"
    assert capabilities["reasoning_summary"]["hidden_chain_exposed"] is False


def test_anthropic_local_protocol_exercises_real_http_and_explicit_cache(tmp_path):
    server, thread, requests = _protocol_server("anthropic")
    base_url = f"http://127.0.0.1:{server.server_port}/v1"
    provider = _provider("anthropic", base_url, _prompt_assembler(tmp_path))
    try:
        provider.discuss_work([], {"work_id": "work-local-anthropic"})
        first_usage = provider.last_usage()
        provider.discuss_work([], {"work_id": "work-local-anthropic"})
        second_usage = provider.last_usage()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert [item["path"] for item in requests] == ["/v1/messages", "/v1/messages"]
    assert requests[0]["headers"]["x-api-key"] == "local-test-key"
    assert requests[0]["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first_usage["input_tokens"] == 152
    assert first_usage["cache_write_tokens"] == 32
    assert first_usage["cache_status"] == "supported_miss"
    assert second_usage["input_tokens"] == 200
    assert second_usage["cache_read_tokens"] == 80
    assert second_usage["cache_status"] == "supported_hit"
    capabilities = provider.descriptor()["capabilities"]
    assert capabilities["cache"]["support"] == "supported"
    assert capabilities["cache"]["mode"] == "explicit_ephemeral"


def test_capability_schema_tracks_provider_descriptor_contract():
    schema_path = Path(__file__).parents[1] / "docs/contracts/provider-capabilities-1.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    descriptor = FakeWritingProvider().descriptor()["capabilities"]

    assert schema["properties"]["schema_version"]["const"] == descriptor["schema_version"]
    support_values = schema["properties"]["cache"]["properties"]["support"]["enum"]
    assert set(support_values) == {"supported", "unsupported", "unknown"}
    observation_values = schema["properties"]["cache"]["properties"]["observation_values"]["items"]["enum"]
    assert observation_values == ["unsupported", "unknown", "supported_miss", "supported_hit"]
