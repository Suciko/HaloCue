import pytest
import threading

import llm
from llm import parse_json_response


def test_parse_json_response_accepts_bare_json():
    assert parse_json_response('{"lines":[]}') == {"lines": []}


def test_parse_json_response_strips_a_complete_markdown_json_fence():
    text = "```json\n{\n  \"lines\": []\n}\n```"

    assert parse_json_response(text) == {"lines": []}


def test_validate_json_schema_rejects_missing_required_structured_field():
    schema = {
        "type": "object",
        "properties": {
            "characters": {"type": "array"},
            "usage_chain": {"type": "array"},
        },
        "required": ["characters", "usage_chain"],
    }

    with pytest.raises(llm.StructuredOutputError, match="usage_chain"):
        llm.validate_json_schema({"characters": []}, schema)


def test_schema_type_union_accepts_only_declared_null():
    schema = {
        "type": "object",
        "properties": {
            "state": {"type": ["string", "null"]},
            "source_id": {"type": "string"},
        },
        "required": ["state", "source_id"],
        "additionalProperties": False,
    }

    assert llm.validate_json_schema(
        {"state": None, "source_id": "src-1"}, schema
    )["state"] is None

    with pytest.raises(llm.StructuredOutputError, match="state"):
        llm.validate_json_schema({"state": 7, "source_id": "src-1"}, schema)

    with pytest.raises(llm.StructuredOutputError, match="source_id"):
        llm.validate_json_schema({"state": None, "source_id": None}, schema)


def test_validate_json_schema_accepts_valid_nested_usage_chain():
    schema = {
        "type": "object",
        "properties": {
            "usage_chain": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "segment": {"type": "string"},
                        "needs": {"type": "array"},
                    },
                    "required": ["segment", "needs"],
                },
            },
        },
        "required": ["usage_chain"],
    }

    assert llm.validate_json_schema(
        {"usage_chain": [{"segment": "开场", "needs": []}]}, schema
    )["usage_chain"][0]["segment"] == "开场"


def test_gateway_timeout_is_retryable_transport_error_not_local_deadline():
    error = llm._provider_http_error(
        "test-model",
        504,
        "gateway timed out",
        "HTTP 504",
        headers={"Retry-After": "2"},
    )

    assert isinstance(error, llm.ModelGatewayTimeoutError)
    assert not isinstance(error, llm.RequestDeadlineError)
    assert error.retry_after == 2


def test_provider_wall_deadline_closes_active_transport():
    provider = llm.Provider({})
    closed = threading.Event()

    class Handle:
        def close(self):
            closed.set()

    with provider._track_active_request(Handle(), wall_timeout=0.01) as guard:
        assert closed.wait(0.5)

    with pytest.raises(llm.RequestDeadlineError):
        provider._raise_if_request_interrupted(guard)


def test_provider_abort_active_request_closes_handle_and_reports_cancellation():
    provider = llm.Provider({"model": "test-model"})
    stopped = threading.Event()
    closed = threading.Event()

    class Handle:
        def close(self):
            closed.set()

    provider.bind_cancellation(stopped.is_set)
    with provider._track_active_request(Handle(), wall_timeout=5) as guard:
        stopped.set()
        provider.abort_active_request()
        assert closed.wait(0.5)

    with pytest.raises(llm.RequestCancelledError):
        provider._raise_if_request_interrupted(guard)
