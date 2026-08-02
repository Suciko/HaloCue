# -*- coding: utf-8 -*-
"""Read-only discovery and safe import of assets from canonical AA history."""

from __future__ import annotations

import os
import uuid
import hashlib
import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Any

from aa_project_assets import AAProjectTarget, validate_windows_path_component
from aa_registry import (
    AssetRemovalError,
    AssetRegistrationError,
    RegistrationConflictError,
    register_background,
    register_character,
    register_sound,
    remove_registered_asset,
)
from asset_catalog import upsert_candidate
import asset_catalog
import assetdb
from asset_models import AssetCandidate, ValidationResult
from asset_validation import validate_background, validate_sound, validate_spine
from aa_registry import load_manifest
from story_workspace import StoryContext


_BACKGROUND_SUFFIXES = {".png", ".jpg", ".jpeg"}
_SOUND_SUFFIXES = {".wav", ".ogg", ".mp3"}


class HistoryAssetError(RuntimeError):
    """An expected historical-asset failure with a stable public code."""

    def __init__(
        self, code: str, message: str, status: int = 422,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


@dataclass(frozen=True)
class _HistoryRecord:
    project: str
    kind: str
    key: str
    display_name: str
    source_path: Path
    manifest_path: str
    identifier: str = ""
    nickname: str = ""
    fingerprint: str = ""
    content_sha: str = ""


@dataclass(frozen=True)
class _LibraryCopy:
    kind: str
    aa_key: str
    sha256: str
    scope: str
    chapter: str
    install_path: Path
    preview_path: Path | None


class HistoryAssetBrowser:
    """Server-local opaque token registry for historical AA project assets.

    Only ``aa_data/projects/<project>`` and ``aa_data/saves/<project>`` are
    searched.  Browser payloads contain tokens and display metadata, never a
    filesystem source path.
    """

    def __init__(self, *, aa_data: str | Path, max_asset_tokens: int = 512):
        self.aa_data = Path(aa_data).resolve()
        self._lock = threading.RLock()
        self._max_asset_tokens = max(1, int(max_asset_tokens))
        self._projects: dict[str, str] = {}
        self._project_tokens: dict[str, str] = {}
        self._assets: dict[str, _HistoryRecord] = {}
        self._record_tokens: dict[tuple[str, str, str, str], str] = {}
        self._last_seen: dict[str, int] = {}
        self._clock = 0
        self._library_copies: dict[str, _LibraryCopy] = {}
        self._library_copy_tokens: dict[tuple[str, str, str, str], str] = {}
        self._library_preview_tokens: dict[str, str] = {}
        self._library_db_path: str | None = None
        self._library_story_token = ""
        self._library_story_scope = ""

    @staticmethod
    def _token(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    def _roots(self, project: str) -> tuple[Path, ...]:
        # Project has priority if a (corrupt or stale) save carries a duplicate.
        roots = []
        for layout in ("projects", "saves"):
            root = self._canonical_project_root(layout, project)
            if root is not None:
                roots.append(root)
        return tuple(roots)

    def _canonical_project_root(self, layout: str, project: str) -> Path | None:
        """Resolve a child only when it remains below AA's canonical layout root."""
        parent = (self.aa_data / layout).resolve()
        child = parent / project
        if not child.is_dir():
            return None
        resolved = child.resolve()
        try:
            resolved.relative_to(parent)
        except ValueError:
            return None
        return resolved

    def _history_manifest(self, root: Path) -> dict | None:
        path = root / "manifest.json"
        if not path.is_file() or not self._inside(root, path):
            return None
        try:
            return load_manifest(root)
        except AssetRegistrationError:
            return None

    @staticmethod
    def _inside(root: Path, candidate: Path) -> bool:
        try:
            return os.path.commonpath((os.path.realpath(root), os.path.realpath(candidate))) == os.path.realpath(root)
        except ValueError:
            return False

    @classmethod
    def _manifest_file(cls, root: Path, value: object, *, folder: str) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        path = PureWindowsPath(value)
        if path.is_absolute() or not path.parts or path.parts[0].casefold() != folder.casefold():
            return None
        if any(part in {"", ".", ".."} for part in path.parts):
            return None
        candidate = root.joinpath(*path.parts)
        if not cls._inside(root, candidate) or not candidate.is_file():
            return None
        return candidate.resolve()

    @classmethod
    def _manifest_stem(cls, root: Path, value: object, *, folder: str) -> Path | None:
        """Resolve a manifest Spine base path without accepting traversal/symlinks."""
        if not isinstance(value, str) or not value:
            return None
        path = PureWindowsPath(value)
        if path.is_absolute() or not path.parts or path.parts[0].casefold() != folder.casefold():
            return None
        if any(part in {"", ".", ".."} for part in path.parts):
            return None
        base = root.joinpath(*path.parts)
        if not cls._inside(root, base):
            return None
        required = [
            base.with_suffix(".skel"), base.with_suffix(".atlas"),
            base.with_suffix(".png"), base.with_name(base.name + "-avatar.png"),
        ]
        if not all(cls._inside(root, item) and item.is_file() for item in required):
            return None
        return base.resolve()

    @classmethod
    def _character_source(cls, root: Path, spine_path: object, portrait_path: object) -> Path | None:
        """Validate both manifest path fields and their required AA relationship."""
        base = cls._manifest_stem(root, spine_path, folder="characters")
        portrait = cls._manifest_file(root, portrait_path, folder="characters")
        if base is None or portrait is None:
            return None
        expected_portrait = base.with_name(base.name + "-avatar.png").resolve()
        if portrait != expected_portrait:
            return None
        return base

    def list_projects(self) -> list[dict[str, str]]:
        with self._lock:
            names: set[str] = set()
            for parent in (self.aa_data / "projects", self.aa_data / "saves"):
                if not parent.is_dir():
                    continue
                for child in parent.iterdir():
                    if not child.is_dir():
                        continue
                    try:
                        names.add(validate_windows_path_component(child.name, label="AA project name"))
                    except ValueError:
                        continue
            result: list[dict[str, str]] = []
            for project in sorted(names, key=str.casefold):
                if not any(self._history_manifest(root) is not None for root in self._roots(project)):
                    continue
                token = self._project_tokens.get(project)
                if token is None:
                    token = self._token("history")
                    self._projects[token] = project
                self._project_tokens[project] = token
                result.append({"history_token": token, "project": project})
            active_projects = {row["project"] for row in result}
            for project, token in list(self._project_tokens.items()):
                if project not in active_projects:
                    self._project_tokens.pop(project, None)
                    self._projects.pop(token, None)
            return result

    def _project_for_token(self, token: str) -> str:
        try:
            return self._projects[token]
        except KeyError as exc:
            raise HistoryAssetError("invalid_history_token", "unknown history token", 404) from exc

    def _remember(self, record: _HistoryRecord) -> str:
        identity = (record.project, record.kind, record.key.casefold(), record.fingerprint)
        token = self._record_tokens.get(identity)
        if token is not None:
            self._touch(token)
            return token
        token = self._token("history-asset")
        self._assets[token] = record
        self._record_tokens[identity] = token
        self._touch(token)
        self._prune_assets()
        return token

    def _touch(self, token: str) -> None:
        self._clock += 1
        self._last_seen[token] = self._clock

    def _prune_assets(self) -> None:
        while len(self._assets) > self._max_asset_tokens:
            token = min(self._assets, key=lambda item: self._last_seen.get(item, 0))
            record = self._assets.pop(token)
            self._last_seen.pop(token, None)
            self._record_tokens.pop(
                (record.project, record.kind, record.key.casefold(), record.fingerprint), None
            )

    def _drop_token(self, token: str) -> None:
        record = self._assets.pop(token, None)
        self._last_seen.pop(token, None)
        if record is not None:
            self._record_tokens.pop(
                (record.project, record.kind, record.key.casefold(), record.fingerprint), None
            )

    def _remember_library_copy(self, copy: _LibraryCopy) -> str:
        identity = (copy.kind, copy.aa_key, copy.sha256, copy.scope)
        token = self._library_copy_tokens.get(identity)
        if token is None:
            token = self._token("copy")
            self._library_copies[token] = copy
            self._library_copy_tokens[identity] = token
        return token

    def _preview_token(self, copy_token: str) -> str:
        for token, known_copy_token in self._library_preview_tokens.items():
            if known_copy_token == copy_token:
                return token
        token = self._token("preview")
        self._library_preview_tokens[token] = copy_token
        return token

    @staticmethod
    def _catalog_database_path(con) -> str | None:
        for row in con.execute("PRAGMA database_list"):
            if row[1] == "main" and row[2]:
                return str(row[2])
        return None

    @staticmethod
    def _library_copy_from_row(row) -> _LibraryCopy:
        metadata = asset_catalog._safe_metadata(row["metadata_json"])
        install_path = Path(str(row["install_path"] or "")).resolve()
        preview = asset_catalog._preview_path(str(row["kind"]), str(install_path), metadata)
        if preview is not None:
            preview = preview.resolve()
        scope = str(row["scope"] or "")
        return _LibraryCopy(
            kind=str(row["kind"]), aa_key=str(row["aa_key"]), sha256=str(row["sha256"]),
            scope=scope, chapter=Path(scope).name or "未命名章节",
            install_path=install_path, preview_path=preview,
        )

    @staticmethod
    def _preview_mime(kind: str, path: Path) -> str | None:
        return {
            "background": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"},
            "character": {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"},
            "sound": {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"},
        }.get(kind, {}).get(path.suffix.casefold())

    def list_library(self, con, *, current_context: StoryContext | None) -> dict:
        """Aggregate registered custom copies and issue process-local workbench tokens."""
        with self._lock:
            self._library_db_path = self._catalog_database_path(con)
            current_scope = str(current_context.project_dir) if current_context else ""
            if current_context is not None:
                self._library_story_token = current_context.story_token
                self._library_story_scope = current_scope
            groups: dict[tuple[str, str, str], dict[str, Any]] = {}
            profiles = {
                (str(row["kind"]), str(row["aa_key"]), str(row["sha256"])): row
                for row in con.execute(
                    "SELECT kind,aa_key,sha256,asset_role,series_name FROM asset_library_profile"
                )
            }
            for row in asset_catalog.library_custom_rows(con):
                copy = self._library_copy_from_row(row)
                key = (copy.kind, copy.aa_key, copy.sha256)
                profile = profiles.get(key)
                item = groups.setdefault(key, {
                    "kind": copy.kind,
                    "aa_key": asset_catalog._numeric_key(copy.aa_key),
                    "sha256": copy.sha256,
                    "name": asset_catalog._safe_catalog_text(row["display_name"], fallback=copy.aa_key),
                    "asset_role": str(profile["asset_role"]) if profile else "chapter_only",
                    "series_name": str(profile["series_name"]) if profile else "",
                    "details": asset_catalog._library_item_details(
                        copy.kind, asset_catalog._safe_metadata(row["metadata_json"])
                    ),
                    "registered_in_current": False,
                    "preview_available": False,
                    "preview_token": "",
                    "copies": [],
                })
                copy_token = self._remember_library_copy(copy)
                item["copies"].append({
                    "chapter": copy.chapter,
                    "is_current": copy.scope == current_scope,
                    "copy_token": copy_token,
                })
                item["registered_in_current"] = item["registered_in_current"] or copy.scope == current_scope
                if copy.preview_path is not None and self._inside(copy.install_path, copy.preview_path):
                    item["preview_available"] = True
                    item["preview_token"] = self._preview_token(copy_token)
            out = {"characters": [], "backgrounds": [], "sounds": [], "bgms": []}
            bucket = {"character": "characters", "background": "backgrounds", "sound": "sounds"}
            for item in groups.values():
                item["copies"].sort(key=lambda copy: (not copy["is_current"], copy["chapter"].casefold()))
                item["copy_count"] = len(item["copies"])
                out[bucket[item["kind"]]].append(item)
            for values in out.values():
                values.sort(key=lambda item: (item["series_name"].casefold(), item["name"].casefold()))
            out["counts"] = {key: len(out[key]) for key in out}
            return out

    def _reload_library_copy(self, copy: _LibraryCopy) -> _LibraryCopy | None:
        if not self._library_db_path:
            return None
        con = assetdb.connect(self._library_db_path)
        try:
            row = con.execute(
                """
                SELECT kind,aa_key,sha256,scope,status,metadata_json,install_path
                FROM asset_install WHERE kind=? AND aa_key=? AND sha256=? AND scope=?
                """,
                (copy.kind, copy.aa_key, copy.sha256, copy.scope),
            ).fetchone()
            if not row:
                return None
            metadata = asset_catalog._safe_metadata(row["metadata_json"])
            if not asset_catalog._is_story_custom_row(row, metadata):
                return None
            current = self._library_copy_from_row(row)
            if current.preview_path is None or not self._inside(current.install_path, current.preview_path):
                return current
            if current.kind == "background":
                result = validate_background(current.preview_path)
            elif current.kind == "sound":
                result = validate_sound(current.preview_path)
            else:
                files = metadata.get("files") or {}
                stem = Path(str(files.get("skel") or "asset.skel")).stem
                result = validate_spine(current.install_path / stem, identifier=current.aa_key)
            if not result.ok or result.candidate is None or result.candidate.sha256 != current.sha256:
                return replace(current, sha256="")
            return current
        finally:
            con.close()

    def preview_path(self, preview_token: str) -> tuple[Path, str]:
        """Revalidate a catalog copy and return only a safe preview stream target."""
        with self._lock:
            copy_token = self._library_preview_tokens.get(preview_token)
            copy = self._library_copies.get(copy_token or "")
            if copy is None:
                raise HistoryAssetError("invalid_preview_token", "asset preview not found", 404)
            current = self._reload_library_copy(copy)
            if current is None or current.sha256 != copy.sha256 or current.preview_path is None:
                raise HistoryAssetError("preview_changed", "asset preview changed; refresh the workbench", 409)
            if not self._inside(current.install_path, current.preview_path):
                raise HistoryAssetError("preview_outside_copy", "asset preview not found", 404)
            mime = self._preview_mime(current.kind, current.preview_path)
            if not mime or not current.preview_path.is_file():
                raise HistoryAssetError("asset_preview_missing", "asset preview not found", 404)
            return current.preview_path, mime

    def _library_copy_for_token(self, copy_token: str) -> _LibraryCopy:
        try:
            copy = self._library_copies[copy_token]
        except KeyError as exc:
            raise HistoryAssetError("invalid_library_copy_token", "library copy is not available", 404) from exc
        current = self._reload_library_copy(copy)
        if current is None:
            raise HistoryAssetError("library_copy_missing", "library copy is no longer available", 410)
        if current != copy:
            raise HistoryAssetError("library_copy_changed", "library copy changed; refresh the workbench", 409)
        return current

    def _history_token_for_copy(self, copy: _LibraryCopy) -> str:
        """Re-discover the installed source through its AA manifest before copying it."""
        scope = Path(copy.scope).resolve()
        try:
            project = validate_windows_path_component(scope.name, label="AA project name")
        except ValueError as exc:
            raise HistoryAssetError("library_copy_missing", "library copy is no longer available", 410) from exc
        if scope not in self._roots(project):
            raise HistoryAssetError("library_copy_missing", "library copy is no longer available", 410)
        for record in self._records(project):
            record_key = record.identifier or record.key
            installed_source = record.source_path.parent if record.kind == "character" else record.source_path
            if (
                record.kind == copy.kind
                and str(record_key).casefold() == copy.aa_key.casefold()
                and installed_source == copy.install_path
            ):
                if record.content_sha != copy.sha256:
                    raise HistoryAssetError("library_copy_changed", "library copy changed; refresh the workbench", 409)
                return self._remember(record)
        raise HistoryAssetError("library_copy_missing", "library copy is no longer available", 410)

    def copy_library_asset(
        self,
        copy_token: str,
        story_context: StoryContext,
        *,
        con=None,
        running_probe=None,
    ) -> dict[str, Any]:
        """Copy one revalidated library source through the existing AA transaction."""
        with self._lock:
            if (
                story_context.story_token != self._library_story_token
                or str(story_context.project_dir) != self._library_story_scope
            ):
                raise HistoryAssetError(
                    "story_context_changed", "the workbench story context changed", 409
                )
            copy = self._library_copy_for_token(copy_token)
            history_token = self._history_token_for_copy(copy)
            result = self.copy_to_story(
                history_token, story_context, con=con, running_probe=running_probe
            )
            state = "registered" if result["changed"] else "already_registered"
            asset = {**result, "aa_key": copy.aa_key}
            return {"state": state, "asset": asset, **result}

    def _copy_references(self, copy: _LibraryCopy, draft_store) -> list[dict]:
        if draft_store is None or not draft_store.base_dir.is_dir():
            return []
        references = []
        for draft_dir in draft_store.base_dir.iterdir():
            session_path = draft_dir / "session.json"
            if not draft_dir.is_dir() or not session_path.is_file():
                continue
            try:
                session = json.loads(session_path.read_text(encoding="utf-8"))
                if str(session.get("project") or "") != copy.chapter:
                    continue
                found = draft_store.find_asset_references(
                    token=draft_dir.name, kind=copy.kind, aa_key=copy.aa_key
                )
            except (OSError, ValueError, FileNotFoundError):
                continue
            for reference in found:
                references.append({
                    **reference,
                    "draft_token": draft_dir.name,
                    "draft_label": copy.chapter,
                })
        return references

    def describe_copy(self, copy_token: str, *, con, draft_store=None) -> dict:
        """Return a browser-safe description and current draft references."""
        with self._lock:
            copy = self._library_copy_for_token(copy_token)
            row = con.execute(
                """
                SELECT display_name FROM asset_install
                WHERE kind=? AND aa_key=? AND sha256=? AND scope=?
                """,
                (copy.kind, copy.aa_key, copy.sha256, copy.scope),
            ).fetchone()
            return {
                "copy_token": copy_token,
                "kind": copy.kind,
                "aa_key": copy.aa_key,
                "sha256": copy.sha256,
                "name": str(row["display_name"] or copy.aa_key) if row else copy.aa_key,
                "chapter": copy.chapter,
                "references": self._copy_references(copy, draft_store),
            }

    def describe_preview_copies(self, preview_token: str, *, con, draft_store=None) -> dict:
        with self._lock:
            representative = self._library_preview_tokens.get(preview_token)
            copy = self._library_copies.get(representative or "")
            if copy is None:
                raise HistoryAssetError(
                    "invalid_preview_token", "asset preview is not available", 404
                )
            copies = [
                self.describe_copy(token, con=con, draft_store=draft_store)
                for token, candidate in self._library_copies.items()
                if (candidate.kind, candidate.aa_key, candidate.sha256)
                == (copy.kind, copy.aa_key, copy.sha256)
            ]
            copies.sort(key=lambda item: item["chapter"].casefold())
            return {
                "kind": copy.kind,
                "aa_key": copy.aa_key,
                "sha256": copy.sha256,
                "copies": copies,
            }

    def remove_copy(
        self,
        copy_token: str,
        *,
        con,
        draft_store=None,
        running_probe=None,
        confirm_chapter: str | None = None,
    ) -> dict:
        """Remove one revalidated chapter copy and its matching catalog row."""
        with self._lock:
            copy = self._library_copy_for_token(copy_token)
            if confirm_chapter is not None and str(confirm_chapter) != copy.chapter:
                raise HistoryAssetError(
                    "copy_confirmation_mismatch", "confirmed chapter does not match copy", 409
                )
            references = self._copy_references(copy, draft_store)
            if references:
                raise HistoryAssetError(
                    "asset_in_use",
                    "asset is referenced by a draft",
                    409,
                    {"references": references},
                )
            project_dir = self._canonical_project_root("projects", copy.chapter)
            if project_dir is None or project_dir != Path(copy.scope).resolve():
                raise HistoryAssetError(
                    "library_copy_missing", "library copy is no longer available", 410
                )
            target = AAProjectTarget(
                project_dir,
                self.aa_data / "saves" / copy.chapter,
                copy.chapter,
            )

            def remove_catalog(_result) -> None:
                asset_catalog.remove_story_copy(
                    con,
                    scope=copy.scope,
                    kind=copy.kind,
                    aa_key=copy.aa_key,
                    sha256=copy.sha256,
                )

            try:
                remove_registered_asset(
                    target,
                    kind=copy.kind,
                    aa_key=copy.aa_key,
                    expected_sha256=copy.sha256,
                    running_probe=running_probe,
                    after_remove=remove_catalog,
                )
            except AssetRemovalError as exc:
                code = "aa_running" if "aa_running" in str(exc) else "asset_remove_failed"
                status = 409 if code == "aa_running" else 422
                raise HistoryAssetError(code, "asset copy could not be removed", status) from exc
            self._library_copies.pop(copy_token, None)
            self._library_copy_tokens.pop(
                (copy.kind, copy.aa_key, copy.sha256, copy.scope), None
            )
            return {
                "removed": True,
                "kind": copy.kind,
                "aa_key": copy.aa_key,
                "sha256": copy.sha256,
                "chapter": copy.chapter,
            }

    @staticmethod
    def _file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _signed(self, record: _HistoryRecord) -> _HistoryRecord:
        files = [record.source_path]
        if record.kind == "character":
            base = record.source_path
            files = [
                base.with_suffix(".skel"), base.with_suffix(".atlas"), base.with_suffix(".png"),
                base.with_name(base.name + "-avatar.png"),
            ]
        content_sha = self._candidate_content_sha(record)
        payload = {
            "project": record.project, "kind": record.kind, "key": record.key,
            "display_name": record.display_name, "manifest_path": record.manifest_path,
            "identifier": record.identifier, "nickname": record.nickname,
            "files": [(path.name, self._file_hash(path)) for path in files],
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return replace(record, fingerprint=fingerprint, content_sha=content_sha)

    def _candidate_content_sha(self, record: _HistoryRecord) -> str:
        """Compute the same content hash shape returned by the validators."""
        if record.kind != "character":
            return self._file_hash(record.source_path)
        digest = hashlib.sha256()
        base = record.source_path
        for path in (
            base.with_suffix(".skel"), base.with_suffix(".atlas"), base.with_suffix(".png"),
            base.with_name(base.name + "-avatar.png"),
        ):
            digest.update(path.name.encode("utf-8"))
            digest.update(bytes.fromhex(self._file_hash(path)))
        return digest.hexdigest()

    def _records(self, project: str) -> list[_HistoryRecord]:
        records: list[_HistoryRecord] = []
        seen: set[tuple[str, str]] = set()
        for root in self._roots(project):
            manifest = self._history_manifest(root)
            if manifest is None:
                continue
            for value in manifest["BgOverrides"]:
                source = self._manifest_file(root, value, folder="bgs")
                if source is None or source.suffix.casefold() not in _BACKGROUND_SUFFIXES:
                    continue
                key = source.stem
                if ("background", key.casefold()) not in seen:
                    seen.add(("background", key.casefold()))
                    records.append(self._signed(_HistoryRecord(project, "background", key, key, source, str(value))))
            for value in manifest["SoundOverrides"]:
                source = self._manifest_file(root, value, folder="sounds")
                if source is None or source.suffix.casefold() not in _SOUND_SUFFIXES:
                    continue
                key = source.stem
                if ("sound", key.casefold()) not in seen:
                    seen.add(("sound", key.casefold()))
                    records.append(self._signed(_HistoryRecord(project, "sound", key, key, source, str(value))))
            for entry in manifest["CharacterOverrides"]:
                if not isinstance(entry, dict):
                    continue
                identifier = str(entry.get("Identifier") or "")
                try:
                    validate_windows_path_component(identifier, label="character Identifier")
                except ValueError:
                    continue
                source = self._character_source(
                    root, entry.get("SpinePortraitPath"), entry.get("SmallPortraitPath")
                )
                if source is None or ("character", identifier.casefold()) in seen:
                    continue
                seen.add(("character", identifier.casefold()))
                records.append(self._signed(_HistoryRecord(
                    project, "character", identifier,
                    str(entry.get("Name") or identifier), source,
                    str(entry.get("SpinePortraitPath") or ""), identifier,
                    str(entry.get("Nickname") or ""),
                )))
            # BgmOverrides deliberately stays inaccessible until Task 1/2 has a
            # verified native contract and mirrored registration implementation.
        return records

    def list_assets(self, history_token: str) -> list[dict[str, str]]:
        with self._lock:
            project = self._project_for_token(history_token)
            rows = []
            records = self._records(project)
            active = {
                (record.project, record.kind, record.key.casefold(), record.fingerprint)
                for record in records
            }
            for token, prior in list(self._assets.items()):
                identity = (prior.project, prior.kind, prior.key.casefold(), prior.fingerprint)
                if prior.project == project and identity not in active:
                    self._drop_token(token)
            for record in records:
                rows.append({
                    "history_asset_token": self._remember(record),
                    "kind": record.kind,
                    "name": record.display_name,
                    "aa_key": record.identifier or record.key,
                    "project": record.project,
                })
            return rows

    def asset_token(self, history: dict[str, str], *, kind: str, key: str) -> str:
        with self._lock:
            token = str(history.get("history_token") or "")
            for row in self.list_assets(token):
                if row["kind"] == kind and str(row["aa_key"]).casefold() == str(key).casefold():
                    return row["history_asset_token"]
            raise HistoryAssetError("history_asset_not_found", "history asset not found", 404)

    def _current_record(self, token: str) -> _HistoryRecord:
        with self._lock:
            try:
                record = self._assets[token]
            except KeyError as exc:
                raise HistoryAssetError("invalid_history_asset_token", "unknown history asset token", 404) from exc
            self._touch(token)
            # Re-discover rather than trusting an old path.  A matching path
            # with another signed fingerprint is stale, not safe to copy.
            current_records = self._records(record.project)
            for current in current_records:
                if current.kind == record.kind and current.key.casefold() == record.key.casefold() and current.source_path == record.source_path:
                    if current.fingerprint != record.fingerprint:
                        raise HistoryAssetError("history_asset_stale", "historical asset changed", 410)
                    return current
            raise HistoryAssetError("history_source_missing", "historical source is no longer available", 410)

    def _validated(self, record: _HistoryRecord) -> ValidationResult:
        try:
            current_sha = self._candidate_content_sha(record)
        except FileNotFoundError as exc:
            raise HistoryAssetError(
                "history_source_missing", "historical source is no longer available", 410
            ) from exc
        if current_sha != record.content_sha:
            raise HistoryAssetError("history_asset_stale", "historical asset changed", 410)
        if record.kind == "background":
            result = validate_background(record.source_path)
        elif record.kind == "sound":
            result = validate_sound(record.source_path)
        elif record.kind == "character":
            result = validate_spine(record.source_path, identifier=record.identifier)
        else:
            raise HistoryAssetError("validation_failed", "unsupported historical asset type")
        if result.candidate is not None and result.candidate.sha256 != record.content_sha:
            raise HistoryAssetError("history_asset_stale", "historical asset changed", 410)
        return result

    @staticmethod
    def _target(context: StoryContext) -> AAProjectTarget:
        return AAProjectTarget(context.project_dir, context.save_dir, context.project)

    def copy_to_story(self, history_asset_token: str, story_context: StoryContext, *, con=None, running_probe=None) -> dict[str, Any]:
        record = self._current_record(history_asset_token)
        result = self._validated(record)
        if not result.ok or result.candidate is None:
            raise HistoryAssetError("validation_failed", "historical asset failed current validation")
        target = self._target(story_context)
        candidate: AssetCandidate = result.candidate

        def write_catalog(registration) -> None:
            if con is None:
                return
            catalog_candidate = AssetCandidate(
                kind=candidate.kind, source_path=candidate.source_path, stem=candidate.stem,
                aa_key=candidate.aa_key, sha256=candidate.sha256,
                metadata={
                    **candidate.metadata,
                    "catalog_source": "history_import",
                    "source_project": record.project,
                    "manifest_paths": [str(path) for path in registration.manifest_paths],
                },
            )
            upsert_candidate(
                con, catalog_candidate, scope=str(target.project_dir), status="registered",
                install_path=str(registration.install_path), display_name=record.display_name,
            )

        try:
            if record.kind == "background":
                registration = register_background(
                    result, target, running_probe=running_probe, after_register=write_catalog
                )
            elif record.kind == "sound":
                registration = register_sound(
                    result, target, running_probe=running_probe, after_register=write_catalog
                )
            else:
                registration = register_character(
                    result, target, display_name=record.display_name,
                    nickname=record.nickname, running_probe=running_probe, after_register=write_catalog,
                )
        except RegistrationConflictError as exc:
            raise HistoryAssetError(
                "same_name_different_content",
                "an asset with the same name has different content",
                409,
            ) from exc
        except AssetRegistrationError as exc:
            text = str(exc)
            if "aa_running" in text:
                raise HistoryAssetError("aa_running", "AzureArchive must be closed", 409) from exc
            raise HistoryAssetError(
                "validation_failed", "historical asset registration failed", 422
            ) from exc
        except Exception as exc:
            raise HistoryAssetError("catalog_failed", "asset copy could not be completed", 500) from exc
        return {
            "kind": record.kind,
            "name": record.display_name,
            "aa_key": registration.aa_key,
            "source_project": record.project,
            "install_path": str(registration.install_path),
            "changed": registration.changed,
        }
