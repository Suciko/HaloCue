"""World-first authoring and editable outlines over the existing revision model."""

from __future__ import annotations

import json

from .ba_world_starter import starter_bible
from .chapter_review import ChapterReview
from .document_import import DocumentImport
from .errors import DomainError, NotFound, RevisionConflict
from .repository import canonical_json, new_id, now
from .workspace_access import workspace_operation


WORLD_DRAFT_SCHEMA = """
CREATE TABLE IF NOT EXISTS world_drafts (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, version INTEGER NOT NULL,
 current_revision_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS world_draft_revisions (
 id TEXT PRIMARY KEY, world_id TEXT NOT NULL REFERENCES world_drafts(id),
 ordinal INTEGER NOT NULL, content_json TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(world_id, ordinal)
);
"""


class AuthoringWorkspace:
    def __init__(self, service):
        self.service = service
        self.repo = service.repo
        self.data_access = service.data_access
        self.chapters = ChapterReview(service)
        self.imports = DocumentImport(service)

    @staticmethod
    def _text(value, field, limit=500_000):
        if not isinstance(value, str) or len(value) > limit:
            raise DomainError("validation_error", f"{field}需要文本，且不能超过 {limit} 个字符。")
        return value

    @workspace_operation
    def list_worlds(self):
        with self.repo.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM world_drafts ORDER BY updated_at DESC,id"
                )
            ]

    @workspace_operation
    def get_world(self, world_id):
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT * FROM world_drafts WHERE id=?", (world_id,)
            ).fetchone()
            if not row:
                raise NotFound("世界底稿", world_id)
            history = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM world_draft_revisions WHERE world_id=? ORDER BY ordinal DESC",
                    (world_id,),
                )
            ]
        for revision in history:
            revision["content"] = json.loads(revision.pop("content_json"))
        return {
            **dict(row),
            "schema_version": "world-draft/1.0",
            "content": history[0]["content"],
            "history": history,
        }

    @workspace_operation
    def save_world(self, payload, world_id=None):
        previous = self.get_world(world_id) if world_id else None
        if previous:
            raw = {**previous["content"], **payload}
        else:
            raw = {
                **(starter_bible() if payload.get("world_seed") == "ba_starter" else {}),
                **payload,
            }
        raw["title"] = self._text(raw.get("title", ""), "底稿名称", 200).strip() or "未命名世界"
        raw["overview"] = self._text(raw.get("overview", ""), "世界总说明")
        content = self.service._normalize_world_bible_payload(raw)
        world_id = world_id or new_id("world")
        revision_id, timestamp = new_id("world-revision"), now()
        with self.repo.transaction() as connection:
            if previous:
                current = connection.execute(
                    "SELECT version FROM world_drafts WHERE id=?", (world_id,)
                ).fetchone()
                expected = payload.get("expected_version")
                if expected != current["version"]:
                    raise RevisionConflict(expected, current["version"])
                version = current["version"] + 1
                connection.execute(
                    "UPDATE world_drafts SET title=?,version=?,current_revision_id=?,updated_at=? WHERE id=?",
                    (content["title"], version, revision_id, timestamp, world_id),
                )
            else:
                version = 1
                connection.execute(
                    "INSERT INTO world_drafts VALUES (?,?,?,?,?,?)",
                    (world_id, content["title"], version, revision_id, timestamp, timestamp),
                )
            connection.execute(
                "INSERT INTO world_draft_revisions VALUES (?,?,?,?,?)",
                (revision_id, world_id, version, canonical_json(content), timestamp),
            )
        return self.get_world(world_id)

    @staticmethod
    def _outline_text(content, scope_type="work", scope_id=None):
        lines = []
        if isinstance(content.get("volumes"), list):
            if scope_type == "work" and content.get("summary"):
                lines.append(content["summary"])
            for volume in content["volumes"]:
                if scope_type == "volume" and volume.get("id") != scope_id:
                    continue
                chapters = [chapter for chapter in volume.get("chapters", [])
                            if scope_type != "chapter" or chapter.get("id") == scope_id]
                if scope_type == "chapter" and not chapters:
                    continue
                if scope_type != "chapter":
                    lines.append(str(volume.get("title", "卷")))
                    if volume.get("goal"):
                        lines.append(str(volume["goal"]))
                for chapter in chapters:
                    lines.append(str(chapter.get("title", "章")))
                    if chapter.get("goal"):
                        lines.append(str(chapter["goal"]))
                    for scene in chapter.get("scenes", []):
                        goal = scene.get("contract", {}).get("goal") or scene.get("goal") or ""
                        lines.append(f"- {scene.get('title', '场景')}：{goal}".rstrip("："))
            return "\n\n".join(lines)
        for field in ("idea", "premise", "central_conflict", "chapter_goal"):
            if content.get(field):
                lines.append(str(content[field]))
        for field in ("direction", "beats", "continuity_notes"):
            if isinstance(content.get(field), list):
                lines.append("\n".join(f"- {item}" for item in content[field]))
        return "\n\n".join(lines)

    @workspace_operation
    def get_outline(self, work_id):
        work = self.service.get_work(work_id)
        artifacts = work.get("artifacts", [])
        scopes = [("work", work["id"], work["title"])]
        for volume in work["volumes"]:
            scopes.append(("volume", volume["id"], volume["title"]))
            scopes.extend(
                ("chapter", chapter["id"], chapter["title"]) for chapter in volume["chapters"]
            )
        documents = []
        for kind, scope_id, title in scopes:
            own = next(
                (
                    item
                    for item in artifacts
                    if item["kind"] == "outline_document"
                    and item["scope_type"] == kind
                    and item["scope_id"] == scope_id
                ),
                None,
            )
            sources = [
                item
                for item in artifacts
                if (
                    item["kind"] == "story_structure"
                    or
                    kind == "work"
                    and item["kind"] in {"brief", "story_blueprint"}
                    or kind == "chapter"
                    and item["kind"] == "chapter_plan"
                    and item["scope_id"] == scope_id
                )
                and item.get("current_revision")
                and item["current_revision"]["content"].get("status", "accepted")
                not in {"proposed", "analysis_pending", "draft", "rejected"}
            ]
            source_refs = [
                {"artifact_id": item["id"], "revision_id": item["current_revision"]["id"]}
                for item in sources
            ]
            adopted = "\n\n".join(
                self._outline_text(item["current_revision"]["content"], kind, scope_id) for item in sources
            )
            revision = own.get("current_revision") if own else None
            documents.append(
                {
                    "scope_type": kind,
                    "scope_id": scope_id,
                    "title": title,
                    "text": revision["content"]["text"] if revision else adopted,
                    "revision_id": revision["id"] if revision else None,
                    "history": own.get("revisions", []) if own else [],
                    "adopted_text": adopted,
                    "source_refs": source_refs,
                    "source_changed": bool(
                        revision and revision["content"].get("source_refs", []) != source_refs
                    ),
                }
            )
        return {
            "schema_version": "authoring-outline/1.0",
            "work_id": work_id,
            "version": work["version"],
            "documents": documents,
        }

    @workspace_operation
    def save_outline(self, work_id, payload):
        outline = self.get_outline(work_id)
        scope = (payload.get("scope_type"), payload.get("scope_id"))
        document = next(
            (
                item
                for item in outline["documents"]
                if (item["scope_type"], item["scope_id"]) == scope
            ),
            None,
        )
        if not document:
            raise NotFound("大纲范围", str(scope))
        text = self._text(payload.get("text"), "大纲")
        with self.repo.transaction() as connection:
            version = self.service._check_work_version(
                connection, work_id, payload.get("expected_version", -1)
            )
            artifact = self.service._artifact(connection, work_id, "outline_document", *scope)
            if artifact["current_revision_id"] != payload.get("expected_base_revision_id"):
                raise DomainError(
                    "outline_conflict", "大纲已有新版本，请保留草稿并重新载入。", status=409
                )
            revision = self.service._add_revision(
                connection,
                artifact,
                {
                    "schema_version": "outline-document/1.0",
                    "text": text,
                    "source_refs": document["source_refs"],
                },
                "user",
                {"workflow": "outline.edit"},
            )
            self.service._bump_work(connection, work_id, version)
        return {
            "revision_id": revision,
            "outline": self.get_outline(work_id),
            "work": self.service.get_work(work_id),
        }

    @workspace_operation
    def save_chapter(self, work_id, chapter_id, payload):
        edits = payload.get("scenes")
        if not isinstance(edits, list) or not edits:
            raise DomainError("validation_error", "请提供本章要保存的场景正文。")
        if any(not isinstance(item, dict) for item in edits):
            raise DomainError("validation_error", "场景正文格式无效。")
        ids = [str(item.get("scene_id", "")) for item in edits]
        if len(set(ids)) != len(ids):
            raise DomainError("validation_error", "同一场景不能重复保存。")
        normalized = [self.service._normalize_scene_blocks(item.get("blocks")) for item in edits]
        saved, superseded = {}, []
        with self.repo.transaction() as connection:
            version = self.service._check_work_version(
                connection, work_id, payload.get("expected_version", -1)
            )
            chapter = connection.execute(
                "SELECT id FROM chapters WHERE id=? AND work_id=?", (chapter_id, work_id)
            ).fetchone()
            if not chapter:
                raise NotFound("章节", chapter_id)
            owned = {
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM scenes WHERE chapter_id=? AND work_id=?", (chapter_id, work_id)
                )
            }
            if any(scene_id not in owned for scene_id in ids):
                raise DomainError(
                    "chapter_scope_mismatch", "保存内容包含不属于本章的场景。", status=409
                )
            for item, blocks in zip(edits, normalized):
                revision, old_proposals = self.service._write_scene_manuscript(
                    connection,
                    work_id,
                    item["scene_id"],
                    item.get("expected_base_revision_id") or None,
                    blocks,
                )
                saved[item["scene_id"]] = revision
                superseded.extend(old_proposals)
            self.service._bump_work(connection, work_id, version)
        for revision in saved.values():
            self.service._schedule_commit_projection(work_id, revision)
        return {
            "scene_revisions": saved,
            "superseded_proposal_ids": superseded,
            "work": self.service.get_work(work_id),
        }

    def outline_context(self, work_id, chapter_id):
        work = self.service.get_work(work_id)
        chapter = next((item for item in work["chapters"] if item["id"] == chapter_id), None)
        if not chapter:
            raise NotFound("章节", chapter_id)
        scopes = {work_id, chapter_id, chapter["volume_id"]}
        return [
            {key: item[key] for key in ("scope_type", "scope_id", "text", "revision_id")}
            for item in self.get_outline(work_id)["documents"]
            if item["scope_id"] in scopes and item["text"]
        ]

    def route(self, method, parts, payload=None):
        """Return (handled, result); called within the HTTP workspace guard."""
        payload = payload or {}
        if method == "POST" and parts[:3] == ["api", "v1", "document-import"] and len(parts) == 4:
            if parts[3] == "preview":
                return True, self.imports.preview(payload)
            if parts[3] == "adopt":
                return True, self.imports.adopt(payload)
        if len(parts) == 7 and parts[:3] == ["api", "v1", "works"] and parts[4] == "chapters":
            if method == "GET" and parts[6] == "review":
                return True, self.chapters.get(parts[3], parts[5])
            if method == "POST" and parts[6] == "review:decide":
                return True, self.chapters.decide(parts[3], parts[5], payload)
        if (
            method == "POST"
            and len(parts) == 7
            and parts[:3] == ["api", "v1", "works"]
            and parts[4] == "chapters"
            and parts[6] == "manuscript"
        ):
            return True, self.save_chapter(parts[3], parts[5], payload)
        if parts[:3] != ["api", "v1", "world-drafts"]:
            if len(parts) == 5 and parts[:3] == ["api", "v1", "works"] and parts[4] == "outline":
                return True, self.get_outline(parts[3]) if method == "GET" else self.save_outline(
                    parts[3], payload
                )
            return False, None
        if len(parts) == 3:
            return True, self.list_worlds() if method == "GET" else self.save_world(payload)
        if len(parts) == 4 and parts[3].endswith(":create-work") and method == "POST":
            world_id = parts[3][:-12]
            world = self.get_world(world_id)
            if payload.get("expected_version") != world["version"]:
                raise RevisionConflict(payload.get("expected_version"), world["version"])
            work = self.service.create_work(
                {
                    "title": payload.get("title", ""),
                    "world_draft_id": world_id,
                    "world_draft_revision_id": world["current_revision_id"],
                }
            )
            return True, {"work": work}
        if len(parts) == 4:
            return True, self.get_world(parts[3]) if method == "GET" else self.save_world(
                payload, parts[3]
            )
        return False, None
