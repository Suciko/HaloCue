"""A chapter-level user action orchestrating existing review and memory workers."""

from __future__ import annotations

import json
import threading

from .errors import DomainError, NotFound
from .repository import canonical_json, new_id, now, sha256_text
from .workspace_access import workspace_operation

SCHEMA = """
CREATE TABLE IF NOT EXISTS chapter_reviews (
 id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
 chapter_id TEXT NOT NULL REFERENCES chapters(id), status TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, result_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chapter_reviews_scope ON chapter_reviews(work_id,chapter_id,created_at);
"""


class ChapterReview:
    def __init__(self, service):
        self.service, self.repo, self.data_access = service, service.repo, service.data_access
        self._lock = threading.Lock()

    def snapshot(self, work_id, chapter_id):
        work = self.service.get_work(work_id)
        chapter = next((ch for ch in work["chapters"] if ch["id"] == chapter_id), None)
        if not chapter:
            raise NotFound("章节", chapter_id)
        dependencies = sorted(
            (a["id"], a["current_revision_id"])
            for a in work["artifacts"]
            if a["kind"]
            in {"brief", "story_blueprint", "world_bible", "character_card", "work_canon"}
            or a["kind"] in {"chapter_plan", "outline_document"}
            and a["scope_id"] in {work_id, chapter_id, chapter["volume_id"]}
        )
        return {
            "scenes": [
                {
                    "scene_id": scene["id"],
                    "revision_id": scene["current_revision_id"],
                    "contract": scene["contract"],
                    "assets": scene.get("asset_references", []),
                }
                for scene in chapter["scenes"]
            ],
            "dependencies": dependencies,
        }

    def _same(self, snapshot, work_id, chapter_id):
        return canonical_json(snapshot) == canonical_json(self.snapshot(work_id, chapter_id))

    @workspace_operation
    def get(self, work_id, chapter_id):
        snapshot = self.snapshot(work_id, chapter_id)
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_reviews WHERE work_id=? AND chapter_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (work_id, chapter_id),
            ).fetchone()
        if not row:
            return {
                "schema_version": "chapter-review/1.0",
                "status": "not_checked",
                "chapter_id": chapter_id,
            }
        result = json.loads(row["result_json"])
        work = self.service.get_work(work_id)
        revisions = {item["revision_id"] for item in snapshot["scenes"]}
        findings = [
            f
            for f in work.get("review_findings", [])
            if f.get("revision_id") in revisions and f.get("status") == "open"
        ]
        proposal = next(
            (p for p in work.get("proposals", []) if p["id"] == result.get("proposal_id")), None
        )
        stale = canonical_json(snapshot) != row["snapshot_json"]
        status = row["status"]
        if stale:
            status = "stale"
        elif status not in {"running", "failed"}:
            if any(f.get("severity") == "blocking" for f in findings):
                status = "blocked"
            elif result.get("decision"):
                status = "complete"
            else:
                status = "awaiting_changes"
        return {
            "schema_version": "chapter-review/1.0",
            "id": row["id"],
            "chapter_id": chapter_id,
            "status": status,
            "stale": stale,
            "findings": findings,
            "proposal": proposal,
            "result": result,
            "updated_at": row["updated_at"],
        }

    def _record(self, review_id, result, status):
        with self.repo.transaction() as connection:
            connection.execute(
                "UPDATE chapter_reviews SET result_json=?,status=?,updated_at=? WHERE id=?",
                (canonical_json(result), status, now(), review_id),
            )

    @workspace_operation
    def run(self, work_id, chapter_id, payload):
        if not self._lock.acquire(blocking=False):
            raise DomainError(
                "chapter_review_busy", "已有章节正在检查，请等它完成后继续。", status=409
            )
        try:
            return self._run(work_id, chapter_id, payload)
        finally:
            self._lock.release()

    def _run(self, work_id, chapter_id, payload):
        # A queued review pins manuscript and material dependencies. Background
        # suggestions can bump the work version without changing those inputs.
        if not payload.get("_chapter_snapshot"):
            with self.repo.connect() as connection:
                self.service._check_work_version(
                    connection, work_id, payload.get("expected_version", -1)
                )
        snapshot = self.snapshot(work_id, chapter_id)
        if payload.get("_chapter_snapshot") and canonical_json(
            payload["_chapter_snapshot"]
        ) != canonical_json(snapshot):
            raise DomainError(
                "chapter_review_stale", "排队期间章节已变化，请重新检查当前版本。", status=409
            )
        if not snapshot["scenes"] or any(not s["revision_id"] for s in snapshot["scenes"]):
            raise DomainError(
                "chapter_requires_manuscript", "请先保存本章各场景的正文。", status=409
            )
        previous = self.get(work_id, chapter_id)
        # A retry reuses completed work only for the exact same source snapshot.
        reusable = previous.get("id") and not previous.get("stale")
        if reusable and previous["status"] in {"complete", "awaiting_changes", "blocked"}:
            return {"review": previous, "work": self.service.get_work(work_id)}
        review_id = previous["id"] if reusable else new_id("chapter-review")
        result = dict(previous.get("result", {})) if reusable else {"scene_ids": [], "gate_ids": []}
        result.pop("error", None)
        if not reusable:
            with self.repo.transaction() as connection:
                timestamp = now()
                connection.execute(
                    "INSERT INTO chapter_reviews VALUES (?,?,?,?,?,?,?,?)",
                    (
                        review_id,
                        work_id,
                        chapter_id,
                        "running",
                        canonical_json(snapshot),
                        canonical_json(result),
                        timestamp,
                        timestamp,
                    ),
                )
        self._record(review_id, result, "running")

        agent_run_id = new_id("agent-run")
        snapshot_uri, snapshot_hash = self.repo.atomic_write_text(
            f"agent-runs/{agent_run_id}/input.json", canonical_json(snapshot)
        )
        with self.repo.transaction() as connection:
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_run_id,
                    work_id,
                    "chapter",
                    chapter_id,
                    "检查本章并整理变化",
                    "running",
                    canonical_json({"workflow": "chapter.review", "chapter_review_id": review_id}),
                    snapshot_uri,
                    snapshot_hash,
                    None,
                    None,
                    now(),
                    None,
                ),
            )
        result["agent_run_id"] = agent_run_id
        child_payload = {
            key: value for key, value in payload.items() if key != "_run_started_callback"
        }

        def request():
            with self.repo.connect() as connection:
                self.service._require_agent_run_committable(connection, agent_run_id)
            if not self._same(snapshot, work_id, chapter_id):
                raise DomainError(
                    "chapter_review_stale", "本章正文或引用资料已变化，请重新检查。", status=409
                )
            return {**child_payload, "expected_version": self.service.get_work(work_id)["version"]}

        try:
            self.service._notify_agent_run_started(payload, agent_run_id)
            for index, scene in enumerate(snapshot["scenes"]):
                if scene["scene_id"] in result["scene_ids"]:
                    continue
                result["step"] = f"检查本章内容 {index + 1}/{len(snapshot['scenes'])}"
                self._record(review_id, result, "running")
                checked = self.service.review_scene(work_id, scene["scene_id"], request())
                result["scene_ids"].append(scene["scene_id"])
                result["gate_ids"].append(checked["gate_id"])
                self._record(review_id, result, "running")
            if not result.get("continuity_gate_id"):
                result["step"] = "检查场景之间的承接"
                self._record(review_id, result, "running")
                pack = self.service._assemble_work_review_pack(work_id, "continuity.review")
                pack["chapter_id"] = chapter_id
                pack["scenes"] = [s for s in pack["scenes"] if s["chapter_id"] == chapter_id]
                # Preserve complete text rather than the work-wide excerpt view.
                with self.repo.connect() as connection:
                    for item in pack["scenes"]:
                        content = self.service._revision_content(connection, item["revision_id"])
                        excerpt = self.service._traceable_text_excerpt(
                            content.get("text", ""),
                            max_chars=max(1, len(content.get("text", ""))),
                            include_start=True,
                        )
                        item.update(
                            text_excerpt=excerpt["text"],
                            excerpt_segments=excerpt["segments"],
                            text_truncated=False,
                        )
                pack["outline"] = self.service.authoring.outline_context(work_id, chapter_id)
                pack["digest"] = sha256_text(
                    canonical_json({k: v for k, v in pack.items() if k != "digest"})
                )
                checked = self.service._run_work_review_agent(
                    work_id,
                    request(),
                    "continuity.review",
                    review_pack=pack,
                    provider=self.service._provider_for_request(payload)[0],
                )
                result["continuity_gate_id"] = checked["gate_id"]
                self._record(review_id, result, "running")
            if not result.get("proposal_id"):
                result["step"] = "整理本章变化"
                self._record(review_id, result, "running")
                work = self.service.get_work(work_id)
                pending = next(
                    (
                        p
                        for p in work["proposals"]
                        if p["kind"] == "memory_bundle"
                        and p["scope_id"] == chapter_id
                        and p["status"] == "pending"
                    ),
                    None,
                )
                refs = [(s["scene_id"], s["revision_id"]) for s in snapshot["scenes"]]
                if (
                    pending
                    and [
                        (s["scene_id"], s["revision_id"])
                        for s in pending.get("candidate", {}).get("source_scene_revisions", [])
                    ]
                    == refs
                ):
                    result["proposal_id"] = pending["id"]
                else:
                    if pending:
                        with self.repo.transaction() as connection:
                            connection.execute(
                                "UPDATE proposals SET status='superseded',decided_at=? WHERE id=? AND status='pending'",
                                (now(), pending["id"]),
                            )
                    result["proposal_id"] = self.service.sweep_chapter_memory(
                        work_id, chapter_id, request()
                    )["proposal_id"]
            request()
            result["step"] = "检查完成，请确认本章变化"
            self._record(review_id, result, "awaiting_changes")
            with self.repo.transaction() as connection:
                connection.execute(
                    "UPDATE agent_runs SET status='waiting_user',proposal_id=?,finished_at=? WHERE id=? AND status='running'",
                    (result["proposal_id"], now(), agent_run_id),
                )
        except Exception as exc:
            result["error"] = {
                "code": getattr(exc, "code", "chapter_review_failed"),
                "message": exc.message if isinstance(exc, DomainError) else "检查未完成，请重试。",
            }
            self._record(review_id, result, "failed")
            with self.repo.transaction() as connection:
                connection.execute(
                    "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                    (canonical_json(result["error"]), now(), agent_run_id),
                )
            raise
        return {"review": self.get(work_id, chapter_id), "work": self.service.get_work(work_id)}

    @workspace_operation
    def decide(self, work_id, chapter_id, payload):
        current = self.get(work_id, chapter_id)
        if current.get("id") != payload.get("review_id") or current["status"] in {
            "stale",
            "running",
            "failed",
            "not_checked",
        }:
            raise DomainError("chapter_review_stale", "请重新检查当前版本后处理变化。", status=409)
        if current["result"].get("decision"):
            return {"review": current, "work": self.service.get_work(work_id)}
        decision = payload.get("decision")
        if decision not in {"accept", "keep"}:
            raise DomainError("validation_error", "请选择采用本章变化或保留现有资料。")
        proposal = current.get("proposal")
        if not proposal:
            raise DomainError(
                "chapter_changes_missing", "本章变化结果暂不可用，请重新检查。", status=409
            )
        if proposal["status"] == "pending":
            if decision == "accept" and proposal.get("candidate", {}).get("items"):
                self.service.accept_proposal(work_id, proposal["id"], payload)
            else:
                self.service.reject_proposal(
                    work_id,
                    proposal["id"],
                    {**payload, "note": "作者已查看本章变化，保留现有资料。"},
                )
        elif proposal["status"] not in {"accepted", "partially_accepted", "rejected"}:
            raise DomainError("chapter_changes_stale", "变化建议已经过期，请重新检查。", status=409)
        result = {**current["result"], "decision": decision, "decided_at": now()}
        self._record(current["id"], result, "complete")
        with self.repo.transaction() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='succeeded',finished_at=? WHERE id=? AND status='waiting_user'",
                (now(), result.get("agent_run_id")),
            )
        return {"review": self.get(work_id, chapter_id), "work": self.service.get_work(work_id)}
