# -*- coding: utf-8 -*-
"""自定义素材的验证、安装状态和模型约束目录。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
import re
import threading
from pathlib import Path

import assetdb
from asset_models import AssetCandidate


ASSET_SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_install (
    kind          TEXT NOT NULL,
    aa_key        TEXT NOT NULL,
    display_name  TEXT,
    source_path   TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    scope         TEXT NOT NULL,
    install_path  TEXT,
    status        TEXT NOT NULL,
    error         TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    registered_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, aa_key, scope)
);
CREATE INDEX IF NOT EXISTS ix_asset_install_status
ON asset_install(kind, status);
CREATE TABLE IF NOT EXISTS asset_library_profile (
    kind        TEXT NOT NULL,
    aa_key      TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    asset_role  TEXT NOT NULL DEFAULT 'chapter_only',
    series_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, aa_key, sha256)
);
"""

ALLOWED_MODEL_STATUSES = ("registered", "verified")
STORY_ASSET_STATUS = "registered"
_ASSET_SCHEMA_VERSION = "2"
_MIGRATE_LOCK = threading.RLock()
_OFFICIAL_CATALOG_SOURCES = {
    "observed", "verified", "aa_verified", "aap_observed", "official",
    "builtin", "built_in", "database", "library",
}
_CUSTOM_CATALOG_SOURCES = {
    "custom", "import", "imported", "导入登记", "overrides", "override",
    "history_import", "historical_import", "local_import",
}
_LIBRARY_ROLES = {"series_shared", "chapter_only"}
_SAFE_LABEL_FIELDS = {
    "label", "tags", "place", "time", "weather", "mood", "usage",
    "indoor_outdoor", "description", "season",
}
_SOURCE_PRIORITY = {
    "aa_verified": 0,
    "aap_observed": 2,
    "spine_semantic": 3,
    "atlas_candidate": 4,
}

_FACE_VISUAL_EVIDENCE = {
    "unknown": 0,
    "context_inferred": 1,
    "asset_semantic": 2,
    "visual_confirmed": 3,
}


def _source_priority(source: str) -> int:
    if source.startswith("vision:"):
        return 1
    return _SOURCE_PRIORITY.get(source, 99)


def face_visual_evidence(face: dict) -> str:
    """Return the strongest reviewable evidence class for one scoped face."""
    explicit = str(face.get("visual_evidence") or "")
    strongest = explicit if explicit in _FACE_VISUAL_EVIDENCE else "unknown"
    sources = {str(source) for source in (face.get("sources") or [])}
    if any(source.startswith("vision:") for source in sources):
        strongest = _stronger_face_visual_evidence(strongest, "visual_confirmed")
    if "spine_semantic" in sources:
        strongest = _stronger_face_visual_evidence(strongest, "asset_semantic")
    has_semantic_label = any(
        str(face.get(field) or "").strip()
        for field in ("semantic_cn", "cn", "label")
    )
    if "atlas_candidate" in sources and has_semantic_label:
        strongest = _stronger_face_visual_evidence(strongest, "asset_semantic")
    if "aa_verified" in sources and has_semantic_label:
        strongest = _stronger_face_visual_evidence(strongest, "asset_semantic")
    if {"aap_observed", "aa_verified"} & sources:
        strongest = _stronger_face_visual_evidence(strongest, "context_inferred")
    return strongest


def _stronger_face_visual_evidence(current: str, candidate: str) -> str:
    if _FACE_VISUAL_EVIDENCE[candidate] > _FACE_VISUAL_EVIDENCE[current]:
        return candidate
    return current


