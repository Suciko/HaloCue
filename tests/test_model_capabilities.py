# -*- coding: utf-8 -*-
import pytest

from model_capabilities import (
    normalize_remote_model_record,
    resolve_output_capability,
    resolve_reasoning_capability,
)


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


def test_deepseek_reasoning_capability_declares_toggle_and_efforts():
    result = resolve_reasoning_capability("deepseek-v4-flash", service_preset="deepseek")
    assert result["toggle"] is True
    assert result["efforts"] == ["low", "medium", "high"]
    assert result["default_mode"] == "medium"
    assert result["wire_protocol"] == "deepseek_thinking"


def test_unknown_reasoning_capability_does_not_invent_toggle():
    result = resolve_reasoning_capability("private-wrapper-7b", service_preset="custom")
    assert result == {
        "toggle": False,
        "efforts": [],
        "default_mode": "provider_default",
        "wire_protocol": "none",
        "source": "unknown",
    }
