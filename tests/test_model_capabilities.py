# -*- coding: utf-8 -*-
import pytest

import model_capabilities
from model_capabilities import (
    normalize_registry_model_record,
    normalize_remote_model_record,
    resolve_output_capability,
    resolve_reasoning_capability,
)


def test_models_dev_request_identifies_client_and_loads_registry(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"google":{"models":{}}}'

    def require_user_agent(request, timeout):
        assert timeout == 3
        assert request.get_header("User-agent") == "AA-AutoWriter/1.0"
        return Response()

    monkeypatch.setattr(model_capabilities, "_REGISTRY_CACHE", None)
    monkeypatch.setattr(model_capabilities, "urlopen", require_user_agent)

    assert model_capabilities._load_models_dev() == {"google": {"models": {}}}


def test_remote_explicit_output_limit_beats_catalog():
    result = resolve_output_capability(
        "gpt-4o",
        service_preset="openai",
        remote_record={
            "id": "gpt-4o", "context_length": 128000,
            "max_completion_tokens": 8192,
        },
    )
    assert result["max_output_tokens"] == 8192
    assert result["source"] == "api"
    assert result["context_length"] == 128000


def test_context_length_is_never_used_as_output_limit():
    result = resolve_output_capability(
        "unlisted-model",
        remote_record={"id": "unlisted-model", "context_length": 1_000_000},
    )
    assert result["max_output_tokens"] is None
    assert result["source"] == "unknown"


@pytest.mark.parametrize("model_id,expected", [
    ("gpt-4o", 16384),
    ("gpt-4o-2024-11-20", 16384),
    ("gemini-2.5-flash", 65536),
    ("deepseek-v4-flash", 384000),
    ("glm-4.6", 128000),
])
def test_verified_catalog_matches_exact_models_and_bounded_aliases(model_id, expected):
    result = resolve_output_capability(model_id)
    assert result["max_output_tokens"] == expected
    assert result["source"] == "catalog"
    assert result["source_url"].startswith("https://")
    assert result["verified_at"] == "2026-08-07"


def test_similar_unknown_name_does_not_match_by_substring():
    result = resolve_output_capability("my-gpt-4o-wrapper-unverified")
    assert result["max_output_tokens"] is None
    assert result["source"] == "unknown"


def test_remote_normalization_drops_untrusted_fields():
    result = normalize_remote_model_record({
        "id": "deepseek-v4-flash",
        "context_length": 1_000_000,
        "max_completion_tokens": 384_000,
        "pricing": {"prompt": "private-shape-not-forwarded"},
    })
    assert result == {
        "id": "deepseek-v4-flash",
        "context_length": 1_000_000,
        "max_output_tokens": 384_000,
        "max_output_field": "max_completion_tokens",
    }


def test_remote_reasoning_metadata_uses_model_family_wire_when_omitted():
    result = resolve_reasoning_capability(
        "qwen3.7-plus",
        service_preset="qwen",
        remote_record={
            "id": "qwen3.7-plus",
            "reasoning": {"toggle": True, "efforts": ["low", "medium", "high"]},
        },
    )

    assert result["wire_protocol"] == "qwen_thinking"


def test_remote_context_window_is_exposed_as_its_own_capability():
    result = resolve_output_capability(
        "deepseek-v4-flash",
        remote_record={"id": "deepseek-v4-flash", "context_length": 1_000_000, "max_completion_tokens": 384000},
    )

    assert result["context_length"] == 1_000_000
    assert result["max_output_tokens"] == 384000


def test_catalog_output_with_remote_context_keeps_api_context_provenance():
    result = resolve_output_capability(
        "gpt-4o",
        remote_record={"id": "gpt-4o", "context_length": 128_000},
    )

    assert result["max_output_tokens"] == 16_384
    assert result["source"] == "catalog"
    assert result["context_window_tokens"] == 128_000
    assert result["context_window_source"] == "api"


def test_deepseek_reasoning_capability_declares_toggle_and_efforts():
    result = resolve_reasoning_capability("deepseek-v4-flash", service_preset="deepseek")
    assert result["toggle"] is True
    assert result["efforts"] == ["low", "medium", "high"]
    assert result["default_mode"] == "medium"
    assert result["wire_protocol"] == "deepseek_thinking"


def test_verified_deepseek_uses_registry_for_context_without_overriding_catalog_output():
    result = resolve_output_capability(
        "deepseek-v4-flash",
        service_preset="deepseek",
        registry_record=normalize_registry_model_record({
            "id": "deepseek-v4-flash",
            "limit": {"context": 1_000_000, "output": 384_000},
        }),
    )

    assert result["source"] == "catalog"
    assert result["max_output_tokens"] == 384_000
    assert result["context_window_tokens"] == 1_000_000
    assert result["context_window_source"] == "models_dev"


def test_versioned_deepseek_reasoning_capability_matches_bounded_suffix():
    result = resolve_reasoning_capability(
        "deepseek-v4-flash-20260808", service_preset="deepseek",
    )

    assert result["wire_protocol"] == "deepseek_thinking"
    assert result["toggle"] is True


def test_unknown_reasoning_capability_does_not_invent_toggle():
    result = resolve_reasoning_capability("private-wrapper-7b", service_preset="custom")
    assert result == {
        "toggle": False,
        "efforts": [],
        "default_mode": "provider_default",
        "wire_protocol": "none",
        "source": "unknown",
    }


