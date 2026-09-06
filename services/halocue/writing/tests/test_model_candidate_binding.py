import os

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.model_settings import WritingModelSettings


@pytest.fixture
def settings(tmp_path):
    store = WritingModelSettings(tmp_path)
    store.save({"provider": "openai", "base_url": "https://models.example/v1", "model": "a", "api_key": "old-key"})
    return store


@pytest.mark.parametrize("change", [
    {"base_url": "https://other.example/v1"},
    {"provider": "anthropic"},
    {"base_url": "https://127.0.0.1.evil.example/v1", "preset_id": "ollama"},
    {"clear_secret": True},
])
@pytest.mark.parametrize("operation", ["save", "test_connection", "fetch_models"])
def test_endpoint_change_never_reuses_stored_key(settings, change, operation, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("must reject before network"))
    with pytest.raises(DomainError) as rejected:
        getattr(settings, operation)(change)
    assert rejected.value.code == "model_secret_required"
    assert settings.get_credentials()["api_key"] == "old-key"


def test_canonical_endpoint_reuses_key(settings):
    candidate = settings.resolve_candidate({"base_url": "https://MODELS.example:443/v1/chat/completions/", "model": "b"})
    assert candidate["api_key"] == "old-key"
    assert candidate["base_url"] == "https://models.example/v1"


def test_environment_key_does_not_require_dpapi(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_TEST_MODEL_KEY", "env-key")
    monkeypatch.setattr("halocue_writing.model_settings.ModelSecretStore._protect", lambda *a: pytest.fail("environment must remain usable without DPAPI"))
    store = WritingModelSettings(tmp_path)
    result = store.save({"provider": "openai", "model": "a", "api_key_env": "HALOCUE_TEST_MODEL_KEY"})
    assert result["model"]["secret_source"] == "environment"
    assert store.resolve_candidate({"model": "b"})["api_key"] == "env-key"


def test_failed_atomic_activation_preserves_old_credential_version(settings, monkeypatch):
    previous = settings.path.read_bytes()
    original_replace = os.replace

    def fail_public_switch(source, target):
        if target == settings.path:
            raise OSError("disk unavailable")
        return original_replace(source, target)

    monkeypatch.setattr("halocue_writing.model_settings.os.replace", fail_public_switch)
    with pytest.raises(OSError):
        settings.save({"api_key": "new-key", "model": "b"})
    assert settings.path.read_bytes() == previous
    assert settings.get_credentials()["api_key"] == "old-key"


@pytest.mark.parametrize("endpoint", ["http://localhost:11434/v1", "http://[::1]:11434/v1"])
def test_loopback_can_be_keyless(tmp_path, endpoint):
    store = WritingModelSettings(tmp_path)
    result = store.save({"provider": "openai", "base_url": endpoint, "model": "local"})
    assert result["model"]["configured"] is True
    assert store.get_credentials()["api_key"] == ""
