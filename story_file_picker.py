"""Cross-device story file selection without exposing selectable host paths."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from picker_token import register_file_token


MAX_STORY_BYTES = 10 * 1024 * 1024
STORY_SUFFIXES = {".txt", ".md"}


def windows_host_roots(
    workspace: str | os.PathLike[str],
    *,
    home: str | os.PathLike[str] | None = None,
    drives: Iterable[str | os.PathLike[str]] | None = None,
) -> list[Path]:
    """Return useful existing host locations while preserving stable order."""
    user_home = Path(home).resolve() if home is not None else Path.home().resolve()
    candidates = [Path(workspace), user_home / "Desktop", user_home / "Documents", user_home / "Downloads"]
    if drives is None and os.name == "nt":
        candidates.extend(Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    else:
        candidates.extend(Path(value) for value in (drives or []))
    roots = []
    for candidate in candidates:
        try:
            canonical = candidate.resolve()
        except OSError:
            continue
        if canonical.is_dir() and canonical not in roots:
            roots.append(canonical)
    return roots


class StoryFilePickerError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class _HostEntry:
    path: Path
    kind: str
    size: int
    modified_ns: int
    expires_at: float


class StoryFilePicker:
    """Own uploaded copies and issue exact, expiring tokens for host entries."""

    def __init__(
        self,
        *,
        roots: Iterable[str | os.PathLike[str]],
        upload_dir: str | os.PathLike[str],
        token_ttl: int = 600,
        allowed_suffixes: Iterable[str] | None = STORY_SUFFIXES,
    ):
        canonical = []
        for value in roots:
            path = Path(value).resolve()
            if path.is_dir() and path not in canonical:
                canonical.append(path)
        if not canonical:
            raise ValueError("StoryFilePicker requires at least one existing root")
        self.roots = tuple(canonical)
        self.upload_dir = Path(upload_dir).resolve()
        self.token_ttl = int(token_ttl)
        self.allowed_suffixes = (
            None
            if allowed_suffixes is None
            else frozenset(str(value).casefold() for value in allowed_suffixes)
        )
        self._entries: dict[str, _HostEntry] = {}
        self._lock = threading.RLock()

    def _inside_roots(self, path: Path) -> bool:
        canonical = path.resolve()
        for root in self.roots:
            try:
                canonical.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _stat_entry(self, path: Path) -> tuple[str, int, int]:
        stat = path.stat()
        kind = "directory" if path.is_dir() else "file"
        return kind, 0 if kind == "directory" else stat.st_size, stat.st_mtime_ns

    def _issue_entry(self, path: str | os.PathLike[str]) -> str:
        canonical = Path(path).resolve()
        if not self._inside_roots(canonical):
            raise StoryFilePickerError(
                "host_entry_outside_roots", "该位置不在允许浏览的范围内", 403
            )
        try:
            kind, size, modified_ns = self._stat_entry(canonical)
        except OSError as exc:
            raise StoryFilePickerError("host_entry_missing", "该文件已不存在", 410) from exc
        if (
            kind == "file"
            and self.allowed_suffixes is not None
            and canonical.suffix.casefold() not in self.allowed_suffixes
        ):
            raise StoryFilePickerError("unsupported_story_type", "只支持 .txt 和 .md 剧情文本")
        token = f"entry-{uuid.uuid4().hex}"
        with self._lock:
            self._entries[token] = _HostEntry(
                canonical, kind, size, modified_ns, time.monotonic() + self.token_ttl
            )
        return token

    def _resolve_entry(self, token: str, *, expected_kind: str | None = None) -> _HostEntry:
        with self._lock:
            entry = self._entries.get(str(token or ""))
            if entry is None:
                raise StoryFilePickerError("invalid_host_entry", "该位置已失效，请刷新", 404)
            if time.monotonic() > entry.expires_at:
                self._entries.pop(str(token), None)
                raise StoryFilePickerError("expired_host_entry", "该位置已过期，请刷新", 410)
        if not self._inside_roots(entry.path):
            raise StoryFilePickerError("host_entry_outside_roots", "该位置不在允许浏览的范围内", 403)
        try:
            current = self._stat_entry(entry.path)
        except OSError as exc:
            raise StoryFilePickerError("host_entry_changed", "文件已变化，请刷新后重试", 409) from exc
        if current != (entry.kind, entry.size, entry.modified_ns):
            raise StoryFilePickerError("host_entry_changed", "文件已变化，请刷新后重试", 409)
        if expected_kind and entry.kind != expected_kind:
            raise StoryFilePickerError("host_entry_kind_mismatch", "请选择剧情文本", 422)
        return entry

    @staticmethod
    def _decode_story(content: bytes) -> str:
        if b"\0" in content:
            raise StoryFilePickerError("unreadable_story_text", "文件不是可读取的文本")
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = content.decode(encoding)
            except UnicodeDecodeError:
                continue
            controls = sum(ord(char) < 32 and char not in "\r\n\t" for char in text)
            if controls <= max(1, len(text) // 100):
                return text
        raise StoryFilePickerError("unreadable_story_text", "文件不是可读取的文本")

    def _clean_uploads(self) -> None:
        if not self.upload_dir.is_dir():
            return
        cutoff = time.time() - self.token_ttl
        for path in self.upload_dir.iterdir():
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    shutil.rmtree(path)
            except OSError:
                continue

    def upload(self, name: str, content: bytes) -> dict:
        safe_name = Path(str(name or "").replace("\\", "/")).name.strip()
        if Path(safe_name).suffix.casefold() not in STORY_SUFFIXES:
            raise StoryFilePickerError("unsupported_story_type", "只支持 .txt 和 .md 剧情文本")
        if not content:
            raise StoryFilePickerError("empty_story_file", "剧情文本不能为空")
        if len(content) > MAX_STORY_BYTES:
            raise StoryFilePickerError("story_file_too_large", "剧情文本不能超过 10 MiB", 413)
        text = self._decode_story(content)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._clean_uploads()
        owned_dir = Path(tempfile.mkdtemp(prefix="story-", dir=self.upload_dir))
        target = owned_dir / safe_name
        descriptor, temporary = tempfile.mkstemp(prefix="upload-", dir=owned_dir)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(owned_dir, ignore_errors=True)
            raise
        return {
            "file_token": register_file_token(str(target)),
            "name": safe_name,
            "size": len(content),
        }

    def _entry_payload(self, path: Path) -> dict:
        kind, size, modified_ns = self._stat_entry(path)
        suffix = path.suffix.casefold()
        return {
            "entry_token": self._issue_entry(path),
            "name": path.name,
            "kind": kind,
            "size": size,
            "modified": dt.datetime.fromtimestamp(
                modified_ns / 1_000_000_000, tz=dt.timezone.utc
            ).isoformat(),
            "type": "文件夹" if kind == "directory" else ("Markdown" if suffix == ".md" else "文本文件"),
        }

    def _breadcrumb(self, directory: Path) -> list[dict]:
        root = next(root for root in self.roots if directory == root or root in directory.parents)
        paths = [root]
        current = root
        for part in directory.relative_to(root).parts:
            current = current / part
            paths.append(current)
        return [{"name": path.name or str(path), "entry_token": self._issue_entry(path)} for path in paths]

    def list_directory(
        self,
        entry_token: str = "",
        query: str = "",
        sort: str = "name",
        direction: str = "asc",
    ) -> dict:
        directory = self._resolve_entry(entry_token, expected_kind="directory").path if entry_token else self.roots[0]
        needle = str(query or "").strip().casefold()
        entries = []
        try:
            candidates = list(directory.iterdir())
        except OSError as exc:
            raise StoryFilePickerError("host_directory_unavailable", "无法读取该文件夹", 403) from exc
        for path in candidates:
            if path.name.startswith("."):
                continue
            try:
                canonical = path.resolve()
                if not self._inside_roots(canonical):
                    continue
                if canonical.is_dir():
                    if needle and needle not in path.name.casefold():
                        continue
                elif (
                    canonical.is_file()
                    and (
                        self.allowed_suffixes is None
                        or canonical.suffix.casefold() in self.allowed_suffixes
                    )
                ):
                    if needle and needle not in path.name.casefold():
                        continue
                else:
                    continue
                entries.append(self._entry_payload(canonical))
            except OSError:
                continue
        key_name = sort if sort in {"name", "size", "modified", "type"} else "name"
        entries.sort(
            key=lambda row: (row["kind"] != "directory", row[key_name].casefold() if isinstance(row[key_name], str) else row[key_name], row["name"].casefold()),
            reverse=str(direction).casefold() == "desc",
        )
        root = next(root for root in self.roots if directory == root or root in directory.parents)
        parent = directory.parent if directory != root else None
        return {
            "location": directory.name or str(directory),
            "location_token": self._issue_entry(directory),
            "parent_token": self._issue_entry(parent) if parent else "",
            "breadcrumbs": self._breadcrumb(directory),
            "roots": [
                {"name": path.name or str(path), "entry_token": self._issue_entry(path)}
                for path in self.roots
            ],
            "entries": entries,
        }

    def select(self, entry_token: str) -> dict:
        entry = self._resolve_entry(entry_token, expected_kind="file")
        return {
            "file_token": register_file_token(str(entry.path)),
            "name": entry.path.name,
            "size": entry.size,
        }

    def resolve_entry_path(
        self, entry_token: str, *, expected_kind: str | None = None
    ) -> Path:
        """Resolve a short-lived host token for server-side settings only."""
        return self._resolve_entry(entry_token, expected_kind=expected_kind).path
