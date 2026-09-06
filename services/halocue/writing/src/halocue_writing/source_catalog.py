"""Immutable source snapshots and explicit append/update operations."""
from __future__ import annotations

import base64
import difflib
import json
from collections import defaultdict, deque

from .errors import DomainError, NotFound
from .repository import canonical_json, new_id, now, sha256_text
from .story_import import parse_story_payload


def source_windows(chapters: list[dict], max_characters: int = 10000) -> list[dict]:
    if not 256 <= max_characters <= 60000:
        raise DomainError("invalid_source_window", "原文窗口大小无效。")
    result = []
    for chapter in chapters:
        pieces, size = [], 0
        for paragraph in chapter.get("paragraphs", []):
            text = paragraph["text"]
            for start in range(0, len(text), max_characters):
                part = text[start:start + max_characters]
                if size and size + len(part) > max_characters:
                    result.append({"id": f"{chapter['id']}-window-{len(result) + 1}", "chapter_id": chapter["id"], "title": chapter["title"], "spans": pieces})
                    pieces, size = [], 0
                pieces.append({"paragraph_id": paragraph["id"], "start": start, "end": start + len(part), "text": part})
                size += len(part)
        if pieces:
            result.append({"id": f"{chapter['id']}-window-{len(result) + 1}", "chapter_id": chapter["id"], "title": chapter["title"], "spans": pieces})
    return result


