# -*- coding: utf-8 -*-
"""Unified discovery, validation, and project-private custom asset import."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from aa_registry import (
    RegistrationConflictError,
    register_background,
    register_character,
    register_sound,
)
from aa_project_assets import resolve_project_target
from asset_catalog import upsert_candidate
from asset_validation import (
    validate_background,
    validate_sound,
    validate_spine,
)


class AssetImportRequestError(ValueError):
    """The import request is incomplete or names an unsupported asset type."""

    def __init__(self, message: str, *, code: str = "invalid_asset_request"):
        self.code = code
        super().__init__(message)


def resolve_character_source(root: str | Path) -> Path:
    """Return the directory containing the only complete Spine bundle in root."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise AssetImportRequestError(
            "Selected character directory does not exist",
            code="character_bundle_missing",
        )
    files = [path for path in base.rglob("*") if path.is_file()]
    atlas_keys = {
        (path.parent, path.stem.casefold())
        for path in files
        if path.suffix.casefold() == ".atlas"
    }
    bundles = [
        path
        for path in files
        if path.suffix.casefold() == ".skel"
        and (path.parent, path.stem.casefold()) in atlas_keys
    ]
    if not bundles:
        raise AssetImportRequestError(
            "Selected directory contains no matching .skel and .atlas pair",
            code="character_bundle_missing",
        )
    if len(bundles) != 1:
        raise AssetImportRequestError(
            "Selected directory contains more than one Spine character bundle",
            code="character_bundle_ambiguous",
        )
    return bundles[0].parent


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part.startswith(".") or part in {"out", "__pycache__"} for part in parts)


def discover_assets(root: str | Path, *, limit: int = 2000) -> list[dict[str, Any]]:
    """Discover supported source assets without writing to the source directory."""
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise AssetImportRequestError(f"素材目录不存在：{base}")

    files = [
        path
        for path in base.rglob("*")
        if path.is_file() and not _is_ignored(path, base)
    ]
    spine_bases = {
        path.with_suffix("")
        for path in files
        if path.suffix.casefold() == ".skel"
        and path.with_suffix(".atlas").is_file()
    }
    rows: list[dict[str, Any]] = []
    for spine in sorted(spine_bases, key=lambda path: str(path).casefold()):
        rows.append(
            {
                "kind": "character",
                "source": str(spine.parent),
                "stem": spine.name,
                "identifier_required": True,
            }
        )

    for path in sorted(files, key=lambda item: str(item).casefold()):
        suffix = path.suffix.casefold()
        stem_path = path.with_suffix("")
        if suffix in {".png", ".jpg", ".jpeg"}:
            if path.name.casefold().endswith("-avatar.png"):
                continue
            if stem_path in spine_bases:
                continue
            rows.append(
                {"kind": "background", "source": str(path), "stem": path.stem}
            )
        elif suffix in {".wav", ".ogg", ".mp3"}:
            rows.append({"kind": "sound", "source": str(path), "stem": path.stem})
        if len(rows) >= limit:
            break
    return rows[:limit]


def _validate(data: dict[str, Any]):
    kind = str(data.get("kind") or "").strip().casefold()
    source = str(data.get("source") or "").strip()
    if not source:
        raise AssetImportRequestError("source is required")
    if kind == "background":
        return validate_background(source)
    if kind == "sound":
        return validate_sound(source)
    if kind == "character":
        return validate_spine(
            source,
            identifier=str(data.get("identifier") or ""),
        )
    raise AssetImportRequestError(f"unsupported asset kind: {kind or '<empty>'}")


def _validation_payload(result) -> dict[str, Any]:
    candidate = result.candidate
    return {
        "ok": result.ok,
        "kind": candidate.kind if candidate else None,
        "stem": candidate.stem if candidate else None,
        "aa_key": candidate.aa_key if candidate else None,
        "source": str(candidate.source_path) if candidate else None,
        "sha256": candidate.sha256 if candidate else None,
        "metadata": candidate.metadata if candidate else {},
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
            }
            for issue in result.issues
        ],
    }


def validate_asset_request(data: dict[str, Any]) -> dict[str, Any]:
    """Validate one web/CLI import request without changing AA state."""
    return _validation_payload(_validate(data))


