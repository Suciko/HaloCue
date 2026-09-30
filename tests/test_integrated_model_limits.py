import pytest
import model_capabilities

from model_capabilities import (
    ModelCapabilityError,
    capabilities,
    completion_parameters,
    normalize_advanced,
    upstream_capabilities,
)


def test_model_limits_are_not_context_aliases():
    known = capabilities("gpt-6-sol")
    assert known["context_window"] == 1050000
    assert known["max_output_tokens"] == 128000
    assert capabilities("private-model")["max_output_tokens"] is None
    result = upstream_capabilities({"id": "private-model", "context_length": 32000})
    assert result["context_window"] == 32000 and result["max_output_tokens"] is None


def test_on_demand_catalog_suggests_unknown_model_without_changing_runtime_defaults(monkeypatch):
    monkeypatch.setattr(model_capabilities, "registry_model_record", lambda *_args, **_kwargs: {
        "id": "private-model", "context_length": 65536,
        "max_input_tokens": 48000, "max_output_tokens": 8192,
    })
    assert capabilities("private-model")["known"] is False
    suggested = capabilities("private-model", include_registry=True)
    assert (suggested["context_window"], suggested["max_input_tokens"], suggested["max_output_tokens"]) == (65536, 48000, 8192)
    assert suggested["source"] == "models_dev"


def test_gateway_capabilities_override_catalog_and_wire_can_be_overridden():
    info = upstream_capabilities(
        {"id": "gpt-6-sol", "max_output_tokens": 16000}, base_url="https://example.test/v1"
    )
    assert info["max_output_tokens"] == 16000 and info["source"] == "provider_metadata"
    params = completion_parameters(
        {"model": "gpt-6-sol", "token_limit_parameter": "max_tokens", "max_tokens": 12000}, "正文"
    )
    assert params == {"max_tokens": 12000}


def test_transport_uses_model_parameter_and_reserves_context():
    assert completion_parameters({"model": "gpt-6-sol"}, "hello", tools=True) == {
        "max_completion_tokens": 128000,
        "reasoning_effort": "none",
    }
    params = completion_parameters(
        {"model": "private", "context_window": 4096, "max_tokens": 8192}, "x" * 3000
    )
    assert 2500 < params["max_tokens"] < 4096
    with pytest.raises(ModelCapabilityError, match="超出配置"):
        completion_parameters({"context_window": 1000}, "正文" * 1000)


def test_probe_respects_anthropic_thinking_budget():
    config = {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "thinking_budget": 5000,
        "temperature": 0.5,
    }
    params = completion_parameters(config, "你好", probe=True)
    assert params["max_tokens"] > 5000 and params["thinking"]["budget_tokens"] == 5000
    assert "temperature" not in params


@pytest.mark.parametrize(
    "config",
    [
        {"context_window": 2.5},
        {"temperature": "nan"},
        {"context_window": 100, "max_output_tokens": 200},
    ],
)
def test_invalid_limits_rejected(config):
    with pytest.raises(ModelCapabilityError):
        normalize_advanced(config)


def test_images_not_estimated_as_base64_text():
    params = completion_parameters(
        {"context_window": 8000}, {"type": "image", "source": {"data": "a" * 1000000}}
    )
    assert params["max_tokens"] > 5000
