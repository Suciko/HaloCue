# -*- coding: utf-8 -*-
"""Recoverable resolution of custom backgrounds requested by the annotator."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from background_requests import (
    background_generation_prompt,
    collect_background_requests,
)


_REQUEST_LINE = re.compile(
    r"^(?P<indent>\s*)#\s*待生成自定义背景\s*[：:]\s*(?P<description>.+?)\s*$",
    re.MULTILINE,
)
_SAFE_BACKGROUND_NAME = re.compile(r"^[^\x00-\x1f\r\n]+$")


class BackgroundResolutionError(ValueError):
    """A background request cannot be safely or consistently resolved."""


@dataclass
class BackgroundRequestItem:
    id: str
    description: str
    prompt: str
    lines: list[int] = field(default_factory=list)
    status: str = "pending"
    background_name: str = ""

    def public(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "prompt": self.prompt,
            "lines": list(self.lines),
            "status": self.status,
            "background_name": self.background_name,
        }


@dataclass
class BackgroundResolutionSession:
    script_path: Path
    project: str
    requests: list[BackgroundRequestItem] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        script_path: str | Path,
        *,
        project: str,
    ) -> "BackgroundResolutionSession":
        path = Path(script_path).resolve()
        text = path.read_text(encoding="utf-8")
        descriptions = collect_background_requests(text)
        lines_by_description: dict[str, list[int]] = {
            description: [] for description in descriptions
        }
        for match in _REQUEST_LINE.finditer(text):
            description = match.group("description").strip()
            if description in lines_by_description:
                lines_by_description[description].append(
                    text.count("\n", 0, match.start()) + 1
                )
        requests = [
            BackgroundRequestItem(
                id=hashlib.sha256(description.encode("utf-8")).hexdigest()[:16],
                description=description,
                prompt=background_generation_prompt(description),
                lines=lines_by_description[description],
            )
            for description in descriptions
        ]
        return cls(script_path=path, project=str(project), requests=requests)

    def public_state(self) -> dict:
        return {
            "project": self.project,
            "ready": bool(self.requests) and all(
                item.status == "resolved" for item in self.requests
            ),
            "requests": [item.public() for item in self.requests],
        }

    def resolve(
        self,
        request_id: str,
        background_name: str,
        *,
        registered_backgrounds,
    ) -> dict:
        item = next(
            (request for request in self.requests if request.id == str(request_id)),
            None,
        )
        if item is None:
            raise BackgroundResolutionError("找不到指定的背景请求")

        name = str(background_name).strip()
        if (
            not name
            or name != str(background_name)
            or not _SAFE_BACKGROUND_NAME.fullmatch(name)
            or name.startswith("@")
            or name.startswith("#")
        ):
            raise BackgroundResolutionError("背景名称包含不允许的字符")
        known = {str(value) for value in registered_backgrounds}
        if name not in known:
            raise BackgroundResolutionError(
                f"背景 {name!r} 尚未登记到当前 AA 工程"
            )

        text = self.script_path.read_text(encoding="utf-8")
        replaced = 0

        def replacement(match: re.Match) -> str:
            nonlocal replaced
            if match.group("description").strip() != item.description:
                return match.group(0)
            replaced += 1
            return f"{match.group('indent')}@bg {name}"

        rewritten = _REQUEST_LINE.sub(replacement, text)
        if replaced == 0 and item.status != "resolved":
            raise BackgroundResolutionError("标注文件中已找不到对应的背景请求")
        if replaced:
            temporary = self.script_path.with_suffix(
                self.script_path.suffix + ".background.tmp"
            )
            temporary.write_text(rewritten, encoding="utf-8")
            temporary.replace(self.script_path)

        item.status = "resolved"
        item.background_name = name
        return self.public_state()