def register_asset_request(
    data: dict[str, Any],
    *,
    con=None,
    saves_root: str | Path | None = None,
    running_probe=None,
) -> dict[str, Any]:
    """Validate and register one asset into an explicitly named project."""
    project_value = str(data.get("project_dir") or "").strip()
    if not project_value:
        raise AssetImportRequestError("project_dir is required")
    try:
        target = resolve_project_target(project_value, saves_root=saves_root)
    except ValueError as exc:
        raise AssetImportRequestError(str(exc)) from exc
    result = _validate(data)
    if not result.ok or result.candidate is None:
        return {
            **_validation_payload(result),
            "status": "rejected",
            "project_dir": str(target.project_dir),
            "save_dir": str(target.save_dir),
            "install_paths": [],
            "manifest_paths": [],
            "changed": False,
        }

    kind = result.candidate.kind
    if kind == "background":
        registration = register_background(result, target, running_probe=running_probe)
    elif kind == "sound":
        registration = register_sound(result, target, running_probe=running_probe)
    else:
        display_name = str(data.get("display_name") or "").strip()
        if not display_name:
            raise AssetImportRequestError("display_name is required for character")
        reused = None
        if con is not None:
            from asset_catalog import migrate as migrate_asset_catalog

            migrate_asset_catalog(con)
            reused = con.execute(
                """SELECT aa_key,display_name,install_path,source_path,sha256,metadata_json
                   FROM asset_install
                   WHERE kind='character' AND status='registered' AND scope=?
                     AND (CAST(aa_key AS TEXT)=? OR sha256=?)
                   ORDER BY registered_at DESC LIMIT 1""",
                (
                    str(target.project_dir),
                    str(result.candidate.aa_key),
                    str(result.candidate.sha256 or ""),
                ),
            ).fetchone()
        if reused is not None:
            stored_sha = str(reused["sha256"] or "")
            same_content = bool(
                result.candidate.sha256
                and stored_sha
                and stored_sha.casefold() == str(result.candidate.sha256).casefold()
            )
            same_identifier = str(reused["aa_key"] or "") == str(result.candidate.aa_key)
            if same_identifier and not same_content:
                # Let the normal AA registry path produce the stable conflict
                # error for an identifier that points at different content.
                reused = None
            elif same_content and str(reused["display_name"] or "") != display_name:
                raise RegistrationConflictError(
                    f"Identifier {result.candidate.aa_key!r} 已用于不同身份或内容"
                )
        if reused is not None:
            return {
                **_validation_payload(result),
                "metadata": {
                    **result.candidate.metadata,
                    "display_name": display_name,
                    "nickname": str(data.get("nickname") or ""),
                },
                "ok": True,
                "status": "registered",
                "reused": True,
                "changed": False,
                "project_dir": str(target.project_dir),
                "save_dir": str(target.save_dir),
                "install_path": str(reused["install_path"] or ""),
                "source_path": str(reused["source_path"] or ""),
                "sha256": str(reused["sha256"] or result.candidate.sha256 or ""),
                "install_paths": [str(reused["install_path"] or "")],
                "manifest_paths": [],
            }
        registration = register_character(
            result,
            target,
            display_name=display_name,
            nickname=str(data.get("nickname") or ""),
            running_probe=running_probe,
        )

    labels = data.get("labels") or {}
    catalog_candidate = replace(
        result.candidate,
        metadata={
            **result.candidate.metadata,
            "catalog_source": "custom",
            "labels": labels,
            "manifest_paths": [str(path) for path in registration.manifest_paths],
        },
    )
    if con is not None:
        upsert_candidate(
            con,
            catalog_candidate,
            scope=str(target.project_dir),
            status="registered",
            install_path=str(registration.install_path),
            display_name=str(data.get("display_name") or result.candidate.stem),
        )
        _sync_legacy_catalog(
            con,
            catalog_candidate,
            display_name=str(data.get("display_name") or result.candidate.stem),
            nickname=str(data.get("nickname") or ""),
        )
    return {
        **_validation_payload(result),
        "metadata": {
            **result.candidate.metadata,
            **(
                {
                    "display_name": str(data.get("display_name") or ""),
                    "nickname": str(data.get("nickname") or ""),
                }
                if kind == "character"
                else {}
            ),
        },
        "ok": True,
        "status": "registered",
        "project_dir": str(target.project_dir),
        "save_dir": str(target.save_dir),
        "install_path": str(registration.install_path),
        "manifest_path": str(registration.manifest_path),
        "install_paths": [str(path) for path in registration.install_paths],
        "manifest_paths": [str(path) for path in registration.manifest_paths],
        "changed": registration.changed,
    }


def _sync_legacy_catalog(
    con,
    candidate,
    *,
    display_name: str,
    nickname: str,
) -> None:
    """Keep the existing browser/search tables in sync with registered assets."""
    labels = candidate.metadata.get("labels") or {}
    if candidate.kind == "background":
        con.execute(
            """
            INSERT INTO bg(name,hash,label,place,time,mood,tags,labeled_by)
            VALUES(?,?,?,?,?,?,?,'manual')
            ON CONFLICT(name) DO UPDATE SET
              hash=excluded.hash,
              label=COALESCE(excluded.label,bg.label),
              place=COALESCE(excluded.place,bg.place),
              time=COALESCE(excluded.time,bg.time),
              mood=COALESCE(excluded.mood,bg.mood),
              tags=COALESCE(excluded.tags,bg.tags)
            """,
            (
                candidate.stem,
                int(candidate.aa_key),
                labels.get("label"),
                labels.get("place"),
                labels.get("time"),
                labels.get("mood"),
                labels.get("tags"),
            ),
        )
    elif candidate.kind == "sound":
        con.execute(
            """
            INSERT INTO sound(name,label,tags,labeled_by)
            VALUES(?,?,?,'manual')
            ON CONFLICT(name) DO UPDATE SET
              label=COALESCE(excluded.label,sound.label),
              tags=COALESCE(excluded.tags,sound.tags)
            """,
            (candidate.stem, labels.get("label"), labels.get("tags")),
        )
    elif candidate.kind == "character":
        identifier = str(candidate.aa_key)
        con.execute(
            """
            INSERT INTO character(ident,name,club,spine,source)
            VALUES(?,?,?,NULL,'custom')
            ON CONFLICT(ident) DO UPDATE SET
              name=excluded.name,
              club=excluded.club,
              source='custom'
            """,
            (identifier, display_name, nickname),
        )
        for face in candidate.metadata.get("faces", []):
            con.execute(
                """
                INSERT INTO face(ident,face_id,raw,label,label_cn,source)
                VALUES(?,?,?,NULL,NULL,'atlas')
                ON CONFLICT(ident,face_id) DO UPDATE SET
                  raw=excluded.raw,
                  source='atlas'
                """,
                (identifier, str(face), str(face)),
            )
    con.commit()
