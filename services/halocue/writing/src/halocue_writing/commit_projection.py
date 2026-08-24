from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .errors import DomainError, NotFound
from .repository import Repository, canonical_json, now, sha256_text


PROJECTION_KINDS = ("summary", "search", "memory_followup", "review_followup")
KNOWLEDGE_ARTIFACT_KINDS = {"character_card", "world_bible", "work_canon"}
KNOWLEDGE_SKIPPED_KINDS = ("memory_followup", "review_followup")
SEARCHABLE_ARTIFACT_KINDS = {"character_card", "world_bible", "work_canon", "scene_script"}
_PUBLIC_ITEM_STATUSES = {"pending", "done", "failed", "skipped"}


class CommitProjection:
    """Materialize replaceable data derived from one immutable Revision.

    Revision and Artifact rows remain the source of truth. Projection outputs can
    be deleted and rebuilt from the pinned revision without changing formal data.
    """

    def __init__(self, repository: Repository):
        self.repository = repository
        self.repository.recover_commit_projection_items()

    def ensure(self, work_id: str, revision_id: str) -> dict[str, Any]:
        with self.repository.connect() as connection:
            source = self._source_row(connection, work_id, revision_id)
        projection = self.repository.ensure_commit_projection(
            work_id=work_id,
            revision_id=revision_id,
            input_digest=self._batch_digest(source),
        )
        if source["artifact_kind"] in KNOWLEDGE_ARTIFACT_KINDS:
            for kind in KNOWLEDGE_SKIPPED_KINDS:
                self.repository.skip_commit_projection_item(
                    projection_id=projection["id"],
                    kind=kind,
                    decision={
                        "decision": "skipped",
                        "code": "not_applicable",
                        "reason": "正式资料 Revision 不需要场景记忆提取或场景审查待办。",
                        "source_kind": source["artifact_kind"],
                        "decided_at": now(),
                    },
                )
            projection = self.repository.get_commit_projection(
                work_id=work_id,
                revision_id=revision_id,
            )
        return self._with_source(projection, source)

    def get(self, work_id: str, revision_id: str) -> dict[str, Any]:
        projection = self.repository.get_commit_projection(
            work_id=work_id,
            revision_id=revision_id,
        )
        if not projection:
            raise NotFound("commit_projection", revision_id)
        with self.repository.connect() as connection:
            source = self._source_row(connection, work_id, revision_id)
        return self._with_source(projection, source)

    def list_for_work(self, work_id: str, *, current_only: bool = False) -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
            where = "projection.work_id=?"
            parameters: list[Any] = [work_id]
            if current_only:
                where += " AND artifact.current_revision_id=projection.revision_id"
            rows = connection.execute(
                f"""SELECT projection.* FROM commit_projections AS projection
                    JOIN revisions AS revision ON revision.id=projection.revision_id
                    JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                    WHERE {where} ORDER BY projection.created_at DESC""",
                parameters,
            ).fetchall()
            result = []
            for row in rows:
                items = connection.execute(
                    "SELECT * FROM commit_projection_items WHERE projection_id=? ORDER BY kind",
                    (row["id"],),
                ).fetchall()
                source = self._source_row(connection, work_id, row["revision_id"])
                result.append(self._with_source(self._public(row, items), source))
            return result

    def run(
        self,
        work_id: str,
        revision_id: str,
        provider,
        *,
        projection_kinds: list[str] | tuple[str, ...] | None = None,
        failed_only: bool = False,
        postprocess: Callable[[str, dict, dict], dict] | None = None,
    ) -> dict[str, Any]:
        projection = self.ensure(work_id, revision_id)
        selected = self._selected_kinds(projection_kinds)
        source = self._projection_input(work_id, revision_id)
        for kind in PROJECTION_KINDS:
            if kind not in selected:
                continue
            current = next(item for item in projection["items"] if item["kind"] == kind)
            allowed_statuses = {"failed"} if failed_only else {"pending", "failed"}
            if current["status"] not in allowed_statuses:
                continue
            claim = self.repository.claim_commit_projection_item(
                projection_id=projection["id"],
                kind=kind,
                allowed_statuses=tuple(sorted(allowed_statuses)),
            )
            if not claim["claimed"]:
                continue
            claimed_item = claim["item"]
            try:
                raw = provider.project_commit_revision(kind, dict(source))
                output = self._validate_output(raw, kind, revision_id)
                if postprocess:
                    enriched = postprocess(kind, dict(source), dict(output))
                    if enriched is not None:
                        output = self._validate_output(enriched, kind, revision_id)
                text = canonical_json(output) + "\n"
                output_ref, output_hash = self.repository.atomic_write_text(
                    f"projections/{projection['id']}/{kind}-attempt-{claimed_item['attempt_count']}.json",
                    text,
                )
                with self.repository.connect() as connection:
                    current_source = self._source_row(connection, work_id, revision_id)
                    if current_source["content_hash"] != source["content_hash"]:
                        raise DomainError(
                            "commit_projection_source_changed",
                            "投影固定的 Revision 内容校验失败。",
                            status=409,
                            details={"revision_id": revision_id},
                        )
                self.repository.complete_commit_projection_item(
                    item_id=claimed_item["id"],
                    output_ref=output_ref,
                    output_hash=output_hash,
                    attempt_count=claimed_item["attempt_count"],
                )
            except Exception as exc:
                error = self._error_payload(exc, kind)
                self.repository.fail_commit_projection_item(
                    item_id=claimed_item["id"],
                    error=error,
                    attempt_count=claimed_item["attempt_count"],
                )
            projection = self.get(work_id, revision_id)
        return self.get(work_id, revision_id)

    def retry(
        self,
        work_id: str,
        revision_id: str,
        provider,
        *,
        postprocess: Callable[[str, dict, dict], dict] | None = None,
    ) -> dict[str, Any]:
        return self.run(
            work_id,
            revision_id,
            provider,
            failed_only=True,
            postprocess=postprocess,
        )

    def skip(self, work_id: str, revision_id: str, kind: str, *, reason: str) -> dict[str, Any]:
        kind = str(kind or "").strip()
        reason = str(reason or "").strip()
        if kind not in PROJECTION_KINDS:
            raise DomainError(
                "validation_error",
                "未知的提交投影步骤。",
                details={"field": "kind", "allowed": list(PROJECTION_KINDS)},
            )
        if not reason:
            raise DomainError(
                "validation_error",
                "跳过投影步骤时必须说明理由。",
                details={"field": "reason"},
            )
        projection = self.ensure(work_id, revision_id)
        item = next(item for item in projection["items"] if item["kind"] == kind)
        result = self.repository.skip_commit_projection_item(
            projection_id=projection["id"],
            kind=kind,
            decision={"decision": "skipped", "reason": reason, "decided_at": now()},
        )
        if not result["applied"] and item["status"] != "skipped":
            raise DomainError(
                "commit_projection_item_not_skippable",
                "只有待处理或失败的投影步骤可以跳过。",
                status=409,
                details={"kind": kind, "status": item["status"]},
            )
        return self.get(work_id, revision_id)

    def recover_interrupted(self) -> int:
        return self.repository.recover_commit_projection_items()["recovered_count"]

    def health(self, work_id: str) -> dict[str, Any]:
        projections = self.list_for_work(work_id, current_only=True)
        broken_outputs: list[str] = []
        failed_items: list[str] = []
        pending_items: list[str] = []
        for projection in projections:
            for item in projection["items"]:
                if item["status"] == "failed":
                    failed_items.append(item["id"])
                elif item["status"] == "pending":
                    pending_items.append(item["id"])
                if item["status"] != "done":
                    continue
                try:
                    content = self.repository.read_text(item["output_ref"])
                except (OSError, UnicodeError, ValueError, TypeError):
                    broken_outputs.append(item["id"])
                    continue
                if sha256_text(content) != item["output_hash"]:
                    broken_outputs.append(item["id"])
        return {
            "projection_count": len(projections),
            "failed_item_ids": failed_items,
            "pending_item_ids": pending_items,
            "broken_output_item_ids": broken_outputs,
            "ok": not failed_items and not broken_outputs,
        }

    def search_current(
        self,
        work_id: str,
        query: str,
        *,
        artifact_kinds: list[str] | tuple[str, ...] | None = None,
        limit: int | str = 8,
    ) -> dict[str, Any]:
        """Search replaceable indexes, then return their pinned formal sources."""

        query = str(query or "").strip()
        if len(query) > 1000:
            raise DomainError(
                "validation_error",
                "检索内容过长。",
                details={"field": "query", "max_length": 1000},
            )
        try:
            limit_value = int(limit)
        except (TypeError, ValueError) as exc:
            raise DomainError(
                "validation_error",
                "检索数量必须是整数。",
                details={"field": "limit"},
            ) from exc
        if not 1 <= limit_value <= 50:
            raise DomainError(
                "validation_error",
                "检索数量必须在 1 到 50 之间。",
                details={"field": "limit"},
            )

        selected = set(artifact_kinds or SEARCHABLE_ARTIFACT_KINDS)
        unknown = sorted(selected.difference(SEARCHABLE_ARTIFACT_KINDS))
        if unknown:
            raise DomainError(
                "validation_error",
                "包含不可检索的正式资料类型。",
                details={"field": "artifact_kinds", "unknown": unknown},
            )
        if not selected:
            raise DomainError(
                "validation_error",
                "至少需要选择一种正式资料类型。",
                details={"field": "artifact_kinds"},
            )

        placeholders = ",".join("?" for _ in selected)
        with self.repository.connect() as connection:
            if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
            sources = connection.execute(
                f"""SELECT revision.id,revision.artifact_id,revision.content_uri,revision.content_hash,
                           artifact.kind AS artifact_kind,artifact.scope_type,artifact.scope_id
                    FROM artifacts AS artifact
                    JOIN revisions AS revision ON revision.id=artifact.current_revision_id
                    WHERE artifact.work_id=? AND artifact.kind IN ({placeholders})
                    ORDER BY artifact.kind,artifact.scope_id""",
                (work_id, *sorted(selected)),
            ).fetchall()

        query_terms = self._search_terms(query)
        normalized_query = " ".join(query.lower().split())
        results: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        for source in sources:
            projection = self.repository.get_commit_projection(
                work_id=work_id,
                revision_id=source["id"],
            )
            if not projection:
                unavailable.append(self._search_unavailable(source, "not_registered"))
                continue
            search_item = next(
                (item for item in projection["items"] if item["kind"] == "search"),
                None,
            )
            if not search_item or search_item["status"] != "done":
                unavailable.append(
                    self._search_unavailable(
                        source,
                        search_item["status"] if search_item else "missing",
                    )
                )
                continue
            try:
                output_text = self.repository.read_text(search_item["output_ref"])
                if sha256_text(output_text) != search_item["output_hash"]:
                    raise ValueError("projection output hash mismatch")
                output = json.loads(output_text)
                indexed = output.get("content") if isinstance(output, dict) else None
                if (
                    not isinstance(output, dict)
                    or output.get("schema_version") != "commit-projection-output/1.0"
                    or output.get("kind") != "search"
                    or output.get("source_revision_id") != source["id"]
                    or not isinstance(indexed, dict)
                ):
                    raise ValueError("projection output contract mismatch")
                formal_text = self.repository.read_text(source["content_uri"])
                if sha256_text(formal_text) != source["content_hash"]:
                    raise ValueError("formal revision hash mismatch")
                formal_content = json.loads(formal_text)
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                unavailable.append(self._search_unavailable(source, "integrity_failed"))
                continue

            haystack = " ".join(
                [
                    str(indexed.get("text") or ""),
                    " ".join(str(item) for item in indexed.get("terms", []) if str(item)),
                ]
            ).lower()
            matched_terms = [term for term in query_terms if term in haystack]
            exact = bool(normalized_query and normalized_query in haystack)
            score = (8 if exact else 0) + len(matched_terms) * 2
            if query and score <= 0:
                continue
            results.append(
                {
                    "source": {
                        "kind": source["artifact_kind"],
                        "scope_type": source["scope_type"],
                        "scope_id": source["scope_id"],
                        "revision_id": source["id"],
                        "content_hash": source["content_hash"],
                    },
                    "score": score,
                    "matched_terms": matched_terms,
                    "excerpt": str(indexed.get("text") or "")[:600],
                    "content": formal_content,
                    "projection": {
                        "id": projection["id"],
                        "output_hash": search_item["output_hash"],
                    },
                }
            )
        results.sort(
            key=lambda item: (
                -item["score"],
                item["source"]["kind"],
                item["source"]["scope_id"],
            )
        )
        return {
            "schema_version": "commit-projection-search/1.0",
            "work_id": work_id,
            "query": query,
            "artifact_kinds": sorted(selected),
            "source_revision_count": len(sources),
            "searched_revision_count": len(sources) - len(unavailable),
            "complete": not unavailable,
            "unavailable": unavailable,
            "results": results[:limit_value],
        }

    def _projection_input(self, work_id: str, revision_id: str) -> dict[str, Any]:
        with self.repository.connect() as connection:
            source = self._source_row(connection, work_id, revision_id)
        try:
            text = self.repository.read_text(source["content_uri"])
        except (OSError, UnicodeError, ValueError) as exc:
            raise DomainError(
                "commit_projection_source_missing",
                "提交投影的来源 Revision 无法读取。",
                status=409,
                details={"revision_id": revision_id},
            ) from exc
        if sha256_text(text) != source["content_hash"]:
            raise DomainError(
                "commit_projection_source_integrity_failed",
                "提交投影的来源 Revision 哈希不一致。",
                status=409,
                details={"revision_id": revision_id},
            )
        try:
            content = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DomainError(
                "commit_projection_source_invalid",
                "提交投影的来源 Revision 不是有效的结构化内容。",
                status=409,
                details={"revision_id": revision_id},
            ) from exc
        return {
            "schema_version": "commit-projection-input/1.0",
            "work_id": work_id,
            "revision_id": revision_id,
            "artifact_id": source["artifact_id"],
            "artifact_kind": source["artifact_kind"],
            "source_kind": source["artifact_kind"],
            "scope_type": source["scope_type"],
            "scope_id": source["scope_id"],
            "scene_id": source["scope_id"] if source["scope_type"] == "scene" else None,
            "content_hash": source["content_hash"],
            "content": content,
        }

    @staticmethod
    def _source_row(connection, work_id: str, revision_id: str):
        row = connection.execute(
            """SELECT revision.id,revision.artifact_id,revision.content_uri,revision.content_hash,
                      artifact.kind AS artifact_kind,artifact.scope_type,artifact.scope_id
               FROM revisions AS revision
               JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
               WHERE revision.id=? AND artifact.work_id=?""",
            (revision_id, work_id),
        ).fetchone()
        if not row:
            raise NotFound("revision", revision_id)
        return row

    @staticmethod
    def _batch_digest(source) -> str:
        return sha256_text(
            canonical_json(
                {
                    "schema_version": "commit-projection-batch/1.0",
                    "revision_id": source["id"],
                    "artifact_id": source["artifact_id"],
                    "content_hash": source["content_hash"],
                    "kinds": list(PROJECTION_KINDS),
                }
            )
        )

    @staticmethod
    def _selected_kinds(value) -> set[str]:
        if value is None:
            return set(PROJECTION_KINDS)
        if not isinstance(value, (list, tuple)):
            raise DomainError(
                "validation_error",
                "projection_kinds 必须是数组。",
                details={"field": "projection_kinds"},
            )
        selected = {str(item).strip() for item in value if str(item).strip()}
        unknown = sorted(selected.difference(PROJECTION_KINDS))
        if unknown:
            raise DomainError(
                "validation_error",
                "包含未知的提交投影步骤。",
                details={"field": "projection_kinds", "unknown": unknown},
            )
        return selected

    @staticmethod
    def _validate_output(value: Any, kind: str, revision_id: str) -> dict:
        if not isinstance(value, dict):
            raise DomainError(
                "commit_projection_output_invalid",
                "提交投影没有返回结构化结果。",
                status=502,
                details={"kind": kind},
            )
        if value.get("schema_version") != "commit-projection-output/1.0":
            raise DomainError(
                "commit_projection_output_invalid",
                "提交投影返回了未知版本。",
                status=502,
                details={"kind": kind, "field": "schema_version"},
            )
        if value.get("kind") != kind or value.get("source_revision_id") != revision_id:
            raise DomainError(
                "commit_projection_output_invalid",
                "提交投影结果与固定输入不匹配。",
                status=502,
                details={"kind": kind, "revision_id": revision_id},
            )
        if not isinstance(value.get("content"), dict):
            raise DomainError(
                "commit_projection_output_invalid",
                "提交投影的 content 必须是对象。",
                status=502,
                details={"kind": kind, "field": "content"},
            )
        return dict(value)

    @staticmethod
    def _error_payload(exc: Exception, kind: str) -> dict:
        if isinstance(exc, DomainError):
            return {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "retryable": exc.status >= 500,
                "kind": kind,
            }
        return {
            "code": "commit_projection_failed",
            "message": "提交投影未能完成。",
            "details": {"type": type(exc).__name__},
            "retryable": True,
            "kind": kind,
        }

    @staticmethod
    def _json(value: str | None):
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"code": "stored_json_invalid"}

    @staticmethod
    def _with_source(projection: dict[str, Any], source) -> dict[str, Any]:
        return {
            **projection,
            "source": {
                "kind": source["artifact_kind"],
                "scope_type": source["scope_type"],
                "scope_id": source["scope_id"],
                "revision_id": source["id"],
            },
        }

    @staticmethod
    def _search_terms(value: str) -> list[str]:
        terms: list[str] = []
        for item in re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,12}", value.lower()):
            if item not in terms:
                terms.append(item)
        return terms

    @staticmethod
    def _search_unavailable(source, reason: str) -> dict[str, Any]:
        return {
            "kind": source["artifact_kind"],
            "scope_type": source["scope_type"],
            "scope_id": source["scope_id"],
            "revision_id": source["id"],
            "reason": reason,
        }

    def _public(self, row, items) -> dict[str, Any]:
        public_items = []
        for item in items:
            item_status = item["status"]
            public_items.append(
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "status": item_status if item_status in _PUBLIC_ITEM_STATUSES else item_status,
                    "attempt_count": item["attempt_count"],
                    "input_digest": item["input_digest"],
                    "output_ref": item["output_ref"],
                    "output_hash": item["output_hash"],
                    "error": self._json(item["error_json"]),
                    "decision": self._json(item["decision_json"]),
                    "updated_at": item["updated_at"],
                }
            )
        return {
            "schema_version": "commit-projection/1.0",
            "id": row["id"],
            "work_id": row["work_id"],
            "revision_id": row["revision_id"],
            "input_digest": row["input_digest"],
            "status": row["status"],
            "items": public_items,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