def _face_capabilities(con) -> dict[str, list[dict]]:
    variants: dict[tuple[str, str, str], dict] = {}
    for row in con.execute(
        "SELECT ident,spine_signature,outfit_key,spine FROM character_variant"
    ):
        variants[(row["ident"], row["spine_signature"], row["outfit_key"])] = {
            "spine_signature": row["spine_signature"], "outfit_key": row["outfit_key"],
            "spine": row["spine"], "faces": {},
        }
    for row in con.execute(
        """
        SELECT * FROM face_evidence
        ORDER BY ident,spine_signature,outfit_key,face_id,
          CASE source
            WHEN 'aa_verified' THEN 0
            WHEN 'aap_observed' THEN 2
            WHEN 'spine_semantic' THEN 3
            WHEN 'atlas_candidate' THEN 4
            ELSE CASE WHEN source LIKE 'vision:%' THEN 1 ELSE 5 END
          END
        """
    ):
        key = (row["ident"], row["spine_signature"], row["outfit_key"])
        variant = variants.setdefault(key, {
            "spine_signature": row["spine_signature"], "outfit_key": row["outfit_key"],
            "spine": "", "faces": {},
        })
        face = variant["faces"].setdefault(row["face_id"], {
            "id": row["face_id"], "raw": row["raw"], "label": row["label"],
            "cn": row["label_cn"], "semantic_cn": "", "sources": [],
            "observed_count": 0, "verified": False, "semantic_level": "unknown",
            "visual_evidence": "unknown",
        })
        face["sources"].append(row["source"])
        face["observed_count"] += row["observed_count"] or 0
        face["verified"] = face["verified"] or row["source"] == "aa_verified"
        row_evidence = face_visual_evidence({
            "sources": [row["source"]],
            "label": row["label"],
            "cn": row["label_cn"],
        })
        face["visual_evidence"] = _stronger_face_visual_evidence(
            face["visual_evidence"], row_evidence
        )
        if row["source"].startswith("vision:"):
            try:
                rich = json.loads(row["raw"] or "{}")
            except (TypeError, ValueError):
                rich = {}
            if isinstance(rich, dict):
                fields = (
                    "emotion_family", "intensity", "expression_class", "beat_fit",
                    "hold_policy", "special_tags", "avoid_when_cn",
                )
                for field in fields:
                    if field in rich:
                        face[field] = rich[field]
                if any(field in rich for field in fields):
                    face["semantic_level"] = "rich"
        if (
            (row["source"] == "spine_semantic" or row["source"].startswith("vision:"))
            and row["label_cn"]
            and not face["semantic_cn"]
        ):
            face["semantic_cn"] = row["label_cn"]
        if face["semantic_level"] == "unknown" and (row["label_cn"] or row["label"]):
            face["semantic_level"] = "basic"
    by_ident: dict[str, list[dict]] = {}
    for (ident, signature, outfit), variant in sorted(variants.items()):
        faces = variant.pop("faces")
        if not faces:
            continue
        variant["faces"] = [
            {**face, "sources": sorted(face["sources"], key=_source_priority)}
            for _, face in sorted(faces.items())
        ]
        by_ident.setdefault(ident, []).append(variant)
    return by_ident


def _union_faces(existing: list[dict], capabilities: list[dict]) -> list[dict]:
    faces = {face["id"]: face for face in existing}
    for variant in capabilities:
        for face in variant["faces"]:
            faces.setdefault(face["id"], {
                "id": face["id"], "raw": face["raw"], "label": face["label"],
                "cn": face.get("cn", ""),
            })
    return [faces[key] for key in sorted(faces)]


def _metadata_face_capabilities(metadata: dict) -> list[dict]:
    supplied = metadata.get("face_capabilities")
    if supplied:
        return supplied
    faces = metadata.get("faces") or []
    if not faces:
        return []
    records = []
    for face in faces:
        if isinstance(face, dict):
            face_id = face["id"]
            raw = face.get("raw", face_id)
            label = face.get("label", "")
            cn = face.get("cn", "")
        else:
            face_id = raw = str(face)
            label = cn = ""
        records.append({
            "id": face_id, "raw": raw, "label": label, "cn": cn,
            "sources": ["atlas_candidate"], "observed_count": 0, "verified": False,
            "visual_evidence": face_visual_evidence({
                "sources": ["atlas_candidate"], "label": label, "cn": cn,
            }),
        })
    return [{
        "spine_signature": metadata.get("spine_signature", ""),
        "outfit_key": metadata.get("outfit_key", ""), "spine": metadata.get("spine", ""),
        "faces": records,
    }]


