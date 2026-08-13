# -*- coding: utf-8 -*-
"""Server-side identity and recent-history storage for one AA story workspace."""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from aa_project_assets import validate_windows_path_component


DEFAULT_BGM_POLICY = {"enabled": False, "arrangement": "manual", "bgmId": 999}


def normalize_bgm_policy(policy: object | None) -> dict[str, object]:
    """Return the complete, safe policy shape while retaining valid known values."""
    normalized: dict[str, object] = dict(DEFAULT_BGM_POLICY)
    if not isinstance(policy, dict):
        return normalized
    if isinstance(policy.get("enabled"), bool):
        normalized["enabled"] = policy["enabled"]
    if isinstance(policy.get("arrangement"), str) and policy["arrangement"].strip():
        normalized["arrangement"] = policy["arrangement"]
    bgm_id = policy.get("bgmId")
    if isinstance(bgm_id, int) and not isinstance(bgm_id, bool):
        normalized["bgmId"] = bgm_id
    return normalized


@dataclass(frozen=True)
class StoryContext:
    story_token: str
    project: str
    project_dir: Path
    save_dir: Path
    source_path: Path | None
    latest_draft_token: str | None
    bgm_default: dict
    preflight_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class StorySummary:
    story_token: str
    project: str
    source_name: str
    last_opened_at: str
    latest_draft_token: str | None
    source_display: str = ""
    source_type: str = ""
    source_size: int | None = None
    source_modified: str = ""


def _source_metadata(source_path: Path | None) -> dict[str, Any]:
    """Return bounded source metadata suitable for the browser workbench."""
    if source_path is None:
        return {
            "source_name": "",
            "source_display": "",
            "source_type": "",
            "source_size": None,
            "source_modified": "",
        }
    parts = [part for part in source_path.parts if part not in {source_path.anchor, ""}]
    tail = parts[-4:] if len(parts) > 4 else parts
    display = " / ".join(tail)
    if len(parts) > len(tail):
        display = "… / " + display
    source_type = "Markdown" if source_path.suffix.casefold() == ".md" else "文本文件"
    size = None
    modified = ""
    try:
        stat = source_path.stat()
        size = int(stat.st_size)
        modified = _datetime.datetime.fromtimestamp(
            stat.st_mtime, tz=_datetime.timezone.utc
        ).isoformat()
    except OSError:
        pass
    return {
        "source_name": source_path.name,
        "source_display": display,
        "source_type": source_type,
        "source_size": size,
        "source_modified": modified,
    }


def _source_fingerprint(source_path: Path | None) -> dict[str, Any] | None:
    if source_path is None:
        return None
    try:
        stat = source_path.stat()
        digest = hashlib.sha256()
        with source_path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return {
        "size": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
        "sha256": digest.hexdigest(),
    }


