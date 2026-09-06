from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "packages" / "contracts" / "resource-manifest" / "1.0.schema.json"
EXAMPLE = ROOT / "packages" / "contracts" / "resource-manifest" / "example.synthetic.json"


def load_contract():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return schema, example


def test_resource_manifest_schema_accepts_the_synthetic_fixture():
    schema, example = load_contract()

    assert schema["$id"].endswith("resource-manifest/1.0.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(example)


def test_public_fixture_has_only_synthetic_resources_and_relative_lookups():
    _, example = load_contract()

    for resource in example["resources"]:
        assert resource["uri_scope"] == "public-fixture"
        assert resource["provenance"]["kind"] == "synthetic"
        assert resource["provenance"]["redistribution_scope"] == "public-fixture"
        relative_path = resource["lookup"]["relative_path"]
        assert not Path(relative_path).is_absolute()
        assert ".." not in Path(relative_path).parts
        assert not resource["uri"].startswith(("C:/", "D:/", "E:/", "file:"))


@pytest.mark.parametrize(
    "relative_path",
    [
        "D:/AA/data/background.png",
        "D:\\AA\\data\\background.png",
        "/opt/aa/data/background.png",
        "backgrounds/../private/background.png",
        "backgrounds\\..\\private\\background.png",
    ],
)
def test_resource_manifest_rejects_absolute_or_parent_lookup_paths(relative_path):
    schema, example = load_contract()
    invalid = deepcopy(example)
    invalid["resources"][0]["lookup"]["relative_path"] = relative_path

    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(invalid)
