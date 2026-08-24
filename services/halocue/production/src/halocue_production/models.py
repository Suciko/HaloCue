from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ScriptRelease:
    release_id: str
    project: str
    source_kind: str
    content_sha256: str
    line_count: int
    created_at: str

    @classmethod
    def create(cls, project: str, text: str, source_kind: str) -> "ScriptRelease":
        return cls(
            release_id=new_id("release"),
            project=project,
            source_kind=source_kind,
            content_sha256=content_sha256(text),
            line_count=len(text.splitlines()),
            created_at=utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class WorkItem:
    key: str
    label: str
    state: str
    progress: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ProductionRun:
    run_id: str
    project: str
    release_id: str
    draft_token: str | None
    state: str
    current_stage: str
    created_at: str
    updated_at: str
    work_items: list[WorkItem] = field(default_factory=list)
    source_summary: dict[str, Any] = field(default_factory=dict)
    pending_build_id: str | None = None
    last_build_id: str | None = None
    last_installed_project: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = self.__dict__.copy()
        value["work_items"] = [item.to_dict() for item in self.work_items]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProductionRun":
        data = dict(value)
        data.setdefault("pending_build_id", None)
        data["work_items"] = [WorkItem(**item) for item in data.get("work_items", [])]
        return cls(**data)
