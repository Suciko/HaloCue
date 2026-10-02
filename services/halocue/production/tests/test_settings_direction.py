import json
import pytest
from halocue_production.model_settings import DirectionModelSettings, VENDOR_PRESETS


def test_direction_model_settings_and_presets(tmp_path):
    settings = DirectionModelSettings(tmp_path)

    pub = settings.public()
    assert pub["ok"] is True
    assert pub["model"]["configured"] is False
    assert len(pub["presets"]) >= 8

    # Save
    saved = settings.save({
        "preset_id": "deepseek",
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-direction-test-key",
        "max_tokens": 4096,
        "timeout": 60,
    })

    assert saved["model"]["configured"] is True
    assert saved["model"]["model"] == "deepseek-chat"
    assert saved["model"]["secret_source"] == "dpapi"

    # Verify secret is kept in dpapi, not in public file
    provider, creds = settings.provider_settings()
    assert provider == "openai"
    assert creds["api_key"] == "sk-direction-test-key"
    assert creds["source_context_strategy"] == "window"
    assert creds["transport_retries"] == 2

    file_content = json.loads(settings.path.read_text(encoding="utf-8"))
    assert "api_key" not in file_content


@pytest.mark.parametrize("endpoint", ["http://localhost:11434/v1", "http://127.0.0.1:11434/v1", "http://[::1]:11434/v1"])
def test_local_keyless_direction_provider_matches_configured_status(tmp_path, endpoint, monkeypatch):
    from pathlib import Path
    from halocue_production.direction_models import DirectionModelGateway

    store = DirectionModelSettings(tmp_path)
    store.save({"provider": "openai", "model": "synthetic-local", "base_url": endpoint})
    assert store.public()["model"]["configured"] is True
    gateway = DirectionModelGateway(store, Path(__file__).resolve().parents[4])
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("No network"))
    provider = gateway.provider()
    assert provider.model == "synthetic-local"
    assert provider.cfg["base_url"] == endpoint
    assert "api_key" not in store.public()["model"]