class SourceCatalog:
    def __init__(self, repo):
        self.repo = repo

    def get(self, work_id: str, version_id: str | None = None, *, connection=None):
        if connection is None:
            with self.repo.connect() as current:
                return self.get(work_id, version_id, connection=current)
        if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
            raise NotFound("work", work_id)
        if version_id is None:
            row = connection.execute("SELECT current_version_id FROM work_sources WHERE work_id=?", (work_id,)).fetchone()
            if not row:
                return None
            version_id = row[0]
        row = connection.execute("SELECT * FROM source_versions WHERE id=? AND work_id=?", (version_id, work_id)).fetchone()
        if not row:
            raise NotFound("source_version", version_id)
        return {**json.loads(row["document_json"]), "changes": json.loads(row["changes_json"]), "original_uri": row["original_uri"], "normalized_uri": row["normalized_uri"]}

    @staticmethod
    def _chapter(parsed: dict, lines: list[dict], old: dict | None = None):
        reusable = defaultdict(deque)
        for paragraph in (old or {}).get("paragraphs", []):
            reusable[paragraph["text"]].append(paragraph["id"])
        paragraphs = []
        for line in lines:
            text = line["raw_text"]
            paragraph_id = reusable[text].popleft() if reusable[text] else new_id("source-paragraph")
            paragraphs.append({"id": paragraph_id, "text": text, "source_paragraph": line["source_paragraph"]})
        content = "\n".join(p["text"] for p in paragraphs)
        return {"id": old["id"] if old else new_id("source-chapter"), "title": parsed["title"], "paragraphs": paragraphs, "content_digest": sha256_text(content), "characters": len(content)}

    def prepare(self, work_id: str, payload: dict):
        previous = self.get(work_id)
        mode = str(payload.get("mode") or "append")
        if mode not in {"append", "update"}:
            raise DomainError("invalid_source_mode", "请选择追加章节或更新选定章节。")
        expected = payload.get("base_version_id")
        if expected != (previous or {}).get("id"):
            raise DomainError("source_version_conflict", "原文已经更新，请刷新差异后再提交。", status=409)
        try:
            parsed = parse_story_payload(payload)
        except ValueError as exc:
            raise DomainError("invalid_source", str(exc), status=422) from exc
        if mode == "append":
            with self.repo.connect() as connection:
                duplicate = connection.execute("SELECT id FROM source_versions WHERE work_id=? AND source_digest=?", (work_id, parsed["source_digest"])).fetchone()
            if duplicate:
                return {"duplicate": True, "base_version_id": expected, "document": previous, "changes": [], "preview_digest": sha256_text(canonical_json({"base": expected, "source": parsed["source_digest"], "mode": mode})), "mode": mode, "normalized_text": parsed["normalized_text"]}
        completion = payload.get("completion_state", (previous or {}).get("completion_state", "ongoing"))
        if completion not in {"ongoing", "complete"}:
            raise DomainError("invalid_completion_state", "作品状态必须为连载中或已完结。")
        old_chapters = (previous or {}).get("chapters", [])
        selected = payload.get("chapter_ids", [])
        grouped = defaultdict(list)
        for line in parsed["lines"]:
            grouped[line["chapter_id"]].append(line)
        incoming = [(chapter, grouped[chapter["id"]]) for chapter in parsed["chapters"] if grouped[chapter["id"]]]
        if not incoming:
            raise DomainError("source_empty", "原文没有可改编的正文。")
        if mode == "update":
            ids = [chapter["id"] for chapter in old_chapters]
            if not isinstance(selected, list) or not selected or any(item not in ids for item in selected) or len(selected) != len(incoming):
                raise DomainError("invalid_source_selection", "更新文件的章节数与所选旧章节数不一致。")
        chapters = list(old_chapters)
        changes = []
        for index, (chapter, lines) in enumerate(incoming):
            old = next((c for c in old_chapters if mode == "update" and c["id"] == selected[index]), None)
            changed = self._chapter(chapter, lines, old)
            if old:
                chapters[chapters.index(old)] = changed
            else:
                chapters.append(changed)
            if old is None or old["content_digest"] != changed["content_digest"] or old["title"] != changed["title"]:
                changes.append({"chapter_id": changed["id"], "title": changed["title"], "kind": "updated" if old else "added", "previous_digest": (old or {}).get("content_digest"), "content_digest": changed["content_digest"], "diff": list(difflib.unified_diff([p["text"] for p in (old or {}).get("paragraphs", [])], [p["text"] for p in changed["paragraphs"]], lineterm=""))})
        document = {"schema_version": "adaptation-source/1.0", "id": new_id("source-version"), "work_id": work_id, "parent_version_id": expected, "filename": parsed["filename"], "parser_version": parsed["parser_version"], "completion_state": completion, "provided_scope": str(payload.get("provided_scope") or ""), "chapters": chapters, "characters": sum(c["characters"] for c in chapters), "source_digest": parsed["source_digest"], "created_at": now()}
        preview_digest = sha256_text(canonical_json({"base": expected, "source": parsed["source_digest"], "mode": mode, "selected": selected, "completion": completion, "provided_scope": document["provided_scope"]}))
        return {"duplicate": False, "base_version_id": expected, "document": document, "changes": changes, "preview_digest": preview_digest, "mode": mode, "normalized_text": parsed["normalized_text"]}

    def preview(self, work_id: str, payload: dict):
        prepared = self.prepare(work_id, payload)
        return {k: v for k, v in prepared.items() if k != "normalized_text"}

    def apply(self, work_id: str, payload: dict):
        prepared = self.prepare(work_id, payload)
        if payload.get("preview_digest") != prepared["preview_digest"]:
            raise DomainError("source_preview_required", "请先查看本次原文更新的差异。", status=409)
        if prepared.get("duplicate"):
            return {"source": prepared["document"], "duplicate": True, "changes": []}
        document = prepared["document"]
        original_uri, _ = self.repo.atomic_write_bytes(f"sources/{document['id']}/original", base64.b64decode(payload["content_base64"], validate=True))
        normalized_uri, _ = self.repo.atomic_write_text(f"sources/{document['id']}/normalized.txt", prepared["normalized_text"])
        with self.repo.transaction() as connection:
            current = self.get(work_id, connection=connection)
            if (current or {}).get("id") != prepared["base_version_id"]:
                raise DomainError("source_version_conflict", "原文已经更新，请重新预览。", status=409)
            connection.execute("INSERT INTO source_versions VALUES (?,?,?,?,?,?,?,?,?,?)", (document["id"], work_id, prepared["base_version_id"], prepared["mode"], document["source_digest"], original_uri, normalized_uri, canonical_json(document), canonical_json(prepared["changes"]), document["created_at"]))
            connection.execute("INSERT INTO work_sources VALUES (?,?) ON CONFLICT(work_id) DO UPDATE SET current_version_id=excluded.current_version_id", (work_id, document["id"]))
        return {"source": self.get(work_id), "duplicate": False, "changes": prepared["changes"]}