def test_models_dev_record_normalizes_context_output_and_reasoning_controls():
    result = normalize_registry_model_record({
        "id": "qwen3.7-plus",
        "reasoning": True,
        "reasoning_options": [
            {"type": "toggle"},
            {"type": "effort", "values": ["low", "medium", "high", "invalid"]},
            {"type": "budget", "min": 0, "max": 81920},
        ],
        "limit": {"context": 1_000_000, "output": 65_536},
        "cost": {"input": 0.1},
    })

    assert result == {
        "id": "qwen3.7-plus",
        "context_length": 1_000_000,
        "max_output_tokens": 65_536,
        "reasoning": {
            "supported": True,
            "toggle": True,
            "efforts": ["low", "medium", "high"],
            "budget_min": 0,
            "budget_max": 81_920,
        },
    }


def test_models_dev_accepts_single_reasoning_option_object():
    result = normalize_registry_model_record({
        "id": "gemini-3.6-flash",
        "reasoning": True,
        "reasoning_options": {
            "type": "effort", "values": ["minimal", "low", "medium", "high"],
        },
        "limit": {"context": 1_048_576, "output": 65_536},
    })

    assert result["reasoning"]["efforts"] == ["minimal", "low", "medium", "high"]


def test_registry_limit_fills_missing_provider_metadata():
    registry = normalize_registry_model_record({
        "id": "qwen3.7-plus",
        "limit": {"context": 1_000_000, "output": 65_536},
    })

    result = resolve_output_capability(
        "qwen3.7-plus",
        service_preset="qwen",
        remote_record={"id": "qwen3.7-plus"},
        registry_record=registry,
    )

    assert result["max_output_tokens"] == 65_536
    assert result["context_window_tokens"] == 1_000_000
    assert result["source"] == "models_dev"
    assert result["context_window_source"] == "models_dev"


@pytest.mark.parametrize(
    "model_id,preset,wire_protocol",
    [
        ("gpt-5.2", "openai", "openai_reasoning_effort"),
        ("gemini-3.1-pro", "gemini", "gemini_reasoning_effort"),
        ("qwen3.7-plus", "qwen", "qwen_thinking"),
        ("glm-5", "glm", "glm_thinking"),
        ("kimi-k2.6", "moonshot", "kimi_thinking"),
        ("claude-sonnet-4-6", "anthropic", "anthropic_thinking"),
    ],
)
def test_registry_reasoning_controls_use_provider_wire_profile(model_id, preset, wire_protocol):
    registry = normalize_registry_model_record({
        "id": model_id,
        "reasoning": True,
        "reasoning_options": [
            {"type": "toggle"},
            {"type": "effort", "values": ["low", "medium", "high"]},
        ],
    })

    result = resolve_reasoning_capability(
        model_id,
        service_preset=preset,
        registry_record=registry,
    )

    assert result["toggle"] is True
    assert result["efforts"] == ["low", "medium", "high"]
    assert result["wire_protocol"] == wire_protocol
    assert result["source"] == "models_dev"


def test_custom_proxy_can_infer_known_family_wire_from_model_name():
    registry = normalize_registry_model_record({
        "id": "vendor/deepseek-v4-flash",
        "reasoning": True,
        "reasoning_options": [{"type": "toggle"}, {"type": "effort", "values": ["low", "high", "max"]}],
    })

    result = resolve_reasoning_capability(
        "vendor/deepseek-v4-flash",
        service_preset="custom",
        registry_record=registry,
    )

    assert result["wire_protocol"] == "deepseek_thinking"
    assert result["toggle"] is True


def test_registry_reasoning_membership_without_controls_does_not_invent_toggle():
    registry = normalize_registry_model_record({
        "id": "deepseek-reasoner",
        "reasoning": True,
        "reasoning_options": [],
    })

    result = resolve_reasoning_capability(
        "deepseek-reasoner",
        service_preset="deepseek",
        registry_record=registry,
    )

    assert result["toggle"] is False
    assert result["efforts"] == []
    assert result["default_mode"] == "provider_default"
    assert result["wire_protocol"] == "deepseek_thinking"


def test_custom_proxy_registry_lookup_searches_known_owners(monkeypatch):
    monkeypatch.setattr("model_capabilities._load_models_dev", lambda: {
        "deepseek": {"models": {
            "deepseek-v4-flash": {
                "id": "deepseek-v4-flash", "reasoning": True,
                "reasoning_options": [{"type": "toggle"}],
                "limit": {"context": 1_000_000, "output": 384_000},
            },
        }},
    })

    result = resolve_output_capability(
        "relay/deepseek-v4-flash", service_preset="custom",
    )

    assert result["context_window_tokens"] == 1_000_000


def test_effort_only_registry_model_is_not_marked_toggleable():
    registry = normalize_registry_model_record({
        "id": "gemini-3.1-pro-preview", "reasoning": True,
        "reasoning_options": [{"type": "effort", "values": ["low", "medium", "high"]}],
    })

    result = resolve_reasoning_capability(
        "gemini-3.1-pro-preview", service_preset="gemini", registry_record=registry,
    )

    assert result["toggle"] is False
    assert result["efforts"] == ["low", "medium", "high"]
