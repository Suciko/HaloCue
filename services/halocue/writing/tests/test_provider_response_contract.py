import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.provider_response import validate_completion
from halocue_writing.providers import LLMWritingProvider


@pytest.mark.parametrize("protocol,body,code", [
    ("openai", {}, "provider_output_invalid"),
    ("openai", {"choices": [{"message": {"content": "{}"}}]}, "provider_output_invalid"),
    ("openai", {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}, "provider_output_truncated"),
    ("openai", {"choices": [{"message": {"content": "{}", "refusal": "refused"}, "finish_reason": "stop"}]}, "provider_refused"),
    ("anthropic", {"content": [{"type": "text", "text": "{}"}], "stop_reason": "max_tokens"}, "provider_output_truncated"),
    ("anthropic", {"content": [{"type": "text", "text": "{}"}], "stop_reason": "pause_turn"}, "provider_output_invalid"),
    ("anthropic", {"content": [{"type": "refusal"}], "stop_reason": "end_turn"}, "provider_refused"),
])
def test_incomplete_or_refused_response_cannot_become_artifact(protocol, body, code):
    with pytest.raises(DomainError) as rejected:
        validate_completion(body, protocol)
    assert rejected.value.code == code


@pytest.mark.parametrize("body", [{}, {"findings": None}, {"findings": [{}]}])
def test_scene_review_rejects_missing_fields(body, monkeypatch):
    provider = LLMWritingProvider({"provider": "openai", "model": "fixture"})
    monkeypatch.setattr(provider, "_scene_skill_request", lambda *a, **kw: {"system_prompt": "", "user_prompt": ""})
    monkeypatch.setattr(provider, "_call_llm", lambda *a, **kw: type("Call", (), {"text": json.dumps(body)})())
    with pytest.raises(DomainError) as rejected:
        provider.review_scene({}, "Narrator: supplied scene")
    assert rejected.value.code == "provider_output_invalid"


def test_explicit_empty_review_is_valid(monkeypatch):
    provider = LLMWritingProvider({"provider": "openai", "model": "fixture"})
    monkeypatch.setattr(provider, "_scene_skill_request", lambda *a, **kw: {"system_prompt": "", "user_prompt": ""})
    monkeypatch.setattr(provider, "_call_llm", lambda *a, **kw: type("Call", (), {"text": '{"findings":[]}'})())
    assert provider.review_scene({}, "Narrator: supplied scene") == []
