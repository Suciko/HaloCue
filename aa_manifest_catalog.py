"""Read AA's local character manifest without rewriting user configuration."""

from __future__ import annotations

import copy
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping


_OUTFIT_SUFFIX = re.compile(r"\s*[（(][^）)]*[）)]\s*$")


@dataclass(frozen=True)
class AAManifestCharacter:
    identifier: str
    display_name: str
    nickname: str
    spine_path: str
    avatar_path: str

    @property
    def spine_key(self) -> str:
        return spine_resource_key(self.spine_path)

    @property
    def base_identifier(self) -> str:
        value = self.identifier
        while True:
            shortened = _OUTFIT_SUFFIX.sub("", value).strip()
            if not shortened or shortened == value:
                return value
            value = shortened


@lru_cache(maxsize=1)
def _traditional_converter():
    try:
        from opencc import OpenCC

        return OpenCC("t2s")
    except Exception:
        return None


def to_simplified(value: object) -> str:
    """Convert Traditional Chinese where possible while preserving other scripts."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    converter = _traditional_converter()
    if converter is None or not text:
        return text
    try:
        return str(converter.convert(text)).strip()
    except Exception:
        return text


def name_key(value: object) -> str:
    """Return the comparison key used for local character names and aliases."""
    return "".join(to_simplified(value).casefold().split())


def spine_resource_key(value: object) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1].casefold() if normalized else ""


def manifest_path_for_data(aa_data: str | os.PathLike | None) -> Path | None:
    if not aa_data:
        return None
    try:
        data = Path(aa_data).expanduser().resolve()
    except (OSError, TypeError, ValueError):
        return None
    return data / "overrides" / "manifest.json"


def read_manifest_characters(
    manifest_path: str | os.PathLike | None,
) -> list[AAManifestCharacter]:
    """Read AA's effective character overrides; duplicate identifiers use the last row."""
    if manifest_path is None:
        return []
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return []
    rows = payload.get("CharacterOverrides") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    selected: dict[str, AAManifestCharacter] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("Identifier") or "").strip()
        if not identifier:
            continue
        selected[identifier] = AAManifestCharacter(
            identifier=identifier,
            display_name=str(row.get("Name") or "").strip(),
            nickname=str(row.get("Nickname") or "").strip(),
            spine_path=str(row.get("SpinePortraitPath") or "").strip(),
            avatar_path=str(row.get("SmallPortraitPath") or "").strip(),
        )
    return list(selected.values())


def read_characters_for_data(
    aa_data: str | os.PathLike | None,
) -> list[AAManifestCharacter]:
    return read_manifest_characters(manifest_path_for_data(aa_data))


def _record_spine_keys(record: Mapping) -> set[str]:
    keys = {spine_resource_key(record.get("spine"))}
    for variant in record.get("face_capabilities") or []:
        if not isinstance(variant, Mapping):
            continue
        keys.update(
            {
                spine_resource_key(variant.get("spine")),
                spine_resource_key(variant.get("outfit_key")),
            }
        )
    return {key for key in keys if key}


def _unique_spine_matches(
    records: Mapping[str, Mapping],
) -> dict[str, str]:
    owners: dict[str, set[str]] = {}
    for identifier, record in records.items():
        for key in _record_spine_keys(record):
            owners.setdefault(key, set()).add(str(identifier))
    return {
        key: next(iter(identifiers))
        for key, identifiers in owners.items()
        if len(identifiers) == 1
    }


def _aliases_for(
    character: AAManifestCharacter,
    source: Mapping | None,
) -> list[str]:
    values = [
        character.display_name,
        to_simplified(character.display_name),
        character.base_identifier,
        to_simplified(character.base_identifier),
    ]
    if source:
        source_name = str(source.get("name") or "").strip()
        source_identifier = str(source.get("identifier") or source.get("ident") or "").strip()
        values.extend(
            [source_name, to_simplified(source_name), source_identifier]
        )
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = name_key(value)
        if value and key and key not in seen:
            seen.add(key)
            result.append(str(value).strip())
    return result


