"""Durable chapter candidates on the existing Agent run/lease/task boundary."""

from __future__ import annotations

import json

from .errors import DomainError, NotFound
from .adaptation_targets import resolve_target
from .repository import canonical_json, new_id, now, sha256_text
from .workspace_access import workspace_operation

OPERATION = "adaptation.chapter.generate"


class AdaptationJobs:
    def __init__(self, service):
        self.service = service
        self.repo = service.repo
        self.data_access = self.repo.data_access

    def _pins(self, connection, work_id, adaptation_id, chapter_id):
        row = connection.execute(
            "SELECT * FROM adaptations WHERE id=? AND work_id=?", (adaptation_id, work_id)
        ).fetchone()
        if not row:
            raise NotFound("adaptation", adaptation_id)
        if row["status"] not in {"ready", "running", "analyzed"}:
            raise DomainError("adaptation_plan_required", "请先确认改编计划。", status=409)
        selected = json.loads(row["selected_chapter_ids_json"])
        chapter = connection.execute(
            "SELECT * FROM adaptation_chapters WHERE adaptation_id=? AND source_chapter_id=?",
            (adaptation_id, chapter_id),
        ).fetchone()
        if chapter_id not in selected or not chapter:
            raise NotFound("adaptation_chapter", chapter_id)
        source = connection.execute(
            "SELECT current_version_id FROM work_sources WHERE work_id=?", (work_id,)
        ).fetchone()
        if not source or source["current_version_id"] != row["source_version_id"]:
            raise DomainError(
                "adaptation_inputs_changed", "原文版本已变化，请重新确认改编计划。", status=409
            )
        source_row = connection.execute(
            "SELECT document_json FROM source_versions WHERE id=? AND work_id=?",
            (row["source_version_id"], work_id),
        ).fetchone()
        if not source_row:
            raise NotFound("source", row["source_version_id"])
        source_doc = json.loads(source_row["document_json"])
        source_chapter = next((c for c in source_doc["chapters"] if c["id"] == chapter_id), None)
        if not source_chapter:
            raise NotFound("source_chapter", chapter_id)
        target = resolve_target(connection, work_id, chapter)
        return {
            "work_id": work_id,
            "adaptation_id": adaptation_id,
            "chapter_id": chapter_id,
            "scope_id": chapter["id"],
            "source_version_id": row["source_version_id"],
            "source_digest": source_chapter["content_digest"],
            "plan_digest": sha256_text(canonical_json(json.loads(row["plan_json"]))),
            "base_revision_id": target["base_revision_id"],
            "target": target,
        }

    def _assert_pins(self, connection, snapshot):
        if not isinstance(snapshot.get("target"), dict):
            raise DomainError(
                "adaptation_target_confirmation_required",
                "旧任务没有固定场景目标，不能直接重试；请重新生成并确认目标。",
                status=409,
                details={"retryable": False},
            )
        current = self._pins(
            connection, snapshot["work_id"], snapshot["adaptation_id"], snapshot["chapter_id"]
        )
        if any(snapshot.get(key) != value for key, value in current.items()):
            raise DomainError(
                "adaptation_inputs_changed",
                "原文、计划或已采纳正文已变化，本轮不会继续写入。",
                status=409,
            )

    @workspace_operation
    def enqueue(self, work_id, adaptation_id, chapter_id, payload=None, *, retry_snapshot=None):
        payload = payload or {}
        # Reading the public descriptor does not wait for an unrelated model call.
        # The worker verifies this identity against its actual captured provider.
        provider_runtime = self.service.provider.descriptor()
        if "expected_provider" in payload and (
            not isinstance(payload["expected_provider"], dict)
            or canonical_json(payload["expected_provider"]) != canonical_json(provider_runtime)
        ):
            raise DomainError(
                "provider_config_changed", "模型已变化，请重新查看当前模型后确认生成。", status=409
            )
        if retry_snapshot is not None:
            provider_runtime = retry_snapshot["provider_runtime"]
        agent_id, item_id, attempt_id, job_id = (
            new_id(p) for p in ("agent", "item", "attempt", "agent-job")
        )
        with self.repo.transaction() as c:
            pins = self._pins(c, work_id, adaptation_id, chapter_id)
            if retry_snapshot is not None:
                self._assert_pins(c, retry_snapshot)
            active = c.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE operation=? AND status IN ('ready','running') AND agent_run_id IN (SELECT id FROM agent_runs WHERE status IN ('queued','running')) ORDER BY created_at",
                (OPERATION,),
            ).fetchall()
            for row in active:
                existing = json.loads(row["payload_json"])
                if (
                    existing.get("work_id") == work_id
                    and existing.get("scope_id") == pins["scope_id"]
                ):
                    return {
                        "agent_run_id": row["agent_run_id"],
                        "job": self.service._public_agent_job(
                            work_id, self.repo._agent_work_row(row)
                        ),
                        "deduplicated": True,
                    }
            snapshot = {
                "schema_version": "adaptation-agent-input/1.1",
                **pins,
                "provider_runtime": provider_runtime,
            }
            uri, digest = self.repo.atomic_write_text(
                f"agent-runs/{agent_id}/input.json", canonical_json(snapshot)
            )
            production = c.execute(
                "SELECT id FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1",
                (work_id,),
            ).fetchone()
            if not production:
                raise DomainError("creation_run_missing", "作品缺少创作运行记录。", status=409)
            timestamp = now()
            policy = {
                "workflow": OPERATION,
                "write_boundary": "proposal_only",
                "provider_runtime": provider_runtime,
                "retry_of_agent_run_id": payload.get("_retry_of"),
            }
            c.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_id,
                    work_id,
                    "adaptation_chapter",
                    pins["scope_id"],
                    "改编已提供的原文章节；仅生成待审核候选。",
                    "queued",
                    canonical_json(policy),
                    uri,
                    digest,
                    None,
                    None,
                    timestamp,
                    None,
                ),
            )
            c.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    production["id"],
                    OPERATION,
                    "adaptation_chapter",
                    pins["scope_id"],
                    "queued",
                    canonical_json([pins["source_version_id"]]),
                    "[]",
                    canonical_json(
                        {"proposal_only": True, "agent_run_id": agent_id, "retryable": True}
                    ),
                    1,
                    None,
                    timestamp,
                    timestamp,
                ),
            )
            c.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    item_id,
                    1,
                    self.service.provider.kind,
                    digest,
                    "queued",
                    None,
                    None,
                    timestamp,
                    None,
                ),
            )
            job_payload = {
                "work_id": work_id,
                "scope_id": pins["scope_id"],
                "item_id": item_id,
                "attempt_id": attempt_id,
                "production_run_id": production["id"],
            }
            c.execute(
                "INSERT INTO agent_dispatch_jobs (id,agent_run_id,work_item_id,operation,payload_json,status,available_at,created_at,updated_at) VALUES (?,?,?,?,?,'ready',?,?,?)",
                (
                    job_id,
                    agent_id,
                    item_id,
                    OPERATION,
                    canonical_json(job_payload),
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = c.execute("SELECT * FROM agent_dispatch_jobs WHERE id=?", (job_id,)).fetchone()
            public = self.service._public_agent_job(work_id, self.repo._agent_work_row(row))
            self._refresh_run(c, production["id"])
        self.service.agent_dispatcher.start()
        self.service.agent_dispatcher.notify()
        return {"agent_run_id": agent_id, "job": public, "deduplicated": False}

    def _lease(self, connection, job):
        row = connection.execute(
            "SELECT * FROM agent_dispatch_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        if (
            not row
            or row["status"] != "running"
            or row["cancel_requested_at"]
            or row["lease_token"] != job["lease_token"]
            or row["lease_owner"] != job["lease_owner"]
            or not row["lease_expires_at"]
            or row["lease_expires_at"] <= now()
        ):
            raise DomainError(
                "agent_dispatch_lease_lost",
                "改编任务已停止或租约失效，迟到结果不会保存。",
                status=409,
            )

    @staticmethod
    def _refresh_run(connection, run_id):
        states = {
            row[0]
            for row in connection.execute("SELECT status FROM work_items WHERE run_id=?", (run_id,))
        }
        state = (
            "running"
            if states & {"ready", "queued", "running"}
            else ("waiting_user" if "waiting_user" in states else "failed")
        )
        connection.execute(
            "UPDATE production_runs SET status=?,updated_at=? WHERE id=?", (state, now(), run_id)
        )

    def _finish(self, c, job, proposal_id):
        timestamp = now()
        payload = job["payload"]
        c.execute(
            "UPDATE agent_runs SET status='completed',proposal_id=?,finished_at=? WHERE id=? AND status='running'",
            (proposal_id, timestamp, job["agent_run_id"]),
        )
        c.execute(
            "UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?",
            (proposal_id, timestamp, payload["attempt_id"]),
        )
        c.execute(
            "UPDATE work_items SET status='waiting_user',output_refs_json=?,updated_at=? WHERE id=?",
            (canonical_json([proposal_id]), timestamp, payload["item_id"]),
        )
        self._refresh_run(c, payload["production_run_id"])

    def dispatch(self, job):
        run_id = job["agent_run_id"]
        try:
            with self.repo.transaction() as c:
                self._lease(c, job)
                row = c.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
                if not row or row["status"] != "queued":
                    raise DomainError("agent_run_interrupted", "改编运行不能再次执行。", status=409)
                raw = self.repo.read_text(row["input_snapshot_uri"])
                if sha256_text(raw) != row["input_digest"]:
                    raise DomainError("agent_input_corrupted", "改编固定输入校验失败。", status=409)
                snapshot = json.loads(raw)
                self._assert_pins(c, snapshot)
                timestamp = now()
                c.execute("UPDATE agent_runs SET status='running' WHERE id=?", (run_id,))
                c.execute(
                    "UPDATE job_attempts SET status='started' WHERE id=?",
                    (job["payload"]["attempt_id"],),
                )
                c.execute(
                    "UPDATE work_items SET status='running',updated_at=? WHERE id=?",
                    (timestamp, job["payload"]["item_id"]),
                )
            provider, identity = self.service._capture_provider(snapshot["provider_runtime"])
            if canonical_json(identity) != canonical_json(snapshot["provider_runtime"]):
                raise DomainError(
                    "provider_config_changed",
                    "本轮固定的模型或模拟模式已变化；请确认当前配置后重新发起，不会静默替换执行。",
                    status=409,
                )

            def guard(connection):
                self._lease(connection, job)
                self.service._require_agent_run_committable(connection, run_id)
                self._assert_pins(connection, snapshot)

            return self.service.adaptations.generate_chapter_candidate(
                snapshot["adaptation_id"],
                snapshot["chapter_id"],
                {
                    "_provider_instance": provider,
                    "_expected_provider": identity,
                    "_commit_guard": guard,
                    "_candidate_committed": lambda c, ident: self._finish(c, job, ident),
                },
            )
        except Exception as error:
            failure = {
                "code": getattr(error, "code", "adaptation_provider_failed"),
                "message": getattr(error, "message", "改编生成失败，请查看任务并明确重试。"),
                "retryable": error.code != "adaptation_target_confirmation_required"
                if isinstance(error, DomainError)
                else True,
            }
            with self.repo.transaction() as c:
                completed = c.execute(
                    "SELECT proposal_id FROM agent_runs WHERE id=? AND status='completed'",
                    (run_id,),
                ).fetchone()
                if completed and completed["proposal_id"]:
                    # Presentation can fail after the durable candidate commits.
                    # Do not convert a delivered result into a retryable failure.
                    return {"agent_run_id": run_id, "proposal_id": completed["proposal_id"]}
                timestamp = now()
                c.execute(
                    "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status IN ('queued','running')",
                    (canonical_json(failure), timestamp, run_id),
                )
                c.execute(
                    "UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status IN ('queued','started')",
                    (failure["code"], timestamp, job["payload"]["attempt_id"]),
                )
                changed = c.execute(
                    "UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status IN ('queued','running')",
                    (canonical_json(failure), timestamp, job["payload"]["item_id"]),
                ).rowcount
                if changed:
                    self._refresh_run(c, job["payload"]["production_run_id"])
            raise

    def retry(self, work_id, run, payload):
        raw = self.repo.read_text(run["input_snapshot_uri"])
        if sha256_text(raw) != run["input_digest"]:
            raise DomainError("agent_input_corrupted", "改编固定输入校验失败。", status=409)
        snapshot = json.loads(raw)
        return self.enqueue(
            work_id,
            snapshot["adaptation_id"],
            snapshot["chapter_id"],
            {"_retry_of": run["id"]},
            retry_snapshot=snapshot,
        )
