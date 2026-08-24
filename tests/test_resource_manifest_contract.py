import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "packages" / "contracts" / "resource-manifest" / "1.0.schema.json"
EXAMPLE = ROOT / "packages" / "contracts" / "resource-manifest" / "example.synthetic.json"


def test_resource_manifest_schema_and_fixture_are_valid_json():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    assert schema["$id"].endswith("resource-manifest/1.0.schema.json")
    assert schema["properties"]["schema_version"]["const"] == "resource-manifest/1.0"
    assert example["schema_version"] == "resource-manifest/1.0"


def test_public_fixture_has_only_synthetic_resources_and_relative_lookups():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    for resource in example["resources"]:
        assert resource["uri_scope"] == "public-fixture"
        assert resource["provenance"]["kind"] == "synthetic"
        assert resource["provenance"]["redistribution_scope"] == "public-fixture"
        relative_path = resource["lookup"]["relative_path"]
        assert not Path(relative_path).is_absolute()
        assert ".." not in Path(relative_path).parts
        assert not resource["uri"].startswith(("C:/", "D:/", "E:/", "file:"))