def merge_runtime_catalog(
    records: Mapping[str, Mapping],
    aliases: Iterable[tuple[str, str, str, int]],
    characters: Iterable[AAManifestCharacter],
) -> tuple[dict[str, dict], list[tuple[str, str, str, int]]]:
    """Overlay the user's actual AA bindings on database character metadata."""
    merged = {str(key): copy.deepcopy(dict(value)) for key, value in records.items()}
    merged_aliases = list(aliases)
    spine_matches = _unique_spine_matches(merged)

    for character in characters:
        source_identifier = character.identifier if character.identifier in merged else None
        if source_identifier is None and character.spine_key:
            source_identifier = spine_matches.get(character.spine_key)
        source = merged.get(source_identifier or "")

        if character.identifier in merged:
            record = merged[character.identifier]
        elif source is not None:
            record = copy.deepcopy(source)
            record["catalog_ident"] = source_identifier
            merged[character.identifier] = record
        else:
            record = {
                "ident": character.identifier,
                "name": to_simplified(character.display_name)
                or to_simplified(character.base_identifier)
                or character.identifier,
                "club": character.nickname,
                "spine": character.spine_path,
                "avatar": character.avatar_path,
                "source": "aa_manifest",
                "nface": 0,
            }
            merged[character.identifier] = record

        record["ident"] = character.identifier
        record["manifest_bound"] = True
        record["manifest_name"] = character.display_name
        record["manifest_spine"] = character.spine_path
        if character.spine_path:
            record["spine"] = character.spine_path
        if character.avatar_path:
            record["avatar"] = character.avatar_path
        if not record.get("club") and character.nickname:
            record["club"] = character.nickname
        if source_identifier and source_identifier != character.identifier:
            record["catalog_source"] = str(source.get("source") or "")
            record["source"] = "aa_manifest"

        for alias in _aliases_for(character, source):
            merged_aliases.append((alias, character.identifier, "portrait", 100))

    deduped_aliases: dict[tuple[str, str, str], tuple[str, str, str, int]] = {}
    for alias, identifier, kind, uses in merged_aliases:
        key = (name_key(alias), str(identifier), str(kind))
        if not key[0] or not key[1]:
            continue
        current = deduped_aliases.get(key)
        candidate = (str(alias), str(identifier), str(kind), int(uses or 0))
        if current is None or candidate[3] > current[3]:
            deduped_aliases[key] = candidate
    return merged, list(deduped_aliases.values())


def merge_model_index(
    index: Mapping,
    characters: Iterable[AAManifestCharacter],
) -> dict:
    """Bind local manifest identifiers to existing face metadata for one build."""
    merged = copy.deepcopy(dict(index))
    rows = [dict(row) for row in merged.get("characters") or [] if isinstance(row, dict)]
    records = {
        str(row.get("identifier") or ""): row
        for row in rows
        if str(row.get("identifier") or "")
    }
    capabilities = merged.setdefault("face_capabilities", {})
    for identifier, variants in list(capabilities.items()):
        record = records.get(str(identifier))
        if record is not None and not record.get("face_capabilities"):
            record["face_capabilities"] = variants
    spine_matches = _unique_spine_matches(records)

    for character in characters:
        source_identifier = character.identifier if character.identifier in records else None
        if source_identifier is None and character.spine_key:
            source_identifier = spine_matches.get(character.spine_key)
        source = records.get(source_identifier or "")

        if character.identifier in records:
            record = records[character.identifier]
        elif source is not None:
            record = copy.deepcopy(source)
            record["identifier"] = character.identifier
            record["catalog_identifier"] = source_identifier
            rows.append(record)
            records[character.identifier] = record
        else:
            record = {
                "identifier": character.identifier,
                "name": to_simplified(character.display_name)
                or to_simplified(character.base_identifier)
                or character.identifier,
                "club": character.nickname,
                "spine": character.spine_path,
                "avatar": character.avatar_path,
                "source": "aa_manifest",
                "faces": [],
            }
            rows.append(record)
            records[character.identifier] = record

        if character.spine_path:
            record["spine"] = character.spine_path
        if character.avatar_path:
            record["avatar"] = character.avatar_path
        if not record.get("club") and character.nickname:
            record["club"] = character.nickname
        record["manifest_bound"] = True
        record["aliases"] = list(
            dict.fromkeys([*(record.get("aliases") or []), *_aliases_for(character, source)])
        )
        if source_identifier and source_identifier != character.identifier:
            source_capabilities = capabilities.get(source_identifier)
            if source_capabilities is None and source is not None:
                source_capabilities = source.get("face_capabilities")
            if source_capabilities is not None:
                capabilities[character.identifier] = copy.deepcopy(source_capabilities)
                record["face_capabilities"] = copy.deepcopy(source_capabilities)

    merged["characters"] = rows
    return merged
