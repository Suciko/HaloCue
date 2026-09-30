"""Provider setup defaults and metadata used by automatic model parameters."""

from urllib.parse import urlparse

import pytest

from halocue_writing.model_settings import VENDOR_PRESETS, WritingModelSettings
from halocue_writing.model_capabilities import completion_parameters, upstream_capabilities


def test_accelerator_providers_have_official_openai_endpoints_and_links():
    presets = {item["id"]: item for item in VENDOR_PRESETS}
    expected = {
        "nvidia": "https://integrate.api.nvidia.com/v1",
        "amd": "https://developer.amd.com.cn/radeon/api/v1",
    }
    for name, endpoint in expected.items():
        item = presets[name]
        assert item["provider"] == "openai"
        assert item["base_url"] == endpoint
        assert item["models"] and item["default_model"] in item["models"]
        assert item["api_key_env"]
    for item in VENDOR_PRESETS:
        if item["id"] == "custom":
            continue
        for field in ("website_url", "docs_url"):
            assert urlparse(item[field]).scheme == "https"
        if item["id"] != "ollama":
            assert urlparse(item["api_key_url"]).scheme == "https"


def test_identified_output_limit_is_default_budget_but_probe_stays_small():
    config = WritingModelSettings._validated(
        {
            "provider": "openai",
            "base_url": "http://127.0.0.1:12345/v1",
            "model": "private-fixture",
            "max_output_tokens": 32000,
            "context_window": 128000,
        }
    )
    assert config["max_tokens"] == 32000
    assert completion_parameters(config, "small input")["max_tokens"] == 32000
    assert completion_parameters(config, "small input", probe=True)["max_tokens"] == 512


@pytest.mark.parametrize(
    "metadata",
    [
        {"context_window": 65536, "max_output_tokens": 16384},
        {"context_length": "65536", "top_provider": {"max_completion_tokens": "16384"}},
        {"limit": {"context": 65536, "input": 48000, "output": 16384}},
        {"context_length": 65536, "max_completion_tokens": 16384},
    ],
)
def test_provider_limits_are_extracted_for_automatic_form(metadata):
    info = upstream_capabilities(
        {"id": "private-fixture", **metadata}, "openai", "https://relay.example/v1"
    )
    assert info["context_window"] == 65536
    assert info["max_output_tokens"] == 16384
    assert info["source"] == "provider_metadata"
    assert set(info["provider_fields"]) >= {"context_window", "max_output_tokens"}


def test_id_only_metadata_never_claims_catalog_limits_came_from_provider():
    info = upstream_capabilities({"id": "gpt-6-astra"}, "openai", "https://relay.example/v1")
    assert info["source"] == "official_preset"
    assert info.get("provider_fields", []) == []


def test_smaller_gateway_context_does_not_inherit_impossible_output_cap():
    info = upstream_capabilities({"id": "gpt-6-astra", "context_length": 32768})
    assert info["context_window"] == 32768
    assert info["max_output_tokens"] is None


def test_upstream_token_parameter_is_automatically_recognized():
    info = upstream_capabilities(
        {"id": "relay-fixture", "supported_parameters": ["max_completion_tokens"]}
    )
    assert info["token_limit_parameter"] == "max_completion_tokens"


def test_official_deployment_specs_are_scoped_to_the_actual_service():
    from halocue_writing.model_capabilities import capabilities

    nvidia = capabilities(
        "deepseek-ai/deepseek-v4.1-flash", "openai", "https://integrate.api.nvidia.com/v1"
    )
    assert nvidia["context_window"] == 1048576
    assert nvidia["max_output_tokens"] == 1048576
    assert nvidia["source"] == "provider_documentation"
    assert nvidia["token_limit_parameter"] == "max_tokens"
    custom = capabilities("deepseek-ai/deepseek-v4.1-flash", "openai", "https://relay.example/v1")
    assert custom["max_output_tokens"] is None
    amd = capabilities(
        "DeepSeek-V4.1-Flash", "openai", "https://developer.amd.com.cn/radeon/api/v1"
    )
    assert amd["context_window"] == 1048576
    assert amd["max_output_tokens"] is None, "AMD docs do not publish a separate output cap"


def test_free_access_badges_are_scoped_and_do_not_invent_expiry_dates():
    presets = {item["id"]: item for item in VENDOR_PRESETS}
    assert presets["nvidia"]["access_badge"] == "免费试用"
    assert presets["amd"]["access_badge"] == "限额免费"
    assert "速率" in presets["nvidia"]["access_note"]
    assert "配额" in presets["amd"]["access_note"]
    assert not any(presets[name].get("access_badge") for name in ("openai", "anthropic", "custom"))
    assert all("90 天" not in item.get("access_note", "") for item in VENDOR_PRESETS)
