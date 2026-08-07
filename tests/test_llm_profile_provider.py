import io
import json
from urllib.error import HTTPError

import pytest

import llm
from model_profiles import ModelProfileError, ModelProfileStore


class FakeCredentials:
    available = True

    def __init__(self):
        self.values = {}

    def read(self, target):
        return self.values.get(target)

    def write(self, target, secret):
        self.values[target] = secret

    def delete(self, target):
        self.values.pop(target, None)


def test_direct_profile_secret_takes_precedence_without_environment(
    monkeypatch,
):
    monkeypatch.delenv("PROFILE_TEST_KEY", raising=False)
    provider = llm.Provider(
        {
            "model": "example",
            "api_key": "memory-secret",
            "api_key_env": "PROFILE_TEST_KEY",
        }
    )

    assert provider._key() == "memory-secret"


def test_profile_store_builds_provider_settings_without_exposing_public_key(
    tmp_path,
):
    store = ModelProfileStore(
        tmp_path / "profiles.json",
        credentials=FakeCredentials(),
    )
    public = store.save_profile(
        {
            "name": "Vision endpoint",
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "vision-model",
            "max_tokens": 9000,
            "vision": True,
            "api_key": "memory-secret",
            "save_key": False,
        }
    )

    provider_name, settings = store.provider_settings(public["id"])

    assert provider_name == "openai"
    assert settings == {
        "model": "vision-model",
        "base_url": "https://example.invalid/v1",
        "max_tokens": 9000,
        "vision": True,
        "api_key": "memory-secret",
    }
    assert "api_key" not in public


