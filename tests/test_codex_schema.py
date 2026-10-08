import copy
import json

import jsonschema
import pytest

from annotation_protocol import build_chunk_schema, build_compact_chunk_schema
from services.halocue.codex_schema import CodexOutputContract


@pytest.mark.parametrize("compact", [False, True])
def test_real_direction_schema_round_trip_preserves_optional_intent_and_state(compact):
    local = build_compact_chunk_schema(2) if compact else build_chunk_schema(["src-1", "src-2"])
    before = copy.deepcopy(local)
    contract = CodexOutputContract(local)
    CodexOutputContract.validate_strict(contract.wire)
    state = {name: None for name in local["properties"]["state_delta"]["properties"]}
    state.update(
        positions=[{"key": "Actor", "value": 2}], last_faces=[{"key": "Actor", "value": "04"}]
    )
    wire = {"lines": [], "state_delta": state, "memory_events": [], "beats": None}
    restored = json.loads(contract.restore_text(json.dumps(wire)))
    assert restored["state_delta"]["positions"] == {"Actor": 2}
    assert restored["state_delta"]["last_faces"] == {"Actor": "04"}
    assert restored["state_delta"]["background"] is None  # Existing nullable fields stay nullable.
    assert "beats" not in restored  # Optional null means absent, not a new director intent.
    assert (
        local == before
        and local["properties"]["state_delta"]["properties"]["positions"]["maxProperties"] == 5
    )
    wire["state_delta"]["positions"] *= 2
    with pytest.raises(ValueError, match="Duplicate dictionary key"):
        contract.restore_text(json.dumps(wire))
    wire["state_delta"]["positions"] = [{"key": str(index), "value": 2} for index in range(6)]
    with pytest.raises(jsonschema.ValidationError):
        contract.restore_text(
            json.dumps(wire)
        )  # The original local cardinality bound still applies.


def test_optional_nested_direction_nulls_do_not_become_continuity_commands():
    local = build_chunk_schema(["src-1"])
    contract = CodexOutputContract(local)
    row = {
        name: False
        if child.get("type") == "boolean"
        else 0
        if child.get("type") == "integer"
        else ""
        for name, child in local["properties"]["lines"]["items"]["properties"].items()
    }
    row.update(source_id="src-1", text_fingerprint="fingerprint")
    row["direction"] = {
        name: None
        for name in local["properties"]["lines"]["items"]["properties"]["direction"]["properties"]
    }
    row["direction"]["continuity"] = {name: None for name in ("act", "emo", "face", "fx", "bgfx")}
    row["direction"]["continuity"]["act"] = "hold"
    wire = {
        "lines": [row],
        "state_delta": {name: None for name in local["properties"]["state_delta"]["properties"]},
        "memory_events": [],
        "beats": [],
    }
    value = json.loads(contract.restore_text(json.dumps(wire)))
    assert value["lines"][0]["direction"] == {"continuity": {"act": "hold"}}
    row["source_id"] = None
    with pytest.raises(jsonschema.ValidationError):
        contract.restore_text(json.dumps(wire))


def test_optional_reference_and_enum_null_round_trip():
    schema = {
        "type": "object",
        "properties": {"choice": {"$ref": "#/$defs/choice"}},
        "additionalProperties": False,
        "$defs": {"choice": {"type": "string", "enum": ["yes", "no"]}},
    }
    contract = CodexOutputContract(schema)
    assert json.loads(contract.restore_text('{"choice":null}')) == {}
    assert json.loads(contract.restore_text('{"choice":"yes"}')) == {"choice": "yes"}
    with pytest.raises(jsonschema.ValidationError):
        contract.restore_text('{"choice":"other"}')


def test_unrepresentable_schema_fails_before_dispatch():
    with pytest.raises(ValueError, match="Unbounded"):
        CodexOutputContract({"type": "object", "additionalProperties": True})
