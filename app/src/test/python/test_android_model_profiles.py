from __future__ import annotations

import json
import re
import urllib.request

import pytest

import android_credentials
import android_web_server
import model_profiles
import webui


class FakeCredentialBackend:
    def __init__(self):
        self.values: dict[str, str] = {}

    def put(self, name: str, value: str) -> None:
        self.values[name] = value

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def has(self, name: str) -> bool:
        return name in self.values

    def masked(self, name: str) -> str | None:
        value = self.values.get(name)
        if value is None:
            return None
        return "\u2022" * 4 if len(value) <= 4 else "\u2022" * 4 + value[-4:]

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


@pytest.fixture
def credential_backend(monkeypatch):
    backend = FakeCredentialBackend()
    monkeypatch.setenv("HALOCUE_PLATFORM", "android")
    android_credentials.set_backend_for_tests(backend)
    yield backend
    android_credentials.set_backend_for_tests(None)


@pytest.fixture
def stopped_server():
    android_web_server.stop()
    yield
    android_web_server.stop()


def _profile_payload(api_key: str) -> dict:
    return {
        "name": "Android DeepSeek",
        "provider": "openai",
        "service_preset": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": api_key,
    }


def test_android_default_store_maps_targets_to_stable_legal_names(
    tmp_path, credential_backend
):
    first = model_profiles.ModelProfileStore(tmp_path / "first.json")
    second = model_profiles.ModelProfileStore(tmp_path / "second.json")

    first.credentials.write("AA-AutoWriter/connection/profile-1", "sk-first-1234")
    second.credentials.write("AA-AutoWriter/connection/profile-1", "sk-second-5678")

    assert isinstance(first.credentials, model_profiles.AndroidCredentialStore)
    assert len(credential_backend.values) == 1
    name = next(iter(credential_backend.values))
    assert re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name)
    assert "/" not in name
    assert first.credentials.read("AA-AutoWriter/connection/profile-1") == "sk-second-5678"


def test_android_profile_public_state_is_masked_and_json_has_no_secret(
    tmp_path, credential_backend
):
    path = tmp_path / "profiles.json"
    store = model_profiles.ModelProfileStore(path)

    profile = store.save_profile(_profile_payload("sk-private-1234"))
    state = store.public_state()

    assert profile["credential"] == {"configured": True, "masked": "\u2022\u2022\u2022\u20221234"}
    assert state["profiles"][0]["credential"] == profile["credential"]
    assert state["connections"][0]["credential"] == profile["credential"]
    assert "api_key" not in state["profiles"][0]
    assert "api_key" not in state["connections"][0]
    assert "sk-private-1234" not in path.read_text(encoding="utf-8")
    assert "sk-private-1234" not in json.dumps(state)


def test_provider_settings_resolve_real_key_without_exposing_it(
    tmp_path, credential_backend
):
    store = model_profiles.ModelProfileStore(tmp_path / "profiles.json")
    profile = store.save_profile(_profile_payload("sk-provider-9012"))

    provider, settings = store.provider_settings(profile["id"])
    connection = store.public_state()["connections"][0]
    model = store.public_state()["models"][0]
    model_provider, model_settings = store.provider_settings_for_model(model["id"])

    assert provider == model_provider == "openai"
    assert settings["api_key"] == model_settings["api_key"] == "sk-provider-9012"
    assert connection["credential"] == {"configured": True, "masked": "\u2022\u2022\u2022\u20229012"}


def test_profile_metadata_update_restores_missing_companion_connection_key(
    tmp_path, credential_backend
):
    store = model_profiles.ModelProfileStore(tmp_path / "profiles.json")
    profile = store.save_profile(_profile_payload("sk-retained-7788"))
    state = store.public_state()
    connection = state["connections"][0]
    model = state["models"][0]
    store.save_connection({**connection, "clear_secret": True})

    store.save_profile({**profile, "name": "Renamed profile"})

    _provider, settings = store.provider_settings_for_model(model["id"])
    assert settings["api_key"] == "sk-retained-7788"


def test_profiles_endpoint_returns_masked_status_only(
    tmp_path, credential_backend, stopped_server
):
    server = android_web_server.start(str(tmp_path), "model-session")
    origin = server["url"].split("?", 1)[0].rstrip("/")
    body = json.dumps(_profile_payload("sk-http-secret-3456")).encode("utf-8")
    save_request = urllib.request.Request(
        origin + "/api/llm/profiles/save",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-HaloCue-Session": "model-session",
        },
    )
    saved = json.load(urllib.request.urlopen(save_request))
    state_request = urllib.request.Request(
        origin + "/api/llm/profiles",
        headers={"X-HaloCue-Session": "model-session"},
    )
    state = json.load(urllib.request.urlopen(state_request))

    assert saved["credential"] == {"configured": True, "masked": "\u2022\u2022\u2022\u20223456"}
    assert state["profiles"][0]["credential"] == saved["credential"]
    assert "sk-http-secret-3456" not in json.dumps(saved)
    assert "sk-http-secret-3456" not in json.dumps(state)


def test_explicit_pc_credential_store_contract_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("HALOCUE_PLATFORM", raising=False)
    credentials = model_profiles.WindowsCredentialStore(win32cred_module=None)
    store = model_profiles.ModelProfileStore(
        tmp_path / "profiles.json", credentials=credentials
    )

    assert store.credentials is credentials
    assert "credential" not in store.save_profile(_profile_payload(""))


def test_model_discovery_uses_short_network_timeout(monkeypatch):
    captured = {}

    class FakeProvider:
        def list_model_records(self):
            return [{"id": "available-model"}]

    def make_provider(protocol, settings):
        captured.update(settings)
        return FakeProvider()

    monkeypatch.setattr(webui.llm, "make_provider_from_settings", make_provider)

    result = webui.list_workbench_models(
        {
            "name": "Temporary",
            "protocol": "openai",
            "service_preset": "custom",
            "base_url": "https://example.invalid/v1",
            "api_key": "test-only-key",
        },
        {"model": "model-list", "max_tokens": 16000},
    )

    assert captured["timeout"] == 20
    assert result["models"][0]["model_id"] == "available-model"
