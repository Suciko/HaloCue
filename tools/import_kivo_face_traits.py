# -*- coding: utf-8 -*-
"""Audit or import objective eye/mouth traits from face_table_kivo.json.

The Kivo descriptions are useful as visual evidence, but their emotion wording
is repetitive and must not replace the richer semantics in aa_assets.db.
This importer therefore fills only blank objective fields and defaults to a
read-only dry run.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Mapping


_SPINE_FACE = re.compile(
    r"^(?P<base>.+?)_spr[-_](?P<face>\d{2}|99)(?:_|$)", re.IGNORECASE
)
_PLAIN_FACE = re.compile(
    r"^(?P<base>.+?)[-_](?P<face>\d{2}|99)(?:_|$)", re.IGNORECASE
)


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def parse_asset_face_key(value: object) -> tuple[str, str] | None:
    """Return a conservative (skeleton base, face id) pair."""
    text = str(value or "").strip()
    match = _SPINE_FACE.match(text)
    if not match and "_spr_" in text.casefold():
        return None
    match = match or _PLAIN_FACE.match(text)
    if not match:
        return None
    base = _key(match.group("base"))
    return (base, match.group("face").zfill(2)) if base else None


def extract_visual_traits(description: object) -> dict[str, str]:
    """Extract only high-confidence visible traits, never inferred emotion."""
    text = re.sub(r"\s+", "", str(description or ""))
    result: dict[str, str] = {}
    if re.search(r"闭着眼|闭上(?:双)?眼|双眼紧闭|闭眼|闭目", text):
        result["eyes"] = "闭眼"
    elif re.search(r"眨眼|单眼闭合|一只眼.*闭", text):
        result["eyes"] = "单眼闭合"
    elif re.search(r"眯着眼|眯眼|眼睛微眯|微微眯起|半闭眼", text):
        result["eyes"] = "半闭眼"
    elif re.search(r"瞪大眼|睁得(?:很|大|圆)|睁大|眼睛睁", text):
        result["eyes"] = "睁眼"

    if re.search(r"张大嘴|大张嘴", text):
        result["mouth"] = "大张嘴"
    elif re.search(r"嘴巴微张|嘴微张|微微张开|嘴角微张", text):
        result["mouth"] = "微张嘴"
    elif re.search(r"张嘴", text):
        result["mouth"] = "张嘴"
    elif re.search(r"嘴角下撇|撇嘴", text):
        result["mouth"] = "嘴角下撇"
    elif re.search(r"嘴角(?:微微)?上扬|嘴角微扬", text):
        result["mouth"] = "嘴角上扬"
    elif re.search(r"抿嘴|紧抿|嘴巴紧闭|闭嘴", text):
        result["mouth"] = "闭嘴"
    return result


def _outfit_aliases(outfit: object) -> set[str]:
    value = str(outfit or "").replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"^CharacterSpine_", "", value, flags=re.IGNORECASE)
    value = re.sub(r"_spr$", "", value, flags=re.IGNORECASE)
    aliases = {_key(value)}
    for suffix in ("noweapon", "weapon", "normal"):
        if value.casefold().endswith("_" + suffix):
            aliases.add(_key(value[: -(len(suffix) + 1)]))
    return {alias for alias in aliases if alias}


def import_kivo_traits(
    con: sqlite3.Connection,
    source: Mapping,
    *,
    apply: bool = False,
) -> dict[str, int]:
    """Match exact skeleton aliases and fill blank eye/mouth columns."""
    scopes_by_alias: dict[str, set[tuple[str, str, str]]] = {}
    for row in con.execute(
        "SELECT ident,spine_signature,outfit_key FROM character_variant"
    ):
        scope = (str(row[0]), str(row[1]), str(row[2]))
        for alias in _outfit_aliases(row[2]):
            scopes_by_alias.setdefault(alias, set()).add(scope)

    candidates: dict[tuple[str, str, str, str], dict[str, str]] = {}
    parsed_faces = 0
    for character in source.values():
        if not isinstance(character, Mapping):
            continue
        for outfit in character.values():
            if not isinstance(outfit, Mapping):
                continue
            for asset_key, description in outfit.items():
                parsed = parse_asset_face_key(asset_key)
                if not parsed:
                    continue
                parsed_faces += 1
                base, face_id = parsed
                traits = extract_visual_traits(description)
                if not traits:
                    continue
                for scope in scopes_by_alias.get(base, ()):
                    candidates.setdefault((*scope, face_id), {}).update(traits)

    matched_faces = 0
    rows_to_update: list[tuple[tuple[str, str, str, str], dict[str, str]]] = []
    for scope, traits in candidates.items():
        rows = con.execute(
            """
            SELECT eyes,mouth FROM face_visual_label
            WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
            """,
            scope,
        ).fetchall()
        if not rows:
            continue
        matched_faces += 1
        if any(
            (traits.get("eyes") and not str(row[0] or "").strip())
            or (traits.get("mouth") and not str(row[1] or "").strip())
            for row in rows
        ):
            rows_to_update.append((scope, traits))

    updated_rows = 0
    if apply:
        for scope, traits in rows_to_update:
            cursor = con.execute(
                """
                UPDATE face_visual_label
                SET eyes=CASE WHEN TRIM(COALESCE(eyes,''))='' THEN ? ELSE eyes END,
                    mouth=CASE WHEN TRIM(COALESCE(mouth,''))='' THEN ? ELSE mouth END
                WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
                  AND ((?<>'' AND TRIM(COALESCE(eyes,''))='')
                    OR (?<>'' AND TRIM(COALESCE(mouth,''))=''))
                """,
                (
                    traits.get("eyes", ""), traits.get("mouth", ""), *scope,
                    traits.get("eyes", ""), traits.get("mouth", ""),
                ),
            )
            updated_rows += max(0, int(cursor.rowcount or 0))
        con.commit()

    return {
        "parsed_faces": parsed_faces,
        "matched_faces": matched_faces,
        "fillable_faces": len(rows_to_update),
        "updated_rows": updated_rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="审计或导入 Kivo 表情表中的客观眼睛/嘴型字段"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--db", type=Path, default=Path("aa_assets.db"))
    parser.add_argument("--apply", action="store_true", help="写入空字段；默认只审计")
    args = parser.parse_args(argv)

    source = json.loads(args.source.read_text(encoding="utf-8"))
    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.db.with_name(f"{args.db.name}.pre-kivo-{stamp}.bak")
        shutil.copy2(args.db, backup)
        print(f"数据库备份: {backup}")
    con = sqlite3.connect(args.db)
    try:
        report = import_kivo_traits(con, source, apply=args.apply)
    finally:
        con.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
