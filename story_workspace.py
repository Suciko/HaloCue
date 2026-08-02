# -*- coding: utf-8 -*-
"""Server-side identity and recent-history storage for one AA story workspace."""

from __future__ import annotations

import datetime as _datetime
import json
import os
import threading
import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True)
class StorySummary:
    story_token: str
    project: str
    source_name: str
    last_opened_at: str
    latest_draft_token: str | None


def public_story_context(context: StoryContext) -> dict[str, Any]:
    """Serialize only display-safe fields; filesystem locations remain server-only."""
    return {
        "story_token": context.story_token,
        "project": context.project,
        "source_name": context.source_path.name if context.source_path else "",
        "latest_draft_token": context.latest_draft_token,
        "bgm_default": dict(context.bgm_default),
    }


def public_story_summary(summary: StorySummary) -> dict[str, Any]:
    return {
        "story_token": summary.story_token,
        "project": summary.project,
        "source_name": summary.source_name,
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

    def _context_from_record(self, record: dict[str, Any], token: str | None = None) -> StoryContext:
        project = validate_windows_path_component(record["project"], label="project name")
        source_path = self._safe_source_path(record.get("source_path"))
        story_token = token or f"story-{uuid.uuid4().hex}"
        return StoryContext(
            story_token=story_token,
            project=project,
            project_dir=(self.aa_data / "projects" / project).resolve(),
            save_dir=(self.aa_data / "saves" / project).resolve(),
            source_path=source_path,
            latest_draft_token=record.get("latest_draft_token") or None,
            bgm_default=normalize_bgm_policy(None),
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
            self._records.append({
                "project": context.project,
                "source_path": str(context.source_path) if context.source_path else "",
                "last_opened_at": str(record.get("last_opened_at") or self._now()),
                "latest_draft_token": context.latest_draft_token,
            })
            self._contexts[context.story_token] = context
            self._tokens_by_project[key] = context.story_token

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
            "project": context.project,
            "source_path": str(context.source_path) if context.source_path else "",
            "last_opened_at": last_opened_at,
            "latest_draft_token": context.latest_draft_token,
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
                summaries.append(StorySummary(
                    story_token=token,
                    project=record["project"],
                    source_name=source_path.name if source_path else "",
                    last_opened_at=record["last_opened_at"],
                    latest_draft_token=record.get("latest_draft_token") or None,
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
            )
            self._contexts[story_token] = updated
            self._replace_record(updated, last_opened_at=self._now())
            self._persist()
            return updated