def _safe_preflight_snapshot(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = value.get("result")
    fingerprint = value.get("fingerprint")
    if not isinstance(result, dict) or not isinstance(fingerprint, dict):
        return None
    if not isinstance(fingerprint.get("size"), int):
        return None
    if not isinstance(fingerprint.get("modified_ns"), int):
        return None
    if not isinstance(fingerprint.get("sha256"), str):
        return None
    try:
        clean_result = json.loads(json.dumps(result, ensure_ascii=False))
    except (TypeError, ValueError):
        return None
    clean_result.pop("ai_diagnostics", None)
    return {
        "result": clean_result,
        "fingerprint": {
            "size": fingerprint["size"],
            "modified_ns": fingerprint["modified_ns"],
            "sha256": fingerprint["sha256"],
        },
        "saved_at": str(value.get("saved_at") or ""),
        "approved": bool(value.get("approved", False)),
    }


def _public_preflight_snapshot(context: StoryContext) -> dict[str, Any] | None:
    snapshot = _safe_preflight_snapshot(context.preflight_snapshot)
    if snapshot is None:
        return None
    current = _source_fingerprint(context.source_path)
    return {
        "state": "fresh" if current is not None and current == snapshot["fingerprint"] else "stale",
        "result": snapshot["result"],
        "saved_at": snapshot["saved_at"],
        "approved": snapshot["approved"],
    }


def public_story_context(context: StoryContext) -> dict[str, Any]:
    """Serialize only display-safe fields; filesystem locations remain server-only."""
    return {
        "story_token": context.story_token,
        "project": context.project,
        **_source_metadata(context.source_path),
        "latest_draft_token": context.latest_draft_token,
        "bgm_default": dict(context.bgm_default),
        "preflight_snapshot": _public_preflight_snapshot(context),
    }


def public_story_summary(summary: StorySummary) -> dict[str, Any]:
    return {
        "story_token": summary.story_token,
        "project": summary.project,
        "source_name": summary.source_name,
        "source_display": summary.source_display or summary.source_name,
        "source_type": summary.source_type,
        "source_size": summary.source_size,
        "source_modified": summary.source_modified,
        "last_opened_at": summary.last_opened_at,
        "latest_draft_token": summary.latest_draft_token,
    }


class StoryWorkspaceRegistry:
    """Maintains opaque in-process story tokens and an atomic recent-story index."""

    def __init__(self, index_path: str | Path, aa_data: str | Path):
        self.index_path = Path(index_path).resolve()
        self.aa_data = Path(aa_data).resolve()
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._contexts: dict[str, StoryContext] = {}
        self._tokens_by_project: dict[str, str] = {}
        self._load()

    @staticmethod
    def _now() -> str:
        return _datetime.datetime.now(_datetime.timezone.utc).isoformat()

    @staticmethod
    def _project_key(project: str) -> str:
        return project.casefold()

    @staticmethod
    def _safe_source_path(value: object) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        return Path(value).resolve()

    @staticmethod
    def _safe_story_token(value: object) -> str | None:
        if not isinstance(value, str) or not value.startswith("story-"):
            return None
        suffix = value[6:]
        if len(suffix) != 32 or any(char not in "0123456789abcdef" for char in suffix):
            return None
        return value

    def _context_from_record(self, record: dict[str, Any], token: str | None = None) -> StoryContext:
        project = validate_windows_path_component(record["project"], label="project name")
        source_path = self._safe_source_path(record.get("source_path"))
        story_token = token or self._safe_story_token(record.get("story_token")) or f"story-{uuid.uuid4().hex}"
        return StoryContext(
            story_token=story_token,
            project=project,
            project_dir=(self.aa_data / "projects" / project).resolve(),
            save_dir=(self.aa_data / "saves" / project).resolve(),
            source_path=source_path,
            latest_draft_token=record.get("latest_draft_token") or None,
            bgm_default=normalize_bgm_policy(None),
            preflight_snapshot=_safe_preflight_snapshot(record.get("preflight_snapshot")),
        )

    def _load(self) -> None:
        if not self.index_path.is_file():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            records = raw.get("stories", []) if isinstance(raw, dict) else []
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(records, list):
            return

        seen: set[str] = set()
        migrated = False
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                context = self._context_from_record(record)
            except (KeyError, TypeError, ValueError):
                continue
            key = self._project_key(context.project)
            if key in seen:
                continue
            seen.add(key)
            if self._safe_story_token(record.get("story_token")) != context.story_token:
                migrated = True
            self._records.append({
                "story_token": context.story_token,
                "project": context.project,
                "source_path": str(context.source_path) if context.source_path else "",
                "last_opened_at": str(record.get("last_opened_at") or self._now()),
                "latest_draft_token": context.latest_draft_token,
                "preflight_snapshot": context.preflight_snapshot,
            })
            self._contexts[context.story_token] = context
            self._tokens_by_project[key] = context.story_token
        if migrated and self._records:
            self._persist()

    def _persist(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"stories": self._records}
        temp_path = self.index_path.with_name(
            f".{self.index_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp_path, self.index_path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _replace_record(self, context: StoryContext, *, last_opened_at: str) -> None:
        key = self._project_key(context.project)
        self._records = [
            record for record in self._records
            if self._project_key(str(record.get("project") or "")) != key
        ]
        self._records.insert(0, {
            "story_token": context.story_token,
            "project": context.project,
            "source_path": str(context.source_path) if context.source_path else "",
            "last_opened_at": last_opened_at,
            "latest_draft_token": context.latest_draft_token,
            "preflight_snapshot": context.preflight_snapshot,
        })

    def open_path(self, path: str | Path, project: str | None = None) -> StoryContext:
        source_path = Path(path).resolve()
        selected_project = validate_windows_path_component(
            project if project is not None else source_path.stem,
            label="project name",
        )
        key = self._project_key(selected_project)
        with self._lock:
            old_token = self._tokens_by_project.get(key)
            old_context = self._contexts.get(old_token or "")
            context = StoryContext(
                story_token=old_token or f"story-{uuid.uuid4().hex}",
                project=selected_project,
                project_dir=(self.aa_data / "projects" / selected_project).resolve(),
                save_dir=(self.aa_data / "saves" / selected_project).resolve(),
                source_path=source_path,
                latest_draft_token=(
                    old_context.latest_draft_token if old_context is not None else None
                ),
                bgm_default=normalize_bgm_policy(None),
                preflight_snapshot=(
                    old_context.preflight_snapshot if old_context is not None else None
                ),
            )
            self._contexts[context.story_token] = context
            self._tokens_by_project[key] = context.story_token
            self._replace_record(context, last_opened_at=self._now())
            self._persist()
            return context

    def list_recent(self) -> list[StorySummary]:
        with self._lock:
            summaries: list[StorySummary] = []
            for record in self._records:
                key = self._project_key(record["project"])
                token = self._tokens_by_project[key]
                source_path = self._safe_source_path(record.get("source_path"))
                metadata = _source_metadata(source_path)
                summaries.append(StorySummary(
                    story_token=token,
                    project=record["project"],
                    source_name=metadata["source_name"],
                    last_opened_at=record["last_opened_at"],
                    latest_draft_token=record.get("latest_draft_token") or None,
                    source_display=metadata["source_display"],
                    source_type=metadata["source_type"],
                    source_size=metadata["source_size"],
                    source_modified=metadata["source_modified"],
                ))
            return summaries

    def resolve_story_token(self, token: str) -> StoryContext:
        with self._lock:
            try:
                return self._contexts[token]
            except KeyError as exc:
                raise KeyError("unknown story token") from exc

    def set_latest_draft_token(self, story_token: str, draft_token: str | None) -> StoryContext:
        with self._lock:
            prior = self.resolve_story_token(story_token)
            updated = StoryContext(
                story_token=prior.story_token,
                project=prior.project,
                project_dir=prior.project_dir,
                save_dir=prior.save_dir,
                source_path=prior.source_path,
                latest_draft_token=draft_token or None,
                bgm_default=normalize_bgm_policy(None),
                preflight_snapshot=prior.preflight_snapshot,
            )
            self._contexts[story_token] = updated
            self._replace_record(updated, last_opened_at=self._now())
            self._persist()
            return updated

    def set_preflight_snapshot(self, story_token: str, result: dict[str, Any]) -> StoryContext:
        with self._lock:
            prior = self.resolve_story_token(story_token)
            fingerprint = _source_fingerprint(prior.source_path)
            if fingerprint is None:
                raise ValueError("story source is unavailable")
            snapshot = _safe_preflight_snapshot({
                "result": result,
                "fingerprint": fingerprint,
                "saved_at": self._now(),
                "approved": False,
            })
            if snapshot is None:
                raise ValueError("invalid preflight snapshot")
            updated = StoryContext(
                story_token=prior.story_token,
                project=prior.project,
                project_dir=prior.project_dir,
                save_dir=prior.save_dir,
                source_path=prior.source_path,
                latest_draft_token=prior.latest_draft_token,
                bgm_default=normalize_bgm_policy(prior.bgm_default),
                preflight_snapshot=snapshot,
            )
            self._contexts[story_token] = updated
            self._replace_record(updated, last_opened_at=self._now())
            self._persist()
            return updated

    def set_preflight_approved(self, story_token: str, approved: bool) -> StoryContext:
        with self._lock:
            prior = self.resolve_story_token(story_token)
            snapshot = _safe_preflight_snapshot(prior.preflight_snapshot)
            if snapshot is None:
                raise ValueError("preflight snapshot is unavailable")
            snapshot["approved"] = bool(approved)
            updated = StoryContext(
                story_token=prior.story_token,
                project=prior.project,
                project_dir=prior.project_dir,
                save_dir=prior.save_dir,
                source_path=prior.source_path,
                latest_draft_token=prior.latest_draft_token,
                bgm_default=normalize_bgm_policy(prior.bgm_default),
                preflight_snapshot=snapshot,
            )
            self._contexts[story_token] = updated
            self._replace_record(updated, last_opened_at=self._now())
            self._persist()
            return updated

    def update_preflight_mapping(self, story_token: str, characters: list[dict[str, Any]]) -> StoryContext:
        """Persist selected character identities inside the existing snapshot."""
        with self._lock:
            prior = self.resolve_story_token(story_token)
            snapshot = _safe_preflight_snapshot(prior.preflight_snapshot)
            if snapshot is None or not isinstance(characters, list):
                raise ValueError("invalid preflight mapping")
            snapshot["result"]["characters"] = json.loads(json.dumps(characters, ensure_ascii=False))
            updated = replace(prior, preflight_snapshot=snapshot)
            self._contexts[story_token] = updated
            self._replace_record(updated, last_opened_at=self._now())
            self._persist()
            return updated

    def bind_preflight_background(
        self, story_token: str, selector: dict[str, Any], binding: dict[str, Any]
    ) -> StoryContext:
        """Bind one verified background to one exact need in the saved snapshot."""
        with self._lock:
            prior = self.resolve_story_token(story_token)
            snapshot = _safe_preflight_snapshot(prior.preflight_snapshot)
            if snapshot is None:
                raise ValueError("preflight snapshot is unavailable")
            current_fingerprint = _source_fingerprint(prior.source_path)
            if current_fingerprint is None or current_fingerprint != snapshot["fingerprint"]:
                raise ValueError("preflight snapshot is stale")
            if not isinstance(selector, dict) or not isinstance(binding, dict):
                raise ValueError("invalid background binding")

            def bounded(value: object, limit: int = 160) -> str:
                text = " ".join(str(value or "").split())
                if not text or len(text) > limit:
                    raise ValueError("invalid background binding")
                return text

            segment_name = bounded(selector.get("segment"))
            location = bounded(selector.get("location"))
            requested_name = bounded(selector.get("requested_name"))
            aa_key = bounded(binding.get("aa_key"))
            selected_label = bounded(binding.get("selected_label") or aa_key)
            source = bounded(binding.get("source"))
            preview_source = bounded(binding.get("preview_source"))
            if source not in {"custom", "official"}:
                raise ValueError("invalid background binding source")
            if preview_source not in {"story", "official"}:
                raise ValueError("invalid background preview source")

            result = snapshot["result"]
            matches = []
            for segment in result.get("usage_chain", []):
                if not isinstance(segment, dict) or str(segment.get("segment") or "") != segment_name:
                    continue
                for need in segment.get("needs", []):
                    if not isinstance(need, dict) or str(need.get("kind") or "") != "background":
                        continue
                    if (
                        str(need.get("location") or "") == location
                        and str(need.get("name") or "") == requested_name
                    ):
                        matches.append(need)
            if len(matches) != 1:
                raise ValueError("background scene selector is missing or ambiguous")

            need = matches[0]
            candidates = need.get("candidates")
            if not isinstance(candidates, list):
                candidates = []
            need.update({
                "status": "registered",
                "aa_key": aa_key,
                "selected_label": selected_label,
                "source": source,
                "preview_source": preview_source,
                "preview_available": bool(binding.get("preview_available")),
                "candidates": candidates,
            })
            need.pop("suggested_aa_key", None)
            need.pop("generation_prompt", None)
            for segment in result.get("usage_chain", []):
                if not isinstance(segment, dict):
                    continue
                for continued in segment.get("needs", []):
                    if not isinstance(continued, dict) or continued.get("kind") != "background":
                        continue
                    if continued.get("status") != "inherited" or continued.get("inherits_from") != selector:
                        continue
                    continued.update({
                        "aa_key": aa_key,
                        "selected_label": selected_label,
                        "source": source,
                        "preview_source": preview_source,
                        "preview_available": bool(binding.get("preview_available")),
                        "candidates": [],
                    })
            snapshot["saved_at"] = self._now()
            snapshot["approved"] = False
            updated = replace(prior, preflight_snapshot=snapshot)
            self._contexts[story_token] = updated
            self._replace_record(updated, last_opened_at=self._now())
            self._persist()
            return updated
