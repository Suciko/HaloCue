# -*- coding: utf-8 -*-
"""Read verified native-character labels from AA's FlatData bundle."""
import base64
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# Extracted from AA's local ScenarioCharacterNameExcel table.  The first four
# bytes are the table's uint-XOR key; the full key decrypts its UTF-16 strings.
CHARACTER_NAME_KEY = bytes.fromhex("268bd50b5cce8633")
CHARACTER_NAME_UINT_KEY = int.from_bytes(CHARACTER_NAME_KEY[:4], "little")


@dataclass(frozen=True)
class CatalogBundleLocation:
    internal_id: str
    bundle_name: str
    content_hash: str
    data_path: Path | None


def decrypt_ba_text(token: str, key: bytes = CHARACTER_NAME_KEY) -> str:
    """Decode one Base64 + XOR + UTF-16LE value from AA FlatData."""
    encrypted = base64.b64decode(token)
    plain = bytes(value ^ key[index % len(key)] for index, value in enumerate(encrypted))
    return plain.decode("utf-16-le")


def _u16(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<H", blob, offset)[0]


def _u32(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<I", blob, offset)[0]


def _i32(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<i", blob, offset)[0]


def _table_fields(blob: bytes, table_offset: int) -> list[int]:
    vtable = table_offset - _i32(blob, table_offset)
    count = (_u16(blob, vtable) - 4) // 2
    return [_u16(blob, vtable + 4 + index * 2) for index in range(count)]


def _encrypted_string(blob: bytes, offset: int) -> str:
    string_offset = offset + _u32(blob, offset)
    size = _u32(blob, string_offset)
    token = blob[string_offset + 4:string_offset + 4 + size].decode("ascii")
    return decrypt_ba_text(token)


def _text_asset_bytes(data_path: Path, asset_name: str) -> bytes:
    import UnityPy

    environment = UnityPy.load(str(data_path))
    for obj in environment.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        if getattr(asset, "m_Name", "") == asset_name:
            return asset.m_Script.encode("utf-8", errors="surrogateescape")
    raise LookupError(f"AA FlatData bundle lacks {asset_name}")


def _decode_character_table(blob: bytes) -> list[dict]:
    root = _u32(blob, 0)
    root_field = _table_fields(blob, root)[0]
    vector_field = root + root_field
    vector = vector_field + _u32(blob, vector_field)
    rows: list[dict] = []
    for index in range(_u32(blob, vector)):
        element = vector + 4 + index * 4
        table = element + _u32(blob, element)
        fields = _table_fields(blob, table)
        if len(fields) < 15 or not all(fields[slot] for slot in range(15)):
            continue

        def text(slot: int) -> str:
            return _encrypted_string(blob, table + fields[slot])

        identifier = text(2).strip()       # NameKR is the native AAP identifier.
        name = text(8).strip()             # NameTW shown in AA's character picker.
        if not identifier or not name:
            continue
        rows.append({
            "identifier": identifier,
            "name": name,
            "club": text(9).strip(),
            "spine": text(13).strip(),
            "avatar": text(14).strip(),
            "native_key": _u32(blob, table + fields[0]) ^ CHARACTER_NAME_UINT_KEY,
            "shape": _u32(blob, table + fields[1]) ^ CHARACTER_NAME_UINT_KEY,
        })
    return rows


def read_character_table_bundle(data_path: str | Path) -> list[dict]:
    """Read AA's official ``ScenarioCharacterNameExcel`` without changing AA."""
    return _decode_character_table(
        _text_asset_bytes(Path(data_path), "scenariocharacternameexceltable")
    )


def _catalog_entries(encoded: str) -> dict[int, tuple[int, ...]]:
    """Read Addressables' compact 7-int ResourceLocation records."""
    return _catalog_entries_raw(base64.b64decode(encoded))


def _catalog_entry_rows_raw(raw: bytes) -> tuple[tuple[int, ...], ...]:
    count = _u32(raw, 0)
    expected = 4 + count * 28
    if len(raw) < expected:
        raise ValueError("truncated Addressables entry table")
    return tuple(
        struct.unpack_from("<7i", raw, 4 + index * 28)
        for index in range(count)
    )


def _catalog_entries_raw(raw: bytes) -> dict[int, tuple[int, ...]]:
    return {row[0]: row for row in _catalog_entry_rows_raw(raw)}


def _catalog_buckets_raw(raw: bytes) -> tuple[tuple[int, ...], ...]:
    """Decode key buckets whose entries are ResourceLocation row indexes."""
    count = _u32(raw, 0)
    offset = 4
    buckets: list[tuple[int, ...]] = []
    for _ in range(count):
        if offset + 8 > len(raw):
            raise ValueError("truncated Addressables bucket table")
        # The first value points into m_KeyDataString. It is not needed when
        # resolving a ResourceLocation's already-known dependency key index.
        _key_data_offset = _i32(raw, offset)
        entry_count = _i32(raw, offset + 4)
        offset += 8
        if entry_count < 0 or offset + entry_count * 4 > len(raw):
            raise ValueError("invalid Addressables bucket entry count")
        buckets.append(tuple(
            _i32(raw, offset + index * 4)
            for index in range(entry_count)
        ))
        offset += entry_count * 4
    return tuple(buckets)


def _bundle_options(encoded: str, offset: int) -> dict:
    return _bundle_options_raw(base64.b64decode(encoded), offset)


def _bundle_options_raw(raw: bytes, offset: int) -> dict:
    json_start = raw.index(b"{\x00", offset)
    size = _u32(raw, json_start - 4)
    return json.loads(raw[json_start:json_start + size].decode("utf-16-le"))


def _cached_bundle_path(
    cache_root: Path,
    bundle_name: str,
    content_hash: str,
) -> Path | None:
    bundle_root = cache_root / bundle_name
    exact = bundle_root / content_hash / "__data"
    if exact.is_file():
        return exact
    cached = sorted(bundle_root.glob("*/__data")) if bundle_root.is_dir() else []
    return cached[0] if len(cached) == 1 else None


def catalog_bundle_locations(
    catalog_path: str | Path,
    cache_root: str | Path,
    *,
    internal_predicate: Callable[[str], bool],
) -> tuple[CatalogBundleLocation, ...]:
    """Map selected Addressables internal IDs to local cache bundles."""
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8-sig"))
    internal_ids = catalog["m_InternalIds"]
    entry_rows = _catalog_entry_rows_raw(
        base64.b64decode(catalog["m_EntryDataString"])
    )
    entries = {row[0]: row for row in entry_rows}
    extra_data = base64.b64decode(catalog["m_ExtraDataString"])
    bucket_data = catalog.get("m_BucketDataString")
    buckets = (
        _catalog_buckets_raw(base64.b64decode(bucket_data))
        if bucket_data else ()
    )
    selected: list[CatalogBundleLocation] = []
    seen: set[tuple[str, str]] = set()
    for internal_index, internal_id in enumerate(internal_ids):
        if not internal_predicate(internal_id):
            continue
        entry = entries.get(internal_index)
        if entry is None:
            continue
        dependency_key_index = entry[2]
        bundle_candidates: list[tuple[int, ...]] = []
        if 0 <= dependency_key_index < len(buckets):
            for location_index in buckets[dependency_key_index]:
                if 0 <= location_index < len(entry_rows):
                    candidate = entry_rows[location_index]
                    candidate_id = str(internal_ids[candidate[0]])
                    if candidate_id.casefold().endswith(".bundle"):
                        bundle_candidates.append(candidate)
        elif dependency_key_index >= 0:
            # Compatibility with early local fixtures and catalogs where the
            # dependency field directly referenced an internal ID.
            candidate = entries.get(dependency_key_index)
            if candidate is not None:
                bundle_candidates.append(candidate)
        elif internal_id.casefold().endswith(".bundle"):
            bundle_candidates.append(entry)
        if not bundle_candidates:
            continue
        bundle_entry = bundle_candidates[0]
        if bundle_entry[4] < 0:
            continue
        options = _bundle_options_raw(extra_data, bundle_entry[4])
        bundle_name = str(options["m_BundleName"])
        content_hash = str(options["m_Hash"])
        bundle_key = (bundle_name, content_hash)
        if bundle_key in seen:
            continue
        seen.add(bundle_key)
        selected.append(
            CatalogBundleLocation(
                internal_id=internal_id,
                bundle_name=bundle_name,
                content_hash=content_hash,
                data_path=_cached_bundle_path(
                    Path(cache_root), bundle_name, content_hash
                ),
            )
        )
    return tuple(selected)


def locate_character_table_bundle(catalog_path: str | Path, cache_root: str | Path) -> Path:
    """Resolve AA's character-name FlatData bundle through its catalog.

    The cache folder names are version hashes and change when AA updates, so
    this intentionally reads the local Addressables catalog instead of using a
    fixed cache path.
    """
    locations = catalog_bundle_locations(
        catalog_path,
        cache_root,
        internal_predicate=lambda value: value.casefold().endswith(
            "scenariocharacternameexceltable.bytes"
        ),
    )
    if locations and locations[0].data_path is not None:
        return locations[0].data_path
    bundle_root = (
        Path(cache_root) / locations[0].bundle_name
        if locations else Path(cache_root)
    )
    raise FileNotFoundError(
        f"AA 缓存缺少或无法唯一确定官方角色表 bundle: {bundle_root}"
    )


def select_native_characters(rows: list[dict], observed_identifiers=()) -> list[dict]:
    """Return only native identifiers proved by AA's own name-table hash.

    AAP stores a Korean identifier, while the FlatData row stores its xxHash32
    key.  Canonical NameKR values and identifiers observed in existing AAPs can
    therefore be matched exactly, including variants such as ``아리스N``.
    """
    from tables import xxh32

    candidates = {str(value) for value in observed_identifiers}
    candidates.update(row["identifier"] for row in rows)
    by_hash = {xxh32(identifier): identifier for identifier in candidates if identifier}
    selected = []
    used = set()
    for row in rows:
        identifier = by_hash.get(row["native_key"])
        if not identifier or identifier in used:
            continue
        selected.append({
            "identifier": identifier,
            "name": row["name"],
            "club": row["club"],
            "spine": row["spine"],
            "avatar": row["avatar"],
            "source": "official_flatdata",
        })
        used.add(identifier)
    return selected
