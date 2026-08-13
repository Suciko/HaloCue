from __future__ import annotations

import copy
import json
from pathlib import Path


_DEFAULT_MAPPING = Path(__file__).with_name("android_resource_mapping.json")


def load_mapping(path: str | Path = _DEFAULT_MAPPING) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("identifier_aliases"), dict)
        or not isinstance(payload.get("characters"), list)
    ):
        raise ValueError("Android resource mapping is invalid")
    return payload


def _capability_faces(faces: list[dict]) -> list[dict]:
    return [
        {
            "id": str(face.get("id") or ""),
            "raw": str(face.get("raw") or face.get("id") or ""),
            "label": str(face.get("label") or ""),
            "cn": "",
            "sources": ["atlas_candidate"],
            "observed_count": 0,
            "verified": False,
        }
        for face in faces
        if str(face.get("id") or "")
    ]


def merge_mapping(index: dict, mapping: dict) -> dict:
    merged = copy.deepcopy(index)
    characters = merged.setdefault("characters", [])
    capabilities = merged.setdefault("face_capabilities", {})
    by_outfit = {
        str(row.get("outfit_key") or ""): row
        for row in characters
        if str(row.get("outfit_key") or "")
    }

    for source in mapping.get("characters", []):
        outfit_key = str(source.get("outfit_key") or "")
        identifier = str(source.get("identifier") or "")
        package_identifier = str(source.get("package_identifier") or identifier)
        if not outfit_key or not identifier or not package_identifier:
            continue
        faces = copy.deepcopy(source.get("faces") or [])
        record = by_outfit.get(outfit_key)
        if record is None:
            record = {
                "identifier": identifier,
                "name": str(source.get("name") or identifier),
                "club": str(source.get("club") or ""),
                "spine": str(source.get("spine") or ""),
                "avatar": outfit_key,
                "outfit_key": outfit_key,
                "faces": faces,
                "android_package_identifier": package_identifier,
            }
            characters.append(record)
            by_outfit[outfit_key] = record
        else:
            record["android_package_identifier"] = package_identifier
            record["avatar"] = outfit_key
            if faces:
                record["faces"] = faces

        variants = capabilities.setdefault(identifier, [])
        variant = next(
            (
                item
                for item in variants
                if str(item.get("outfit_key") or "") == outfit_key
            ),
            None,
        )
        if variant is None:
            variant = {
                "spine_signature": "",
                "outfit_key": outfit_key,
                "spine": str(record.get("spine") or source.get("spine") or ""),
                "faces": [],
            }
            variants.append(variant)
        if faces:
            variant["faces"] = _capability_faces(faces)

    aliases = dict(merged.get("identifier_aliases") or {})
    aliases.update(
        {
            str(source): str(target)
            for source, target in mapping.get("identifier_aliases", {}).items()
            if str(source) and str(target)
        }
    )
    merged["identifier_aliases"] = aliases
    merged["_android_mapping"] = {
        "schema_version": int(mapping.get("schema_version") or 1),
        "source_package": str(mapping.get("source_package") or ""),
        "summary": copy.deepcopy(mapping.get("summary") or {}),
    }
    return merged
