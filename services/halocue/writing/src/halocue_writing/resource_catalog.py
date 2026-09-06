"""Independent HaloCue 1.0 resource catalog.

The 1.0 writing domain owns a compact, metadata-only SQLite catalog.  A 0.95
database can be imported explicitly, but is never opened as a runtime
dependency and is never written back to.
"""

from __future__ import annotations

import json
import re
import sqlite3
import copy
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

from .repository import canonical_json, now, sha256_text


SCHEMA_VERSION = "resource-catalog/1.0"
_MAX_QUERY = 120
_DEFAULT_LIMIT = 24


SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backgrounds (
  key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  place TEXT NOT NULL DEFAULT '',
  indoor_outdoor TEXT NOT NULL DEFAULT '',
  time TEXT NOT NULL DEFAULT '',
  weather TEXT NOT NULL DEFAULT '',
  season TEXT NOT NULL DEFAULT '',
  mood TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '',
  search_terms_json TEXT NOT NULL DEFAULT '[]',
  visual_kind TEXT NOT NULL DEFAULT 'background',
  main_category TEXT NOT NULL DEFAULT '',
  affiliation_json TEXT NOT NULL DEFAULT '[]',
  reuse_scope TEXT NOT NULL DEFAULT '',
  category_path TEXT NOT NULL DEFAULT '',
  usage_hint TEXT NOT NULL DEFAULT '',
  avoid_when TEXT NOT NULL DEFAULT '',
  dialogue_suitable INTEGER NOT NULL DEFAULT 1,
  has_fixed_characters INTEGER NOT NULL DEFAULT 0,
  annotation_json TEXT NOT NULL DEFAULT '{}',
  source_kind TEXT NOT NULL DEFAULT 'halocue-1.0',
  source_version TEXT NOT NULL DEFAULT '',
  source_row_hash TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
  key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  club TEXT NOT NULL DEFAULT '',
  spine TEXT NOT NULL DEFAULT '',
  avatar TEXT NOT NULL DEFAULT '',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  canonical_name TEXT NOT NULL DEFAULT '',
  preferred_name TEXT NOT NULL DEFAULT '',
  identity_aliases_json TEXT NOT NULL DEFAULT '[]',
  spine_key TEXT NOT NULL DEFAULT '',
  manifest_bound INTEGER NOT NULL DEFAULT 0,
  user_custom INTEGER NOT NULL DEFAULT 0,
  manifest_only INTEGER NOT NULL DEFAULT 0,
  source_kind TEXT NOT NULL DEFAULT 'halocue-1.0',
  source_version TEXT NOT NULL DEFAULT '',
  source_row_hash TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS character_variants (
  character_key TEXT NOT NULL,
  spine_signature TEXT NOT NULL DEFAULT '',
  outfit_key TEXT NOT NULL DEFAULT '',
  spine TEXT NOT NULL DEFAULT '',
  source_kind TEXT NOT NULL DEFAULT 'halocue-1.0',
  source_version TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(character_key, spine_signature, outfit_key)
);
CREATE TABLE IF NOT EXISTS faces (
  character_key TEXT NOT NULL,
  spine_signature TEXT NOT NULL DEFAULT '',
  outfit_key TEXT NOT NULL DEFAULT '',
  face_id TEXT NOT NULL,
  raw TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  label_cn TEXT NOT NULL DEFAULT '',
  semantic_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '{}',
  observed_count INTEGER NOT NULL DEFAULT 0,
  official_usage_count INTEGER NOT NULL DEFAULT 0,
  model TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  reviewed INTEGER NOT NULL DEFAULT 0,
  source_kind TEXT NOT NULL DEFAULT 'halocue-1.0',
  source_version TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(character_key, spine_signature, outfit_key, face_id)
);
CREATE TABLE IF NOT EXISTS expression_parts (
  character_key TEXT NOT NULL,
  spine_signature TEXT NOT NULL DEFAULT '',
  outfit_key TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL,
  raw_name TEXT NOT NULL,
  labels_json TEXT NOT NULL DEFAULT '[]',
  source_kind TEXT NOT NULL DEFAULT 'halocue-1.0',
  source_version TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(character_key, spine_signature, outfit_key, kind, raw_name, source_kind)
);
CREATE TABLE IF NOT EXISTS resource_overrides (
  kind TEXT NOT NULL,
  resource_key TEXT NOT NULL,
  patch_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(kind, resource_key)
);
CREATE TABLE IF NOT EXISTS migration_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_manifest_json TEXT NOT NULL,
  imported_json TEXT NOT NULL,
  imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backgrounds_search ON backgrounds(label, place, mood, tags_json, search_terms_json);
CREATE INDEX IF NOT EXISTS idx_characters_search ON characters(display_name, club, spine);
CREATE INDEX IF NOT EXISTS idx_faces_search ON faces(character_key, label_cn, label, raw);
"""


MIGRATION_COLUMNS = {
    "backgrounds": {
        "visual_kind": "TEXT NOT NULL DEFAULT 'background'",
        "main_category": "TEXT NOT NULL DEFAULT ''",
        "affiliation_json": "TEXT NOT NULL DEFAULT '[]'",
        "reuse_scope": "TEXT NOT NULL DEFAULT ''",
        "category_path": "TEXT NOT NULL DEFAULT ''",
        "usage_hint": "TEXT NOT NULL DEFAULT ''",
        "avoid_when": "TEXT NOT NULL DEFAULT ''",
        "dialogue_suitable": "INTEGER NOT NULL DEFAULT 1",
        "has_fixed_characters": "INTEGER NOT NULL DEFAULT 0",
        "annotation_json": "TEXT NOT NULL DEFAULT '{}'",
    },
    "characters": {
        "aliases_json": "TEXT NOT NULL DEFAULT '[]'",
        "canonical_name": "TEXT NOT NULL DEFAULT ''",
        "preferred_name": "TEXT NOT NULL DEFAULT ''",
        "identity_aliases_json": "TEXT NOT NULL DEFAULT '[]'",
        "spine_key": "TEXT NOT NULL DEFAULT ''",
        "manifest_bound": "INTEGER NOT NULL DEFAULT 0",
        "user_custom": "INTEGER NOT NULL DEFAULT 0",
        "manifest_only": "INTEGER NOT NULL DEFAULT 0",
    },
    "character_variants": {"source_kind": "TEXT NOT NULL DEFAULT 'halocue-1.0'"},
    "faces": {
        "observed_count": "INTEGER NOT NULL DEFAULT 0",
        "official_usage_count": "INTEGER NOT NULL DEFAULT 0",
        "model": "TEXT NOT NULL DEFAULT ''",
        "confidence": "REAL NOT NULL DEFAULT 0",
        "reviewed": "INTEGER NOT NULL DEFAULT 0",
    },
}


OVERRIDE_FIELDS = {
    "background": {
        "display_name", "place", "indoor_outdoor", "time", "weather", "season", "mood",
        "tags", "description", "visual_kind", "main_category", "affiliations", "reuse_scope",
        "category_path", "usage_hint", "avoid_when", "dialogue_suitable", "has_fixed_characters",
    },
    "character": {"display_name", "club", "aliases"},
    "face": {"label", "label_cn", "semantic"},
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            parsed = []
        return parsed if isinstance(parsed, list) else []
    return []


def _terms(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            result.extend(_text(item) for item in value)
        else:
            result.extend(re.split(r"[\s,，、/|]+", _text(value)))
    return list(dict.fromkeys(item for item in result if item))


def _name_key(value: Any) -> str:
    """Normalize a local character name without making the catalog depend on 0.95."""
    return "".join(_text(value).casefold().split())


def _spine_key(value: Any) -> str:
    normalized = _text(value).replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1].casefold() if normalized else ""


def _read_character_alias_index(path: Path | None) -> list[dict]:
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = payload.get("characters") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    result: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical = _text(row.get("canonical_name"))
        aliases = [
            _text(value) for value in row.get("aliases") or [] if _text(value)
        ]
        if canonical:
            result.append({"canonical_name": canonical, "aliases": list(dict.fromkeys(aliases))})
    return result


def _read_manifest_characters(path: Path | None) -> list[dict]:
    """Read an AA manifest as an optional, read-only identity overlay."""
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    rows = payload.get("CharacterOverrides") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    selected: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = _text(row.get("Identifier"))
        if not identifier:
            continue
        selected[identifier] = {
            "identifier": identifier,
            "display_name": _text(row.get("Name")),
            "nickname": _text(row.get("Nickname")),
            "spine": _text(row.get("SpinePortraitPath")),
            "avatar": _text(row.get("SmallPortraitPath")),
        }
    return list(selected.values())


def _annotation_extras(payload: dict, known: set[str]) -> dict:
    return {key: value for key, value in payload.items() if key not in known and value not in (None, "", [], {})}


def _background_display_name(row: sqlite3.Row) -> str:
    """Keep export/file identifiers out of the ordinary resource picker."""
    label = _text(row["label"] or row["display_name"])
    semantic = next(
        (
            _text(row[key])
            for key in ("place", "main_category", "category_path")
            if _text(row[key])
        ),
        "",
    )
    technical = bool(
        re.fullmatch(r"\d{3,}-\d+", label)
        or re.match(r"(?:BG|ComfyUI|ChatGPT Image)[_ -]", label, re.IGNORECASE)
    )
    if technical and semantic:
        return semantic
    if technical:
        return "未命名背景"
    return label or "未命名背景"


def _looks_like_custom_background_key(value: Any) -> bool:
    key = _text(value).casefold()
    return bool(
        key.startswith(("chatgpt image", "comfyui_", "gemini_generated_image_", "img_"))
        or re.fullmatch(r"\d+", key)
        or re.fullmatch(r"\d{3,}-\d+", key)
        or (len(key) >= 20 and re.fullmatch(r"[0-9a-f]+", key))
    )


def _looks_like_cg_key(value: Any) -> bool:
    return _text(value).casefold().startswith("bg_cs_")


class ResourceCatalog:
    """Owns the 1.0 resource metadata database and its public projection."""

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir).resolve() / "resource-catalog"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "halocue-1.0.db"
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            for table, columns in MIGRATION_COLUMNS.items():
                existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                for column, declaration in columns.items():
                    if column not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
            connection.execute(
                "INSERT OR IGNORE INTO catalog_meta(key,value) VALUES('schema_version',?)",
                (SCHEMA_VERSION,),
            )
            connection.commit()

    def descriptor(self) -> dict:
        with closing(self._connect()) as connection:
            counts = {
                "backgrounds": connection.execute(
                    """SELECT COUNT(*) FROM backgrounds
                       WHERE COALESCE(NULLIF(LOWER(TRIM(visual_kind)), ''), 'background')='background'"""
                ).fetchone()[0],
                "characters": connection.execute("SELECT COUNT(*) FROM characters").fetchone()[0],
                "variants": connection.execute("SELECT COUNT(*) FROM character_variants").fetchone()[0],
                "faces": connection.execute("SELECT COUNT(*) FROM faces").fetchone()[0],
                "expression_parts": connection.execute("SELECT COUNT(*) FROM expression_parts").fetchone()[0],
                "user_overrides": connection.execute("SELECT COUNT(*) FROM resource_overrides").fetchone()[0],
            }
            source = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='source_manifest'"
            ).fetchone()
        return {
            "schema_version": SCHEMA_VERSION,
            "catalog": "HaloCue 1.0 资源库",
            "storage": "local_read_only_base_with_user_overrides",
            "counts": counts,
            "source_manifest": _json_object(source[0] if source else ""),
            "ready": any(counts.values()),
        }

    @staticmethod
    def _override(connection: sqlite3.Connection, kind: str, key: str) -> dict:
        row = connection.execute(
            "SELECT patch_json FROM resource_overrides WHERE kind=? AND resource_key=?",
            (kind, key),
        ).fetchone()
        return _json_object(row[0] if row else "")

    @staticmethod
    def _apply_override(item: dict, patch: dict) -> dict:
        if not patch:
            return item
        merged = dict(item)
        for key, value in patch.items():
            if key != "technical":
                merged[key] = value
        merged["user_corrected"] = True
        return merged

    @staticmethod
    def _public_background(row: sqlite3.Row) -> dict:
        return {
            "kind": "background",
            "display_name": _background_display_name(row),
            "place": row["place"],
            "indoor_outdoor": row["indoor_outdoor"],
            "time": row["time"],
            "weather": row["weather"],
            "season": row["season"],
            "mood": row["mood"],
            "tags": _json_list(row["tags_json"]),
            "description": row["description"],
            "visual_kind": row["visual_kind"],
            "main_category": row["main_category"],
            "affiliations": _json_list(row["affiliation_json"]),
            "reuse_scope": row["reuse_scope"],
            "category_path": row["category_path"],
            "usage_hint": row["usage_hint"],
            "avoid_when": row["avoid_when"],
            "dialogue_suitable": bool(row["dialogue_suitable"]),
            "has_fixed_characters": bool(row["has_fixed_characters"]),
            "annotation": _json_object(row["annotation_json"]),
            "technical": {"key": row["key"], "source_version": row["source_version"]},
        }

    @staticmethod
    def _public_character(row: sqlite3.Row) -> dict:
        return {
            "kind": "character",
            "display_name": row["display_name"],
            "canonical_name": row["canonical_name"] or row["display_name"],
            "preferred_name": row["preferred_name"] or row["display_name"],
            "club": row["club"],
            "aliases": _json_list(row["aliases_json"]),
            "identity_aliases": _json_list(row["identity_aliases_json"]),
            "avatar_available": bool(row["avatar"]),
            "available": True,
            "manifest_bound": bool(row["manifest_bound"]),
            "user_custom": bool(row["user_custom"]),
            "manifest_only": bool(row["manifest_only"]),
            "technical": {
                "key": row["key"],
                "spine_key": row["spine_key"],
                "source_version": row["source_version"],
            },
        }

    @staticmethod
    def _public_face(row: sqlite3.Row) -> dict:
        return {
            "kind": "face",
            "character_name": row["character_name"] or row["character_key"],
            "outfit": row["outfit_key"],
            "label": row["label_cn"] or row["label"] or row["raw"] or row["face_id"],
            "semantic": _json_object(row["semantic_json"]),
            "evidence": _json_object(row["evidence_json"]),
            "available": True,
            "technical": {
                "character_key": row["character_key"],
                "spine_signature": row["spine_signature"],
                "outfit_key": row["outfit_key"],
                "face_id": row["face_id"],
                "model": row["model"],
                "confidence": float(row["confidence"] or 0),
                "reviewed": bool(row["reviewed"]),
                "source_version": row["source_version"],
            },
        }

    def search(self, kind: str, query: str = "", limit: int = _DEFAULT_LIMIT) -> dict:
        normalized_kind = _text(kind).lower() or "backgrounds"
        if normalized_kind in {"background", "bg", "backgrounds"}:
            normalized_kind = "backgrounds"
        elif normalized_kind in {"character", "characters"}:
            normalized_kind = "characters"
        elif normalized_kind in {"face", "faces", "expression", "expressions"}:
            normalized_kind = "faces"
        else:
            raise ValueError("unsupported resource kind")
        term = _text(query)[:_MAX_QUERY]
        bounded = max(1, min(int(limit or _DEFAULT_LIMIT), 80))
        pattern = f"%{term}%"
        filter_term = {"室内": "indoor", "室外": "outdoor", "白天": "day", "夜晚": "night"}.get(term, term)
        filter_pattern = f"%{filter_term}%"
        with closing(self._connect()) as connection:
            if normalized_kind == "backgrounds":
                rows = connection.execute(
                    """SELECT * FROM backgrounds
                       WHERE COALESCE(NULLIF(LOWER(TRIM(visual_kind)), ''), 'background')='background'
                         AND (?='' OR key LIKE ? OR display_name LIKE ? OR label LIKE ?
                         OR place LIKE ? OR indoor_outdoor LIKE ? OR indoor_outdoor LIKE ?
                         OR time LIKE ? OR time LIKE ? OR weather LIKE ?
                         OR season LIKE ? OR mood LIKE ? OR tags_json LIKE ? OR search_terms_json LIKE ?
                         OR main_category LIKE ? OR affiliation_json LIKE ? OR category_path LIKE ?
                         OR annotation_json LIKE ?)
                       ORDER BY
                         CASE WHEN ?<>'' AND (key=? OR display_name=? OR label=?) THEN 0 ELSE 1 END,
                         CASE
                           WHEN (
                             label GLOB '[0-9]*-[0-9]*'
                             OR UPPER(label) LIKE 'BG[_ -]%'
                             OR label LIKE 'ComfyUI[_ -]%'
                             OR label LIKE 'ChatGPT Image%'
                           )
                           AND TRIM(COALESCE(place, ''))=''
                           AND TRIM(COALESCE(main_category, ''))=''
                           AND TRIM(COALESCE(category_path, ''))=''
                           THEN 1 ELSE 0
                         END,
                         label, key LIMIT ?""",
                    (term, pattern, pattern, pattern, pattern, pattern, filter_pattern, pattern,
                     filter_pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern,
                     pattern, pattern, term, term, term, term, bounded),
                ).fetchall()
                items = [self._apply_override(self._public_background(row), self._override(connection, "background", row["key"])) for row in rows]
            elif normalized_kind == "characters":
                rows = connection.execute(
                    """SELECT * FROM characters
                       WHERE ?='' OR key LIKE ? OR display_name LIKE ? OR canonical_name LIKE ? OR preferred_name LIKE ?
                         OR club LIKE ? OR spine LIKE ? OR aliases_json LIKE ? OR identity_aliases_json LIKE ?
                       ORDER BY CASE WHEN display_name=? THEN 0 ELSE 1 END, display_name, key LIMIT ?""",
                    (term, pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern, term, bounded),
                ).fetchall()
                items = []
                for row in rows:
                    item = self._apply_override(self._public_character(row), self._override(connection, "character", row["key"]))
                    variants = connection.execute(
                        """SELECT character_variants.outfit_key, COUNT(faces.face_id) AS face_count
                           FROM character_variants LEFT JOIN faces
                             ON faces.character_key=character_variants.character_key
                            AND faces.spine_signature=character_variants.spine_signature
                            AND faces.outfit_key=character_variants.outfit_key
                           WHERE character_variants.character_key=?
                           GROUP BY character_variants.outfit_key
                           ORDER BY character_variants.outfit_key""",
                        (row["key"],),
                    ).fetchall()
                    item["outfits"] = [
                        {"name": variant["outfit_key"] or "默认服装", "face_count": int(variant["face_count"] or 0)}
                        for variant in variants
                    ]
                    items.append(item)
            else:
                rows = connection.execute(
                    """SELECT faces.*, characters.display_name AS character_name
                       FROM faces LEFT JOIN characters ON characters.key=faces.character_key
                       WHERE ?='' OR faces.character_key LIKE ? OR characters.display_name LIKE ?
                         OR faces.label LIKE ? OR faces.label_cn LIKE ? OR faces.raw LIKE ? OR faces.semantic_json LIKE ?
                       ORDER BY characters.display_name,
                                CASE WHEN faces.outfit_key='' THEN 1 ELSE 0 END,
                                faces.outfit_key,
                                CASE WHEN faces.official_usage_count > 0 OR faces.semantic_json <> '{}' THEN 0 ELSE 1 END,
                                faces.face_id LIMIT ?""",
                    (term, pattern, pattern, pattern, pattern, pattern, pattern, bounded),
                ).fetchall()
                items = []
                for row in rows:
                    override_key = "|".join((row["character_key"], row["spine_signature"], row["outfit_key"], row["face_id"]))
                    items.append(self._apply_override(self._public_face(row), self._override(connection, "face", override_key)))
        return {"schema_version": SCHEMA_VERSION, "kind": normalized_kind, "query": term, "items": items}

    def lookup(self, kind: str, keys: list[str]) -> dict:
        """Return the best user-facing metadata for a bounded set of asset keys.

        Production snapshots use AA's exact key casing while the writing catalog
        may contain a raw row and a separately annotated, differently-cased row.
        Prefer the annotated row without changing the identity returned by the
        production service.
        """
        normalized_kind = _text(kind).lower() or "backgrounds"
        if normalized_kind in {"background", "bg", "backgrounds"}:
            normalized_kind = "backgrounds"
        else:
            raise ValueError("unsupported resource kind")
        requested = list(dict.fromkeys(_text(key) for key in keys if _text(key)))[:200]
        if not requested:
            return {"schema_version": SCHEMA_VERSION, "kind": normalized_kind, "items": []}

        def score(item: dict, requested_key: str) -> tuple[int, int, int, int, int, str]:
            text = " ".join(
                _text(item.get(field))
                for field in ("display_name", "label", "place", "main_category", "category_path", "description")
            )
            chinese = len(re.findall(r"[\u3400-\u9fff]", text))
            semantic = sum(bool(_text(item.get(field))) for field in ("place", "main_category", "category_path", "description"))
            readable_name = int(_text(item.get("display_name")).casefold() not in {"", requested_key.casefold()})
            annotation = item.get("annotation")
            annotation_score = int(bool(annotation)) if isinstance(annotation, (dict, list, str)) else 0
            return (chinese, semantic, readable_name, int(bool(_text(item.get("label")))), annotation_score, str(item.get("technical", {}).get("key") or ""))

        lowered = {key.casefold(): key for key in requested}
        with closing(self._connect()) as connection:
            placeholders = ",".join("?" for _ in lowered)
            rows = connection.execute(
                f"SELECT * FROM backgrounds WHERE LOWER(key) IN ({placeholders})",
                tuple(lowered),
            ).fetchall()
            candidates: dict[str, list[dict]] = {}
            for row in rows:
                item = self._apply_override(self._public_background(row), self._override(connection, "background", row["key"]))
                candidates.setdefault(str(row["key"]).casefold(), []).append(item)
        items = []
        for lowered_key, requested_key in lowered.items():
            choices = candidates.get(lowered_key, [])
            if choices:
                items.append({"requested_key": requested_key, **max(choices, key=lambda item: score(item, requested_key))})
        return {"schema_version": SCHEMA_VERSION, "kind": normalized_kind, "items": items}

    def facets(self, kind: str) -> dict:
        normalized_kind = _text(kind).lower() or "backgrounds"
        if normalized_kind in {"background", "bg", "backgrounds"}:
            normalized_kind = "backgrounds"
        else:
            raise ValueError("unsupported resource kind")
        counts: dict[str, int] = {}
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT main_category, indoor_outdoor, category_path
                   FROM backgrounds
                   WHERE COALESCE(NULLIF(LOWER(TRIM(visual_kind)), ''), 'background')='background'"""
            ).fetchall()
        for row in rows:
            labels = {_text(row["main_category"])}
            labels.discard("")
            indoor = _text(row["indoor_outdoor"]).casefold()
            labels.add({"indoor": "室内", "outdoor": "室外"}.get(indoor, ""))
            path = _text(row["category_path"])
            if path:
                labels.add(path.split("/")[-1].strip())
            for label in labels - {""}:
                # English export labels are implementation details. They may
                # remain searchable, but should not become visible categories.
                if not re.search(r"[\u3400-\u9fff]", label):
                    continue
                counts[label] = counts.get(label, 0) + 1
        preferred = ["校园", "室内", "室外", "自然", "街道", "商业", "交通", "活动"]
        ordered = sorted(counts.items(), key=lambda pair: (preferred.index(pair[0]) if pair[0] in preferred else len(preferred), -pair[1], pair[0]))
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": normalized_kind,
            "categories": [{"label": label, "count": count} for label, count in ordered[:12]],
        }

    def save_override(self, kind: str, resource_key: str, patch: dict, expected_version: int | None = None) -> dict:
        normalized_kind = _text(kind).lower()
        if normalized_kind not in OVERRIDE_FIELDS:
            raise ValueError("unsupported resource override kind")
        key = _text(resource_key)
        if not key:
            raise ValueError("resource key is required")
        cleaned = {name: value for name, value in dict(patch or {}).items() if name in OVERRIDE_FIELDS[normalized_kind]}
        if not cleaned:
            raise ValueError("resource override has no supported fields")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT version FROM resource_overrides WHERE kind=? AND resource_key=?",
                (normalized_kind, key),
            ).fetchone()
            current_version = int(row[0]) if row else 0
            if expected_version is not None and int(expected_version) != current_version:
                raise ValueError("resource override version conflict")
            version = current_version + 1
            connection.execute(
                """INSERT OR REPLACE INTO resource_overrides(kind,resource_key,patch_json,version,updated_at)
                   VALUES(?,?,?,?,?)""",
                (normalized_kind, key, canonical_json(cleaned), version, now()),
            )
            connection.commit()
        return {"schema_version": SCHEMA_VERSION, "kind": normalized_kind, "resource_key": key, "version": version}

    def import_legacy(
        self,
        source_path: Path,
        source_label: str = "HaloCue 0.95",
        overlay_paths: list[Path] | None = None,
        *,
        character_aliases_path: Path | None = None,
        manifest_path: Path | None = None,
    ) -> dict:
        sources: list[Path] = []
        for candidate in [source_path, *(overlay_paths or [])]:
            resolved = Path(candidate).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(str(resolved))
            if resolved not in sources:
                sources.append(resolved)

        backgrounds: dict[str, dict] = {}
        background_labels: dict[str, tuple[tuple, dict, str]] = {}
        custom_background_keys: set[str] = set()
        characters: dict[str, dict] = {}
        aliases: dict[str, list[str]] = {}
        variants: dict[tuple[str, str, str], dict] = {}
        faces: dict[tuple[str, str, str, str], dict] = {}
        face_visuals: dict[tuple[str, str, str, str], tuple[tuple, dict, str]] = {}
        expressions: dict[tuple[str, str, str, str, str, str], dict] = {}
        source_manifest: list[dict] = []

        alias_index_path = Path(character_aliases_path).resolve() if character_aliases_path else None
        if alias_index_path is None:
            candidate = sources[0].parent / "character_aliases.json"
            if candidate.is_file():
                alias_index_path = candidate
        identity_rows = _read_character_alias_index(alias_index_path)
        manifest_rows = _read_manifest_characters(Path(manifest_path).resolve() if manifest_path else None)

        def table_exists(connection: sqlite3.Connection, table: str) -> bool:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone() is not None

        def keep_values(target: dict, source: dict) -> None:
            for key, value in source.items():
                if value not in (None, "", [], {}):
                    target[key] = value

        with ExitStack() as stack:
            legacy_connections: list[tuple[sqlite3.Connection, Path, str]] = []
            for index, source in enumerate(sources):
                connection = stack.enter_context(closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)))
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                version = f"{source_label}:{index + 1}"
                metadata = {}
                if table_exists(connection, "meta"):
                    metadata = {str(row[0]): str(row[1]) for row in connection.execute("SELECT key,value FROM meta")}
                source_manifest.append({
                    "name": source.name,
                    "role": "base" if index == 0 else "overlay",
                    "version": metadata.get("version") or metadata.get("dataset_version") or version,
                })
                legacy_connections.append((connection, source, version))

            if alias_index_path is not None:
                source_manifest.append({
                    "name": alias_index_path.name,
                    "role": "character_alias_index",
                    "version": source_label,
                })
            if manifest_rows:
                manifest_source = Path(manifest_path).resolve() if manifest_path else None
                source_manifest.append({
                    "name": manifest_source.name if manifest_source else "manifest.json",
                    "role": "aa_manifest_overlay",
                    "version": source_label,
                })

            for legacy, source, version in legacy_connections:
                if table_exists(legacy, "bg"):
                    for row in legacy.execute("SELECT * FROM bg"):
                        data = dict(row); key = _text(data.get("name"))
                        if not key:
                            continue
                        record = backgrounds.setdefault(key, {"key": key, "display_name": key})
                        old_place = _text(data.get("place"))
                        keep_values(record, {
                            "label": _text(data.get("label")) or key,
                            "indoor_outdoor": old_place if old_place in {"室内", "室外", "indoor", "outdoor"} else "",
                            "place": "" if old_place in {"室内", "室外", "indoor", "outdoor"} else old_place,
                            "time": _text(data.get("time")), "mood": _text(data.get("mood")),
                            "tags": _terms(data.get("tags")), "source_kind": _text(data.get("labeled_by")) or source_label,
                            "source_version": version,
                        })
                if table_exists(legacy, "asset_install"):
                    for row in legacy.execute(
                        """SELECT DISTINCT display_name FROM asset_install
                           WHERE kind='background' AND status='registered'"""
                    ):
                        key = _text(row[0])
                        if key:
                            custom_background_keys.add(key)
                if table_exists(legacy, "scene_visual_label"):
                    for row in legacy.execute("SELECT * FROM scene_visual_label WHERE resource_channel='background'"):
                        data = dict(row); key = _text(data.get("asset_key"))
                        if not key:
                            continue
                        label = _json_object(data.get("label_json")); manual = _json_object(data.get("manual_json"))
                        label.update(manual)
                        rank = (
                            1 if manual else 0,
                            1 if _text(data.get("status")) == "ready" else 0,
                            float(data.get("confidence") or label.get("confidence") or 0),
                        )
                        if key not in background_labels or rank >= background_labels[key][0]:
                            background_labels[key] = (rank, label, version)
                if table_exists(legacy, "character"):
                    for row in legacy.execute("SELECT * FROM character"):
                        data = dict(row); key = _text(data.get("ident"))
                        if not key:
                            continue
                        record = characters.setdefault(key, {"key": key})
                        keep_values(record, {
                            "display_name": _text(data.get("name")) or key, "club": _text(data.get("club")),
                            "spine": _text(data.get("spine")), "avatar": _text(data.get("avatar")),
                            "source_kind": _text(data.get("source")) or source_label, "source_version": version,
                        })
                if table_exists(legacy, "name_alias"):
                    for row in legacy.execute("SELECT script_name,ident FROM name_alias"):
                        script_name, ident = _text(row[0]), _text(row[1])
                        if ident and script_name and script_name not in aliases.setdefault(ident, []):
                            aliases[ident].append(script_name)
                if table_exists(legacy, "character_variant"):
                    for row in legacy.execute("SELECT * FROM character_variant"):
                        data = dict(row); character_key = _text(data.get("ident"))
                        if not character_key:
                            continue
                        key = (character_key, _text(data.get("spine_signature")), _text(data.get("outfit_key")))
                        variants[key] = {**data, "source_kind": source_label, "source_version": version}
                if table_exists(legacy, "face"):
                    for row in legacy.execute("SELECT * FROM face"):
                        data = dict(row); character_key, face_id = _text(data.get("ident")), _text(data.get("face_id"))
                        if not character_key or not face_id:
                            continue
                        key = (character_key, "", "", face_id)
                        record = faces.setdefault(key, {"character_key": character_key, "spine_signature": "", "outfit_key": "", "face_id": face_id})
                        keep_values(record, {**data, "source_kind": _text(data.get("source")) or source_label, "source_version": version})
                if table_exists(legacy, "face_evidence"):
                    for row in legacy.execute("SELECT * FROM face_evidence"):
                        data = dict(row)
                        key = (_text(data.get("ident")), _text(data.get("spine_signature")), _text(data.get("outfit_key")), _text(data.get("face_id")))
                        if not key[0] or not key[3]:
                            continue
                        record = faces.setdefault(key, {"character_key": key[0], "spine_signature": key[1], "outfit_key": key[2], "face_id": key[3]})
                        keep_values(record, {
                            "raw": _text(data.get("raw")), "label": _text(data.get("label")), "label_cn": _text(data.get("label_cn")),
                            "observed_count": max(int(record.get("observed_count") or 0), int(data.get("observed_count") or 0)),
                            "source_kind": _text(data.get("source")) or source_label, "source_version": version,
                        })
                        evidence_sources = record.setdefault("evidence_sources", [])
                        source_name = _text(data.get("source"))
                        if source_name and source_name not in evidence_sources:
                            evidence_sources.append(source_name)
                if table_exists(legacy, "face_visual_label"):
                    for row in legacy.execute("SELECT * FROM face_visual_label"):
                        data = dict(row)
                        key = (_text(data.get("ident")), _text(data.get("spine_signature")), _text(data.get("outfit_key")), _text(data.get("face_id")))
                        if not key[0] or not key[3]:
                            continue
                        manual = _json_object(data.get("manual_json"))
                        rank = (
                            1 if manual else 0, int(data.get("reviewed") or 0),
                            float(data.get("confidence") or 0),
                        )
                        if key not in face_visuals or rank >= face_visuals[key][0]:
                            semantic = _json_object(data.get("semantic_json"))
                            keep_values(semantic, {
                                "primary_emotion": _text(data.get("primary_emotion")),
                                "secondary": _json_list(data.get("secondary_json")), "valence": _text(data.get("valence")),
                                "arousal": _text(data.get("arousal")), "eyes": _text(data.get("eyes")),
                                "brows": _text(data.get("brows")), "mouth": _text(data.get("mouth")),
                                "blush": bool(data.get("blush")), "tears": bool(data.get("tears")),
                                "description": _text(data.get("description_cn")), "confidence": float(data.get("confidence") or 0),
                                "reviewed": bool(data.get("reviewed")),
                            })
                            for nested_name in ("observation_json", "backend_json"):
                                nested = _json_object(data.get(nested_name))
                                if nested:
                                    semantic[nested_name.removesuffix("_json")] = nested
                            semantic["model"] = _text(data.get("model"))
                            semantic["manual"] = manual
                            semantic.update(manual)
                            face_visuals[key] = (rank, semantic, version)
                if table_exists(legacy, "face_official_usage"):
                    query = """SELECT ident,spine_signature,outfit_key,face_id,COUNT(*)
                               FROM face_official_usage GROUP BY ident,spine_signature,outfit_key,face_id"""
                    for row in legacy.execute(query):
                        key = (_text(row[0]), _text(row[1]), _text(row[2]), _text(row[3]))
                        if not key[0] or not key[3]:
                            continue
                        record = faces.setdefault(key, {"character_key": key[0], "spine_signature": key[1], "outfit_key": key[2], "face_id": key[3]})
                        record["official_usage_count"] = max(int(record.get("official_usage_count") or 0), int(row[4] or 0))
                        record["source_version"] = version
                if table_exists(legacy, "expression_part"):
                    for row in legacy.execute("SELECT * FROM expression_part"):
                        data = dict(row)
                        key = (_text(data.get("ident")), _text(data.get("spine_signature")), _text(data.get("outfit_key")), _text(data.get("kind")), _text(data.get("raw_name")), _text(data.get("source")) or source_label)
                        if key[0] and key[3] and key[4]:
                            expressions[key] = {**data, "source_version": version}

            for key, (_, label, version) in background_labels.items():
                record = backgrounds.setdefault(key, {"key": key, "display_name": key})
                affiliations = [*_json_list(label.get("affiliation_names_cn")), *_json_list(label.get("compatible_affiliation_names_cn"))]
                keep_values(record, {
                    "label": _text(label.get("label")), "place": _text(label.get("place")),
                    "indoor_outdoor": _text(label.get("indoor_outdoor")), "time": _text(label.get("time")),
                    "weather": _text(label.get("weather")), "season": _text(label.get("season")),
                    "mood": _text(label.get("mood")), "tags": _terms(label.get("tags")),
                    "search_terms": _terms(label.get("search_terms_cn")), "description": _text(label.get("description")),
                    "visual_kind": _text(label.get("visual_kind")) or "background",
                    "main_category": _text(label.get("main_category_cn")) or _text(label.get("main_category")),
                    "affiliations": list(dict.fromkeys(affiliations)), "reuse_scope": _text(label.get("reuse_scope_cn")) or _text(label.get("reuse_scope")),
                    "category_path": _text(label.get("category_path_cn")), "usage_hint": _text(label.get("usage_hint_cn")),
                    "avoid_when": _text(label.get("avoid_when_cn")), "dialogue_suitable": bool(label.get("dialogue_suitable", True)),
                    "has_fixed_characters": bool(label.get("has_fixed_characters", False)), "source_version": version,
                    "annotation": _annotation_extras(label, {
                        "label", "description", "place", "indoor_outdoor", "time", "weather", "season", "mood",
                        "tags", "search_terms_cn", "visual_kind", "main_category", "main_category_cn",
                        "affiliation_names_cn", "compatible_affiliation_names_cn", "reuse_scope", "reuse_scope_cn",
                        "category_path_cn", "usage_hint_cn", "avoid_when_cn", "dialogue_suitable", "has_fixed_characters",
                    }),
                })

            for key in custom_background_keys:
                if key in backgrounds:
                    backgrounds[key]["visual_kind"] = "custom_background"
            for key, record in backgrounds.items():
                if _looks_like_custom_background_key(key):
                    record["visual_kind"] = "custom_background"
                elif _text(record.get("visual_kind")).casefold() in {"", "background"} and _looks_like_cg_key(key):
                    record["visual_kind"] = "cg"

            # 0.95 ships a compact regional-name index separately from the
            # asset database.  Fold it into the independent 1.0 catalog so
            # search and Agent matching do not depend on that file at runtime.
            for identity in identity_rows:
                canonical = identity["canonical_name"]
                aliases_for_identity = identity["aliases"]
                wanted = {_name_key(value) for value in (canonical, *aliases_for_identity) if _name_key(value)}
                matches = [
                    (key, record) for key, record in characters.items()
                    if _name_key(record.get("display_name")) in wanted
                    or _name_key(key) in wanted
                ]
                if len(matches) != 1:
                    continue
                key, record = matches[0]
                record["canonical_name"] = canonical
                record["preferred_name"] = next(
                    (value for value in aliases_for_identity if any("\u4e00" <= char <= "\u9fff" for char in value)),
                    canonical,
                )
                identity_aliases = list(dict.fromkeys([canonical, *aliases_for_identity]))
                record["identity_aliases"] = identity_aliases
                aliases[key] = list(dict.fromkeys([*aliases.get(key, []), *identity_aliases]))

            # An optional AA manifest is an identity overlay, never a write
            # target.  Prefer the manifest Identifier while retaining the
            # imported face/variant capabilities under that stable key.
            if manifest_rows:
                spine_matches: dict[str, str] = {}
                for key, record in characters.items():
                    spine = _spine_key(record.get("spine"))
                    if spine and spine not in spine_matches:
                        spine_matches[spine] = key
                    elif spine:
                        spine_matches[spine] = ""
                for manifest in manifest_rows:
                    manifest_key = manifest["identifier"]
                    source_key = manifest_key if manifest_key in characters else spine_matches.get(_spine_key(manifest.get("spine")))
                    source = characters.get(source_key or "")
                    if source_key and source_key != manifest_key and source is not None:
                        record = copy.deepcopy(source)
                        characters.pop(source_key, None)
                        aliases[manifest_key] = aliases.pop(source_key, [])
                        for old_key, value in list(variants.items()):
                            if old_key[0] == source_key:
                                variants[(manifest_key, *old_key[1:])] = value
                                variants.pop(old_key, None)
                        for old_key, value in list(faces.items()):
                            if old_key[0] == source_key:
                                faces[(manifest_key, *old_key[1:])] = value
                                faces.pop(old_key, None)
                        for old_key, value in list(face_visuals.items()):
                            if old_key[0] == source_key:
                                face_visuals[(manifest_key, *old_key[1:])] = value
                                face_visuals.pop(old_key, None)
                    else:
                        record = copy.deepcopy(source) if source is not None else {"key": manifest_key}
                    record.update({
                        "key": manifest_key,
                        "display_name": _text(manifest.get("display_name")) or record.get("display_name") or manifest_key,
                        "spine": _text(manifest.get("spine")) or record.get("spine") or "",
                        "avatar": _text(manifest.get("avatar")) or record.get("avatar") or "",
                        "manifest_bound": True,
                        "user_custom": source is None or str(record.get("source_kind") or "").casefold() in {"custom", "current_story_custom"},
                        "manifest_only": source is None,
                    })
                    if not record.get("canonical_name"):
                        record["canonical_name"] = record.get("display_name") or manifest_key
                    record["preferred_name"] = record.get("preferred_name") or record["display_name"]
                    record["identity_aliases"] = list(dict.fromkeys([
                        *(_json_list(record.get("identity_aliases"))),
                        _text(manifest.get("display_name")), _text(manifest.get("nickname")), manifest_key,
                    ]))
                    characters[manifest_key] = record
                    aliases[manifest_key] = list(dict.fromkeys([
                        *aliases.get(manifest_key, []), *record["identity_aliases"],
                    ]))

            for key, (_, semantic, version) in face_visuals.items():
                record = faces.setdefault(key, {"character_key": key[0], "spine_signature": key[1], "outfit_key": key[2], "face_id": key[3]})
                record["semantic"] = semantic; record["source_version"] = version

            imported = {
                "backgrounds": len(backgrounds), "characters": len(characters), "variants": len(variants),
                "faces": len(faces), "expression_parts": len(expressions),
            }
            manifest = {"source": source_label, "sources": source_manifest, "imported": imported, "schema_version": SCHEMA_VERSION}

            target = stack.enter_context(closing(self._connect()))
            target.execute("BEGIN IMMEDIATE")
            for table in ("backgrounds", "characters", "character_variants", "faces", "expression_parts"):
                target.execute(f"DELETE FROM {table}")
            for key, record in backgrounds.items():
                tags = list(dict.fromkeys([*_terms(record.get("tags")), *_terms(record.get("search_terms"))]))
                target.execute(
                    """INSERT INTO backgrounds
                       (key,display_name,label,place,indoor_outdoor,time,weather,season,mood,tags_json,description,search_terms_json,
                        visual_kind,main_category,affiliation_json,reuse_scope,category_path,usage_hint,avoid_when,dialogue_suitable,
                        has_fixed_characters,annotation_json,source_kind,source_version,source_row_hash,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, record.get("display_name") or key, record.get("label") or key, record.get("place") or "",
                     record.get("indoor_outdoor") or "", record.get("time") or "", record.get("weather") or "",
                     record.get("season") or "", record.get("mood") or "", canonical_json(_terms(record.get("tags"))),
                     record.get("description") or "", canonical_json(tags), record.get("visual_kind") or "background",
                     record.get("main_category") or "", canonical_json(record.get("affiliations") or []), record.get("reuse_scope") or "",
                     record.get("category_path") or "", record.get("usage_hint") or "", record.get("avoid_when") or "",
                     int(bool(record.get("dialogue_suitable", True))), int(bool(record.get("has_fixed_characters", False))),
                     canonical_json(record.get("annotation") or {}),
                     record.get("source_kind") or source_label, record.get("source_version") or SCHEMA_VERSION,
                     sha256_text(canonical_json(record)), now()),
                )
            for key, record in characters.items():
                target.execute(
                     """INSERT INTO characters
                       (key,display_name,club,spine,avatar,aliases_json,canonical_name,preferred_name,identity_aliases_json,
                        spine_key,manifest_bound,user_custom,manifest_only,source_kind,source_version,source_row_hash,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (key, record.get("display_name") or key, record.get("club") or "", record.get("spine") or "",
                     record.get("avatar") or "", canonical_json(aliases.get(key, [])), record.get("canonical_name") or record.get("display_name") or key,
                     record.get("preferred_name") or record.get("display_name") or key,
                     canonical_json(record.get("identity_aliases") or []), _spine_key(record.get("spine")),
                     int(bool(record.get("manifest_bound"))), int(bool(record.get("user_custom"))), int(bool(record.get("manifest_only"))),
                     record.get("source_kind") or source_label, record.get("source_version") or SCHEMA_VERSION,
                     sha256_text(canonical_json(record)), now()),
                )
            for (character_key, spine_signature, outfit_key), record in variants.items():
                target.execute(
                    """INSERT INTO character_variants(character_key,spine_signature,outfit_key,spine,source_kind,source_version)
                       VALUES(?,?,?,?,?,?)""",
                    (character_key, spine_signature, outfit_key, _text(record.get("spine")), record.get("source_kind") or source_label,
                     record.get("source_version") or SCHEMA_VERSION),
                )
            for key, record in faces.items():
                evidence = {
                    "observed_count": int(record.get("observed_count") or 0),
                    "official_usage_count": int(record.get("official_usage_count") or 0),
                    "sources": record.get("evidence_sources") or [],
                }
                target.execute(
                    """INSERT INTO faces
                       (character_key,spine_signature,outfit_key,face_id,raw,label,label_cn,semantic_json,evidence_json,
                        observed_count,official_usage_count,model,confidence,reviewed,source_kind,source_version)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (*key, _text(record.get("raw")), _text(record.get("label")), _text(record.get("label_cn")),
                     canonical_json(record.get("semantic") or {}), canonical_json(evidence), evidence["observed_count"],
                     evidence["official_usage_count"], _text((record.get("semantic") or {}).get("model")),
                     float((record.get("semantic") or {}).get("confidence") or 0),
                     int(bool((record.get("semantic") or {}).get("reviewed"))), record.get("source_kind") or source_label,
                     record.get("source_version") or SCHEMA_VERSION),
                )
            for key, record in expressions.items():
                target.execute(
                    """INSERT INTO expression_parts
                       (character_key,spine_signature,outfit_key,kind,raw_name,labels_json,source_kind,source_version)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (*key[:5], canonical_json(_json_list(record.get("labels_json"))), key[5], record.get("source_version") or SCHEMA_VERSION),
                )
            target.execute("INSERT OR REPLACE INTO catalog_meta(key,value) VALUES('source_manifest',?)", (canonical_json(manifest),))
            target.execute(
                "INSERT INTO migration_runs(source_manifest_json,imported_json,imported_at) VALUES(?,?,?)",
                (canonical_json(manifest), canonical_json(imported), now()),
            )
            target.commit()
        return {"schema_version": SCHEMA_VERSION, "imported": imported, "descriptor": self.descriptor()}
