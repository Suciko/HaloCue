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

    file_content = json.loads(settings.path.read_text(encoding="utf-8"))
    assert "api_key" not in file_content