def test_provider_settings_require_a_configured_secret(tmp_path):
    store = ModelProfileStore(
        tmp_path / "profiles.json",
        credentials=FakeCredentials(),
    )
    public = store.save_profile(
        {
            "name": "Missing key",
            "provider": "anthropic",
            "model": "claude-example",
        }
    )

    with pytest.raises(ModelProfileError, match="API Key"):
        store.provider_settings(public["id"])


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_openai_model_discovery_uses_builtin_http(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeHttpResponse({"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "a-model"}]})

    monkeypatch.setattr(llm, "urlopen", fake_urlopen, raising=False)
    provider = llm.OpenAIProvider({"api_key": "secret", "base_url": "https://example.invalid/v1/", "model": "chosen"})

    assert provider.list_models() == ["a-model", "z-model"]
    assert requests[0][0].full_url == "https://example.invalid/v1/models"
    assert requests[0][0].headers["Authorization"] == "Bearer secret"


def test_make_provider_from_settings_uses_selected_provider(monkeypatch):
    captured = {}

    class FakeProvider:
        def __init__(self, settings):
            captured.update(settings)

    monkeypatch.setitem(llm.REGISTRY, "profile-test", FakeProvider)

    provider = llm.make_provider_from_settings(
        "profile-test",
        {"model": "chosen", "api_key": "memory-secret"},
    )

    assert isinstance(provider, FakeProvider)
    assert captured == {"model": "chosen", "api_key": "memory-secret"}


def test_openai_text_and_vision_use_builtin_http_contract(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        return FakeHttpResponse({
            "choices": [{"message": {"content": "{\"ok\": true}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 3}},
        })

    monkeypatch.setattr(llm, "urlopen", fake_urlopen, raising=False)
    provider = llm.OpenAIProvider({"api_key": "secret", "base_url": "https://example.invalid/v1", "model": "vision-model", "max_tokens": 100})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    assert provider.complete_json("stable", "volatile", "user", schema) == {"ok": True}
    assert provider.complete_json_vision("system", [("00", b"jpeg")], "inspect", schema) == {"ok": True}
    assert payloads[0]["messages"][0]["content"] == "stable\n\nvolatile"
    assert payloads[0]["response_format"]["type"] == "json_schema"
    assert payloads[1]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert provider.stats == {"in": 24, "out": 8, "cache_read": 6, "cache_write": 0, "calls": 2}


def test_openai_vision_empty_text_reports_model_and_finish_reason(monkeypatch):
    monkeypatch.setattr(
        llm,
        "urlopen",
        lambda request, timeout: FakeHttpResponse({"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]}),
        raising=False,
    )
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "vision-model", "max_tokens": 100})

    with pytest.raises(llm.LLMError, match="vision-model.*空文本.*stop"):
        provider.complete_json_vision(
            "system",
            [("00", b"jpeg")],
            "user",
            {"type": "object"},
        )


def test_openai_empty_text_length_is_capacity_error(monkeypatch):
    monkeypatch.setattr(
        llm,
        "urlopen",
        lambda request, timeout: FakeHttpResponse({
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        }),
        raising=False,
    )
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "deepseek-chat"})

    with pytest.raises(llm.OutputCapacityError, match="finish_reason=length"):
        provider.complete_json("system", "volatile", "user", {"type": "object"})


def test_openai_length_finish_reason_explains_output_budget(monkeypatch):
    monkeypatch.setattr(
        llm,
        "urlopen",
        lambda request, timeout: FakeHttpResponse({
            "choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
        }),
        raising=False,
    )
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "deepseek-chat", "max_tokens": 16000})

    with pytest.raises(llm.OutputCapacityError, match="finish_reason=length.*max_tokens=16000"):
        provider.complete_json("system", "volatile", "user", {"type": "object"})


def test_openai_structured_call_rejects_markdown_response(monkeypatch):
    monkeypatch.setattr(
        llm,
        "urlopen",
        lambda request, timeout: FakeHttpResponse({
            "choices": [{
                "message": {"content": "### 场景演出时间线\n- 商店街入口"},
                "finish_reason": "stop",
            }],
        }),
        raising=False,
    )
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "scene-model", "max_tokens": 100})

    with pytest.raises(llm.StructuredOutputError, match="合法 JSON"):
        provider.complete_json(
            "system", "volatile", "请只返回 JSON",
            {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )


def test_invalid_strict_content_does_not_replay_full_request(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payloads.append(json.loads(request.data))
        return FakeHttpResponse({
            "choices": [{"message": {"content": "### 不是 JSON"}, "finish_reason": "stop"}],
        })

    monkeypatch.setattr(llm, "urlopen", fake_urlopen, raising=False)
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "scene-model", "max_tokens": 100})

    with pytest.raises(llm.StructuredOutputError, match="合法 JSON"):
        provider.complete_json("system", "", "user", {"type": "object"})

    assert len(payloads) == 1


def test_openai_retries_with_json_object_when_endpoint_rejects_json_schema(monkeypatch):
    payloads = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data)
        payloads.append(payload)
        if len(payloads) == 1:
            body = io.BytesIO(json.dumps({
                "error": {"message": "This response_format type is unavailable now"},
            }).encode("utf-8"))
            raise HTTPError(request.full_url, 400, "Bad Request", {}, body)
        return FakeHttpResponse({
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
        })

    monkeypatch.setattr(llm, "urlopen", fake_urlopen, raising=False)
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "deepseek-v4-flash"})
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    assert provider.complete_json("system", "", "user", schema) == {"ok": True}
    assert payloads[0]["response_format"]["type"] == "json_schema"
    assert payloads[1]["response_format"]["type"] == "json_object"
    assert '"ok"' in payloads[1]["messages"][0]["content"]


def test_openai_retries_without_response_format_when_both_formats_are_rejected(
    monkeypatch,
):
    payloads = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data)
        payloads.append(payload)
        if len(payloads) <= 2:
            body = io.BytesIO(json.dumps({
                "error": {"message": "This response_format type is unavailable now"},
            }).encode("utf-8"))
            raise HTTPError(request.full_url, 400, "Bad Request", {}, body)
        return FakeHttpResponse({
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
        })

    monkeypatch.setattr(llm, "urlopen", fake_urlopen, raising=False)
    provider = llm.OpenAIProvider({"api_key": "secret", "model": "compatible-model"})
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    assert provider.complete_json("system", "", "user", schema) == {"ok": True}
    assert payloads[0]["response_format"]["type"] == "json_schema"
    assert payloads[1]["response_format"]["type"] == "json_object"
    assert "response_format" not in payloads[2]
