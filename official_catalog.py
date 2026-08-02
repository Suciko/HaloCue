# -*- coding: utf-8 -*-
"""Read verified native-character labels from AA's FlatData bundle."""
import base64
import json
import struct
from pathlib import Path


# Extracted from AA's local ScenarioCharacterNameExcel table.  The first four
# bytes are the table's uint-XOR key; the full key decrypts its UTF-16 strings.
CHARACTER_NAME_KEY = bytes.fromhex("268bd50b5cce8633")
CHARACTER_NAME_UINT_KEY = int.from_bytes(CHARACTER_NAME_KEY[:4], "little")


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
    raw = base64.b64decode(encoded)
    count = (len(raw) - 4) // 28
    rows = (struct.unpack_from("<7i", raw, 4 + index * 28) for index in range(count))
    return {row[0]: row for row in rows}


def _bundle_options(encoded: str, offset: int) -> dict:
    raw = base64.b64decode(encoded)
    json_start = raw.index(b"{\x00", offset)
    size = _u32(raw, json_start - 4)
    return json.loads(raw[json_start:json_start + size].decode("utf-16-le"))


def locate_character_table_bundle(catalog_path: str | Path, cache_root: str | Path) -> Path:
    """Resolve AA's character-name FlatData bundle through its catalog.

    The cache folder names are version hashes and change when AA updates, so
    this intentionally reads the local Addressables catalog instead of using a
    fixed cache path.
    """
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    internal = catalog["m_InternalIds"]
    target = next(
        index for index, value in enumerate(internal)
        if value.lower().endswith("scenariocharacternameexceltable.bytes")
    )
    entries = _catalog_entries(catalog["m_EntryDataString"])
    table_entry = entries[target]
    bundle_internal_index = table_entry[2]
    bundle_entry = entries[bundle_internal_index]
    options = _bundle_options(catalog["m_ExtraDataString"], bundle_entry[4])
    bundle_root = Path(cache_root) / options["m_BundleName"]
    path = bundle_root / options["m_Hash"] / "__data"
    if path.is_file():
        return path

    # AA's Unity cache can retain a valid current entry under its own cache
    # version hash rather than the catalog content hash.  Use it only when the
    # bundle-name directory has one unambiguous cached version.
    cached = sorted(bundle_root.glob("*/__data")) if bundle_root.is_dir() else []
    if len(cached) == 1:
        return cached[0]
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
