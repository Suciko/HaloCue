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


def test_openai_model_discovery_returns_unique_sorted_ids():
    class Models:
        def list(self):
            return type(
                "Response",
                (),
                {
                    "data": [
                        type("Model", (), {"id": "z-model"})(),
                        type("Model", (), {"id": "a-model"})(),
                        type("Model", (), {"id": "a-model"})(),
                    ]
                },
            )()

    provider = object.__new__(llm.OpenAIProvider)
    provider.client = type("Client", (), {"models": Models()})()

    assert provider.list_models() == ["a-model", "z-model"]


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


def test_openai_vision_empty_text_reports_model_and_finish_reason():
    class Completions:
        def create(self, **kwargs):
            message = type("Message", (), {"content": "   "})()
            choice = type(
                "Choice",
                (),
                {"message": message, "finish_reason": "stop"},
            )()
            return type(
                "Response",
                (),
                {"choices": [choice], "usage": None},
            )()

    provider = object.__new__(llm.OpenAIProvider)
    provider.client = type(
        "Client",
        (),
        {
            "chat": type(
                "Chat",
                (),
                {
                    "completions": Completions(),
                },
            )()
        },
    )()
    provider.model = "vision-model"
    provider.cfg = {"max_tokens": 100}
    provider.stats = {
        "in": 0,
        "out": 0,
        "cache_read": 0,
        "cache_write": 0,
        "calls": 0,
    }

    with pytest.raises(llm.LLMError, match="vision-model.*空文本.*stop"):
        provider.complete_json_vision(
            "system",
            [("00", b"jpeg")],
            "user",
            {"type": "object"},
        )