def _asset_schema_is_current(con) -> bool:
    row = con.execute(
        "SELECT value FROM meta WHERE key='asset_schema_version'"
    ).fetchone()
    return bool(row and str(row[0]) == _ASSET_SCHEMA_VERSION)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def migrate(con) -> None:
    if _asset_schema_is_current(con):
        return
    with _MIGRATE_LOCK:
        if _asset_schema_is_current(con):
            return
        con.executescript(ASSET_SCHEMA)
        columns = {
            str(row["name"]) for row in con.execute("PRAGMA table_info(asset_install)")
        }
        if "registered_at" not in columns:
            con.execute(
                "ALTER TABLE asset_install "
                "ADD COLUMN registered_at TEXT NOT NULL DEFAULT ''"
            )
        assetdb.migrate_face_evidence(con)
        con.execute(
            """
            INSERT INTO meta(key,value) VALUES('asset_schema_version',?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (_ASSET_SCHEMA_VERSION,),
        )
        con.commit()


def upsert_candidate(
    con,
    candidate: AssetCandidate,
    *,
    scope: str,
    status: str = "validated",
    install_path: str | None = None,
    display_name: str | None = None,
    error: str | None = None,
) -> None:
    migrate(con)
    metadata = dict(candidate.metadata)
    if not any(metadata.get(field) for field in ("catalog_source", "source", "origin")):
        metadata["catalog_source"] = "custom"
    con.execute(
        """
        INSERT INTO asset_install
          (kind,aa_key,display_name,source_path,sha256,scope,
           install_path,status,error,metadata_json,registered_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(kind,aa_key,scope) DO UPDATE SET
          display_name=excluded.display_name,
          source_path=excluded.source_path,
          sha256=excluded.sha256,
          install_path=excluded.install_path,
          registered_at=CASE
            WHEN asset_install.registered_at<>'' THEN asset_install.registered_at
            WHEN asset_install.status='registered' THEN ''
            WHEN excluded.status='registered' THEN excluded.registered_at
            ELSE ''
          END,
          status=excluded.status,
          error=excluded.error,
          metadata_json=excluded.metadata_json
        """,
        (
            candidate.kind,
            str(candidate.aa_key),
            display_name or candidate.stem,
            str(candidate.source_path),
            candidate.sha256,
            scope,
            install_path,
            status,
            error,
            json.dumps(metadata, ensure_ascii=False),
            _utc_now_iso() if status == "registered" else "",
        ),
    )
    if candidate.kind == "character":
        metadata = candidate.metadata
        assetdb.replace_expression_parts(
            con,
            ident=str(candidate.aa_key),
            spine_signature=str(metadata.get("spine_signature") or ""),
            outfit_key=str(metadata.get("outfit_key") or ""),
            parts=metadata.get("expression_parts") or [],
        )
        assetdb.replace_semantic_face_evidence(
            con,
            ident=str(candidate.aa_key),
            spine_signature=str(metadata.get("spine_signature") or ""),
            outfit_key=str(metadata.get("outfit_key") or ""),
            combinations=metadata.get("semantic_face_combinations") or {},
        )
    con.commit()


def set_asset_status(
    con,
    *,
    kind: str,
    aa_key: int | str,
    scope: str,
    status: str,
    install_path: str | None = None,
    error: str | None = None,
) -> None:
    changed = con.execute(
        """
        UPDATE asset_install
        SET status=?, install_path=COALESCE(?,install_path), error=?,
            registered_at=CASE
              WHEN registered_at<>'' THEN registered_at
              WHEN status='registered' THEN ''
              WHEN ?='registered' THEN ?
              ELSE ''
            END
        WHERE kind=? AND aa_key=? AND scope=?
        """,
        (
            status, install_path, error, status, _utc_now_iso(),
            kind, str(aa_key), scope,
        ),
    ).rowcount
    if not changed:
        raise KeyError(f"素材目录中不存在 {kind}:{aa_key}@{scope}")
    con.commit()


def _numeric_key(value: str) -> int | str:
    return int(value) if value.isdecimal() else value


def _safe_metadata(value) -> dict:
    try:
        decoded = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _safe_catalog_text(value, *, fallback: str = "") -> str:
    """Keep small descriptive values while rejecting path-shaped metadata."""
    text = " ".join(str(value or "").split())
    if not text or len(text) > 240:
        return fallback
    if text.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", text):
        return fallback
    return text


def _safe_iso_timestamp(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _safe_catalog_labels(value) -> dict:
    if not isinstance(value, dict):
        return {}
    labels = {}
    for key in _SAFE_LABEL_FIELDS:
        if key not in value:
            continue
        raw = value[key]
        if isinstance(raw, list):
            cleaned = [_safe_catalog_text(item) for item in raw[:12]]
            labels[key] = [item for item in cleaned if item]
        else:
            cleaned = _safe_catalog_text(raw)
            if cleaned:
                labels[key] = cleaned
    return labels


def _is_story_custom_row(row, metadata: dict) -> bool:
    """判断剧情素材面板可见的自定义登记。"""
    if str(row["status"] or "") != STORY_ASSET_STATUS:
        return False
    source = str(
        metadata.get("catalog_source")
        or metadata.get("source")
        or metadata.get("origin")
        or ""
    ).strip().casefold()
    if source in _OFFICIAL_CATALOG_SOURCES:
        return False
    if source in _CUSTOM_CATALOG_SOURCES:
        return True
    if source:
        return False
    try:
        raw_metadata = json.loads(row["metadata_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(raw_metadata, dict):
        return False
    # Registrations created before catalog_source was introduced are story-local custom assets.
    return True


def _within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _preview_path(kind: str, install_path: str | None, metadata: dict) -> Path | None:
    """Resolve a browser preview only from the already scoped catalog record."""
    if not install_path:
        return None
    installed = Path(install_path)
    if kind in {"background", "sound"}:
        return installed if installed.is_file() else None
    if kind != "character" or not installed.is_dir():
        return None
    avatar = str((metadata.get("files") or {}).get("avatar") or "")
    # The validation metadata is an audit record and can contain source paths;
    # only its basename is permitted to select a file inside the installed dir.
    candidate = installed / Path(avatar).name
    return candidate if candidate.is_file() and _within(candidate, installed) else None


def story_asset_preview(con, *, scope: str, kind: str, aa_key: str) -> Path | None:
    """Find a preview after the caller has resolved the story token's scope."""
    if kind not in {"background", "sound", "character"}:
        return None
    migrate(con)
    row = con.execute(
        """SELECT status, install_path, metadata_json FROM asset_install
           WHERE scope=? AND kind=? AND aa_key=?""",
        (scope, kind, str(aa_key)),
    ).fetchone()
    if not row:
        return None
    metadata = _safe_metadata(row["metadata_json"])
    if not _is_story_custom_row(row, metadata):
        return None
    return _preview_path(kind, row["install_path"], metadata)


def list_story_assets(con, *, scope: str) -> dict:
    """Return browser-safe, project-scoped custom asset cards.

    The catalog retains source/install paths for audit and compilation, but this
    UI payload deliberately exposes neither.  BGM is explicitly disabled until
    the native AA contract and registration transaction exist.
    """
    migrate(con)
    rows = con.execute(
        """
        SELECT kind, aa_key, display_name, status, metadata_json, install_path
        FROM asset_install
        WHERE scope=? AND status=? AND kind IN ('background', 'sound', 'character')
        ORDER BY kind, display_name, aa_key
        """,
        [scope, STORY_ASSET_STATUS],
    ).fetchall()
    out = {"characters": [], "backgrounds": [], "sounds": [], "bgms": []}
    keys = {"character": "characters", "background": "backgrounds", "sound": "sounds"}
    for row in rows:
        metadata = _safe_metadata(row["metadata_json"])
        if not _is_story_custom_row(row, metadata):
            continue
        item = {
            "name": row["display_name"],
            "aa_key": _numeric_key(row["aa_key"]),
            "status": row["status"],
        }
        if metadata.get("labels"):
            item["labels"] = metadata["labels"]
        if metadata.get("source_project"):
            item["source_project"] = metadata["source_project"]
        if row["kind"] == "background":
            width, height = metadata.get("width"), metadata.get("height")
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                divisor = math.gcd(width, height)
                item.update({
                    "width": width, "height": height,
                    "resolution": f"{width}×{height}",
                    "aspect_ratio": f"{width // divisor}:{height // divisor}",
                })
            else:
                item.update({"resolution": "待检测", "aspect_ratio": "待检测"})
        elif row["kind"] == "sound":
            for field in ("duration", "codec", "sample_rate", "channels"):
                if metadata.get(field) not in (None, "", 0):
                    item[field] = metadata[field]
            item["preview_available"] = _preview_path("sound", row["install_path"], metadata) is not None
        elif row["kind"] == "character":
            files = metadata.get("files") or {}
            item.update({
                "faces": metadata.get("faces") or [],
                "expression_status": metadata.get("expression_status") or "待检测",
                "file_completeness": "完整" if all(files.get(name) for name in ("skel", "atlas", "texture", "avatar")) else "待检测",
                "preview_available": _preview_path("character", row["install_path"], metadata) is not None,
            })
        if row["kind"] == "background":
            item["preview_available"] = _preview_path("background", row["install_path"], metadata) is not None
        out[keys[row["kind"]]].append(item)
    out["counts"] = {key: len(out[key]) for key in ("characters", "backgrounds", "sounds", "bgms")}
    return out


def _library_item_details(kind: str, metadata: dict) -> dict:
    """Return catalog details that help identify a material without paths."""
    if kind == "character":
        files = metadata.get("files")
        file_count = (
            len([value for value in files.values() if value])
            if isinstance(files, dict)
            else None
        )
        faces = metadata.get("faces")
        semantic_count = metadata.get("semantic_face_count")
        if isinstance(faces, list) and faces:
            face_count = len(faces)
        elif isinstance(semantic_count, int) and semantic_count >= 0:
            face_count = semantic_count
        else:
            face_count = None
        return {
            "expression_status": _safe_catalog_text(
                metadata.get("expression_status"), fallback="待检测"
            ),
            "expression_mode": _safe_catalog_text(
                metadata.get("expression_mode"), fallback="opaque_custom"
            ),
            "file_count": file_count,
            "face_count": face_count,
        }
    if kind == "background":
        details = {
            "resolution": "待检测",
            "labels": _safe_catalog_labels(metadata.get("labels")),
            "label_status": _safe_catalog_text(
                metadata.get("label_status"), fallback="not_labeled"
            ),
            "label_error": _safe_catalog_text(metadata.get("label_error")),
            "labels_updated_at": _safe_catalog_text(
                metadata.get("labels_updated_at")
            ),
        }
        width, height = metadata.get("width"), metadata.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            details["resolution"] = f"{width}×{height}"
        return details
    if kind == "sound":
        details = {
            key: metadata[key] for key in ("duration", "codec", "sample_rate", "channels", "labels")
            if metadata.get(key) not in (None, "", 0, {})
        }
        if "labels" in details:
            details["labels"] = _safe_catalog_labels(details["labels"])
        if "codec" in details:
            details["codec"] = _safe_catalog_text(details["codec"])
        return details
    return {}


def library_custom_rows(con):
    """Return server-only catalog rows for reusable registered custom copies."""
    migrate(con)
    rows = con.execute(
        """
        SELECT kind,aa_key,display_name,sha256,scope,status,metadata_json,install_path,
               registered_at
        FROM asset_install
        WHERE status=? AND kind IN ('character','background','sound')
        ORDER BY kind,display_name,aa_key,scope
        """,
        (STORY_ASSET_STATUS,),
    ).fetchall()
    return [
        row for row in rows
        if _is_story_custom_row(row, _safe_metadata(row["metadata_json"]))
    ]


def _visual_label_summaries(con) -> dict[tuple[str, str, str], dict[str, int | str]]:
    return {
        (str(row["ident"]), str(row["spine_signature"]), str(row["outfit_key"])): {
            "labeled_count": int(row["labeled_count"] or 0),
            "labels_updated_at": str(row["labels_updated_at"] or ""),
        }
        for row in con.execute(
            """
            SELECT ident,spine_signature,outfit_key,
                   COUNT(DISTINCT face_id) AS labeled_count,
                   MAX(updated_at) AS labels_updated_at
            FROM face_visual_label
            GROUP BY ident,spine_signature,outfit_key
            """
        )
    }


def _merge_visual_label_summary(
    details: dict,
    *,
    kind: str,
    aa_key: str,
    metadata: dict,
    summaries: dict[tuple[str, str, str], dict[str, int | str]],
) -> None:
    if kind != "character":
        return
    variant = (
        str(aa_key),
        str(metadata.get("spine_signature") or ""),
        str(metadata.get("outfit_key") or ""),
    )
    saved = summaries.get(variant)
    details["labeled_count"] = int(saved["labeled_count"]) if saved else 0
    details["labels_updated_at"] = str(saved["labels_updated_at"]) if saved else ""


def list_library_assets(con) -> dict:
    """List custom material copies across chapters without exposing server paths.

    AA loads overrides per project, so this is intentionally a *catalog of
    reusable copies*, never a global runtime asset source.
    """
    migrate(con)
    profiles = {
        (row["kind"], row["aa_key"], row["sha256"]): row
        for row in con.execute(
            "SELECT kind,aa_key,sha256,asset_role,series_name FROM asset_library_profile"
        )
    }
    rows = library_custom_rows(con)
    visual_counts = _visual_label_summaries(con)
    groups: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        metadata = _safe_metadata(row["metadata_json"])
        key = (str(row["kind"]), str(row["aa_key"]), str(row["sha256"]))
        profile = profiles.get(key)
        item = groups.setdefault(key, {
            "kind": key[0], "aa_key": _numeric_key(key[1]), "sha256": key[2],
            "name": _safe_catalog_text(
                row["display_name"], fallback=str(row["aa_key"])
            ),
            "asset_role": str(profile["asset_role"]) if profile else "chapter_only",
            "series_name": str(profile["series_name"]) if profile else "",
            "chapters": [], "details": _library_item_details(key[0], metadata),
            "_copy_times": [],
        })
        _merge_visual_label_summary(
            item["details"], kind=key[0], aa_key=key[1], metadata=metadata,
            summaries=visual_counts,
        )
        chapter = Path(str(row["scope"] or "")).name or "未命名章节"
        if chapter not in item["chapters"]:
            item["chapters"].append(chapter)
        timestamp = _safe_iso_timestamp(row["registered_at"])
        if timestamp:
            item["_copy_times"].append((timestamp, chapter))
    out = {"characters": [], "backgrounds": [], "sounds": [], "bgms": []}
    bucket = {"character": "characters", "background": "backgrounds", "sound": "sounds"}
    for item in groups.values():
        item["chapters"].sort(key=str.casefold)
        item["copy_count"] = len(item["chapters"])
        copy_times = item.pop("_copy_times")
        item["imported_at"] = min(
            (timestamp for timestamp, _ in copy_times), default=""
        )
        latest = max(copy_times, default=None)
        item["last_used_at"] = latest[0] if latest else ""
        item["last_used_chapter"] = latest[1] if latest else ""
        out[bucket[item["kind"]]].append(item)
    for values in out.values():
        values.sort(key=lambda item: (str(item["series_name"]).casefold(), str(item["name"]).casefold()))
    out["counts"] = {key: len(out[key]) for key in out}
    return out


def library_background_analysis_target(
    con, *, aa_key: str | int, sha256: str
) -> dict:
    """Resolve one installed custom background without exposing it to the browser."""
    migrate(con)
    key = str(aa_key or "").strip()
    digest = str(sha256 or "").strip()
    if not key or not digest:
        raise ValueError("缺少背景素材标识")
    rows = con.execute(
        """
        SELECT aa_key,display_name,status,install_path,metadata_json
        FROM asset_install
        WHERE kind='background' AND aa_key=? AND sha256=? AND status=?
        ORDER BY scope
        """,
        (key, digest, STORY_ASSET_STATUS),
    ).fetchall()
    for row in rows:
        metadata = _safe_metadata(row["metadata_json"])
        if not _is_story_custom_row(row, metadata):
            continue
        installed = Path(str(row["install_path"] or ""))
        if installed.is_file():
            return {
                "source": str(installed),
                "aa_key": str(row["aa_key"]),
                "sha256": digest,
                "name": _safe_catalog_text(row["display_name"], fallback=key),
                "labels": _safe_catalog_labels(metadata.get("labels")),
                "label_status": _safe_catalog_text(
                    metadata.get("label_status"), fallback="not_labeled"
                ),
            }
    raise KeyError("没有可用于场景识别的已登记背景副本")


def update_background_labels(
    con,
    *,
    aa_key: str | int,
    sha256: str,
    labels: object,
    status: str,
    error: str = "",
) -> dict:
    """Persist one semantic result across identical registered custom copies."""
    from background_labeler import normalize_background_labels

    migrate(con)
    key = str(aa_key or "").strip()
    digest = str(sha256 or "").strip()
    normalized = normalize_background_labels(labels)
    state = str(status or "").strip()
    if not key or not digest:
        raise ValueError("缺少背景素材标识")
    if state not in {"not_labeled", "labeling", "ready", "failed"}:
        raise ValueError("背景标注状态无效")
    safe_error = _safe_catalog_text(error)
    rows = con.execute(
        """
        SELECT rowid,display_name,install_path,status,metadata_json
        FROM asset_install
        WHERE kind='background' AND aa_key=? AND sha256=? AND status=?
        """,
        (key, digest, STORY_ASSET_STATUS),
    ).fetchall()
    updated = 0
    legacy_names = set()
    timestamp = datetime.now(timezone.utc).isoformat()
    with con:
        for row in rows:
            metadata = _safe_metadata(row["metadata_json"])
            if not _is_story_custom_row(row, metadata):
                continue
            metadata["labels"] = normalized
            metadata["label_status"] = state
            metadata["label_error"] = safe_error
            metadata["labels_updated_at"] = timestamp
            con.execute(
                "UPDATE asset_install SET metadata_json=? WHERE rowid=?",
                (json.dumps(metadata, ensure_ascii=False), row["rowid"]),
            )
            installed = Path(str(row["install_path"] or ""))
            if installed.name:
                legacy_names.add(installed.stem)
            updated += 1
        for name in legacy_names:
            con.execute(
                """
                UPDATE bg SET label=?,place=?,time=?,mood=?,tags=?,labeled_by='vision'
                WHERE name=?
                """,
                (
                    normalized.get("label") or None,
                    normalized.get("place") or None,
                    normalized.get("time") or None,
                    normalized.get("mood") or None,
                    normalized.get("tags") or None,
                    name,
                ),
            )
    if not updated:
        raise KeyError("素材履历中不存在该已登记背景")
    return {
        "aa_key": _numeric_key(key),
        "sha256": digest,
        "labels": normalized,
        "label_status": state,
        "label_error": safe_error,
        "labels_updated_at": timestamp,
        "updated": updated,
    }


def update_library_profile(
    con, *, kind: str, aa_key: str | int, sha256: str,
    asset_role: str, series_name: str,
) -> dict:
    """Persist the user's reuse classification for one immutable material copy."""
    migrate(con)
    kind = str(kind or "").strip()
    key = str(aa_key or "").strip()
    digest = str(sha256 or "").strip()
    role = str(asset_role or "").strip()
    series = " ".join(str(series_name or "").split())
    if kind not in {"character", "background", "sound"}:
        raise ValueError("素材类型无效")
    if not key or not digest:
        raise ValueError("缺少素材标识")
    if role not in _LIBRARY_ROLES:
        raise ValueError("素材归属无效")
    if len(series) > 80:
        raise ValueError("系列名称不能超过 80 个字符")
    if role == "series_shared" and not series:
        raise ValueError("标记为系列共用时，请填写系列名称")
    exists = con.execute(
        """
        SELECT status,metadata_json FROM asset_install
        WHERE kind=? AND aa_key=? AND sha256=? AND status=?
        LIMIT 1
        """,
        (kind, key, digest, STORY_ASSET_STATUS),
    ).fetchone()
    if not exists or not _is_story_custom_row(exists, _safe_metadata(exists["metadata_json"])):
        raise KeyError("素材履历中不存在该已登记副本")
    con.execute(
        """
        INSERT INTO asset_library_profile(kind,aa_key,sha256,asset_role,series_name)
        VALUES (?,?,?,?,?)
        ON CONFLICT(kind,aa_key,sha256) DO UPDATE SET
          asset_role=excluded.asset_role, series_name=excluded.series_name
        """,
        (kind, key, digest, role, series),
    )
    con.commit()
    return {
        "kind": kind, "aa_key": _numeric_key(key), "sha256": digest,
        "asset_role": role, "series_name": series,
    }


def remove_story_copy(
    con, *, scope: str, kind: str, aa_key: str | int, sha256: str
) -> dict:
    """Delete one exact registered custom copy and prune only an orphan profile."""
    migrate(con)
    key = str(aa_key)
    digest = str(sha256)
    row = con.execute(
        """
        SELECT status,metadata_json FROM asset_install
        WHERE scope=? AND kind=? AND aa_key=? AND sha256=?
        """,
        (str(scope), str(kind), key, digest),
    ).fetchone()
    if not row or not _is_story_custom_row(row, _safe_metadata(row["metadata_json"])):
        raise KeyError("指定剧情素材副本不存在")
    with con:
        con.execute(
            """
            DELETE FROM asset_install
            WHERE scope=? AND kind=? AND aa_key=? AND sha256=?
            """,
            (str(scope), str(kind), key, digest),
        )
        remaining = con.execute(
            """
            SELECT 1 FROM asset_install
            WHERE kind=? AND aa_key=? AND sha256=? AND status=? LIMIT 1
            """,
            (str(kind), key, digest, STORY_ASSET_STATUS),
        ).fetchone()
        if not remaining:
            con.execute(
                "DELETE FROM asset_library_profile WHERE kind=? AND aa_key=? AND sha256=?",
                (str(kind), key, digest),
            )
    return {
        "kind": str(kind),
        "aa_key": _numeric_key(key),
        "sha256": digest,
        "scope_removed": True,
        "profile_removed": not bool(remaining),
    }


def library_character_analysis_target(con, *, aa_key: str | int, sha256: str) -> dict:
    """Resolve an installed custom character copy for a server-side face job."""
    migrate(con)
    key = str(aa_key or "").strip()
    digest = str(sha256 or "").strip()
    if not key or not digest:
        raise ValueError("缺少角色素材标识")
    rows = con.execute(
        """
        SELECT aa_key,display_name,status,install_path,metadata_json
        FROM asset_install
        WHERE kind='character' AND aa_key=? AND sha256=? AND status=?
        ORDER BY scope
        """,
        (key, digest, STORY_ASSET_STATUS),
    ).fetchall()
    for row in rows:
        metadata = _safe_metadata(row["metadata_json"])
        if not _is_story_custom_row(row, metadata):
            continue
        installed = Path(str(row["install_path"] or ""))
        if not installed.is_dir():
            continue
        return {
            "source": str(installed),
            "ident": str(row["aa_key"]),
            "name": _safe_catalog_text(row["display_name"], fallback=key),
            "spine_signature": str(metadata.get("spine_signature") or ""),
            "outfit_key": str(metadata.get("outfit_key") or ""),
        }
    raise KeyError("没有可用于表情标注的已登记骨骼副本")


def export_model_constraints(con, *, scope: str | None = None) -> dict:
    migrate(con)
    marks = ",".join("?" for _ in ALLOWED_MODEL_STATUSES)
    scope_sql = " AND scope=?" if scope is not None else ""
    args = [*ALLOWED_MODEL_STATUSES]
    if scope is not None:
        args.append(scope)
    rows = con.execute(
        f"""
        SELECT * FROM asset_install
        WHERE status IN ({marks})
        {scope_sql}
        ORDER BY kind,display_name,aa_key
        """,
        args,
    ).fetchall()
    out = {"backgrounds": {}, "sounds": {}, "characters": []}
    capabilities = _face_capabilities(con)
    parts_by_variant = assetdb.expression_parts_by_variant(con)
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        if row["kind"] == "background":
            record = {
                "aa_key": _numeric_key(row["aa_key"]),
                "install_path": row["install_path"],
                "status": row["status"],
            }
            if metadata.get("labels"):
                record["labels"] = metadata["labels"]
            out["backgrounds"][row["display_name"]] = record
        elif row["kind"] == "sound":
            record = {
                "aa_key": row["aa_key"],
                "install_path": row["install_path"],
                "status": row["status"],
            }
            if metadata.get("labels"):
                record["labels"] = metadata["labels"]
            out["sounds"][row["display_name"]] = record
        elif row["kind"] == "character":
            face_capabilities = capabilities.get(row["aa_key"], []) or _metadata_face_capabilities(metadata)
            faces = metadata.get("faces", [])
            variant_key = (
                row["aa_key"],
                str(metadata.get("spine_signature") or ""),
                str(metadata.get("outfit_key") or ""),
            )
            out["characters"].append(
                {
                    "identifier": row["aa_key"],
                    "name": row["display_name"],
                    "faces": sorted(set(faces) | {
                        face["id"] for variant in face_capabilities for face in variant["faces"]
                    }),
                    "face_capabilities": face_capabilities,
                    "spine_signature": metadata.get("spine_signature", ""),
                    "outfit_key": metadata.get("outfit_key", ""),
                    "expression_mode": metadata.get(
                        "expression_mode",
                        "numbered_composite" if metadata.get("faces") else "opaque_custom",
                    ),
                    "expression_parts": parts_by_variant.get(variant_key, []),
                    "expression_status": metadata.get(
                        "expression_status",
                        "known" if metadata.get("faces") else "unresolved",
                    ),
                    "install_path": row["install_path"],
                    "status": row["status"],
                }
            )
    return out


def merge_model_constraints(index: dict, con, *, scope: str) -> dict:
    """Return a copy of an official index extended by one project's assets."""
    merged = copy.deepcopy(index)
    custom = export_model_constraints(con, scope=scope)
    merged.setdefault("bg", {})
    merged.setdefault("bg_label", {})
    merged.setdefault("sounds", [])
    merged.setdefault("sound_label", {})
    merged.setdefault("characters", [])

    for name, record in custom["backgrounds"].items():
        merged["bg"][name] = record["aa_key"]
        if record.get("labels"):
            merged["bg_label"][name] = record["labels"]
    known_sounds = set(merged["sounds"])
    for record in custom["sounds"].values():
        key = str(record["aa_key"])
        if key not in known_sounds:
            merged["sounds"].append(key)
            known_sounds.add(key)
        if record.get("labels"):
            merged["sound_label"][key] = record["labels"]
    known_characters = {
        str(record.get("identifier", "")) for record in merged["characters"]
    }
    custom_capabilities = {
        record["identifier"]: record.get("face_capabilities", [])
        for record in custom["characters"]
    }
    for record in custom["characters"]:
        if record["identifier"] in known_characters:
            continue
        merged["characters"].append(
            {
                "identifier": record["identifier"],
                "name": record["name"],
                "club": "",
                "spine": "",
                "faces": [
                    {"id": face, "raw": face, "label": "", "cn": ""}
                    for face in record["faces"]
                ],
                "face_capabilities": record.get("face_capabilities", []),
                "spine_signature": record.get("spine_signature", ""),
                "outfit_key": record.get("outfit_key", ""),
                "expression_mode": record.get("expression_mode", "opaque_custom"),
                "expression_parts": record.get("expression_parts", []),
            }
        )
        known_characters.add(record["identifier"])
    evidence_capabilities = _face_capabilities(con)
    merged_capabilities = {}
    for character in merged["characters"]:
        capabilities = (
            evidence_capabilities.get(character.get("identifier"), [])
            or character.get("face_capabilities", [])
            or custom_capabilities.get(character.get("identifier"), [])
        )
        if not capabilities:
            continue
        character["face_capabilities"] = capabilities
        character["faces"] = _union_faces(character.get("faces", []), capabilities)
        merged_capabilities[character["identifier"]] = capabilities
    if merged_capabilities:
        merged["face_capabilities"] = merged_capabilities
    return merged
