"""Lossless local-schema adapter for Codex's strict Structured Outputs subset."""

from __future__ import annotations

import copy
import json

import jsonschema


class CodexOutputContract:
    def __init__(self, schema: dict):
        self.local = copy.deepcopy(schema)
        jsonschema.Draft202012Validator.check_schema(self.local)
        self.wire = self._convert(self.local, "schema")
        if self.wire.get("type") != "object" or "anyOf" in self.wire:
            raise ValueError("Codex output schema must have an object root")
        self.validate_strict(self.wire)

    @staticmethod
    def _types(node):
        value = node.get("type", [])
        return [value] if isinstance(value, str) else value

    def _resolve(self, node):
        if "$ref" not in node:
            return node
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("Codex schemas only support local references")
        target = self.local
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        return target

    def _nullable(self, node):
        node = self._resolve(node)
        if "anyOf" in node or "oneOf" in node:
            return any(self._nullable(part) for part in node.get("anyOf", node.get("oneOf", [])))
        if "enum" in node:
            return None in node["enum"]
        if "const" in node:
            return node["const"] is None
        return "null" in self._types(node) or ("type" not in node and node.get("const") is None)

    def _convert(self, node, path):
        if not isinstance(node, dict):
            raise ValueError(f"Unsupported Codex schema at {path}")
        unsupported = {
            "allOf",
            "not",
            "if",
            "then",
            "else",
            "dependentRequired",
            "dependentSchemas",
            "patternProperties",
        } & node.keys()
        if unsupported:
            raise ValueError(f"Unsupported Codex schema keywords at {path}: {sorted(unsupported)}")
        result = copy.deepcopy(node)
        # Keep these local domain limits; the remote strict subset rejects them.
        for key in ("maxProperties", "minProperties", "$schema", "default"):
            result.pop(key, None)
        for key in ("$defs", "definitions"):
            if key in node:
                result[key] = {
                    name: self._convert(value, f"{path}.{key}.{name}")
                    for name, value in node[key].items()
                }
        for key in ("anyOf", "oneOf"):
            if key in node:
                result.pop(key, None)
                result["anyOf"] = [self._convert(value, f"{path}.{key}") for value in node[key]]
        if "object" in self._types(node):
            properties = node.get("properties", {})
            extra = node.get("additionalProperties", False)
            if isinstance(extra, dict):
                if properties:
                    raise ValueError(f"Mixed fixed and dynamic Codex object at {path}")
                # Arbitrary role names cannot be properties in a strict schema.
                result.pop("additionalProperties", None)
                result.pop("required", None)
                result.pop("properties", None)
                result["type"] = ["array", "null"] if "null" in self._types(node) else "array"
                result["items"] = {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": self._convert(extra, f"{path}.value"),
                    },
                    "required": ["key", "value"],
                    "additionalProperties": False,
                }
                result["description"] = (
                    str(node.get("description", ""))
                    + " Dictionary as key/value entries; use [] for an empty dictionary. Keys must be unique."
                ).strip()
            else:
                if extra is not False:
                    raise ValueError(f"Unbounded Codex object at {path}")
                required = set(node.get("required", []))
                result["properties"] = {}
                for key, child in properties.items():
                    converted = self._convert(child, f"{path}.properties.{key}")
                    if key not in required and not self._nullable(child):
                        converted = {
                            "anyOf": [converted, {"type": "null"}],
                            "description": "Use null to omit this optional field.",
                        }
                    result["properties"][key] = converted
                result["required"] = list(properties)
                result["additionalProperties"] = False
        elif "array" in self._types(node):
            result["items"] = self._convert(node["items"], f"{path}.items")
        return result

    @classmethod
    def validate_strict(cls, node):
        """Check every schema node, including definitions and union branches."""
        jsonschema.Draft202012Validator.check_schema(node)

        def walk(value):
            if not isinstance(value, dict):
                raise ValueError("Schema nodes must be objects")
            if "maxProperties" in value or "minProperties" in value:
                raise ValueError("Object size limits are not supported by Codex")
            if "object" in cls._types(value):
                props = value.get("properties", {})
                required = value.get("required")
                if (
                    not isinstance(required, list)
                    or set(required) != set(props)
                    or value.get("additionalProperties") is not False
                ):
                    raise ValueError(
                        "Every Codex object must require all properties and reject additional properties"
                    )
                for child in props.values():
                    walk(child)
            if "array" in cls._types(value):
                walk(value["items"])
            for branch in value.get("anyOf", []):
                walk(branch)
            for key in ("$defs", "definitions"):
                for child in value.get(key, {}).values():
                    walk(child)

        walk(node)

    def _restore(self, value, node):
        node = self._resolve(node)
        if value is None:
            return None
        for branch in node.get("anyOf", node.get("oneOf", [])):
            wire = self._convert(branch, "branch")
            validator = jsonschema.Draft202012Validator(self.wire).evolve(schema=wire)
            if validator.is_valid(value):
                return self._restore(value, branch)
        if "object" in self._types(node):
            extra = node.get("additionalProperties", False)
            if isinstance(extra, dict):
                result = {}
                for entry in value:
                    key = entry["key"]
                    if key in result:
                        raise ValueError(f"Duplicate dictionary key: {key}")
                    result[key] = self._restore(entry["value"], extra)
                return result
            required = set(node.get("required", []))
            return {
                key: self._restore(child, node["properties"][key])
                for key, child in value.items()
                if not (
                    child is None
                    and key not in required
                    and not self._nullable(node["properties"][key])
                )
            }
        if "array" in self._types(node):
            return [self._restore(child, node["items"]) for child in value]
        return value

    def restore_text(self, text: str) -> str:
        value = json.loads(text)
        jsonschema.validate(value, self.wire)
        restored = self._restore(value, self.local)
        jsonschema.validate(restored, self.local)
        return json.dumps(restored, ensure_ascii=False)
