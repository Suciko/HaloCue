import pytest

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
