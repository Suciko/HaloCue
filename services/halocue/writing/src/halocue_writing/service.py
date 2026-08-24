from __future__ import annotations

import base64
import binascii
import difflib
import io
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from .errors import DomainError, NotFound, RevisionConflict
from .ba_world_starter import BA_WORLD_STARTER_SOURCE, BA_WORLD_STARTER_VERSION, starter_bible
from .model_settings import UserPreferencesStore, WritingModelSettings
from .memory_store import (
    memory_projection_rows,
    relevant_memories,
    validate_provider_chapter_memory_bundle,
    validate_provider_knowledge_suggestions,
    validate_provider_memory_bundle,
)
from .official_reference_catalog import OfficialReferenceCatalog
from .providers import FakeWritingProvider, make_writing_provider
from .agent_tools import AgentToolRegistry, ToolExecutionContext
from .document_context import index_attachment, normalize_text, retrieve_context
from .conversation_summary import (
    conversation_summary_evidence_ids,
    recent_conversation_history,
    refresh_conversation_summary,
    validate_conversation_summary,
)
from .repository import Repository, canonical_json, new_id, now, sha256_text
from .workflow_pack import COMMON_RULES, DOCUMENT_SKILL, MODE_SOURCES, PACK_VERSION, describe_pack, template_contract
from .ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
from .ba_character_card_import import (
    build_character_card_payload,
    identity_tokens,
    parse_import_payload,
    validation_failure,
)
from .ba_world_card_import import (
    EXTRACTOR_VERSION as WORLD_IMPORT_EXTRACTOR_VERSION,
    PROFILE_FORMAT as WORLD_IMPORT_PROFILE_FORMAT,
    identity_tokens as world_identity_tokens,
    parse_import_payload as parse_world_import_payload,
    validation_failure as world_import_validation_failure,
)
from .backup import WritingBackupManager
from .agent_dispatcher import AgentDispatcher
from .proposal_impact import build_knowledge_impact_preview
from .scene_readiness import build_scene_readiness
from .writing_harness import WritingHarness
from .commit_projection import CommitProjection
from .current_projection import CurrentWorkProjection
from .agent_presentation import AgentPresentationQuery
from .release_integrity import (
    build_production_handoff,
    source_set_digest,
    verify_script_release,
)
from .resource_catalog import ResourceCatalog
from .aap_import import parse_aap_payload
from .story_import import parse_story_payload


class _ProposalAcceptanceStopped(Exception):
    def __init__(self, *, status: str, decision: str, note: str, error: DomainError):
        super().__init__(error.message)
        self.status = status
        self.decision = decision
        self.note = note
        self.error = error


class WritingService:
    def __init__(self, data_dir: Path, production_url: str = "http://127.0.0.1:8892", official_corpus_dir: Path | None = None):
        self.repo = Repository(data_dir)
        self.model_settings = WritingModelSettings(data_dir)
        self.preferences = UserPreferencesStore(data_dir)
        self.ba_skill = BaWritingSkillRegistry()
        self.ba_skill_pack = self.ba_skill.materialize(self.repo)
        self.ba_prompt_assembler = BaWritingPromptAssembler(self.ba_skill)
        self.provider = make_writing_provider(self.model_settings, self.ba_prompt_assembler)
        self.agent_tools = AgentToolRegistry(self)
        self.production_url = production_url.rstrip("/")
        self.feedback_remote_url = os.environ.get("HALOCUE_FEEDBACK_REMOTE_URL", "").strip().rstrip("/")
        self.feedback_remote_token = os.environ.get("HALOCUE_FEEDBACK_REMOTE_TOKEN", "").strip()
        self.feedback_client_version = os.environ.get("HALOCUE_CLIENT_VERSION", "1.0")
        configured_corpus = official_corpus_dir or os.environ.get("HALOCUE_BA_CORPUS_DIR")
        if configured_corpus:
            corpus_dir = Path(configured_corpus)
        else:
            corpus_dir = Path(__file__).resolve().parents[3] / "05-官方演出语料库" / "records"
        self.official_references = OfficialReferenceCatalog(corpus_dir)
        self.resource_catalog = ResourceCatalog(data_dir)
        self._agent_threads: dict[str, threading.Thread] = {}
        self._agent_threads_lock = threading.Lock()
        self._provider_lock = threading.Lock()
        self._data_maintenance_lock = threading.Lock()
        self._release_handoff_lock = threading.Lock()
        self._commit_projection_reconciled = False
        self._commit_projection_reconciliation = {
            "status": "not_started",
            "source_revision_count": 0,
            "registered_count": 0,
            "queued_count": 0,
            "errors": [],
        }
        self._background_knowledge_reconciliation = {
            "ready_count": 0,
            "queued_count": 0,
            "errors": [],
        }
        self.agent_dispatcher = AgentDispatcher(self.repo)
        self.commit_projection = CommitProjection(self.repo)
        self.current_projection = CurrentWorkProjection(self.repo)
        self.writing_harness = WritingHarness(self.repo)
        self.agent_presentation = AgentPresentationQuery(self.repo)
        self.agent_dispatcher.register("conversation.message", self._dispatch_conversation_message)
        self.agent_dispatcher.register("commit.projection", self._dispatch_commit_projection)
        for operation in (
            "scene.candidate.generate",
            "scene.draft.generate",
            "scene.draft.rewrite",
            "scene.review",
            "continuity.review",
            "release.review",
            "memory.extract",
            "memory.sweep",
            "knowledge.discover",
        ):
            self.agent_dispatcher.register(operation, self._dispatch_workflow_operation)

    def start(self):
        """Start recoverable background Agent work for the server process."""
        started = self.agent_dispatcher.start()
        with self._data_maintenance_lock:
            if not self._commit_projection_reconciled:
                self._commit_projection_reconciliation = self._reconcile_commit_projections()
                self._background_knowledge_reconciliation = self._reconcile_background_knowledge_jobs()
                self._commit_projection_reconciled = True
        if (
            self._commit_projection_reconciliation["queued_count"]
            or self._background_knowledge_reconciliation["queued_count"]
        ):
            self.agent_dispatcher.notify()
        return {
            **started,
            "commit_projection_reconciliation": dict(self._commit_projection_reconciliation),
            "background_knowledge_reconciliation": dict(self._background_knowledge_reconciliation),
        }

    def close(self, timeout: float = 5.0):
        """Stop claiming new Agent work and wait a bounded time for the worker."""
        return self.agent_dispatcher.close(timeout=timeout)

    def health(self):
        return {
            "ok": True,
            "service": "halocue-writing",
            "version": "0.1.0",
            "data_dir": str(self.repo.data_dir),
            "provider": self.provider.descriptor(),
            "ba_writing_skill": self.ba_skill.descriptor(),
            "agent_dispatcher": self.agent_dispatcher.descriptor(),
            "commit_projection_reconciliation": dict(self._commit_projection_reconciliation),
            "background_knowledge_reconciliation": dict(self._background_knowledge_reconciliation),
        }

    def _capture_provider(self, expected: dict | None = None):
        """Return one runtime Provider, fenced by its public non-secret identity."""
        with self._provider_lock:
            provider = self.provider
            identity = provider.descriptor()
        if isinstance(expected, dict) and expected:
            expected_digest = str(expected.get("config_digest") or "")
            changed = (
                expected_digest not in {"", "simulation", "unversioned"}
                and expected_digest != str(identity.get("config_digest") or "")
            )
            if changed:
                raise DomainError(
                    "provider_config_changed",
                    "这轮任务固定的模型配置已经变化，系统没有用新模型静默重跑。请确认当前模型后重新发起。",
                    status=409,
                    details={"expected": expected, "actual": identity},
                )
        return provider, identity

    def _provider_for_request(self, payload: dict):
        pinned = payload.get("_provider_instance")
        expected = payload.get("_expected_provider")
        if pinned is None:
            return self._capture_provider(expected if isinstance(expected, dict) else None)
        identity = pinned.descriptor()
        expected_digest = str(expected.get("config_digest") or "") if isinstance(expected, dict) else ""
        if (
            expected_digest not in {"", "simulation", "unversioned"}
            and expected_digest != str(identity.get("config_digest") or "")
        ):
            raise DomainError(
                "provider_config_changed",
                "这轮任务固定的模型配置已经变化，系统没有用新模型静默执行。",
                status=409,
                details={"expected": expected, "actual": identity},
            )
        return pinned, identity

    def capabilities(self):
        return {
            "api_version": "1.0",
            "capabilities": [
                "works",
                "brief_revisions",
                "story_blueprint",
                "scene_context",
                "proposal_diff",
                "script_release",
                "production_handoff",
                "production_asset_handoff",
                "production_asset_reconciliation",
                "work_canon",
                "character_cards",
                "world_bible",
                "ba_world_starter",
                "reference_files",
                "official_reference_catalog",
                "review_findings",
                "agent_runs",
                "volumes",
                "conversation_threads",
                "conversation_attachments",
                "natural_language_intent",
                "intent_plan_confirmation",
                "authorization_policies",
                "feedback_reports",
                "provider_reasoning_trace",
                "agent_tool_registry",
                "scene_writing_pack",
                "ba_scene_review_agent",
                "ba_continuity_review_agent",
                "ba_release_review_agent",
                "long_term_memory",
                "memory_bundle_proposal",
                "memory_context_retrieval",
                "chapter_memory_sweep_agent",
                "durable_agent_dispatcher",
                "idempotent_agent_retry",
                "cancelled_result_fencing",
                "proposal_impact_preview",
                "agent_run_timeline",
                "writing_harness_status",
                "writing_harness_doctor",
                "commit_projection",
                "commit_projection_retry",
                "commit_projection_search",
            ],
            "writing_pack": describe_pack(),
            "ba_writing_skill": self.ba_skill.descriptor(),
            "providers": [self.provider.descriptor()],
            "official_references": self.official_references.descriptor(),
        }

    def _ba_writing_source_digest(self) -> str:
        digest = str(self.ba_skill.descriptor().get("source_digest") or "")
        return digest if digest.startswith("sha256:") else f"sha256:{digest}"

    def get_harness_status(
        self,
        work_id: str,
        *,
        scope_type: str = "work",
        scope_id: str | None = None,
        thread_id: str | None = None,
    ) -> dict:
        return self.writing_harness.resolve(
            work_id,
            scope_type=scope_type,
            scope_id=scope_id,
            provider=self.provider.descriptor(),
            thread_id=thread_id,
        )

    def diagnose_writing_harness(self, work_id: str) -> dict:
        return self.writing_harness.doctor(
            work_id,
            runtime={
                "provider": self.provider.descriptor(),
                "ba_writing_skill": self.ba_skill.descriptor(),
                "dispatcher": self.agent_dispatcher.descriptor(),
            },
        )

    def ensure_commit_projection(self, work_id: str, revision_id: str) -> dict:
        return self.commit_projection.ensure(work_id, revision_id)

    def get_commit_projection(self, work_id: str, revision_id: str) -> dict:
        return self.commit_projection.get(work_id, revision_id)

    def get_current_projection(self, work_id: str) -> dict:
        return self.current_projection.get(work_id)

    def search_commit_projections(
        self,
        work_id: str,
        query: str,
        *,
        artifact_kinds: list[str] | tuple[str, ...] | None = None,
        limit: int | str = 8,
    ) -> dict:
        return self.commit_projection.search_current(
            work_id,
            query,
            artifact_kinds=artifact_kinds,
            limit=limit,
        )

    def run_commit_projection(
        self,
        work_id: str,
        revision_id: str,
        projection_kinds: list[str] | None = None,
    ) -> dict:
        return self.commit_projection.run(
            work_id,
            revision_id,
            self.provider,
            projection_kinds=projection_kinds,
            postprocess=self._postprocess_commit_projection,
        )

    def retry_commit_projection(self, work_id: str, revision_id: str) -> dict:
        return self.commit_projection.retry(
            work_id,
            revision_id,
            self.provider,
            postprocess=self._postprocess_commit_projection,
        )

    def skip_commit_projection(
        self,
        work_id: str,
        revision_id: str,
        kind: str,
        *,
        reason: str,
    ) -> dict:
        return self.commit_projection.skip(
            work_id,
            revision_id,
            kind,
            reason=reason,
        )

    def _postprocess_commit_projection(self, kind: str, source: dict, output: dict) -> dict:
        content = dict(output.get("content") or {})
        if kind == "memory_followup" and content.get("required"):
            scene_id = str(source.get("scene_id") or "")
            if not scene_id:
                raise DomainError(
                    "commit_projection_output_invalid",
                    "记忆待办缺少场景作用域。",
                    status=502,
                )
            with self.repo.transaction() as connection:
                work_item_id, run_id = self._ensure_memory_extract_work_item(
                    connection,
                    source["work_id"],
                    scene_id,
                    source["revision_id"],
                )
            queued = self._queue_background_knowledge_discovery(
                source["work_id"],
                scene_id,
                source["revision_id"],
            )
            content.update({
                "work_item_id": work_item_id,
                "production_run_id": run_id,
                "background_knowledge_job_id": queued["job"]["id"] if queued else None,
            })
        elif kind == "review_followup" and content.get("required"):
            content.update(
                {
                    "action": "scene.review",
                    "scene_id": source.get("scene_id"),
                    "revision_id": source["revision_id"],
                }
            )
        return {**output, "content": content}

    def _queue_background_knowledge_discovery(
        self,
        work_id: str,
        scene_id: str,
        revision_id: str,
    ) -> dict | None:
        """Queue one quiet, revision-pinned formal-knowledge discovery pass."""

        with self.repo.connect() as connection:
            row = connection.execute(
                """SELECT work.version,scene.current_revision_id
                   FROM works AS work JOIN scenes AS scene ON scene.work_id=work.id
                   WHERE work.id=? AND scene.id=?""",
                (work_id, scene_id),
            ).fetchone()
        if not row or row["current_revision_id"] != revision_id:
            return None
        _, provider_runtime = self._capture_provider()
        payload = {
            "work_id": work_id,
            "scope_id": scene_id,
            "request": {
                "expected_version": row["version"],
                "_background": True,
                "_source_revision_id": revision_id,
            },
            "provider_runtime": provider_runtime,
        }
        with self.repo.connect() as connection:
            previous_rows = connection.execute(
                """SELECT * FROM agent_dispatch_jobs
                   WHERE operation='knowledge.discover'
                   ORDER BY created_at DESC"""
            ).fetchall()
        for previous in previous_rows:
            try:
                previous_payload = json.loads(previous["payload_json"] or "{}")
            except json.JSONDecodeError:
                continue
            previous_request = previous_payload.get("request")
            if (
                previous_payload.get("work_id") == work_id
                and previous_payload.get("scope_id") == scene_id
                and isinstance(previous_request, dict)
                and previous_request.get("_source_revision_id") == revision_id
            ):
                return {"created": False, "job": dict(previous)}
        queued = self.repo.enqueue_agent_work(
            operation="knowledge.discover",
            payload=payload,
            dedupe_by_payload=True,
        )
        if queued["created"]:
            self.agent_dispatcher.notify()
        return queued

    def _reconcile_background_knowledge_jobs(self) -> dict:
        """Recover missing discovery jobs for current formal scene revisions."""

        with self.repo.connect() as connection:
            rows = connection.execute(
                """SELECT scene.work_id,scene.id AS scene_id,
                          scene.current_revision_id AS revision_id
                   FROM scenes AS scene
                   WHERE scene.current_revision_id IS NOT NULL
                   ORDER BY scene.created_at"""
            ).fetchall()
        queued_count = 0
        errors = []
        for row in rows:
            try:
                queued = self._queue_background_knowledge_discovery(
                    row["work_id"], row["scene_id"], row["revision_id"]
                )
                if queued and queued["created"]:
                    queued_count += 1
            except Exception as exc:
                errors.append({
                    "scene_id": row["scene_id"],
                    "type": type(exc).__name__,
                    "message": str(exc),
                })
        return {"ready_count": len(rows), "queued_count": queued_count, "errors": errors}

    def _dispatch_commit_projection(self, job: dict):
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        work_id = str(payload.get("work_id") or "")
        revision_id = str(payload.get("revision_id") or "")
        if not work_id or not revision_id:
            raise DomainError(
                "commit_projection_dispatch_invalid",
                "提交投影任务缺少固定 Revision。",
                status=409,
            )
        return self.run_commit_projection(work_id, revision_id)

    def _schedule_commit_projection(self, work_id: str, revision_id: str) -> dict:
        projection = self.ensure_commit_projection(work_id, revision_id)
        if projection["status"] == "completed":
            return projection
        queued = self.repo.enqueue_agent_work(
            operation="commit.projection",
            payload={
                "work_id": work_id,
                "revision_id": revision_id,
                "projection_id": projection["id"],
            },
            dedupe_by_payload=True,
        )
        self.agent_dispatcher.notify()
        return {**projection, "dispatch_job_id": queued["job"]["id"]}

    def _reconcile_commit_projections(self) -> dict:
        """Register current formal revisions created before projection support."""

        with self.repo.connect() as connection:
            sources = connection.execute(
                """SELECT work_id,current_revision_id FROM artifacts
                   WHERE kind IN ('scene_script','character_card','world_bible','work_canon')
                     AND current_revision_id IS NOT NULL
                   ORDER BY work_id,kind,scope_id"""
            ).fetchall()
        registered_count = 0
        queued_count = 0
        errors = []
        for source in sources:
            try:
                existing = self.repo.get_commit_projection(
                    work_id=source["work_id"],
                    revision_id=source["current_revision_id"],
                )
                projection = self.ensure_commit_projection(
                    source["work_id"], source["current_revision_id"]
                )
                if not existing:
                    registered_count += 1
                if projection["status"] != "completed":
                    queued = self.repo.enqueue_agent_work(
                        operation="commit.projection",
                        payload={
                            "work_id": source["work_id"],
                            "revision_id": source["current_revision_id"],
                            "projection_id": projection["id"],
                        },
                        dedupe_by_payload=True,
                    )
                    if queued["created"]:
                        queued_count += 1
            except Exception as exc:
                errors.append({
                    "work_id": source["work_id"],
                    "revision_id": source["current_revision_id"],
                    "type": type(exc).__name__,
                })
        return {
            "status": "completed" if not errors else "partial",
            "source_revision_count": len(sources),
            "registered_count": registered_count,
            "queued_count": queued_count,
            "errors": errors,
        }

    def agent_tool_catalog(self):
        return {
            "schema_version": "agent-tools/1.0",
            "tools": [
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "risk": spec.risk,
                    "allowed_modes": sorted(spec.allowed_modes),
                    "allowed_scopes": sorted(spec.allowed_scopes),
                    "mutates_formal_data": spec.mutates_formal_data,
                    "requires_user_confirmation": spec.requires_user_confirmation,
                    "required_action": spec.required_action,
                }
                for spec in self.agent_tools.specs()
            ],
            "write_boundary": "formal_artifacts_require_proposal_acceptance",
        }

    def agent_usage(self, work_id: str):
        with self.repo.connect() as connection:
            if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
            policies = connection.execute(
                "SELECT policy_json FROM agent_runs WHERE work_id=?",
                (work_id,),
            ).fetchall()
            statuses = self.repo.rows(connection.execute(
                "SELECT status,COUNT(*) AS count FROM agent_runs WHERE work_id=? GROUP BY status ORDER BY status",
                (work_id,),
            ))
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "estimated_cost": 0.0,
        }
        priced_run_count = 0
        for row in policies:
            try:
                policy = json.loads(row["policy_json"] or "{}")
            except json.JSONDecodeError:
                continue
            usage = policy.get("usage") if isinstance(policy.get("usage"), dict) else {}
            for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
                totals[key] += max(0, int(usage.get(key) or 0))
            if usage.get("estimated_cost") is not None:
                totals["estimated_cost"] += max(0.0, float(usage["estimated_cost"]))
                priced_run_count += 1
        input_tokens = int(totals["input_tokens"])
        cache_read = int(totals["cache_read_tokens"])
        denominator = input_tokens
        return {
            "schema_version": "agent-usage/1.0", "work_id": work_id,
            "input_tokens": input_tokens, "output_tokens": int(totals["output_tokens"]),
            "cache_read_tokens": cache_read, "cache_write_tokens": int(totals["cache_write_tokens"]),
            "cache_hit_rate": round(cache_read / denominator, 4) if denominator else 0,
            "estimated_cost": round(float(totals["estimated_cost"]), 6),
            "cost_available": priced_run_count > 0,
            "runs_by_status": {item["status"]: item["count"] for item in statuses},
            "currency": "USD", "cost_is_estimate": True,
        }

    def get_agent_run(self, work_id: str, run_id: str):
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_runs WHERE id=? AND work_id=?", (run_id, work_id)
            ).fetchone()
            if not row:
                raise NotFound("agent_run", run_id)
            run = dict(row)
            run["policy"] = json.loads(run.pop("policy_json"))
            run["failure"] = json.loads(run.pop("failure_json")) if run.get("failure_json") else None
            run["tool_calls"] = self.repo.rows(connection.execute(
                "SELECT * FROM agent_tool_calls WHERE agent_run_id=? ORDER BY ordinal", (run_id,)
            ))
            for call in run["tool_calls"]:
                call["error"] = json.loads(call.pop("error_json")) if call.get("error_json") else None
            run["timeline"] = self._agent_run_timeline(connection, run, run["tool_calls"])
        return run

    def get_agent_presentation(self, work_id: str, thread_id: str, *, limit: int = 100, cursor: str | None = None):
        """Return a read-only, bounded Agent workbench projection."""
        for _ in range(2):
            presentation = self.agent_presentation.get_thread_timeline(
                work_id, thread_id, limit=limit, cursor=cursor,
            )
            thread = presentation["thread"]
            harness = self.get_harness_status(
                work_id,
                scope_type=thread["scope_type"],
                scope_id=thread["scope_id"],
                thread_id=thread_id,
            )
            if harness["work_version"] == presentation["snapshot"]["work_version"]:
                presentation["guidance"] = {
                    "source_schema_version": harness["schema_version"],
                    "work_version": harness["work_version"],
                    "scope": harness["scope"],
                    "outcome": harness["outcome"],
                    "phase": harness["phase"],
                    "headline": harness["headline"],
                    "blockers": [
                        {
                            "id": str(item.get("id") or item.get("code") or "blocker"),
                            "message": str(item.get("message") or "需要先处理阻塞项。"),
                        }
                        for item in harness.get("blockers") or []
                    ],
                    "primary_action": harness["primary_action"],
                }
                return presentation
        raise DomainError(
            "agent_presentation_snapshot_changed",
            "作品状态刚刚发生变化，请重新加载 Agent 页面。",
            status=409,
        )

    def _agent_run_timeline(self, connection, run: dict, tool_calls: list[dict]) -> dict:
        events: list[tuple[str, int, dict]] = [
            (
                str(run["created_at"]),
                0,
                {
                    "id": f"{run['id']}:started",
                    "type": "run_started",
                    "status": "completed" if run["status"] not in {"queued", "running"} else run["status"],
                    "created_at": run["created_at"],
                    "label": "开始处理",
                },
            )
        ]
        for call in tool_calls:
            spec = self.agent_tools.get(str(call.get("tool_name") or ""))
            events.append(
                (
                    str(call["created_at"]),
                    100 + int(call.get("ordinal") or 0),
                    {
                        "id": call["id"],
                        "type": "tool",
                        "status": call["status"],
                        "created_at": call["created_at"],
                        "completed_at": call.get("finished_at"),
                        "label": spec.description if spec else str(call.get("tool_name") or "执行工具"),
                        "tool_name": call.get("tool_name"),
                        "has_error": bool(call.get("error")),
                    },
                )
            )
        messages = self.repo.rows(
            connection.execute(
                "SELECT id,status,proposal_id,content_json,created_at FROM conversation_messages WHERE agent_run_id=? ORDER BY ordinal",
                (run["id"],),
            )
        )
        for message in messages:
            content = json.loads(message.pop("content_json"))
            summary = " ".join(str(content.get("text") or "").split())[:240]
            events.append(
                (
                    str(message["created_at"]),
                    1000,
                    {
                        "id": message["id"],
                        "type": "response",
                        "status": message["status"],
                        "created_at": message["created_at"],
                        "label": "Agent 回复",
                        "summary": summary,
                        "proposal_id": message.get("proposal_id"),
                    },
                )
            )
        if run.get("proposal_id"):
            proposal = connection.execute(
                "SELECT id,kind,status,created_at,decided_at FROM proposals WHERE id=?",
                (run["proposal_id"],),
            ).fetchone()
            if proposal:
                events.append(
                    (
                        str(proposal["created_at"]),
                        1100,
                        {
                            "id": proposal["id"],
                            "type": "proposal",
                            "status": proposal["status"],
                            "created_at": proposal["created_at"],
                            "completed_at": proposal["decided_at"],
                            "label": "生成待审 Proposal",
                            "proposal_kind": proposal["kind"],
                        },
                    )
                )
        if run.get("finished_at"):
            events.append(
                (
                    str(run["finished_at"]),
                    2000,
                    {
                        "id": f"{run['id']}:finished",
                        "type": "run_finished",
                        "status": run["status"],
                        "created_at": run["finished_at"],
                        "label": "处理完成" if run["status"] not in {"failed", "cancelled"} else "处理已结束",
                    },
                )
            )
        started = [entry for entry in events if entry[2]["type"] == "run_started"]
        finished = [entry for entry in events if entry[2]["type"] == "run_finished"]
        middle = [
            entry for entry in events
            if entry[2]["type"] not in {"run_started", "run_finished"}
        ]
        ordered = [
            *[item for _, _, item in started],
            *[item for _, _, item in sorted(middle, key=lambda entry: (entry[0], entry[1], entry[2]["id"]))],
            *[item for _, _, item in finished],
        ]
        for sequence, event in enumerate(ordered, start=1):
            event["sequence"] = sequence
        return {
            "schema_version": "agent-run-timeline/1.0",
            "visibility": "user_summary",
            "event_count": len(ordered),
            "events": ordered,
        }

    def get_proposal_impact(self, work_id: str, proposal_id: str):
        with self.repo.connect() as connection:
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
            if not proposal or proposal["kind"] not in {"character_card", "world_entity", "world_rule", "canon_fact"}:
                raise NotFound("proposal", proposal_id)
            candidate = json.loads(self._verified_proposal_candidate(proposal))
            impact = candidate.get("impact_preview")
            if not isinstance(impact, dict) or impact.get("schema_version") != "proposal-impact/1.0":
                raise DomainError(
                    "proposal_impact_unavailable",
                    "这份资料候选没有可验证的影响预览，请重新整理。",
                    status=409,
                )
            if proposal["kind"] == "character_card":
                artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='character_card' AND scope_type='character' AND scope_id=?",
                    (work_id, candidate["scope_id"]),
                ).fetchone()
            else:
                artifact_kind = "world_bible" if proposal["kind"] in {"world_entity", "world_rule"} else "work_canon"
                artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind=? AND scope_type='work' AND scope_id=?",
                    (work_id, artifact_kind, work_id),
                ).fetchone()
            work = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            current_revision_id = artifact["current_revision_id"] if artifact else None
            base_matches = current_revision_id == candidate.get("base_revision_id")
            live_conflicts = self._knowledge_conflicts(
                connection,
                work_id,
                str(candidate.get("kind") or ""),
                candidate.get("content") or {},
            )
            blocking_conflicts = self._knowledge_decision_conflicts(candidate, live_conflicts)
            live_affected_refs = self._knowledge_affected_refs(
                connection,
                work_id,
                str(candidate.get("kind") or ""),
                str(candidate.get("scope_id") or ""),
                candidate.get("content") or {},
            )
            affected_refs_match = canonical_json(live_affected_refs) == canonical_json(impact.get("affected_refs") or [])
            return {
                "schema_version": "proposal-impact-view/1.0",
                "proposal_id": proposal_id,
                "proposal_status": proposal["status"],
                "candidate_hash": proposal["candidate_hash"],
                "impact": impact,
                "live_validation": {
                    "work_version": work["version"],
                    "current_revision_id": current_revision_id,
                    "base_revision_matches": base_matches,
                    "blocking_conflicts": blocking_conflicts,
                    "affected_refs": live_affected_refs,
                    "affected_refs_match": affected_refs_match,
                    "ready_for_decision": (
                        proposal["status"] == "pending"
                        and base_matches
                        and not blocking_conflicts
                        and affected_refs_match
                    ),
                },
            }

    def cancel_agent_run(self, work_id: str, run_id: str):
        timestamp = now()
        failure = {
            "code": "cancelled_by_user",
            "type": "AgentRunCancelled",
            "message": "用户取消了本轮 Agent 运行，模型结果不会写入对话或正式资料。",
        }
        with self.repo.transaction() as connection:
            run = connection.execute(
                "SELECT status FROM agent_runs WHERE id=? AND work_id=?", (run_id, work_id)
            ).fetchone()
            if not run:
                raise NotFound("agent_run", run_id)
            if run["status"] not in {"queued", "running"}:
                raise DomainError(
                    "agent_run_not_cancellable", "本轮 Agent 已经结束，不能再取消。", status=409,
                    details={"status": run["status"]},
                )
            connection.execute(
                "UPDATE agent_runs SET status='cancelled',failure_json=?,finished_at=? WHERE id=?",
                (canonical_json(failure), timestamp, run_id),
            )
            linked_items = connection.execute(
                "SELECT id,run_id FROM work_items WHERE acceptance_json LIKE ?",
                (f'%"agent_run_id":"{run_id}"%',),
            ).fetchall()
            for item in linked_items:
                connection.execute(
                    """UPDATE job_attempts
                       SET status='cancelled',error_code='cancelled_by_user',finished_at=?
                       WHERE work_item_id=? AND status IN ('queued','started','running')""",
                    (timestamp, item["id"]),
                )
                connection.execute(
                    """UPDATE work_items SET status='cancelled',error_json=?,updated_at=?
                       WHERE id=? AND status IN ('ready','queued','running')""",
                    (canonical_json(failure), timestamp, item["id"]),
                )
                remaining = connection.execute(
                    """SELECT 1 FROM work_items
                       WHERE run_id=? AND status IN ('ready','queued','running') LIMIT 1""",
                    (item["run_id"],),
                ).fetchone()
                if not remaining:
                    connection.execute(
                        "UPDATE production_runs SET status='waiting_user',updated_at=? WHERE id=? AND status='running'",
                        (timestamp, item["run_id"]),
                    )
            connection.execute(
                """UPDATE agent_tool_calls SET status='cancelled',error_json=?,finished_at=?
                   WHERE agent_run_id=? AND status IN ('queued','running')""",
                (canonical_json(failure), timestamp, run_id),
            )
            # The dispatcher table is added by the durable queue migration. Keep
            # older workspaces compatible while the migration is rolling out.
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_dispatch_jobs'"
            ).fetchone():
                connection.execute(
                    """UPDATE agent_dispatch_jobs
                       SET status='cancelled',cancel_requested_at=?,lease_owner=NULL,
                           lease_token=NULL,lease_expires_at=NULL,updated_at=?
                       WHERE agent_run_id=? AND status IN ('ready','running')""",
                    (timestamp, timestamp, run_id),
                )
        return self.get_agent_run(work_id, run_id)

    def _agent_run_is_running(self, run_id: str) -> bool:
        with self.repo.connect() as connection:
            row = connection.execute("SELECT status FROM agent_runs WHERE id=?", (run_id,)).fetchone()
        return bool(row and row["status"] == "running")

    @staticmethod
    def _require_agent_run_committable(connection, run_id: str):
        """Fence every Agent result commit against cancellation or lease loss."""
        row = connection.execute(
            "SELECT status FROM agent_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not row:
            raise DomainError("agent_run_missing", "Agent 运行记录不存在。", status=409)
        if row["status"] != "running":
            raise DomainError(
                "agent_run_interrupted",
                "Agent 运行已被停止，迟到结果不会写入。",
                status=409,
                details={"status": row["status"]},
            )

    @staticmethod
    def _notify_agent_run_started(payload: dict, run_id: str) -> None:
        callback = payload.get("_run_started_callback")
        if callable(callback):
            callback(run_id)

    def _dispatch_conversation_message(self, job: dict):
        queued = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        work_id = str(queued.get("work_id") or "")
        thread_id = str(queued.get("thread_id") or "")
        request = queued.get("request") if isinstance(queued.get("request"), dict) else {}
        if not work_id or not thread_id:
            raise DomainError("agent_dispatch_input_invalid", "持久对话任务缺少作品或对话作用域。", status=409)

        def on_started(run_id: str):
            bound = self.repo.bind_agent_work_run(
                job_id=job["id"],
                lease_owner=job["lease_owner"],
                lease_token=job["lease_token"],
                agent_run_id=run_id,
            )
            if not bound["applied"]:
                try:
                    self.cancel_agent_run(work_id, run_id)
                finally:
                    raise DomainError(
                        "agent_dispatch_lease_lost",
                        "Agent 任务租约已经失效，本轮不会继续提交结果。",
                        status=409,
                    )

        result = self.post_conversation_message(
            work_id,
            thread_id,
            {
                **request,
                "_run_started_callback": on_started,
                "_expected_provider": queued.get("provider_runtime"),
            },
        )
        intent_execution = None
        if not result.get("cancelled"):
            intent_execution = self._auto_execute_intent_scene(
                work_id,
                request,
                expected_provider=queued.get("provider_runtime"),
            )
        if intent_execution:
            result["intent_execution"] = intent_execution
            result["work"] = self.get_work(work_id)
            plan_id = str(request.get("intent_plan_id") or "")
            if plan_id:
                with self.repo.transaction() as connection:
                    row = connection.execute("SELECT result_json FROM intent_plans WHERE id=? AND work_id=?", (plan_id, work_id)).fetchone()
                    if row:
                        plan_result = json.loads(row["result_json"] or "{}")
                        plan_result["intent_execution"] = intent_execution
                        execution_status = str(intent_execution.get("status") or "")
                        plan_status = execution_status if execution_status in {"blocked", "failed", "waiting_user"} else "running"
                        connection.execute(
                            "UPDATE intent_plans SET status=?,result_json=?,updated_at=? WHERE id=?",
                            (plan_status, canonical_json(plan_result), now(), plan_id),
                        )
        return result

    def _auto_execute_intent_scene(
        self,
        work_id: str,
        request: dict,
        *,
        expected_provider: dict | None = None,
    ) -> dict | None:
        """Start the scene Proposal step for an explicit natural-language write.

        Intent uses a work-scoped conversation so the user can keep one
        continuous thread.  Once that discussion is persisted, a scene Agent
        still needs the scene-scoped context and its own Proposal/Diff run.
        This bridge performs that step only for ``request_source=intent``;
        ordinary work conversations remain discussion-only until the user
        chooses the scene action explicitly.
        """
        if str(request.get("request_source") or "") != "intent":
            return None
        scope = request.get("task_scope") if isinstance(request.get("task_scope"), dict) else {}
        if str(scope.get("surface") or "") != "scene" or bool(scope.get("discussion_only")):
            return None
        scene_id = str(scope.get("scene_id") or "").strip()
        if not scene_id:
            return None

        work = self.get_work(work_id)
        scene = next(
            (
                scene
                for chapter in work.get("chapters", [])
                for scene in chapter.get("scenes", [])
                if scene.get("id") == scene_id
            ),
            None,
        )
        if not scene:
            return {
                "status": "blocked",
                "code": "invalid_scene_target",
                "message": "自然语言目标场景已经不存在，请重新选择当前章节结构。",
            }
        # Intent-created scenes have no manual context picker.  When the
        # work already has confirmed source material, pin only cards named by
        # this scene or request. Selecting every confirmed card can silently
        # replace an unknown requested character with an unrelated cast.
        contract = scene.get("contract") if isinstance(scene.get("contract"), dict) else {}
        selection = contract.get("context_selection") if isinstance(contract.get("context_selection"), dict) else {}
        intent_owned_selection = bool(contract.get("intent_source")) and (
            selection.get("mode") != "explicit"
            or selection.get("source") == "intent_auto"
            or "source" not in selection
        )
        instruction = str(request.get("text") or "").strip()
        if selection.get("mode") != "explicit" or intent_owned_selection:
            card_ids, available_card_names = self._intent_character_context(work, scene, instruction)
            if card_ids or (intent_owned_selection and available_card_names):
                world_ids = []
                world_artifact = next((item for item in work.get("artifacts", []) if item.get("kind") == "world_bible"), None)
                world_content = (world_artifact or {}).get("current_revision", {}).get("content", {})
                for collection in ("entities", "rules", "timeline"):
                    world_ids.extend(
                        item.get("id")
                        for item in world_content.get(collection, [])
                        if item.get("id")
                        and item.get("status", "active") == "active"
                        and item.get("confidence_status") == "confirmed"
                    )
                reference_ids = [
                    item.get("id")
                    for item in work.get("reference_files", [])
                    if item.get("id") and item.get("trust_status") == "confirmed"
                ]
                try:
                    configured = self._configure_intent_scene_context(
                        work_id,
                        scene_id,
                        expected_version=work["version"],
                        character_card_ids=card_ids,
                        world_item_ids=world_ids,
                        reference_file_ids=reference_ids,
                    )
                except DomainError as exc:
                    return {
                        "status": "blocked",
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details if isinstance(exc.details, dict) else {},
                    }
                work = configured["work"]
                scene = next(
                    (
                        scene
                        for chapter in work.get("chapters", [])
                        for scene in chapter.get("scenes", [])
                        if scene.get("id") == scene_id
                    ),
                    scene,
                )

            if intent_owned_selection and available_card_names and not card_ids:
                return {
                    "status": "blocked",
                    "code": "intent_character_context_missing",
                    "message": "本场提到的人物尚未匹配到已确认人物卡；系统没有用其他角色代替，也没有生成正文候选。",
                    "details": {
                        "scene_id": scene_id,
                        "available_character_cards": available_card_names,
                        "recovery": "先根据本轮讨论建立并确认所需人物卡，或在本场上下文中明确选择人物。",
                    },
                }

        pending = next(
            (
                proposal
                for proposal in work.get("proposals", [])
                if proposal.get("kind") == "scene_script"
                and proposal.get("scope_id") == scene_id
                and proposal.get("status") == "pending"
            ),
            None,
        )
        if pending:
            return {
                "status": "waiting_user",
                "proposal_id": pending["id"],
                "message": "本场已有候选等待审查，系统没有重复生成。",
            }

        context = self.assemble_context(work_id, scene_id)
        if context["readiness"]["real_ba_writing"] != "ready_for_provider":
            return {
                "status": "blocked",
                "code": "agent_blocked",
                "message": "本场运行时人物卡或 BA 写作规则尚未就绪，已保留讨论结果，没有伪造正文候选。",
                "details": {
                    "missing_runtime_character_cards": context["readiness"].get("missing_runtime_character_cards", []),
                    "skill_source": context["readiness"].get("skill_source"),
                    "missing_skill_files": context.get("skill_runtime", {}).get("missing_files", []),
                },
            }

        if not instruction:
            return None
        constraints = {
            "schema_version": "intent-scene-constraints/1.0",
            "source": "natural_language_intent",
            "original_message": instruction,
            "scene_id": scene_id,
            "write_boundary": "只形成场景 Proposal/Diff；用户采纳前不得写入正式正文。",
        }
        agent_payload = {
            "expected_version": work["version"],
            "instruction": instruction,
            "discussion_constraints": constraints,
            "_expected_provider": expected_provider,
        }
        try:
            if scene.get("current_revision_id"):
                generated = self.run_scene_rewrite_agent(work_id, scene_id, agent_payload)
            else:
                generated = self.run_scene_agent(work_id, scene_id, agent_payload)
        except DomainError as exc:
            return {
                "status": "failed" if exc.code in {"agent_failed", "provider_failed"} else "blocked",
                "code": exc.code,
                "message": exc.message,
                "details": exc.details if isinstance(exc.details, dict) else {},
            }
        return {
            "status": "waiting_user",
            "proposal_id": generated.get("proposal_id"),
            "proposal_agent_run_id": generated.get("agent_run_id"),
            "simulation": generated.get("simulation"),
            "message": "已生成场景候选，正式正文尚未改变。",
        }

    def _dispatch_workflow_operation(self, job: dict):
        queued = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        work_id = str(queued.get("work_id") or "")
        scope_id = str(queued.get("scope_id") or "")
        request = queued.get("request") if isinstance(queued.get("request"), dict) else {}
        operation = str(job.get("operation") or "")
        if not work_id:
            raise DomainError("agent_dispatch_input_invalid", "持久 Agent 任务缺少作品作用域。", status=409)
        if operation in {"memory.extract", "knowledge.discover"} and request.get("_background"):
            with self.repo.connect() as connection:
                current_work = connection.execute(
                    "SELECT version FROM works WHERE id=?", (work_id,)
                ).fetchone()
            if not current_work:
                raise NotFound("work", work_id)
            request = {**request, "expected_version": current_work["version"]}

        def on_started(run_id: str):
            bound = self.repo.bind_agent_work_run(
                job_id=job["id"],
                lease_owner=job["lease_owner"],
                lease_token=job["lease_token"],
                agent_run_id=run_id,
            )
            if not bound["applied"]:
                try:
                    self.cancel_agent_run(work_id, run_id)
                finally:
                    raise DomainError(
                        "agent_dispatch_lease_lost",
                        "Agent 任务租约已经失效，本轮不会继续提交结果。",
                        status=409,
                    )

        provider, provider_runtime = self._capture_provider(queued.get("provider_runtime"))
        dispatched_request = {
            **request,
            "_run_started_callback": on_started,
            "_provider_instance": provider,
            "_expected_provider": provider_runtime,
        }
        if operation == "scene.candidate.generate":
            return self.generate_scene_candidate(work_id, scope_id, dispatched_request)
        if operation == "scene.draft.generate":
            return self.run_scene_agent(work_id, scope_id, dispatched_request)
        if operation == "scene.draft.rewrite":
            return self.run_scene_rewrite_agent(work_id, scope_id, dispatched_request)
        if operation == "scene.review":
            return self.review_scene(work_id, scope_id, dispatched_request)
        if operation == "continuity.review":
            return self.review_continuity(work_id, dispatched_request)
        if operation == "release.review":
            return self.review_release(work_id, dispatched_request)
        if operation == "memory.extract":
            return self.generate_memory_proposal(work_id, scope_id, dispatched_request)
        if operation == "memory.sweep":
            return self.sweep_chapter_memory(work_id, scope_id, dispatched_request)
        if operation == "knowledge.discover":
            return self.discover_scene_knowledge(work_id, scope_id, dispatched_request)
        raise DomainError("agent_operation_not_registered", "Agent 工作流未注册。", status=409)

    def enqueue_agent_operation(self, work_id: str, payload: dict):
        operation = str(payload.get("operation") or "").strip()
        allowed = {
            "scene.candidate.generate": "scene",
            "scene.draft.generate": "scene",
            "scene.draft.rewrite": "scene",
            "scene.review": "scene",
            "continuity.review": "work",
            "release.review": "work",
            "memory.extract": "scene",
            "memory.sweep": "chapter",
        }
        if operation not in allowed:
            raise DomainError(
                "validation_error",
                "不支持的 Agent 工作流。",
                details={"field": "operation", "allowed": sorted(allowed)},
            )
        scope_id = str(payload.get("scope_id") or (work_id if allowed[operation] == "work" else "")).strip()
        if not scope_id:
            raise DomainError("validation_error", "Agent 工作流缺少作用域。", details={"field": "scope_id"})
        request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        _, provider_runtime = self._capture_provider()
        queued = self.repo.enqueue_agent_work(
            operation=operation,
            payload={
                "work_id": work_id,
                "scope_id": scope_id,
                "request": request,
                "provider_runtime": provider_runtime,
            },
        )["job"]
        self.agent_dispatcher.start()
        self.agent_dispatcher.notify()
        return self._public_agent_job(work_id, queued)

    def get_agent_job(self, work_id: str, job_id: str):
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE id=?", (job_id,)
            ).fetchone()
        if not row:
            raise NotFound("agent_job", job_id)
        return self._public_agent_job(work_id, self.repo._agent_work_row(row))

    def cancel_agent_job(self, work_id: str, job_id: str):
        current = self.get_agent_job(work_id, job_id)
        if current.get("agent_run_id"):
            self.cancel_agent_run(work_id, current["agent_run_id"])
        else:
            self.repo.cancel_agent_work(job_id=job_id)
        return self.get_agent_job(work_id, job_id)

    @staticmethod
    def _public_agent_job(work_id: str, job: dict):
        queued_payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        if queued_payload.get("work_id") != work_id:
            raise NotFound("agent_job", job.get("id", ""))
        return {
            "id": job["id"],
            "operation": job["operation"],
            "scope_id": queued_payload.get("scope_id") or queued_payload.get("thread_id"),
            "status": job["status"],
            "agent_run_id": job.get("agent_run_id"),
            "error": job.get("error"),
            "available_at": job.get("available_at"),
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }

    def enqueue_conversation_message(self, work_id: str, thread_id: str, payload: dict):
        """Persist the request, then return once its fixed AgentRun exists."""
        with self.repo.connect() as connection:
            active = self._active_conversation_run(connection, work_id, thread_id)
        if active:
            raise DomainError(
                "agent_run_active",
                "当前对话仍有一轮 Agent 在运行；请停止本轮，或把新要求作为转向提交。",
                status=409,
                details={"agent_run_id": active["id"]},
            )
        durable_request = {
            key: value
            for key, value in payload.items()
            if not key.startswith("_") and not callable(value)
        }
        _, provider_runtime = self._capture_provider()
        queued = self.repo.enqueue_agent_work(
            operation="conversation.message",
            payload={
                "work_id": work_id,
                "thread_id": thread_id,
                "request": durable_request,
                "provider_runtime": provider_runtime,
            },
        )["job"]
        self.agent_dispatcher.start()
        self.agent_dispatcher.notify()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.repo.connect() as connection:
                row = connection.execute(
                    "SELECT agent_run_id,status,error_json FROM agent_dispatch_jobs WHERE id=?",
                    (queued["id"],),
                ).fetchone()
            if not row:
                raise DomainError("agent_start_failed", "持久 Agent 任务记录不存在。", status=500)
            if row["agent_run_id"]:
                run = self.get_agent_run(work_id, row["agent_run_id"])
                return {
                    "agent_run_id": run["id"],
                    "status": run["status"],
                    "work": self.get_work(work_id),
                }
            if row["status"] in {"failed", "cancelled"}:
                error = json.loads(row["error_json"]) if row["error_json"] else {}
                raise DomainError(
                    "agent_start_failed",
                    "Agent 运行未能建立。",
                    status=500,
                    details=error,
                )
            time.sleep(0.01)

        self.repo.cancel_agent_work(job_id=queued["id"])
        raise DomainError("agent_start_timeout", "Agent 输入未能及时保存，请重试。", status=503)

    @staticmethod
    def _active_conversation_run(connection, work_id: str, thread_id: str):
        rows = connection.execute(
            "SELECT * FROM agent_runs WHERE work_id=? AND status IN ('queued','running') ORDER BY created_at DESC,id DESC",
            (work_id,),
        ).fetchall()
        for row in rows:
            try:
                policy = json.loads(row["policy_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if policy.get("thread_id") == thread_id:
                return dict(row)
        return None

    def redirect_agent_run(self, work_id: str, run_id: str, payload: dict):
        text = str(payload.get("text") or "").strip()
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        expected_thread_version = int(payload.get("expected_thread_version", -1))
        if not text:
            raise DomainError("validation_error", "转向要求不能为空。", details={"field": "text"})
        if not idempotency_key or len(idempotency_key) > 160:
            raise DomainError("validation_error", "转向需要有效的幂等键。", details={"field": "idempotency_key"})
        request_key = f"redirect:{idempotency_key}"
        claim = self.repo.claim_agent_retry(original_run_id=run_id, idempotency_key=request_key)
        request = claim["request"]
        if not claim["claimed"]:
            return self._wait_for_agent_redirect(run_id, request_key)
        try:
            with self.repo.connect() as connection:
                run = connection.execute(
                    "SELECT * FROM agent_runs WHERE id=? AND work_id=?", (run_id, work_id)
                ).fetchone()
                if not run:
                    raise NotFound("agent_run", run_id)
                policy = json.loads(run["policy_json"] or "{}")
                thread_id = str(policy.get("thread_id") or "")
                if not thread_id:
                    raise DomainError("agent_redirect_unsupported", "这类 Agent 运行不支持对话转向。", status=409)
                self._check_thread_version(connection, work_id, thread_id, expected_thread_version)
                if run["status"] not in {"queued", "running"}:
                    raise DomainError("agent_run_not_active", "本轮 Agent 已经结束，不能再转向。", status=409)
            self.cancel_agent_run(work_id, run_id)
            result = self.enqueue_conversation_message(
                work_id,
                thread_id,
                {
                    "expected_thread_version": expected_thread_version,
                    "text": text,
                    "attachment_ids": payload.get("attachment_ids") or [],
                    "task_scope": payload.get("task_scope"),
                    "redirect_of": run_id,
                },
            )
            result["redirected_from_agent_run_id"] = run_id
        except Exception as exc:
            error = {
                "code": getattr(exc, "code", "agent_redirect_failed"),
                "message": getattr(exc, "message", str(exc) or "Agent 转向失败。"),
                "status": getattr(exc, "status", 500),
                "details": getattr(exc, "details", {}),
            }
            self.repo.fail_agent_retry(
                original_run_id=run_id, idempotency_key=request_key,
                claim_token=request["claim_token"], error=error,
            )
            raise
        self.repo.complete_agent_retry(
            original_run_id=run_id, idempotency_key=request_key,
            claim_token=request["claim_token"], new_run_id=result["agent_run_id"], result=result,
        )
        return result

    def _wait_for_agent_redirect(self, run_id: str, request_key: str):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            request = self.repo.get_agent_retry(original_run_id=run_id, idempotency_key=request_key)
            if request and request["status"] == "succeeded":
                return json.loads(request["result_json"])
            if request and request["status"] == "failed":
                error = json.loads(request["error_json"] or "{}")
                raise DomainError(
                    str(error.get("code") or "agent_redirect_failed"),
                    str(error.get("message") or "Agent 转向失败。"),
                    status=int(error.get("status") or 500),
                    details=error.get("details") if isinstance(error.get("details"), dict) else {},
                )
            time.sleep(0.01)
        raise DomainError(
            "agent_redirect_in_progress", "同一轮 Agent 正在处理转向，请稍后查看运行状态。",
            status=409, details={"agent_run_id": run_id},
        )

    def retry_agent_run(self, work_id: str, run_id: str, payload: dict):
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key:
            return self._retry_agent_run_once(work_id, run_id, payload)
        if len(idempotency_key) > 160:
            raise DomainError(
                "validation_error",
                "重试幂等键过长。",
                details={"field": "idempotency_key"},
            )

        claim = self.repo.claim_agent_retry(
            original_run_id=run_id,
            idempotency_key=idempotency_key,
        )
        request = claim["request"]
        if not claim["claimed"]:
            return self._wait_for_agent_retry(run_id, idempotency_key)

        try:
            result = self._retry_agent_run_once(work_id, run_id, payload)
        except Exception as exc:
            error = {
                "code": getattr(exc, "code", "agent_retry_failed"),
                "message": getattr(exc, "message", str(exc) or "Agent 重试失败。"),
                "status": getattr(exc, "status", 500),
                "details": getattr(exc, "details", {}),
            }
            self.repo.fail_agent_retry(
                original_run_id=run_id,
                idempotency_key=idempotency_key,
                claim_token=request["claim_token"],
                error=error,
            )
            raise
        new_run_id = str(result.get("agent_run_id") or "")
        if not new_run_id:
            error = {
                "code": "agent_retry_result_invalid",
                "message": "Agent 重试没有返回新的运行标识。",
                "status": 500,
                "details": {},
            }
            self.repo.fail_agent_retry(
                original_run_id=run_id,
                idempotency_key=idempotency_key,
                claim_token=request["claim_token"],
                error=error,
            )
            raise DomainError(error["code"], error["message"], status=500)
        self.repo.complete_agent_retry(
            original_run_id=run_id,
            idempotency_key=idempotency_key,
            claim_token=request["claim_token"],
            new_run_id=new_run_id,
            result=result,
        )
        return result

    def _wait_for_agent_retry(self, run_id: str, idempotency_key: str):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            request = self.repo.get_agent_retry(
                original_run_id=run_id,
                idempotency_key=idempotency_key,
            )
            if request and request["status"] == "succeeded":
                return json.loads(request["result_json"])
            if request and request["status"] == "failed":
                error = json.loads(request["error_json"] or "{}")
                raise DomainError(
                    str(error.get("code") or "agent_retry_failed"),
                    str(error.get("message") or "Agent 重试失败。"),
                    status=int(error.get("status") or 500),
                    details=error.get("details") if isinstance(error.get("details"), dict) else {},
                )
            time.sleep(0.01)
        raise DomainError(
            "agent_retry_in_progress",
            "同一轮 Agent 正在重试，请稍后查看运行状态。",
            status=409,
            details={"agent_run_id": run_id},
        )

    def _retry_agent_run_once(self, work_id: str, run_id: str, payload: dict):
        expected_thread = int(payload.get("expected_thread_version", -1))
        with self.repo.connect() as connection:
            run = connection.execute("SELECT * FROM agent_runs WHERE id=? AND work_id=?", (run_id, work_id)).fetchone()
            if not run:
                raise NotFound("agent_run", run_id)
            if run["status"] not in {"failed", "cancelled"}:
                raise DomainError("agent_run_not_retryable", "只有失败或已取消的 Agent 运行可以重试。", status=409)
            policy = json.loads(run["policy_json"])
            if policy.get("workflow") in {
                "scene.candidate.generate", "scene.draft.generate", "scene.draft.rewrite", "scene.review",
            }:
                return self._retry_scene_agent_run(work_id, run, payload)
            if policy.get("workflow") in {"continuity.review", "release.review"}:
                return self._retry_review_agent_run(work_id, run, payload)
            if policy.get("workflow") == "memory.extract":
                return self._retry_memory_agent_run(work_id, run, payload)
            if policy.get("workflow") == "memory.sweep":
                return self._retry_memory_sweep_agent_run(work_id, run, payload)
            if policy.get("workflow") == "structure.plan":
                return self._retry_structure_agent_run(work_id, run, payload)
            linked = connection.execute(
                """SELECT thread.* FROM conversation_messages AS message
                   JOIN conversation_threads AS thread ON thread.id=message.thread_id
                   WHERE message.agent_run_id=? AND thread.work_id=?
                   ORDER BY message.ordinal DESC LIMIT 1""",
                (run_id, work_id),
            ).fetchone()
            if not linked:
                raise DomainError("agent_retry_context_missing", "失败运行没有可恢复的对话上下文。", status=409)
            if linked["status"] != "active":
                raise DomainError("agent_thread_archived", "请先恢复归档对话，再重试本轮。", status=409)
            if linked["version"] != expected_thread:
                raise DomainError(
                    "thread_conflict", "对话已在其他位置更新，请刷新后重试。", status=409,
                    details={"expected_version": expected_thread, "actual_version": linked["version"]},
                )
            snapshot = self._read_retry_snapshot(run)
            if snapshot.get("schema_version") not in {
                "conversation-agent-input/1.0",
                "conversation-agent-input/1.1",
                "conversation-agent-input/1.2",
            } or snapshot.get("thread_id") != linked["id"]:
                raise DomainError("agent_retry_context_missing", "失败运行没有可重放的固定对话输入。", status=409)
            snapshot_provider = snapshot.get("provider_runtime")
            if isinstance(snapshot_provider, dict):
                try:
                    self._capture_provider(snapshot_provider)
                except DomainError as exc:
                    if exc.code != "provider_config_changed":
                        raise
                    actual = exc.details.get("actual", {}) if isinstance(exc.details, dict) else {}
                    raise DomainError(
                        "provider_config_changed",
                        "这轮失败记录绑定了旧模型配置。请确认当前模型后重新发送，系统不会静默换模型重试。",
                        status=409,
                        details={
                            "agent_run_id": run_id,
                            "snapshot_config_digest": snapshot_provider.get("config_digest"),
                            "current_config_digest": actual.get("config_digest"),
                        },
                    ) from exc
            thread_id, instruction = linked["id"], str(snapshot.get("instruction") or run["instruction"])
        result = self.post_conversation_message(
            work_id, thread_id,
            {
                "expected_thread_version": expected_thread,
                "text": instruction,
                "retry_of": run_id,
                "_retry_snapshot": snapshot,
            },
        )
        result["retried_from_agent_run_id"] = run_id
        return result

    def _read_retry_snapshot(self, run) -> dict:
        try:
            snapshot_text = self.repo.read_text(run["input_snapshot_uri"])
        except (OSError, ValueError) as exc:
            raise DomainError(
                "agent_snapshot_integrity_failed",
                "Agent 重试输入缺失、损坏或不可读取，不能继续运行。",
                status=409,
                details={"agent_run_id": run["id"]},
            ) from exc
        if sha256_text(snapshot_text) != run["input_digest"]:
            raise DomainError(
                "agent_snapshot_integrity_failed",
                "Agent 重试输入已损坏或被修改，不能继续运行。",
                status=409,
                details={"agent_run_id": run["id"]},
            )
        try:
            snapshot = json.loads(snapshot_text)
        except json.JSONDecodeError as exc:
            raise DomainError("agent_retry_context_missing", "失败运行的输入快照无法读取。", status=409) from exc
        if not isinstance(snapshot, dict):
            raise DomainError("agent_retry_context_missing", "失败运行没有可重放的固定输入。", status=409)
        return snapshot

    def _retry_scene_agent_run(self, work_id: str, run, payload: dict):
        expected = int(payload.get("expected_version", -1))
        policy = json.loads(run["policy_json"])
        workflow = policy.get("workflow")
        snapshot = self._read_retry_snapshot(run)
        snapshot_provider = snapshot.get("provider_runtime")
        if isinstance(snapshot_provider, dict):
            self._capture_provider(snapshot_provider)
        scene_id = str(snapshot.get("scene_id") or run["scope_id"])
        if scene_id != run["scope_id"]:
            raise DomainError("agent_retry_context_missing", "场景重试快照的作用域无效。", status=409)

        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            current_revision_id = scene["current_revision_id"]

        if workflow == "scene.candidate.generate" and current_revision_id != snapshot.get("base_revision_id"):
            raise DomainError("agent_retry_input_stale", "场景正文已经变化，请从当前修订重新生成候选。", status=409)
        if workflow == "scene.draft.generate" and current_revision_id:
            raise DomainError("agent_retry_input_stale", "场景已经产生正文，请改用受控改写。", status=409)
        if workflow == "scene.draft.rewrite" and current_revision_id != snapshot.get("base_revision_id"):
            raise DomainError("agent_retry_input_stale", "场景正文已经变化，请基于当前修订重新发起改写。", status=409)
        if workflow == "scene.review" and current_revision_id != snapshot.get("revision_id"):
            raise DomainError("agent_retry_input_stale", "场景正文已经变化，请重新运行本场审查。", status=409)

        current_context = self.assemble_context(work_id, scene_id)
        pinned_fingerprints = policy.get("fingerprints") if isinstance(policy.get("fingerprints"), dict) else {}
        if pinned_fingerprints and current_context.get("fingerprints") != pinned_fingerprints:
            raise DomainError(
                "agent_retry_input_stale",
                "场景上下文或 BA 写作规则已经变化，请从当前场景重新运行。",
                status=409,
                details={"agent_run_id": run["id"]},
            )

        with self.repo.transaction() as connection:
            connection.execute(
                """UPDATE work_items SET status='failed',error_json=?,updated_at=?
                   WHERE status='ready' AND acceptance_json LIKE ?""",
                (canonical_json({"code": "retried", "retry_of": run["id"]}), now(), f'%"{run["id"]}"%'),
            )

        retry_payload = {"expected_version": expected, "_retry_of": run["id"]}
        if workflow == "scene.candidate.generate":
            result = self.generate_scene_candidate(work_id, scene_id, retry_payload)
        elif workflow == "scene.draft.generate":
            retry_payload["instruction"] = str(snapshot.get("instruction") or run["instruction"])
            retry_payload["discussion_constraints"] = snapshot.get("discussion_constraints")
            retry_payload["scene_conversation_context"] = snapshot.get("scene_conversation_context")
            result = self.run_scene_agent(work_id, scene_id, retry_payload)
        elif workflow == "scene.draft.rewrite":
            retry_payload.update({
                "instruction": str(snapshot.get("instruction") or run["instruction"]),
                "selection": snapshot.get("selection"),
                "discussion_constraints": snapshot.get("discussion_constraints"),
                "scene_conversation_context": snapshot.get("scene_conversation_context"),
            })
            result = self.run_scene_rewrite_agent(work_id, scene_id, retry_payload)
        else:
            result = self.review_scene(work_id, scene_id, retry_payload)
        result["retried_from_agent_run_id"] = run["id"]
        return result

    def _retry_review_agent_run(self, work_id: str, run, payload: dict):
        workflow = json.loads(run["policy_json"]).get("workflow")
        expected = int(payload.get("expected_version", -1))
        # Keep review retries on the same fixed-snapshot boundary as every
        # other workflow.  In particular, a deleted/unreadable snapshot must
        # become a stable domain error instead of leaking FileNotFoundError
        # through the HTTP layer.
        snapshot = self._read_retry_snapshot(run)
        review_pack = snapshot.get("review_pack")
        if (
            not isinstance(review_pack, dict)
            or review_pack.get("schema_version") != "work-review-pack/1.0"
            or review_pack.get("workflow") != workflow
        ):
            raise DomainError("agent_retry_context_missing", "失败运行没有可重放的作品级审查输入。", status=409)
        stored_digest = review_pack.get("digest")
        unsigned = {key: value for key, value in review_pack.items() if key != "digest"}
        if stored_digest != sha256_text(canonical_json(unsigned)):
            raise DomainError(
                "agent_snapshot_integrity_failed",
                "作品级审查包的固定指纹无效，不能重试。",
                status=409,
                details={"agent_run_id": run["id"]},
            )
        current_pack = self._assemble_work_review_pack(work_id, workflow)
        if current_pack["digest"] != stored_digest:
            raise DomainError(
                "agent_retry_input_stale",
                "作品正文或正式资料已变化，请运行一次新的审查。",
                status=409,
                details={"agent_run_id": run["id"], "current_digest": current_pack["digest"]},
            )
        with self.repo.transaction() as connection:
            self._check_work_version(connection, work_id, expected)
            connection.execute(
                """UPDATE work_items SET status='failed',error_json=?,updated_at=?
                   WHERE status='ready' AND acceptance_json LIKE ?""",
                (canonical_json({"code": "retried", "retry_of": run["id"]}), now(), f'%"{run["id"]}"%'),
            )
        return self._run_work_review_agent(
            work_id,
            {"expected_version": expected},
            workflow,
            review_pack=review_pack,
            retry_of=run["id"],
        )

    def _retry_memory_agent_run(self, work_id: str, run, payload: dict):
        expected = int(payload.get("expected_version", -1))
        snapshot = self._read_retry_snapshot(run)
        if (
            snapshot.get("schema_version") != "memory-extract-input/1.0"
            or snapshot.get("work_id") != work_id
        ):
            raise DomainError(
                "agent_retry_context_missing", "失败运行没有可重放的长期记忆输入。", status=409
            )
        scene = snapshot.get("scene") if isinstance(snapshot.get("scene"), dict) else {}
        scene_id = str(scene.get("id") or run["scope_id"])
        if scene_id != run["scope_id"]:
            raise DomainError("agent_retry_context_missing", "长期记忆重试作用域无效。", status=409)
        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected)
            current_scene = connection.execute(
                "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not current_scene or current_scene["current_revision_id"] != scene.get("revision_id"):
                raise DomainError(
                    "agent_retry_input_stale", "场景正文已经变化，请从当前修订重新提取记忆。", status=409
                )
            current_revision = connection.execute(
                "SELECT content_hash FROM revisions WHERE id=?", (current_scene["current_revision_id"],)
            ).fetchone()
            if not current_revision or current_revision["content_hash"] != scene.get("revision_hash"):
                raise DomainError("agent_snapshot_integrity_failed", "场景修订内容校验失败。", status=409)
            current_memories = [
                {
                    "memory_id": item["id"],
                    "kind": item["kind"],
                    "scope_type": item["scope_type"],
                    "scope_id": item["scope_id"],
                    "content": item["content"],
                    "confidence_status": item["confidence_status"],
                    "lifecycle_status": item["lifecycle_status"],
                    "current_revision_id": item["current_revision_id"],
                }
                for item in memory_projection_rows(connection, work_id)
            ]
        if current_memories != snapshot.get("existing_memories", []):
            raise DomainError(
                "agent_retry_input_stale", "长期记忆投影已经变化，请基于当前资料重新提取。", status=409
            )
        with self.repo.transaction() as connection:
            connection.execute(
                """UPDATE work_items SET status='failed',error_json=?,updated_at=?
                   WHERE status='ready' AND acceptance_json LIKE ?""",
                (canonical_json({"code": "retried", "retry_of": run["id"]}), now(), f'%"{run["id"]}"%'),
            )
        result = self.generate_memory_proposal(
            work_id, scene_id,
            {"expected_version": expected, "_retry_of": run["id"]},
        )
        result["retried_from_agent_run_id"] = run["id"]
        return result

    def _retry_memory_sweep_agent_run(self, work_id: str, run, payload: dict):
        expected = int(payload.get("expected_version", -1))
        snapshot = self._read_retry_snapshot(run)
        if (
            snapshot.get("schema_version") != "memory-sweep-input/1.0"
            or snapshot.get("work_id") != work_id
        ):
            raise DomainError(
                "agent_retry_context_missing", "失败运行没有可重放的章节记忆清扫输入。", status=409
            )
        chapter = snapshot.get("chapter") if isinstance(snapshot.get("chapter"), dict) else {}
        chapter_id = str(chapter.get("id") or run["scope_id"])
        if chapter_id != run["scope_id"]:
            raise DomainError("agent_retry_context_missing", "章节记忆清扫的重试作用域无效。", status=409)
        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected)
        current = self._assemble_chapter_memory_sweep_input(work_id, chapter_id)
        if current.get("digest") != snapshot.get("digest"):
            raise DomainError(
                "agent_retry_input_stale",
                "章节正文或长期记忆已经变化，请从当前章节重新运行清扫。",
                status=409,
            )
        result = self._run_chapter_memory_sweep(
            work_id,
            chapter_id,
            {"expected_version": expected, "_retry_of": run["id"]},
            sweep_input=snapshot,
        )
        result["retried_from_agent_run_id"] = run["id"]
        return result

    def _retry_structure_agent_run(self, work_id: str, run, payload: dict):
        expected = int(payload.get("expected_version", -1))
        snapshot = self._read_retry_snapshot(run)
        if (
            snapshot.get("schema_version") != "structure-plan-agent-input/1.0"
            or snapshot.get("work_id") != work_id
        ):
            raise DomainError(
                "agent_retry_context_missing", "失败运行没有可重放的作品结构输入。", status=409
            )
        thread_id = str(snapshot.get("thread_id") or "")
        structure_context = (
            snapshot.get("structure_context")
            if isinstance(snapshot.get("structure_context"), dict)
            else {}
        )
        task_contract = (
            structure_context.get("task_contract")
            if isinstance(structure_context.get("task_contract"), dict)
            else {}
        )
        if not thread_id or task_contract.get("id") != "structure.plan":
            raise DomainError("agent_retry_context_missing", "作品结构任务契约缺失。", status=409)
        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected)
            thread = connection.execute(
                "SELECT * FROM conversation_threads WHERE id=? AND work_id=?", (thread_id, work_id)
            ).fetchone()
            if not thread or thread["status"] != "active":
                raise DomainError("agent_thread_archived", "请先恢复作品主对话，再重试结构整理。", status=409)
            if int(thread["version"]) != int(snapshot.get("thread_version", -1)):
                raise DomainError(
                    "agent_retry_input_stale", "作品讨论已经变化，请根据最新讨论重新整理结构。", status=409
                )
            current_structure = self._structure_snapshot(connection, work_id)
            current_blueprint = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'",
                (work_id,),
            ).fetchone()
            if (
                current_structure["digest"] != snapshot.get("structure_digest")
                or not current_blueprint
                or current_blueprint["current_revision_id"]
                != structure_context.get("story_blueprint_revision_id")
            ):
                raise DomainError(
                    "agent_retry_input_stale", "作品方向或结构已经变化，请重新整理结构。", status=409
                )
            thread_version = int(thread["version"])
        with self.repo.transaction() as connection:
            connection.execute(
                """UPDATE work_items SET status='failed',error_json=?,updated_at=?
                   WHERE status='ready' AND acceptance_json LIKE ?""",
                (canonical_json({"code": "retried", "retry_of": run["id"]}), now(), f'%"{run["id"]}"%'),
            )
        result = self._organize_structure_plan_proposal(
            work_id,
            thread_id,
            {
                "expected_version": expected,
                "expected_thread_version": thread_version,
                "_retry_of": run["id"],
            },
            task_contract,
        )
        result["retried_from_agent_run_id"] = run["id"]
        return result

    def search_official_references(self, query: str, limit: int = 12):
        bounded = max(1, min(int(limit or 12), 30))
        return {
            "catalog": self.official_references.descriptor(),
            "query": str(query).strip(),
            "items": self.official_references.search(query, bounded),
        }

    def resource_catalog_public(self) -> dict:
        return self.resource_catalog.descriptor()

    def search_resource_catalog(self, kind: str, query: str = "", limit: int = 24) -> dict:
        try:
            return self.resource_catalog.search(kind, query, limit)
        except ValueError as exc:
            raise DomainError("resource_kind_unsupported", "暂不支持这种资源类型。", status=400) from exc

    def lookup_resource_catalog(self, kind: str, keys: list[str]) -> dict:
        try:
            return self.resource_catalog.lookup(kind, keys)
        except ValueError as exc:
            raise DomainError("resource_kind_unsupported", "暂不支持这种资源类型。", status=400) from exc

    def resource_catalog_facets(self, kind: str) -> dict:
        try:
            return self.resource_catalog.facets(kind)
        except ValueError as exc:
            raise DomainError("resource_kind_unsupported", "暂不支持这种资源类型。", status=400) from exc

    def import_resource_catalog(self, payload: dict) -> dict:
        source_path = Path(str(payload.get("source_path") or "").strip()).expanduser()
        if not source_path.is_file():
            raise DomainError("resource_source_missing", "找不到要导入的 0.95 资源数据库。", status=422)
        overlay_paths = [Path(str(item)).expanduser() for item in payload.get("overlay_paths") or []]
        if any(not path.is_file() for path in overlay_paths):
            raise DomainError("resource_overlay_missing", "找不到要叠加的 0.95 资源数据库。", status=422)
        for field, label in (("character_aliases_path", "0.95 人物别名索引"), ("manifest_path", "AA 人物清单")):
            if payload.get(field) and not Path(str(payload[field]).strip()).expanduser().is_file():
                raise DomainError("resource_overlay_missing", f"找不到要叠加的{label}。", status=422)
        try:
            return self.resource_catalog.import_legacy(
                source_path,
                str(payload.get("source_label") or "HaloCue 0.95"),
                overlay_paths,
                character_aliases_path=(
                    Path(str(payload["character_aliases_path"]).strip()).expanduser()
                    if payload.get("character_aliases_path") else None
                ),
                manifest_path=(
                    Path(str(payload["manifest_path"]).strip()).expanduser()
                    if payload.get("manifest_path") else None
                ),
            )
        except (OSError, ValueError, sqlite3.DatabaseError) as exc:
            raise DomainError("resource_catalog_import_failed", "资源数据库导入失败，1.0 数据库没有改变。", status=422) from exc

    def save_resource_override(self, payload: dict) -> dict:
        try:
            return self.resource_catalog.save_override(
                str(payload.get("kind") or ""),
                str(payload.get("resource_key") or ""),
                payload.get("patch") or {},
                payload.get("expected_version"),
            )
        except ValueError as exc:
            code = "resource_override_conflict" if "conflict" in str(exc) else "resource_override_invalid"
            status = 409 if code == "resource_override_conflict" else 422
            raise DomainError(code, "资源修正未保存；基础资源库没有改变。", status=status) from exc

    def preview_aap_import(self, payload: dict) -> dict:
        try:
            return parse_aap_payload(payload)
        except ValueError as exc:
            raise DomainError("aap_preview_failed", str(exc), status=422) from exc

    def stage_aap_import(self, payload: dict) -> dict:
        if payload.get("confirm") is not True:
            raise DomainError("aap_confirmation_required", "预览通过后，仍需明确确认才能暂存导入草稿。", status=409)
        preview = self.preview_aap_import(payload)
        try:
            raw = base64.b64decode(str(payload.get("content_base64") or ""), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DomainError("aap_preview_failed", ".aap 文件编码无效。", status=422) from exc
        import_id = new_id("aap-import")
        target = self.repo.data_dir / "imports" / "aap" / import_id
        target.mkdir(parents=True, exist_ok=False)
        (target / "source.aap").write_bytes(raw)
        (target / "preview.json").write_text(canonical_json(preview), encoding="utf-8")
        return {"schema_version": "story-import/1.0", "import_id": import_id, "filename": preview["filename"], "status": "staged_draft", "preview": preview, "write_boundary": "staged_import_only_no_formal_revision"}

    def preview_story_import(self, payload: dict) -> dict:
        try:
            return parse_story_payload(payload)
        except ValueError as exc:
            raise DomainError("story_import_preview_failed", str(exc), status=422) from exc

    def stage_story_import(self, payload: dict) -> dict:
        if payload.get("confirm") is not True:
            raise DomainError(
                "story_import_confirmation_required",
                "预览通过后，仍需明确确认才能暂存导入草稿。",
                status=409,
            )
        preview = self.preview_story_import(payload)
        try:
            raw = base64.b64decode(str(payload.get("content_base64") or ""), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DomainError("story_import_preview_failed", "导入文件编码无效。", status=422) from exc
        import_id = new_id("story-import")
        target = self.repo.data_dir / "imports" / "story" / import_id
        target.mkdir(parents=True, exist_ok=False)
        suffix = Path(preview["filename"]).suffix.lower()
        (target / f"source{suffix}").write_bytes(raw)
        (target / "preview.json").write_text(canonical_json(preview), encoding="utf-8")
        return {
            "schema_version": "story-import/1.0",
            "import_id": import_id,
            "filename": preview["filename"],
            "status": "staged_draft",
            "preview": preview,
            "write_boundary": "staged_import_only_no_formal_revision",
        }

    def list_works(self):
        with self.repo.connect() as connection:
            return self.repo.rows(connection.execute("SELECT * FROM works ORDER BY updated_at DESC"))

    @staticmethod
    def _intent_chapter_number(text: str) -> int | None:
        match = re.search(r"第\s*(\d+|[一二三四五六七八九十百]+)\s*章", text)
        if not match:
            return None
        value = match.group(1)
        if value.isdigit():
            return max(1, min(int(value), 999))
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
        if value in digits:
            return digits[value]
        if len(value) == 2 and value[0] == "十" and value[1] in digits:
            return 10 + digits[value[1]]
        if len(value) == 2 and value[1] == "十" and value[0] in digits:
            return digits[value[0]] * 10
        return None

    @staticmethod
    def _intent_scene_number(text: str) -> int | None:
        match = re.search(r"第\s*(\d+|[一二三四五六七八九十百]+)\s*(?:幕|场)", text)
        if not match:
            return None
        value = match.group(1)
        if value.isdigit():
            return max(1, min(int(value), 200))
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
        if value in digits:
            return digits[value]
        if len(value) == 2 and value[0] == "十" and value[1] in digits:
            return 10 + digits[value[1]]
        if len(value) == 2 and value[1] == "十" and value[0] in digits:
            return digits[value[0]] * 10
        return None

    @staticmethod
    def _intent_scene_title(text: str) -> str:
        match = re.search(r"第\s*(\d+|[一二三四五六七八九十百]+)\s*(幕|场)", text)
        if not match:
            return ""
        named = re.search(
            rf"第\s*{re.escape(match.group(1))}\s*{match.group(2)}\s*(?:叫|名为|标题(?:是|为)|是|[:：])\s*[《「『“\"]?([^》」』”\"，。；;\n]{{1,120}})",
            text,
        )
        return (named.group(1).strip() if named else f"第{match.group(1)}{match.group(2)}")

    @staticmethod
    def _intent_scene_titles(text: str) -> list[tuple[int, str]]:
        """Extract every explicitly named act/scene without treating later targets as new titles."""
        digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100}
        pattern = re.compile(
            r"第\s*(\d+|[一二三四五六七八九十百]+)\s*(幕|场)\s*(?:叫|名为|标题(?:是|为)|是|[:：])\s*[《「『“\"]?([^》」』”\"，。；;\n]{1,120})"
        )
        titles: list[tuple[int, str]] = []
        for match in pattern.finditer(text):
            raw = match.group(1)
            if raw.isdigit():
                ordinal = int(raw)
            elif len(raw) == 2 and raw[0] == "十" and raw[1] in digits:
                ordinal = 10 + digits[raw[1]]
            elif len(raw) == 2 and raw[1] == "十" and raw[0] in digits:
                ordinal = digits[raw[0]] * 10
            else:
                ordinal = digits.get(raw)
            if ordinal is None or not 1 <= ordinal <= 200:
                continue
            title = match.group(3).strip()
            if title and (ordinal, title) not in titles:
                titles.append((ordinal, title))
        return titles

    @staticmethod
    def _intent_target_scene_number(text: str) -> int | None:
        """Prefer an explicit navigation/write target over the first title declaration."""
        match = re.search(
            r"(?:开始|继续|去写|跳转到|进入|打开)\s*(?:写(?:作)?\s*)?(?:第\s*(\d+|[一二三四五六七八九十百]+)\s*(?:幕|场))",
            text,
        )
        if not match:
            return WritingService._intent_scene_number(text)
        return WritingService._intent_scene_number(match.group(0))

    @staticmethod
    def _intent_chapter_title(text: str) -> str:
        match = re.search(r"第\s*(\d+|[一二三四五六七八九十百]+)\s*章", text)
        if not match:
            return ""
        named = re.search(
            rf"第\s*{re.escape(match.group(1))}\s*章\s*(?:叫|名为|标题(?:是|为)|是|[:：])\s*[《「『“\"]?([^》」』”\"，。；;\n]{{1,120}})",
            text,
        )
        return named.group(1).strip() if named else ""

    @staticmethod
    def _intent_risk(text: str) -> tuple[str, bool, list[str]]:
        high_risk_terms = ("覆盖正式正文", "删除", "永久删除", "采纳", "发布", "冻结", "编译", "安装", "确认人物卡", "确认世界规则", "修改 WorkCanon")
        negation = re.compile(r"(?:不|不要|不会|未|无需|无须|勿|别)\s*$")
        matched = []
        for term in high_risk_terms:
            start = text.find(term)
            if start < 0:
                continue
            prefix = text[max(0, start - 4):start]
            if negation.search(prefix):
                continue
            matched.append(term)
        return ("high" if matched else "low", bool(matched), matched)

    @staticmethod
    def _intent_discussion_only(text: str) -> bool:
        """Recognize an explicit read-only discussion boundary for Intent turns."""
        normalized = re.sub(r"\s+", "", str(text or ""))
        discussion = any(marker in normalized for marker in ("只讨论", "仅讨论", "只做讨论", "只想讨论"))
        no_write = any(
            marker in normalized
            for marker in (
                "不写入正式正文",
                "不要写入正式正文",
                "不改正式正文",
                "不要改正式正文",
                "不生成正文候选",
                "不要生成正文候选",
                "不生成候选",
                "不要生成候选",
            )
        )
        return discussion and no_write

    @staticmethod
    def _intent_character_context(work: dict, scene: dict, instruction: str) -> tuple[list[str], list[str]]:
        """Match confirmed cards to the named scene instead of selecting the whole cast."""
        contract = scene.get("contract") if isinstance(scene.get("contract"), dict) else {}
        haystack = "\n".join(
            str(value or "")
            for value in (
                instruction,
                scene.get("title"),
                contract.get("goal"),
                contract.get("location"),
                contract.get("intent_source"),
            )
        )
        matched: list[str] = []
        available_names: list[str] = []
        for artifact in work.get("artifacts", []):
            if artifact.get("kind") != "character_card":
                continue
            content = artifact.get("current_revision", {}).get("content")
            if not isinstance(content, dict):
                continue
            if content.get("status", "active") != "active" or content.get("trust_status") != "confirmed":
                continue
            names = [
                str(value).strip()
                for value in (
                    content.get("name"),
                    content.get("canonical_name"),
                    *(content.get("aliases") or []),
                )
                if str(value or "").strip()
            ]
            if names:
                available_names.append(names[0])
            if names and any(name in haystack for name in names):
                matched.append(str(artifact.get("scope_id") or ""))
        return list(dict.fromkeys(item for item in matched if item)), list(dict.fromkeys(available_names))

    def _ensure_intent_structure(
        self,
        work_id: str,
        text: str,
        chapter_number: int | None,
        scene_titles: list[tuple[int, str]] | None = None,
        scene_number: int | None = None,
    ) -> dict:
        """Create only reversible containers; formal writing still needs a Proposal."""
        with self.repo.transaction() as connection:
            work = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            if not work:
                raise NotFound("work", work_id)
            volume = connection.execute("SELECT id FROM volumes WHERE work_id=? ORDER BY stable_order_key LIMIT 1", (work_id,)).fetchone()
            if not volume:
                volume_id = new_id("volume")
                timestamp = now()
                connection.execute("INSERT INTO volumes VALUES (?,?,?,?,?,?,?,?)", (volume_id, work_id, "000001", "第一卷", "active", 1, timestamp, timestamp))
                volume = {"id": volume_id}
            target_number = chapter_number or 1
            chapters = connection.execute("SELECT id,title,stable_order_key,status FROM chapters WHERE work_id=? AND volume_id=? ORDER BY stable_order_key", (work_id, volume["id"])).fetchall()
            while len(chapters) < target_number:
                ordinal = len(chapters) + 1
                chapter_id = new_id("chapter")
                timestamp = now()
                chapter_label = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}.get(ordinal, str(ordinal))
                connection.execute("INSERT INTO chapters (id,work_id,volume_id,stable_order_key,title,status,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (chapter_id, work_id, volume["id"], f"{ordinal:06d}", f"第{chapter_label}章", "placeholder", 1, timestamp, timestamp))
                chapters = connection.execute("SELECT id,title,stable_order_key,status FROM chapters WHERE work_id=? AND volume_id=? ORDER BY stable_order_key", (work_id, volume["id"])).fetchall()
            chapter = chapters[target_number - 1]
            requested_chapter_title = self._intent_chapter_title(text)
            if requested_chapter_title and chapter["status"] == "placeholder":
                connection.execute("UPDATE chapters SET title=?,updated_at=? WHERE id=?", (requested_chapter_title, now(), chapter["id"]))
                chapter = {**dict(chapter), "title": requested_chapter_title}
            scene_titles = scene_titles or self._intent_scene_titles(text)
            scene_number = scene_number or self._intent_target_scene_number(text)
            if scene_number is None and scene_titles:
                scene_number = scene_titles[0][0]
            requested_scene_title = next((title for ordinal, title in scene_titles if ordinal == scene_number), "")
            if not requested_scene_title:
                requested_scene_title = self._intent_scene_title(text)
            scene_rows = connection.execute("SELECT id,title,status,stable_order_key,current_revision_id,contract_json FROM scenes WHERE chapter_id=? ORDER BY stable_order_key,id", (chapter["id"],)).fetchall()
            desired_count = max([ordinal for ordinal, _ in scene_titles] or [scene_number or 1])
            while len(scene_rows) < desired_count:
                ordinal = len(scene_rows) + 1
                scene_id = new_id("scene")
                timestamp = now()
                title = dict(scene_titles).get(ordinal) or f"场景 {ordinal:02d} · 待理解"
                contract = {"location": "", "goal": "", "writing_mode": "bond_short", "intent_source": text[:2000], "stop_boundary": "必要事实成立后停止"}
                contract["title_source"] = "intent"
                connection.execute("INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (scene_id, work_id, chapter["id"], f"{ordinal:06d}", title, "planned", 1, None, canonical_json(contract), timestamp, timestamp))
                scene_rows = connection.execute("SELECT id,title,status,stable_order_key,current_revision_id,contract_json FROM scenes WHERE chapter_id=? ORDER BY stable_order_key,id", (chapter["id"],)).fetchall()
            for ordinal, title in scene_titles:
                if ordinal > len(scene_rows):
                    continue
                row = scene_rows[ordinal - 1]
                try:
                    row_contract = json.loads(row["contract_json"] or "{}")
                except (TypeError, json.JSONDecodeError):
                    row_contract = {}
                intent_owned = row_contract.get("title_source") == "intent" or (
                    row_contract.get("intent_source") and not row_contract.get("title_source")
                )
                renameable = (
                    row["status"] in {"planned", "placeholder"}
                    and not row["current_revision_id"]
                    and intent_owned
                )
                generic_placeholder = row["title"].startswith("场景") or row["title"].startswith("第")
                if row["status"] in {"planned", "placeholder"} and (generic_placeholder or renameable) and row["title"] != title:
                    connection.execute("UPDATE scenes SET title=?,updated_at=? WHERE id=?", (title, now(), row["id"]))
            scene_rows = connection.execute("SELECT id,title,status,stable_order_key,current_revision_id,contract_json FROM scenes WHERE chapter_id=? ORDER BY stable_order_key,id", (chapter["id"],)).fetchall()
            target_index = max(1, min(scene_number or 1, len(scene_rows)))
            existing_scene = scene_rows[target_index - 1] if scene_rows else None
            scene_id = existing_scene["id"] if existing_scene else None
            if existing_scene is None:
                scene_id = new_id("scene")
                timestamp = now()
                contract = {"location": "", "goal": "", "writing_mode": "bond_short", "intent_source": text[:2000], "stop_boundary": "必要事实成立后停止"}
                contract["title_source"] = "intent"
                connection.execute("INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (scene_id, work_id, chapter["id"], f"{target_index:06d}", requested_scene_title or f"场景 {target_index:02d} · 待理解", "planned", 1, None, canonical_json(contract), timestamp, timestamp))
            timestamp = now()
            connection.execute("UPDATE works SET version=version+1,updated_at=? WHERE id=?", (timestamp, work_id))
            scene = connection.execute("SELECT title FROM scenes WHERE id=?", (scene_id,)).fetchone()
            return {"chapter_id": chapter["id"], "chapter_title": chapter["title"], "scene_id": scene_id, "scene_title": scene["title"], "work_version": int(work["version"]) + 1}

    def plan_intent(self, payload: dict) -> dict:
        text = str(payload.get("message") or payload.get("text") or "").strip()
        if not text:
            raise DomainError("validation_error", "请直接告诉我你想创作什么。", details={"field": "message"})
        requested_work_id = str(payload.get("work_id") or "").strip()
        chapter_number = self._intent_chapter_number(text)
        scene_titles = self._intent_scene_titles(text)
        scene_number = self._intent_target_scene_number(text)
        risk_level, requires_confirmation, matched_risks = self._intent_risk(text)
        idempotency_key = str(payload.get("idempotency_key") or "").strip() or sha256_text(canonical_json({"work_id": requested_work_id, "message": text, "chapter": chapter_number}))
        with self.repo.connect() as connection:
            existing = connection.execute("SELECT * FROM intent_plans WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing:
            result = self.get_intent_plan(existing["id"])
            result["existing_work"] = True
            return result
        if requested_work_id:
            work_id = requested_work_id
        else:
            latest = self.list_works()
            work_id = latest[0]["id"] if latest else ""
        created_work = False
        if not work_id:
            work = self.create_work({"title": "未命名作品", "permission_mode": payload.get("permission_mode", "review")})
            work_id = work["id"]
            created_work = True
        structure = self._ensure_intent_structure(work_id, text, chapter_number, scene_titles, scene_number)
        work = self.get_work(work_id)
        thread = next((item for item in work["conversation_threads"] if item["scope_type"] == "work" and item["status"] == "active"), None)
        if not thread:
            created = self.create_conversation_thread(work_id, {"expected_version": work["version"], "scope_type": "work", "title": "创作主对话"})
            work = created["work"]
            thread = next(item for item in work["conversation_threads"] if item["id"] == created["thread_id"])
        target = {
            "surface": "scene",
            "scene_id": structure["scene_id"],
            "scene_title": structure["scene_title"],
            "chapter_id": structure["chapter_id"],
            "chapter_title": structure["chapter_title"],
            "discussion_only": self._intent_discussion_only(text),
        }
        actions = [
            {"id": "workspace.ensure", "label": "准备作品、章节和场景容器", "risk": "low", "status": "completed"},
            {"id": "context.read", "label": "读取已确认资料、前文和附件", "risk": "low", "status": "planned"},
            {"id": "agent.discuss", "label": "把原文交给当前作品 Agent", "risk": "low", "status": "planned"},
        ]
        if requires_confirmation:
            actions.append({"id": "user.confirm", "label": "等待确认：" + "、".join(matched_risks), "risk": "high", "status": "blocked"})
        result = {"created_work": created_work, "created_structure": structure, "agent_run_id": None, "status": "awaiting_confirmation" if requires_confirmation else "queued"}
        timestamp = now()
        plan_id = new_id("intent")
        with self.repo.transaction() as connection:
            connection.execute("INSERT INTO intent_plans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (plan_id, work_id, thread["id"], idempotency_key, text, canonical_json(target), canonical_json(["brief", "story_blueprint", "work_canon", "world_bible", "character_card", "reference_files", "recent_revisions"]), canonical_json(actions), risk_level, int(requires_confirmation), result["status"], canonical_json(result), timestamp, timestamp))
        if not requires_confirmation:
            attachment_ids = [str(value).strip() for value in (payload.get("attachment_ids") or []) if str(value).strip()]
            if len(attachment_ids) > 4:
                raise DomainError("validation_error", "每轮最多附带 4 个附件。", details={"field": "attachment_ids"})
            raw_attachments = payload.get("attachments") if isinstance(payload.get("attachments"), list) else []
            if len(raw_attachments) + len(attachment_ids) > 4:
                raise DomainError("validation_error", "每轮最多附带 4 个附件。", details={"field": "attachments"})
            for attachment in raw_attachments:
                if not isinstance(attachment, dict):
                    raise DomainError("validation_error", "附件条目无效。", details={"field": "attachments"})
                uploaded = self.create_conversation_attachment(work_id, thread["id"], {"expected_thread_version": thread["version"], **attachment})
                attachment_ids.append(uploaded["attachment_id"])
                work = uploaded["work"]
                thread = next(item for item in work["conversation_threads"] if item["id"] == thread["id"])
            queued = self.enqueue_conversation_message(work_id, thread["id"], {"expected_thread_version": thread["version"], "text": text, "attachment_ids": attachment_ids, "task_scope": target, "request_source": "intent", "intent_plan_id": plan_id})
            result.update({"agent_run_id": queued.get("agent_run_id"), "status": "running"})
            with self.repo.transaction() as connection:
                connection.execute("UPDATE intent_plans SET result_json=?,status='running',updated_at=? WHERE id=?", (canonical_json(result), now(), plan_id))
        return self.get_intent_plan(plan_id)

    @staticmethod
    def _public_intent_plan(row, *, existing_work: bool = False) -> dict:
        item = dict(row)
        item["plan_id"] = item.get("id")
        for key in ("target_json", "read_refs_json", "actions_json", "result_json"):
            try:
                item[key[:-5] if key.endswith("_json") else key] = json.loads(item.pop(key) or "{}")
            except json.JSONDecodeError:
                item[key[:-5] if key.endswith("_json") else key] = []
        item["requires_confirmation"] = bool(item.get("requires_confirmation"))
        item["existing_work"] = existing_work
        return item

    @staticmethod
    def _project_intent_plan_execution(plan: dict, work: dict) -> dict:
        projected = dict(plan)
        actions = [dict(action) for action in projected.get("actions") or []]
        result = dict(projected.get("result") or {})
        run_id = str(result.get("agent_run_id") or "")
        run = next((item for item in work.get("agent_runs") or [] if item["id"] == run_id), None)
        if not run:
            projected["actions"] = actions
            projected["result"] = result
            return projected

        run_status = run.get("status") or "queued"
        terminal_success = run_status in {"completed", "waiting_user", "succeeded"}
        terminal_failure = run_status in {"failed", "cancelled"}
        target = projected.get("target") if isinstance(projected.get("target"), dict) else {}
        if target.get("surface") == "scene" and not target.get("discussion_only"):
            intent_execution = result.get("intent_execution") if isinstance(result.get("intent_execution"), dict) else {}
            linked_proposal_id = str(intent_execution.get("proposal_id") or result.get("proposal_id") or "")
            pending_proposal = next(
                (
                    proposal
                    for proposal in work.get("proposals") or []
                    if linked_proposal_id
                    and proposal.get("id") == linked_proposal_id
                    and proposal.get("kind") == "scene_script"
                    and proposal.get("scope_id") == target.get("scene_id")
                    and proposal.get("status") == "pending"
                ),
                None,
            )
            if pending_proposal:
                result["proposal_id"] = pending_proposal["id"]
                proposal_run = next(
                    (
                        item for item in work.get("agent_runs") or []
                        if item.get("proposal_id") == pending_proposal["id"]
                    ),
                    None,
                )
                if proposal_run:
                    result["proposal_agent_run_id"] = proposal_run["id"]
                result["status"] = "waiting_user"
                result["run_status"] = "waiting_user"
                run_status = "waiting_user"
                terminal_success = True
                terminal_failure = False
                projected["status"] = "waiting_user"
            elif isinstance(result.get("intent_execution"), dict):
                execution_status = str(result["intent_execution"].get("status") or "")
                if execution_status in {"blocked", "failed"}:
                    projected["status"] = execution_status
        # Different workflows expose context assembly through either the
        # aggregate reader or scoped search tools. Treat all of them as
        # evidence for the same user-facing "读取资料" step.
        context_calls = [
            item
            for item in run.get("tool_calls") or []
            if item.get("tool_name")
            in {
                "read_work_context",
                "search_world_bible",
                "search_work_canon",
                "search_character_cards",
                "search_reference_files",
                "read_recent_revisions",
            }
        ]
        context_call = next(
            (item for item in context_calls if item.get("status") == "succeeded"),
            None,
        ) or next(
            (item for item in context_calls if item.get("status") == "failed"),
            None,
        )
        for action in actions:
            if action.get("id") == "user.confirm":
                # The confirmation gate is complete once the fixed request has
                # been accepted; any later proposal/release decision is a
                # separate boundary and must not keep this step looking blocked.
                action["status"] = "completed" if result.get("confirmed") is True else "blocked"
            elif action.get("id") == "context.read":
                if context_call and context_call.get("status") == "succeeded":
                    action["status"] = "completed"
                elif context_call and context_call.get("status") == "failed":
                    action["status"] = "failed"
                elif run_status in {"queued", "running"}:
                    action["status"] = "running"
            elif action.get("id") == "agent.discuss":
                action["status"] = "completed" if terminal_success else "failed" if terminal_failure else "running"

        if projected.get("status") == "running" and run_status not in {"queued", "running"}:
            projected["status"] = "failed" if terminal_failure else run_status
        result["run_status"] = run_status
        # Keep the persisted result envelope truthful as well as the plan's
        # top-level status. Older plans stored the initial "running" value
        # here, which made a completed Intent look unfinished to consumers
        # that read result.status directly.
        execution_status = str((result.get("intent_execution") or {}).get("status") or "")
        result["status"] = execution_status if execution_status in {"blocked", "failed"} and projected.get("status") != "waiting_user" else run_status
        if terminal_failure:
            result["recovery"] = {
                "action": "retry_agent_run",
                "agent_run_id": run["id"],
                "fixed_input_ref": run.get("input_snapshot_uri"),
            }
        projected["actions"] = actions
        projected["result"] = result
        return projected

    def confirm_intent(self, plan_id: str, payload: dict) -> dict:
        if payload.get("confirmed") is not True:
            raise DomainError("confirmation_required", "需要明确确认后才能继续这条高风险请求。", status=409)
        with self.repo.connect() as connection:
            row = connection.execute("SELECT * FROM intent_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise NotFound("intent_plan", plan_id)
        plan = self._public_intent_plan(row)
        if plan["status"] not in {"awaiting_confirmation", "failed"}:
            return self.get_intent_plan(plan_id)
        work = self.get_work(plan["work_id"])
        thread = next(item for item in work["conversation_threads"] if item["id"] == plan["thread_id"])
        queued = self.enqueue_conversation_message(plan["work_id"], plan["thread_id"], {"expected_thread_version": thread["version"], "text": plan["original_message"], "task_scope": plan["target"], "request_source": "intent", "intent_plan_id": plan_id})
        result = {"agent_run_id": queued.get("agent_run_id"), "status": "running", "confirmed": True}
        with self.repo.transaction() as connection:
            connection.execute("UPDATE intent_plans SET status='running',result_json=?,updated_at=? WHERE id=?", (canonical_json(result), now(), plan_id))
        return self.get_intent_plan(plan_id)

    def retry_intent(self, plan_id: str, payload: dict) -> dict:
        """Resume a blocked scene Intent from its original message and stable target."""
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            row = connection.execute("SELECT * FROM intent_plans WHERE id=?", (plan_id,)).fetchone()
            if not row:
                raise NotFound("intent_plan", plan_id)
            plan = self._public_intent_plan(row)
            work = connection.execute("SELECT version FROM works WHERE id=?", (plan["work_id"],)).fetchone()
            if not work:
                raise NotFound("work", plan["work_id"])
            if int(work["version"]) != expected:
                raise RevisionConflict(expected, int(work["version"]))
            if plan["status"] not in {"blocked", "failed"}:
                raise DomainError(
                    "intent_not_retryable",
                    "只有阻塞或失败的自然语言计划可以从当前输入继续。",
                    status=409,
                    details={"status": plan["status"]},
                )
            target = plan.get("target") if isinstance(plan.get("target"), dict) else {}
            if target.get("surface") != "scene" or target.get("discussion_only"):
                raise DomainError("intent_not_retryable", "这条计划没有可恢复的场景写作步骤。", status=409)
            result = dict(plan.get("result") or {})
            result["retry"] = {
                "status": "running",
                "requested_at": now(),
                "fixed_original_message": True,
                "stable_target": {
                    "chapter_id": target.get("chapter_id"),
                    "scene_id": target.get("scene_id"),
                },
            }
            changed = connection.execute(
                "UPDATE intent_plans SET status='running',result_json=?,updated_at=? WHERE id=? AND status IN ('blocked','failed')",
                (canonical_json(result), now(), plan_id),
            ).rowcount
            if changed != 1:
                raise DomainError("intent_retry_in_progress", "这条计划已经在继续处理中。", status=409)

        try:
            execution = self._auto_execute_intent_scene(
                plan["work_id"],
                {
                    "request_source": "intent",
                    "text": plan["original_message"],
                    "task_scope": target,
                    "intent_plan_id": plan_id,
                },
            ) or {
                "status": "failed",
                "code": "intent_retry_result_missing",
                "message": "场景写作步骤没有返回可恢复结果。",
            }
        except Exception as exc:
            execution = {
                "status": "failed",
                "code": getattr(exc, "code", "intent_retry_failed"),
                "message": getattr(exc, "message", str(exc) or "场景写作继续失败。"),
                "details": getattr(exc, "details", {}) if isinstance(getattr(exc, "details", {}), dict) else {},
            }

        with self.repo.transaction() as connection:
            current = connection.execute("SELECT result_json FROM intent_plans WHERE id=?", (plan_id,)).fetchone()
            result = json.loads(current["result_json"] or "{}") if current else {}
            result["intent_execution"] = execution
            retry = dict(result.get("retry") or {})
            retry.update({"status": execution.get("status"), "completed_at": now()})
            result["retry"] = retry
            status = str(execution.get("status") or "failed")
            if status not in {"blocked", "failed", "waiting_user", "completed"}:
                status = "failed"
            connection.execute(
                "UPDATE intent_plans SET status=?,result_json=?,updated_at=? WHERE id=?",
                (status, canonical_json(result), now(), plan_id),
            )
        return self.get_intent_plan(plan_id)

    def get_intent_plan(self, plan_id: str) -> dict:
        with self.repo.connect() as connection:
            row = connection.execute("SELECT * FROM intent_plans WHERE id=?", (plan_id,)).fetchone()
        if not row:
            raise NotFound("intent_plan", plan_id)
        plan = self._public_intent_plan(row)
        work = self.get_work(plan["work_id"])
        return {**self._project_intent_plan_execution(plan, work), "work": work}

    def submit_feedback(self, payload: dict):
        category = str(payload.get("category", "usability")).strip()
        if category not in {"bug", "usability", "suggestion", "runtime_error", "generation_quality"}:
            raise DomainError("validation_error", "反馈类型无效。", details={"field": "category"})
        summary = str(payload.get("summary", "")).strip()
        details = str(payload.get("details", "")).strip()
        if not summary or not details:
            raise DomainError(
                "validation_error",
                "请填写问题概述和详细说明。",
                details={"fields": ["summary", "details"]},
            )
        if len(summary) > 120 or len(details) > 4000:
            raise DomainError(
                "validation_error",
                "反馈内容过长。",
                details={"summary_max": 120, "details_max": 4000},
            )
        severity = str(payload.get("severity", "minor")).strip() or "minor"
        if severity not in {"blocker", "major", "minor", "cosmetic"}:
            raise DomainError("validation_error", "反馈影响程度无效。", details={"field": "severity"})
        raw_work_id = payload.get("work_id")
        work_id = str(raw_work_id).strip() if raw_work_id is not None else ""
        work_id = work_id or None
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        timestamp = now()
        report_id = new_id("feedback")
        with self.repo.transaction() as connection:
            if work_id and not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
            connection.execute(
                """
                INSERT INTO feedback_reports
                  (id, work_id, category, summary, details, context_json,
                   severity, error_json, status, remote_status, remote_id,
                   remote_error, last_sync_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, NULL, NULL, NULL, ?, ?)
                """,
                (report_id, work_id, category, summary, details, canonical_json(context), severity,
                 canonical_json(error), "pending" if self.feedback_remote_url else "disabled", timestamp, timestamp),
            )
        result = {
            "id": report_id,
            "status": "open",
            "stored_locally": True,
            "created_at": timestamp,
        }
        if self.feedback_remote_url:
            remote = self._sync_feedback_report(
                report_id,
                {
                    "source_id": report_id,
                    "client": "halocue",
                    "version": self.feedback_client_version,
                    "category": category,
                    "summary": summary,
                    "details": details,
                    "severity": severity,
                    "context": context,
                    "error": error,
                },
            )
            result["remote"] = remote
        else:
            result["remote"] = {"status": "disabled"}
        return result

    def _sync_feedback_report(self, report_id: str, payload: dict) -> dict:
        """Send feedback server-to-server; the browser never receives the remote token."""
        request = urllib.request.Request(
            self.feedback_remote_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.feedback_remote_token}"} if self.feedback_remote_token else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode("utf-8"))
            remote_id = str(body.get("id", "")) or None
            timestamp = now()
            with self.repo.transaction() as connection:
                connection.execute(
                    "UPDATE feedback_reports SET remote_status='synced', remote_id=?, remote_error=NULL, last_sync_at=?, updated_at=? WHERE id=?",
                    (remote_id, timestamp, timestamp, report_id),
                )
            return {"status": "synced", "id": remote_id}
        except Exception as exc:
            message = str(exc)[:500]
            with self.repo.transaction() as connection:
                connection.execute(
                    "UPDATE feedback_reports SET remote_status='pending', remote_error=?, last_sync_at=?, updated_at=? WHERE id=?",
                    (message, now(), now(), report_id),
                )
            return {"status": "pending", "error": message}

    def sync_pending_feedback(self, limit: int = 20) -> dict:
        if not self.feedback_remote_url:
            return {"status": "disabled", "synced": 0, "pending": 0}
        with self.repo.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback_reports WHERE remote_status='pending' ORDER BY created_at LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        synced = 0
        pending = 0
        for row in rows:
            result = self._sync_feedback_report(
                row["id"],
                {
                    "source_id": row["id"],
                    "client": "halocue",
                    "version": self.feedback_client_version,
                    "category": row["category"],
                    "summary": row["summary"],
                    "details": row["details"],
                    "severity": row["severity"],
                    "context": json.loads(row["context_json"] or "{}"),
                    "error": json.loads(row["error_json"] or "{}"),
                },
            )
            if result["status"] == "synced":
                synced += 1
            else:
                pending += 1
        return {"status": "completed", "synced": synced, "pending": pending}

    def _append_conversation_message(
        self, connection, thread_id: str, role: str, kind: str, content: dict,
        *, provider: dict | None = None, proposal_id: str | None = None,
        agent_run_id: str | None = None, usage: dict | None = None,
    ) -> str:
        usage = usage if isinstance(usage, dict) else {}
        ordinal = connection.execute(
            "SELECT COALESCE(MAX(ordinal),0)+1 FROM conversation_messages WHERE thread_id=?",
            (thread_id,),
        ).fetchone()[0]
        message_id = new_id("message")
        connection.execute(
            "INSERT INTO conversation_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                message_id, thread_id, ordinal, role, kind, canonical_json(content),
                "complete", canonical_json(provider) if provider else None,
                agent_run_id, proposal_id, None, None, None, None, None, now(), None,
            ),
        )
        connection.execute(
            "UPDATE conversation_messages SET input_tokens=?,output_tokens=?,cache_read_tokens=?,cache_write_tokens=?,estimated_cost=? WHERE id=?",
            (
                int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0),
                int(usage.get("cache_read_tokens") or 0), int(usage.get("cache_write_tokens") or 0),
                float(usage["estimated_cost"]) if usage.get("estimated_cost") is not None else None, message_id,
            ),
        )
        self._refresh_conversation_summary(connection, thread_id)
        return message_id

    def _refresh_conversation_summary(self, connection, thread_id: str):
        summary = refresh_conversation_summary(connection, thread_id)
        connection.execute(
            "UPDATE conversation_threads SET summary_json=?,archived_message_count=? WHERE id=?",
            (canonical_json(summary), summary["archived_message_count"], thread_id),
        )
        return summary

    def _conversation_summary(self, connection, thread_id: str) -> dict:
        row = connection.execute(
            "SELECT summary_json FROM conversation_threads WHERE id=?", (thread_id,)
        ).fetchone()
        try:
            summary = json.loads(row["summary_json"] or "{}") if row else {}
        except json.JSONDecodeError:
            summary = {}
        if summary.get("schema_version") != "conversation-summary/1.1":
            summary = self._refresh_conversation_summary(connection, thread_id)
        return validate_conversation_summary(connection, thread_id, summary)

    def _provider_usage(self, provider=None) -> dict:
        provider = provider or self.provider
        getter = getattr(provider, "last_usage", None)
        value = getter() if callable(getter) else getattr(provider, "_last_usage", {})
        if not isinstance(value, dict):
            return {}
        estimated_cost = value.get("estimated_cost")
        return {
            "input_tokens": max(0, int(value.get("input_tokens") or 0)),
            "output_tokens": max(0, int(value.get("output_tokens") or 0)),
            "cache_read_tokens": max(0, int(value.get("cache_read_tokens") or 0)),
            "cache_write_tokens": max(0, int(value.get("cache_write_tokens") or 0)),
            "estimated_cost": max(0.0, float(estimated_cost)) if estimated_cost is not None else None,
        }

    @staticmethod
    def _merge_usage(first: dict, second: dict) -> dict:
        merged = {
            key: int(first.get(key) or 0) + int(second.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
        }
        costs = [value.get("estimated_cost") for value in (first, second) if value.get("estimated_cost") is not None]
        merged["estimated_cost"] = sum(float(value) for value in costs) if costs else None
        return merged

    def _conversation_task_contract(self, connection, work_id: str, requested_scope: dict | None = None) -> dict:
        """Resolve the active director task from persisted work state.

        The browser never selects a writing template.  A work conversation is
        continuous, while each provider turn receives only the template that
        the current, server-validated workflow stage permits.
        """
        contents: dict[str, dict] = {}
        for artifact in connection.execute(
            "SELECT kind,current_revision_id FROM artifacts WHERE work_id=? AND kind IN ('brief','story_blueprint')",
            (work_id,),
        ).fetchall():
            if artifact["current_revision_id"]:
                revision = connection.execute(
                    "SELECT content_uri FROM revisions WHERE id=?", (artifact["current_revision_id"],)
                ).fetchone()
                if revision:
                    contents[artifact["kind"]] = json.loads(self.repo.read_text(revision["content_uri"]))

        brief = contents.get("brief")
        blueprint = contents.get("story_blueprint")
        scene_count = connection.execute("SELECT COUNT(*) FROM scenes WHERE work_id=?", (work_id,)).fetchone()[0]
        drafted_count = connection.execute(
            "SELECT COUNT(*) FROM scenes WHERE work_id=? AND current_revision_id IS NOT NULL", (work_id,)
        ).fetchone()[0]
        pending_count = connection.execute(
            "SELECT COUNT(*) FROM proposals WHERE work_id=? AND status='pending'", (work_id,)
        ).fetchone()[0]

        requested_scope = requested_scope if isinstance(requested_scope, dict) else {}
        surface = str(requested_scope.get("surface", "auto"))
        chapter = None
        scene = None
        memory_scene = None
        if surface == "chapter":
            chapter_id = str(requested_scope.get("chapter_id", "")).strip()
            if not chapter_id:
                target_artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='writing_target'",
                    (work_id,),
                ).fetchone()
                if target_artifact and target_artifact["current_revision_id"]:
                    target_revision = connection.execute(
                        "SELECT content_uri FROM revisions WHERE id=?", (target_artifact["current_revision_id"],)
                    ).fetchone()
                    if target_revision:
                        chapter_id = str(json.loads(self.repo.read_text(target_revision["content_uri"])).get("chapter_id", ""))
            chapter = connection.execute(
                "SELECT id,title FROM chapters WHERE id=? AND work_id=?", (chapter_id, work_id)
            ).fetchone()
            if not chapter:
                raise DomainError("invalid_writing_target", "当前写作章节不存在，请重新选择。", status=409)
        elif surface == "scene":
            scene_id = str(requested_scope.get("scene_id", "")).strip()
            scene = connection.execute(
                """
                SELECT scene.id,scene.title,scene.current_revision_id,scene.contract_json,
                       chapter.id AS chapter_id,chapter.title AS chapter_title
                FROM scenes AS scene
                JOIN chapters AS chapter ON chapter.id=scene.chapter_id
                WHERE scene.id=? AND scene.work_id=?
                """,
                (scene_id, work_id),
            ).fetchone()
            if not scene:
                raise DomainError("invalid_scene_target", "当前写作场景不存在，请重新选择。", status=409)
        elif surface == "scene_memory":
            scene_id = str(requested_scope.get("scene_id", "")).strip()
            memory_scene = connection.execute(
                """
                SELECT scene.id,scene.title,scene.current_revision_id,scene.contract_json,
                       chapter.id AS chapter_id,chapter.title AS chapter_title
                FROM scenes AS scene
                JOIN chapters AS chapter ON chapter.id=scene.chapter_id
                WHERE scene.id=? AND scene.work_id=?
                """,
                (scene_id, work_id),
            ).fetchone()
            if not memory_scene:
                raise DomainError("invalid_scene_memory_target", "要检查的场景不存在。", status=409)
            if not memory_scene["current_revision_id"]:
                raise DomainError("scene_memory_requires_revision", "请先采纳或保存本场正文，再检查资料变化。", status=409)

        if scene:
            discussion_only = bool(requested_scope.get("discussion_only"))
            if discussion_only:
                template_id = "chapter.plan"
                task = (
                    f"只讨论《{scene['chapter_title']} / {scene['title']}》当前写作目标、节拍和承接点；"
                    "读取本场上下文但不生成正文候选、不创建 Proposal，也不修改正式正文。"
                )
            else:
                template_id = (
                    "scene.draft.rewrite"
                    if scene["current_revision_id"]
                    else "scene.draft.generate"
                )
                action = "改写当前正式正文" if scene["current_revision_id"] else "生成第一份正文候选"
                task = (
                    f"只讨论并处理《{scene['chapter_title']} / {scene['title']}》；"
                    f"整理本线程中的作者约束后{action}，只形成待用户审查的 Proposal，不直接写回正文。"
                )
        elif memory_scene:
            template_id = "canon.assemble"
            task = (
                f"检查《{memory_scene['chapter_title']} / {memory_scene['title']}》当前正式正文中新成立的事实、"
                "人物关系变化与伏笔状态；只形成有场景修订来源的资料讨论草稿或 Proposal，不直接写回长期记忆。"
            )
        elif surface == "work" and brief and blueprint and blueprint.get("status") == "accepted" and not scene_count:
            template_id = "structure.plan"
            task = "基于已确认的故事方向，讨论卷、章与场景的稳定结构；结构变更需经用户确认。"
        elif surface == "work" and brief and blueprint and blueprint.get("status") == "accepted":
            template_id = "blueprint.generate"
            task = "在作品栏目维护全作方向、人物关系和世界观边界；任何调整都先形成新的 StoryBlueprint Proposal。"
        elif chapter and brief and blueprint and blueprint.get("status") == "accepted":
            template_id = "chapter.plan"
            task = f"只规划《{chapter['title']}》内部的章节目标、承接点和场景节拍，不重写全作 StoryBlueprint。"
        elif not brief:
            template_id = "brief.build"
            task = "理解这句想法，提出需要讨论的方向，不写入任何正式设定。"
        elif not blueprint or blueprint.get("status") != "accepted" or brief.get("status") != "confirmed":
            template_id = "blueprint.generate"
            task = "围绕当前想法讨论、比较并形成可审查的故事方向 Proposal。"
        elif not scene_count:
            template_id = "structure.plan"
            task = "基于已确认的故事方向，讨论卷、章与场景的稳定结构；结构变更需经用户确认。"
        elif drafted_count < scene_count:
            template_id = "scene.draft.generate"
            task = "协助确定下一场的目标与修改约束；具体正文只能通过该场的 Proposal / Diff 提交。"
        else:
            template_id = "release.review"
            task = "协助全篇审查、确认未决事项，并在 Gate 通过后准备冻结 ScriptRelease。"

        contract = template_contract(template_id)
        selected_modes = [mode for mode in (brief or {}).get("story_modes", []) if mode in MODE_SOURCES]
        if not selected_modes and (brief or {}).get("mode") in MODE_SOURCES:
            selected_modes = [brief["mode"]]
        skill_runtime = self.ba_skill.compile(
            selected_modes[0] if len(selected_modes) == 1 else None,
            bool((brief or {}).get("has_sensei")),
            task_id=template_id,
        )
        prompt_bundle = self.ba_prompt_assembler.describe_bundle(
            template_id,
            mode_key=selected_modes[0] if len(selected_modes) == 1 else None,
            has_sensei=bool((brief or {}).get("has_sensei")),
            output_mode="official_script",
        )
        skill_runtime["prompt_bundle"] = prompt_bundle
        contract.update(
            {
                "task": task,
                "workflow_state": {
                    "scene_count": scene_count,
                    "drafted_scene_count": drafted_count,
                    "pending_proposal_count": pending_count,
                },
                "task_scope": {
                    "surface": "scene" if scene else ("scene_memory" if memory_scene else ("chapter" if chapter else ("work" if surface == "work" else "auto"))),
                    "chapter_id": scene["chapter_id"] if scene else (memory_scene["chapter_id"] if memory_scene else (chapter["id"] if chapter else None)),
                    "chapter_title": scene["chapter_title"] if scene else (memory_scene["chapter_title"] if memory_scene else (chapter["title"] if chapter else None)),
                    "scene_id": scene["id"] if scene else (memory_scene["id"] if memory_scene else None),
                    "scene_title": scene["title"] if scene else (memory_scene["title"] if memory_scene else None),
                    "scene_revision_id": scene["current_revision_id"] if scene else (memory_scene["current_revision_id"] if memory_scene else None),
                },
                "rule_sources": {
                    "common": COMMON_RULES,
                    "modes": {mode: MODE_SOURCES[mode] for mode in selected_modes},
                },
                "write_boundary": "正式 Brief、资料库事实和正文只能由对应 Proposal 采纳后写入。",
                "skill_runtime": skill_runtime,
            }
        )
        return contract

    def _scene_conversation_context(self, connection, work_id: str, task_contract: dict) -> dict | None:
        scope = task_contract.get("task_scope") if isinstance(task_contract.get("task_scope"), dict) else {}
        if scope.get("surface") != "scene":
            return None
        scene = connection.execute(
            """
            SELECT scene.id,scene.title,scene.current_revision_id,scene.contract_json,
                   chapter.id AS chapter_id,chapter.title AS chapter_title
            FROM scenes AS scene
            JOIN chapters AS chapter ON chapter.id=scene.chapter_id
            WHERE scene.id=? AND scene.work_id=?
            """,
            (scope.get("scene_id"), work_id),
        ).fetchone()
        if not scene:
            raise DomainError("scene_conversation_target_stale", "本场对话所绑定的场景已经不存在。", status=409)

        materials = []
        source_revisions = []
        rows = connection.execute(
            """SELECT kind,scope_type,scope_id,current_revision_id
               FROM artifacts
               WHERE work_id=? AND current_revision_id IS NOT NULL
                 AND kind IN ('brief','story_blueprint','story_structure','chapter_plan',
                              'work_canon','world_bible','character_card')
               ORDER BY kind,scope_id""",
            (work_id,),
        ).fetchall()
        for row in rows:
            content = self._revision_content(connection, row["current_revision_id"])
            if row["kind"] == "brief" and content.get("status", "confirmed") != "confirmed":
                continue
            if row["kind"] == "story_blueprint" and content.get("status") != "accepted":
                continue
            if row["kind"] == "character_card" and (
                content.get("trust_status", "confirmed") != "confirmed"
                or content.get("status", "active") == "archived"
            ):
                continue
            if row["kind"] == "work_canon":
                content = {
                    **content,
                    "facts": [
                        item for item in content.get("facts", [])
                        if item.get("status", "active") != "archived"
                        and item.get("confidence_status") == "confirmed"
                    ],
                }
            if row["kind"] == "world_bible":
                content = {
                    **content,
                    **{
                        collection: [
                            item for item in content.get(collection, [])
                            if item.get("status", "active") != "archived"
                            and item.get("confidence_status") == "confirmed"
                        ]
                        for collection in ("entities", "rules", "timeline")
                    },
                }
            material = {
                "kind": row["kind"],
                "scope_type": row["scope_type"],
                "scope_id": row["scope_id"],
                "revision_id": row["current_revision_id"],
                "content": content,
            }
            materials.append(material)
            source_revisions.append({
                "kind": row["kind"],
                "scope_type": row["scope_type"],
                "scope_id": row["scope_id"],
                "revision_id": row["current_revision_id"],
            })

        references = []
        for row in connection.execute(
            """SELECT id,title,kind,content_uri,content_hash,source_label,version
               FROM reference_files
               WHERE work_id=? AND trust_status='confirmed'
               ORDER BY updated_at""",
            (work_id,),
        ).fetchall():
            excerpt = self._traceable_text_excerpt(self.repo.read_text(row["content_uri"]))
            references.append({
                "id": row["id"],
                "title": row["title"],
                "kind": row["kind"],
                "source_label": row["source_label"],
                "version": row["version"],
                "content_hash": row["content_hash"],
                "content": excerpt["text"],
                "content_truncated": excerpt["truncated"],
            })

        manuscript = None
        if scene["current_revision_id"]:
            manuscript = {
                "revision_id": scene["current_revision_id"],
                "content": self._revision_content(connection, scene["current_revision_id"]),
            }
            source_revisions.append({
                "kind": "scene_script",
                "scope_type": "scene",
                "scope_id": scene["id"],
                "revision_id": scene["current_revision_id"],
            })

        scene_asset_references = self._scene_asset_references(connection, work_id, scene["id"])

        return {
            "schema_version": "scene-conversation-context/1.0",
            "scene": {
                "id": scene["id"],
                "title": scene["title"],
                "chapter_id": scene["chapter_id"],
                "chapter_title": scene["chapter_title"],
                "contract": json.loads(scene["contract_json"] or "{}"),
            },
            "current_manuscript": manuscript,
            "scene_asset_references": scene_asset_references,
            "confirmed_materials": materials,
            "confirmed_references": references,
            "source_revisions": source_revisions,
            "source_revision_ids": [item["revision_id"] for item in source_revisions],
            "ba_skill": task_contract.get("skill_runtime"),
            "write_boundary": "只读讨论上下文；不得写回场景正文。正文变更只能形成 Proposal，并由用户审查采纳。",
        }

    def _scene_memory_context(self, connection, work_id: str, task_contract: dict) -> dict | None:
        scope = task_contract.get("task_scope") if isinstance(task_contract.get("task_scope"), dict) else {}
        if scope.get("surface") != "scene_memory":
            return None
        scene = connection.execute(
            """
            SELECT scene.id,scene.title,scene.current_revision_id,scene.contract_json,
                   chapter.id AS chapter_id,chapter.title AS chapter_title
            FROM scenes AS scene
            JOIN chapters AS chapter ON chapter.id=scene.chapter_id
            WHERE scene.id=? AND scene.work_id=?
            """,
            (scope.get("scene_id"), work_id),
        ).fetchone()
        if not scene or not scene["current_revision_id"]:
            raise DomainError("scene_memory_target_stale", "本场正式正文已经变化，请重新发起资料检查。", status=409)
        script = self._revision_content(connection, scene["current_revision_id"])
        canon_rows = connection.execute(
            "SELECT kind,scope_id,current_revision_id FROM artifacts WHERE work_id=? AND kind IN ('work_canon','character_card','world_bible') AND current_revision_id IS NOT NULL",
            (work_id,),
        ).fetchall()
        formal_context = [
            {
                "kind": row["kind"],
                "scope_id": row["scope_id"],
                "revision_id": row["current_revision_id"],
                "content": self._revision_content(connection, row["current_revision_id"]),
            }
            for row in canon_rows
        ]
        return {
            "schema_version": "scene-memory-context/1.0",
            "scene": {
                "id": scene["id"],
                "title": scene["title"],
                "chapter_id": scene["chapter_id"],
                "chapter_title": scene["chapter_title"],
                "contract": json.loads(scene["contract_json"] or "{}"),
                "revision_id": scene["current_revision_id"],
                "script": script,
            },
            "formal_context": formal_context,
            "source_revision_ids": [scene["current_revision_id"], *[row["current_revision_id"] for row in canon_rows]],
            "write_boundary": "输出只能是资料讨论草稿或 Proposal；用户采纳前不得修改 WorkCanon、人物卡或世界观。",
        }

    @staticmethod
    def _effective_conversation_scope(thread, requested_scope: dict | None) -> dict:
        scope = dict(requested_scope) if isinstance(requested_scope, dict) else {}
        surface = str(scope.get("surface") or "auto")
        if thread["scope_type"] == "chapter":
            requested_chapter = str(scope.get("chapter_id") or "").strip()
            if surface in {"", "auto"}:
                return {"surface": "chapter", "chapter_id": thread["scope_id"]}
            if surface != "chapter" or requested_chapter not in {"", thread["scope_id"]}:
                raise DomainError("invalid_thread_scope", "章节对话不能切换到其他作品或章节作用域。", status=409)
            return {**scope, "surface": "chapter", "chapter_id": thread["scope_id"]}
        if thread["scope_type"] == "scene":
            requested_scene = str(scope.get("scene_id") or "").strip()
            if surface in {"", "auto"}:
                return {"surface": "scene", "scene_id": thread["scope_id"]}
            if surface != "scene" or requested_scene not in {"", thread["scope_id"]}:
                raise DomainError("invalid_thread_scope", "场景对话不能切换到其他作品、章节或场景作用域。", status=409)
            return {**scope, "surface": "scene", "scene_id": thread["scope_id"]}
        if thread["scope_type"] == "work" and thread["scope_id"] == thread["work_id"]:
            if surface not in {"", "auto", "work", "chapter", "scene", "scene_memory"}:
                raise DomainError("invalid_thread_scope", "作品对话请求了不支持的任务作用域。", status=409)
            return scope
        raise DomainError("invalid_thread_scope", "当前对话作用域无效。", status=409)

    def create_work(self, payload: dict):
        idea = str(payload.get("idea", "")).strip()
        title = str(payload.get("title", "")).strip() or idea[:24]
        if not title:
            raise DomainError("validation_error", "请写下一句故事想法或作品名称。", details={"fields": ["idea", "title"]})
        world_seed = str(payload.get("world_seed", "blank")).strip() or "blank"
        if world_seed not in {"blank", "ba_starter"}:
            raise DomainError("validation_error", "世界观底稿类型无效。", details={"field": "world_seed"})
        permission_mode = str(payload.get("permission_mode", "review")).strip() or "review"
        if permission_mode not in {"review", "managed"}:
            raise DomainError("validation_error", "Agent 授权模式无效。", details={"field": "permission_mode"})
        work_id = new_id("work")
        volume_id = new_id("volume")
        chapter_id = new_id("chapter")
        thread_id = new_id("thread")
        timestamp = now()
        seed_revision_id = None
        with self.repo.transaction() as connection:
            connection.execute(
                "INSERT INTO works VALUES (?,?,?,?,?,?,?)",
                (work_id, title, "active", 1, PACK_VERSION, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO volumes VALUES (?,?,?,?,?,?,?,?)",
                (volume_id, work_id, "000001", "第一卷", "active", 1, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO chapters (id,work_id,volume_id,stable_order_key,title,status,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (chapter_id, work_id, volume_id, "000001", "第一章", "placeholder", 1, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO conversation_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (thread_id, work_id, "work", work_id, "创作主对话", "active", "discuss", permission_mode, 1, "{}", 0, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO authorization_policies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("policy"), work_id, thread_id, "work", work_id, permission_mode,
                    canonical_json(["read", "discuss"] if permission_mode == "review" else ["read", "discuss", "auto_create_low_risk_proposal"]),
                    12 if permission_mode == "managed" else None,
                    None, None, "active", 1, timestamp, timestamp,
                ),
            )
            run_id = new_id("run")
            connection.execute(
                "INSERT INTO production_runs VALUES (?,?,?,?,?,?,?,?)",
                (run_id, work_id, "creation", permission_mode, "planned", "[]", timestamp, timestamp),
            )
            if world_seed == "ba_starter":
                artifact = self._artifact(connection, work_id, "world_bible", "work", work_id)
                seed_revision_id = self._add_revision(
                    connection,
                    artifact,
                    starter_bible(),
                    "user",
                    {
                        "workflow": "world.starter.apply",
                        "pack": PACK_VERSION,
                        "starter_version": BA_WORLD_STARTER_VERSION,
                        "source": BA_WORLD_STARTER_SOURCE,
                        "disclosure": "这是待核对的产品起始架构，不是自动确认的 BA 原作事实。",
                    },
                )
        if seed_revision_id:
            self._schedule_commit_projection(work_id, seed_revision_id)
        if idea:
            result = self.post_conversation_message(
                work_id, thread_id,
                {"expected_thread_version": 1, "text": idea},
            )
            return result["work"]
        return self.get_work(work_id)

    def get_work(self, work_id: str):
        with self.repo.connect() as connection:
            work = self.repo.row(connection.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone())
            if not work:
                raise NotFound("work", work_id)
            volumes = self.repo.rows(connection.execute("SELECT * FROM volumes WHERE work_id=? ORDER BY stable_order_key", (work_id,)))
            chapters = self.repo.rows(connection.execute(
                """SELECT c.* FROM chapters c
                   LEFT JOIN volumes v ON v.id=c.volume_id
                   WHERE c.work_id=?
                   ORDER BY COALESCE(v.stable_order_key,''),c.stable_order_key,c.id""",
                (work_id,),
            ))
            for chapter in chapters:
                chapter["scenes"] = self.repo.rows(connection.execute("SELECT * FROM scenes WHERE chapter_id=? ORDER BY stable_order_key", (chapter["id"],)))
                for scene in chapter["scenes"]:
                    scene["contract"] = json.loads(scene.pop("contract_json"))
                    scene["asset_references"] = self._scene_asset_references(
                        connection, work_id, scene["id"]
                    )
            for volume in volumes:
                volume["chapters"] = [chapter for chapter in chapters if chapter.get("volume_id") == volume["id"]]
            artifacts = self.repo.rows(connection.execute("SELECT * FROM artifacts WHERE work_id=?", (work_id,)))
            for artifact in artifacts:
                if artifact["current_revision_id"]:
                    revision = self.repo.row(connection.execute("SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone())
                    revision["content"] = json.loads(self.repo.read_text(revision["content_uri"]))
                    if artifact["kind"] == "scene_script" and "blocks" not in revision["content"]:
                        revision["content"] = self._scene_content_from_text(
                            revision["content"].get("text", ""), revision["id"]
                        )
                    revision["provenance"] = json.loads(revision.pop("provenance_json"))
                    artifact["current_revision"] = revision
                history = self.repo.rows(connection.execute(
                    "SELECT id, parent_revision_id, ordinal, schema_version, content_hash, created_by, created_at, content_uri, provenance_json FROM revisions WHERE artifact_id=? ORDER BY ordinal DESC",
                    (artifact["id"],),
                ))
                for item in history:
                    item["content"] = json.loads(self.repo.read_text(item.pop("content_uri")))
                    if artifact["kind"] == "scene_script" and "blocks" not in item["content"]:
                        item["content"] = self._scene_content_from_text(
                            item["content"].get("text", ""), item["id"]
                        )
                    item["provenance"] = json.loads(item.pop("provenance_json"))
                artifact["revisions"] = history
            work["volumes"] = volumes
            work["chapters"] = chapters
            work["artifacts"] = artifacts
            work["proposals"] = self.repo.rows(connection.execute("SELECT * FROM proposals WHERE work_id=? ORDER BY created_at DESC", (work_id,)))
            for proposal in work["proposals"]:
                structured_kinds = {"brief_blueprint", "chapter_plan", "story_structure", "character_card", "world_entity", "world_rule", "canon_fact", "memory_bundle"}
                actual_hash = None
                try:
                    candidate_text = self.repo.read_text(proposal["candidate_uri"])
                    actual_hash = sha256_text(candidate_text)
                except (OSError, UnicodeError, ValueError):
                    candidate_text = None
                integrity_valid = candidate_text is not None and actual_hash == proposal["candidate_hash"]
                proposal["candidate_integrity"] = {
                    "valid": integrity_valid,
                    "expected_hash": proposal["candidate_hash"],
                    "actual_hash": actual_hash,
                }
                if integrity_valid:
                    try:
                        proposal["candidate"] = json.loads(candidate_text) if proposal.get("kind") in structured_kinds else candidate_text
                    except json.JSONDecodeError:
                        proposal["candidate"] = None
                        proposal["candidate_integrity"]["valid"] = False
                        proposal["candidate_integrity"]["parseable"] = False
                else:
                    proposal["candidate"] = None
                if proposal.get("kind") == "scene_script" and isinstance(proposal.get("candidate"), str):
                    base_blocks = self._scene_revision_blocks(connection, proposal.get("base_revision_id"))
                    proposal["block_changes"] = self._scene_block_change_plan(
                        base_blocks,
                        proposal["candidate"],
                        proposal["candidate_hash"],
                    )
                elif proposal.get("kind") == "scene_script":
                    proposal["block_changes"] = []
                proposal["diff"] = json.loads(proposal.pop("diff_json"))
                proposal["evidence"] = json.loads(proposal.pop("evidence_json"))
                proposal["provider"] = json.loads(proposal.pop("provider_json"))
            work["releases"] = self.repo.rows(connection.execute("SELECT * FROM script_releases WHERE work_id=? ORDER BY released_at DESC", (work_id,)))
            work["runs"] = self.repo.rows(connection.execute("SELECT * FROM production_runs WHERE work_id=? ORDER BY created_at DESC", (work_id,)))
            for run in work["runs"]:
                run["work_items"] = self.repo.rows(connection.execute("SELECT * FROM work_items WHERE run_id=? ORDER BY created_at", (run["id"],)))
                for item in run["work_items"]:
                    item["input_refs"] = json.loads(item.get("input_refs_json") or "[]")
                    item["output_refs"] = json.loads(item.get("output_refs_json") or "[]")
                    item["acceptance"] = json.loads(item.get("acceptance_json") or "{}")
                    item["error"] = json.loads(item["error_json"]) if item.get("error_json") else None
                    item["attempts"] = self.repo.rows(connection.execute(
                        "SELECT * FROM job_attempts WHERE work_item_id=? ORDER BY ordinal", (item["id"],)
                    ))
            work["agent_runs"] = self.repo.rows(connection.execute("SELECT * FROM agent_runs WHERE work_id=? ORDER BY created_at DESC", (work_id,)))
            for agent_run in work["agent_runs"]:
                agent_run["policy"] = json.loads(agent_run.pop("policy_json"))
                agent_run["failure"] = json.loads(agent_run.pop("failure_json")) if agent_run.get("failure_json") else None
                agent_run["tool_calls"] = self.repo.rows(connection.execute("SELECT * FROM agent_tool_calls WHERE agent_run_id=? ORDER BY ordinal", (agent_run["id"],)))
                for call in agent_run["tool_calls"]:
                    call["error"] = json.loads(call.pop("error_json")) if call.get("error_json") else None
                agent_run["timeline"] = self._agent_run_timeline(connection, agent_run, agent_run["tool_calls"])
            work["conversation_threads"] = self.repo.rows(connection.execute(
                "SELECT * FROM conversation_threads WHERE work_id=? ORDER BY updated_at DESC", (work_id,)
            ))
            for thread in work["conversation_threads"]:
                thread["summary"] = json.loads(thread.pop("summary_json"))
                thread["messages"] = self.repo.rows(connection.execute(
                    "SELECT * FROM conversation_messages WHERE thread_id=? ORDER BY ordinal", (thread["id"],)
                ))
                for message in thread["messages"]:
                    message["content"] = json.loads(message.pop("content_json"))
                    message["provider"] = json.loads(message.pop("provider_json")) if message.get("provider_json") else None
                thread["attachments"] = self.repo.rows(connection.execute(
                    "SELECT id,message_id,filename,media_type,content_hash,byte_size,status,created_at FROM conversation_attachments WHERE thread_id=? ORDER BY created_at",
                    (thread["id"],),
                ))
                for attachment in thread["attachments"]:
                    attachment["content_url"] = f"/api/v1/works/{work_id}/attachments/{attachment['id']}/content"
                    if not str(attachment.get("media_type", "")).startswith("image/"):
                        attachment["document_index"] = {
                            "version": "document-chunks/1.0",
                            "chunk_count": connection.execute(
                                "SELECT COUNT(*) FROM document_chunks WHERE attachment_id=?",
                                (attachment["id"],),
                            ).fetchone()[0],
                        }
            work["authorization_policies"] = self.repo.rows(connection.execute(
                "SELECT * FROM authorization_policies WHERE work_id=? ORDER BY updated_at DESC", (work_id,)
            ))
            for policy in work["authorization_policies"]:
                policy["allowed_actions"] = json.loads(policy.pop("allowed_actions_json"))
            work["reference_files"] = self.repo.rows(connection.execute("SELECT id,title,kind,content_uri,content_hash,source_label,trust_status,version,created_at,updated_at FROM reference_files WHERE work_id=? ORDER BY updated_at DESC", (work_id,)))
            for reference in work["reference_files"]:
                reference["preview"] = self.repo.read_text(reference.pop("content_uri"))[:1800]
            work["memories"] = memory_projection_rows(connection, work_id)
            work["gates"] = self.repo.rows(connection.execute("SELECT * FROM gates WHERE work_id=? ORDER BY created_at DESC", (work_id,)))
            for gate in work["gates"]:
                gate["snapshot"] = json.loads(gate.pop("result_json"))
            work["review_findings"] = self.repo.rows(connection.execute("SELECT * FROM review_findings WHERE work_id=? ORDER BY created_at DESC", (work_id,)))
            for finding in work["review_findings"]:
                finding["evidence"] = json.loads(finding.pop("evidence_json"))
                finding["revision_refs"] = json.loads(finding.pop("revision_refs_json", "[]") or "[]")
            work["intent_plans"] = self.repo.rows(connection.execute(
                "SELECT id,thread_id,original_message,target_json,risk_level,requires_confirmation,status,actions_json,result_json,created_at,updated_at FROM intent_plans WHERE work_id=? ORDER BY created_at DESC",
                (work_id,),
            ))
            for plan in work["intent_plans"]:
                plan["requires_confirmation"] = bool(plan["requires_confirmation"])
                try:
                    plan["target"] = json.loads(plan.pop("target_json") or "{}")
                    plan["actions"] = json.loads(plan.pop("actions_json") or "[]")
                    plan["result"] = json.loads(plan.pop("result_json") or "{}")
                except json.JSONDecodeError:
                    plan["actions"] = []
                    plan["result"] = {}
                run_id = str(plan["result"].get("agent_run_id") or "")
                run = next((item for item in work["agent_runs"] if item["id"] == run_id), None)
                if plan["status"] == "running" and run and run["status"] not in {"queued", "running"}:
                    plan["status"] = "failed" if run["status"] in {"failed", "cancelled"} else run["status"]
                projected = self._project_intent_plan_execution(plan, work)
                plan.clear()
                plan.update(projected)
            work["harness"] = self.get_harness_status(work_id)
            return work

    def get_user_work_status(self, work_id: str) -> dict:
        """Return the small, human-facing status projection for a work.

        This endpoint deliberately has a separate shape from ``get_work``.
        The full work response remains available to the application and audit
        surfaces, while the normal Agent screen only needs a next action and
        a few understandable counts.
        """
        with self.repo.connect() as connection:
            work = connection.execute(
                "SELECT id,version FROM works WHERE id=?", (work_id,)
            ).fetchone()
            if not work:
                raise NotFound("work", work_id)

            def current_content(kind: str):
                row = connection.execute(
                    """SELECT r.content_uri FROM artifacts a
                       JOIN revisions r ON r.id=a.current_revision_id
                       WHERE a.work_id=? AND a.kind=?""",
                    (work_id, kind),
                ).fetchone()
                if not row:
                    return None
                try:
                    value = json.loads(self.repo.read_text(row["content_uri"]))
                except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                    return None
                return value if isinstance(value, dict) else None

            brief = current_content("brief")
            blueprint = current_content("story_blueprint")
            scene_count = int(connection.execute(
                "SELECT COUNT(*) FROM scenes WHERE work_id=?", (work_id,)
            ).fetchone()[0])
            drafted_count = int(connection.execute(
                "SELECT COUNT(*) FROM scenes WHERE work_id=? AND current_revision_id IS NOT NULL",
                (work_id,),
            ).fetchone()[0])
            pending_proposals = connection.execute(
                """SELECT kind,scope_type,scope_id,created_at
                   FROM proposals
                   WHERE work_id=? AND status='pending'
                   ORDER BY created_at DESC,id DESC""",
                (work_id,),
            ).fetchall()
            pending_count = len(pending_proposals)
            blocking_count = int(connection.execute(
                """SELECT COUNT(*) FROM review_findings
                   WHERE work_id=? AND status='open' AND severity='blocking'""",
                (work_id,),
            ).fetchone()[0])
            active_count = int(connection.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE work_id=? AND status IN ('queued','running')",
                (work_id,),
            ).fetchone()[0])
            # Historical failures remain in the audit timeline. The ordinary
            # status surface only reports the latest run when the harness has
            # verified that its fixed input is still recoverable.
            harness = self.get_harness_status(work_id)
            recovery = harness.get("resume") if isinstance(harness.get("resume"), dict) else {}
            failed_count = int(
                harness.get("phase") == "agent_recovery"
                and bool(recovery.get("available"))
            )

            summaries = []
            for row in connection.execute(
                "SELECT summary_json FROM conversation_threads WHERE work_id=? AND status='active'",
                (work_id,),
            ).fetchall():
                try:
                    summary = json.loads(row["summary_json"] or "{}")
                except json.JSONDecodeError:
                    summary = {}
                if isinstance(summary, dict):
                    summaries.append(summary)
            needs_organizing = any(
                int(summary.get("archived_message_count") or 0) > 0
                or int(summary.get("overflowed_user_context_count") or 0) > 0
                for summary in summaries
            )

            blueprint_confirmed = bool(
                blueprint and blueprint.get("status") in {"accepted", "confirmed"}
            )
            released = bool(connection.execute(
                "SELECT 1 FROM script_releases WHERE work_id=? LIMIT 1", (work_id,)
            ).fetchone())

            # The primary action is semantic. The browser resolves it to the
            # current view, so this projection never needs to expose IDs.
            if blocking_count:
                primary = {
                    "id": "review_blockers",
                    "label": "处理审查问题",
                    "detail": f"有 {blocking_count} 项内容需要先处理。",
                    "target": "draft",
                }
            elif pending_count:
                pending_kind = pending_proposals[0]["kind"]
                if pending_kind == "brief_blueprint":
                    primary = {
                        "id": "review_direction",
                        "label": "审查故事方向",
                        "detail": f"有 {pending_count} 项候选等待你的决定。",
                        "target": "agent",
                    }
                elif pending_kind in {"story_structure", "chapter_plan"}:
                    primary = {
                        "id": "review_structure",
                        "label": "审查章节安排",
                        "detail": f"有 {pending_count} 项候选等待你的决定。",
                        "target": "structure",
                    }
                elif pending_kind == "scene_script":
                    primary = {
                        "id": "review_scene_candidate",
                        "label": "审查正文候选",
                        "detail": f"有 {pending_count} 项候选等待你的决定。",
                        "target": "draft",
                    }
                elif pending_kind == "memory_bundle":
                    primary = {
                        "id": "review_memory",
                        "label": "审查本章变化",
                        "detail": f"有 {pending_count} 项候选等待你的决定。",
                        "target": "draft",
                    }
                elif pending_kind in {"character_card", "world_card", "world_entity", "world_rule", "canon_fact"}:
                    primary = {
                        "id": "review_knowledge",
                        "label": "审查创作资料",
                        "detail": f"有 {pending_count} 项资料候选等待你的决定。",
                        "target": "library_suggestions",
                    }
                else:
                    primary = {
                        "id": "review_pending",
                        "label": "查看待决定内容",
                        "detail": f"有 {pending_count} 项候选等待你的决定。",
                        "target": "agent",
                    }
            elif failed_count and not active_count:
                primary = {
                    "id": "recover_run",
                    "label": "继续未完成的任务",
                    "detail": "上一轮没有完成，输入和已确认资料仍然保留。",
                    "target": "agent",
                }
            elif needs_organizing:
                primary = {
                    "id": "organize_conversation",
                    "label": "整理对话后继续",
                    "detail": "对话内容已经较多，先整理会让下一轮讨论更稳妥。",
                    "target": "agent",
                }
            elif not brief:
                primary = {
                    "id": "start_idea",
                    "label": "开始写作想法",
                    "detail": "先说一句你想写的故事。",
                    "target": "brief",
                }
            elif not blueprint_confirmed:
                primary = {
                    "id": "confirm_direction",
                    "label": "确认故事方向",
                    "detail": "把当前讨论整理成一份可检查的方向候选。",
                    "target": "brief",
                }
            elif not scene_count:
                primary = {
                    "id": "build_structure",
                    "label": "建立章节与场景",
                    "detail": "先建立一章，再把它拆成稳定的场景。",
                    "target": "structure",
                }
            elif drafted_count < scene_count:
                primary = {
                    "id": "continue_draft",
                    "label": "继续写下一场",
                    "detail": f"还有 {scene_count - drafted_count} 场没有正文。",
                    "target": "draft",
                }
            elif not released:
                primary = {
                    "id": "review_release",
                    "label": "检查并发布",
                    "detail": "正文已经准备好，可以进行全篇检查。",
                    "target": "release",
                }
            else:
                primary = {
                    "id": "continue_discussion",
                    "label": "继续创作",
                    "detail": "从当前对话或章节继续推进。",
                    "target": "agent",
                }

            alerts = []
            if pending_count:
                alerts.append({"kind": "decision", "text": f"{pending_count} 项内容等待你的决定"})
            if blocking_count:
                alerts.append({"kind": "blocked", "text": f"{blocking_count} 项审查问题需要处理"})
            if needs_organizing:
                alerts.append({"kind": "organize", "text": "对话内容较多，整理后继续会更稳妥"})
            if failed_count and not active_count:
                alerts.append({"kind": "recovery", "text": "有一轮没有完成，可以从原位置继续"})

            return {
                "schema_version": "work-user-status/1.0",
                "work_version": int(work["version"]),
                "primary_action": primary,
                "alerts": alerts[:3],
                "counts": {
                    "pending_decisions": pending_count,
                    "blocking_issues": blocking_count,
                    "active_runs": active_count,
                    "failed_runs": failed_count,
                    "drafted_scenes": drafted_count,
                    "total_scenes": scene_count,
                },
                "conversation": {
                    "needs_organizing": needs_organizing,
                },
            }

    def _scene_asset_references(self, connection, work_id: str, scene_id: str) -> list[dict]:
        rows = self.repo.rows(
            connection.execute(
                """SELECT * FROM scene_asset_references
                   WHERE work_id=? AND scene_id=?
                   ORDER BY CASE asset_kind
                     WHEN 'background' THEN 1 WHEN 'character' THEN 2
                     WHEN 'sound' THEN 3 ELSE 4 END, created_at, id""",
                (work_id, scene_id),
            )
        )
        for row in rows:
            row["source_snapshot"] = json.loads(row.pop("source_snapshot_json") or "{}")
            row["production_copy"] = (
                json.loads(row.pop("production_copy_json"))
                if row.get("production_copy_json")
                else None
            )
        return rows

    @staticmethod
    def _scene_asset_reference_snapshot(references: list[dict]) -> list[dict]:
        """Freeze the public, traceable part of Scene asset references."""

        return [
            {
                "reference_id": reference["id"],
                "asset_kind": reference["asset_kind"],
                "source_type": reference["source_type"],
                "source_asset_id": reference["source_asset_id"],
                "display_name": reference["display_name"],
                "source_version": reference["source_version"],
                "content_hash": reference["content_hash"],
                "content_hash_kind": reference["content_hash_kind"],
                "source_snapshot": reference["source_snapshot"],
                "production_copy": reference["production_copy"],
            }
            for reference in references
        ]

    @staticmethod
    def _revision_comparison_subject(value, fallback: str) -> str:
        if isinstance(value, dict):
            for key in ("name", "canonical_name", "title", "text"):
                label = str(value.get(key) or "").strip()
                if label:
                    return label[:120]
        return fallback

    @staticmethod
    def _revision_comparison_changes(before, after, path: str = "") -> list[dict]:
        if canonical_json(before) == canonical_json(after):
            return []
        if isinstance(before, dict) and isinstance(after, dict):
            changes = []
            for key in sorted(set(before).union(after)):
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                child_path = f"{path}/{escaped}"
                if key not in before:
                    changes.append({"path": child_path, "operation": "add", "before": None, "after": after[key]})
                elif key not in after:
                    changes.append({"path": child_path, "operation": "remove", "before": before[key], "after": None})
                else:
                    changes.extend(WritingService._revision_comparison_changes(before[key], after[key], child_path))
            return changes
        if isinstance(before, list) and isinstance(after, list):
            combined = [*before, *after]
            identifiable = bool(combined) and all(
                isinstance(item, dict) and str(item.get("id") or "").strip()
                for item in combined
            )
            if identifiable:
                before_by_id = {str(item["id"]): item for item in before}
                after_by_id = {str(item["id"]): item for item in after}
                if len(before_by_id) == len(before) and len(after_by_id) == len(after):
                    changes = []
                    for item_id in sorted(set(before_by_id).union(after_by_id)):
                        escaped = item_id.replace("~", "~0").replace("/", "~1")
                        child_path = f"{path}/{escaped}"
                        before_item = before_by_id.get(item_id)
                        after_item = after_by_id.get(item_id)
                        subject = WritingService._revision_comparison_subject(
                            after_item or before_item, item_id
                        )
                        if before_item is None:
                            changes.append({
                                "path": child_path,
                                "operation": "add",
                                "before": None,
                                "after": after_item,
                                "subject": subject,
                            })
                        elif after_item is None:
                            changes.append({
                                "path": child_path,
                                "operation": "remove",
                                "before": before_item,
                                "after": None,
                                "subject": subject,
                            })
                        else:
                            item_changes = WritingService._revision_comparison_changes(
                                before_item, after_item, child_path
                            )
                            for change in item_changes:
                                change.setdefault("subject", subject)
                            changes.extend(item_changes)
                    return changes
        operation = "replace"
        if before is None:
            operation = "add"
        elif after is None:
            operation = "remove"
        return [{"path": path or "/", "operation": operation, "before": before, "after": after}]

    def _verified_revision_content(self, revision, *, artifact_id: str) -> dict:
        try:
            text = self.repo.read_text(revision["content_uri"])
            if sha256_text(text) != revision["content_hash"]:
                raise ValueError("hash mismatch")
            content = json.loads(text)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DomainError(
                "revision_integrity_failed",
                "资料修订内容损坏或无法验证，系统不会展示不可信比较结果。",
                status=409,
                details={"artifact_id": artifact_id, "revision_id": revision["id"]},
            ) from exc
        if not isinstance(content, dict):
            raise DomainError(
                "revision_integrity_failed",
                "资料修订内容不是有效对象，系统不会展示不可信比较结果。",
                status=409,
                details={"artifact_id": artifact_id, "revision_id": revision["id"]},
            )
        return content

    def compare_artifact_revisions(
        self,
        work_id: str,
        artifact_id: str,
        revision_id: str,
        against_revision_id: str | None = None,
    ) -> dict:
        """Compare two immutable formal revisions without changing either one."""

        with self.repo.connect() as connection:
            artifact = connection.execute(
                "SELECT * FROM artifacts WHERE id=? AND work_id=?",
                (artifact_id, work_id),
            ).fetchone()
            if not artifact:
                raise NotFound("artifact", artifact_id)
            if artifact["kind"] not in {"character_card", "world_bible", "work_canon", "story_structure"}:
                raise DomainError(
                    "revision_comparison_unsupported",
                    "当前资料类型不支持在资料库中比较修订。",
                    status=409,
                    details={"artifact_id": artifact_id, "artifact_kind": artifact["kind"]},
                )
            target_revision_id = str(against_revision_id or artifact["current_revision_id"] or "").strip()
            if not target_revision_id:
                raise DomainError(
                    "revision_comparison_target_missing",
                    "当前资料还没有可比较的正式修订。",
                    status=409,
                    details={"artifact_id": artifact_id},
                )
            rows = connection.execute(
                "SELECT * FROM revisions WHERE artifact_id=? AND id IN (?,?)",
                (artifact_id, revision_id, target_revision_id),
            ).fetchall()
            revisions = {row["id"]: row for row in rows}
            if revision_id not in revisions:
                raise NotFound("revision", revision_id)
            if target_revision_id not in revisions:
                raise NotFound("revision", target_revision_id)
            before_revision = revisions[revision_id]
            after_revision = revisions[target_revision_id]
            before = self._verified_revision_content(before_revision, artifact_id=artifact_id)
            after = self._verified_revision_content(after_revision, artifact_id=artifact_id)

        all_changes = self._revision_comparison_changes(before, after)
        changes = all_changes[:200]
        counts = {
            operation: sum(1 for item in all_changes if item["operation"] == operation)
            for operation in ("add", "remove", "replace")
        }
        core = {
            "schema_version": "artifact-revision-comparison/1.0",
            "work_id": work_id,
            "artifact": {
                "id": artifact_id,
                "kind": artifact["kind"],
                "scope_type": artifact["scope_type"],
                "scope_id": artifact["scope_id"],
            },
            "from_revision": {
                "id": before_revision["id"],
                "ordinal": before_revision["ordinal"],
                "content_hash": before_revision["content_hash"],
                "created_by": before_revision["created_by"],
                "created_at": before_revision["created_at"],
            },
            "to_revision": {
                "id": after_revision["id"],
                "ordinal": after_revision["ordinal"],
                "content_hash": after_revision["content_hash"],
                "created_by": after_revision["created_by"],
                "created_at": after_revision["created_at"],
            },
            "change_counts": counts,
            "total_change_count": len(all_changes),
            "truncated": len(all_changes) > len(changes),
            "changes": changes,
        }
        return {**core, "comparison_digest": sha256_text(canonical_json(core))}

    def list_memories(self, work_id: str):
        with self.repo.connect() as connection:
            if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
            return memory_projection_rows(connection, work_id)

    def _check_work_version(self, connection, work_id: str, expected_version: int):
        row = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
        if not row:
            raise NotFound("work", work_id)
        if row["version"] != expected_version:
            raise RevisionConflict(expected_version, row["version"])
        return row["version"]

    def list_archived_conversations(self, query: str = "") -> list[dict]:
        normalized_query = str(query or "").strip()[:120]
        with self.repo.connect() as connection:
            params: list[str] = []
            where = "WHERE thread.status='archived'"
            if normalized_query:
                where += " AND (thread.title LIKE ? OR work.title LIKE ?)"
                pattern = f"%{normalized_query}%"
                params.extend([pattern, pattern])
            rows = self.repo.rows(
                connection.execute(
                    f"""
                    SELECT thread.id,thread.work_id,thread.title,thread.scope_type,thread.scope_id,
                           thread.version,thread.updated_at,work.title AS work_title,
                           COUNT(message.id) AS message_count
                    FROM conversation_threads AS thread
                    JOIN works AS work ON work.id=thread.work_id
                    LEFT JOIN conversation_messages AS message ON message.thread_id=thread.id
                    {where}
                    GROUP BY thread.id
                    ORDER BY thread.updated_at DESC
                    """,
                    params,
                )
            )
            for row in rows:
                latest = connection.execute(
                    "SELECT content_json FROM conversation_messages WHERE thread_id=? ORDER BY ordinal DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                preview = "还没有对话内容"
                if latest:
                    content = json.loads(latest["content_json"])
                    preview = str(content.get("text") or content.get("summary") or preview).strip() or preview
                row["preview"] = " ".join(preview.split())[:180]
            return rows

    def _bump_work(self, connection, work_id: str, version: int):
        connection.execute("UPDATE works SET version=?, updated_at=? WHERE id=?", (version + 1, now(), work_id))

    def _check_thread_version(self, connection, work_id: str, thread_id: str, expected: int):
        thread = connection.execute(
            "SELECT * FROM conversation_threads WHERE id=? AND work_id=?", (thread_id, work_id)
        ).fetchone()
        if not thread:
            raise NotFound("conversation_thread", thread_id)
        if thread["version"] != expected:
            raise DomainError(
                "thread_conflict", "对话已在其他位置更新，请刷新后重试。", status=409,
                details={"expected_version": expected, "actual_version": thread["version"]},
            )
        return thread

    def _conversation_policy(self, connection, thread, *, retry: bool = False) -> dict:
        if thread["status"] != "active":
            raise DomainError("agent_thread_archived", "请先恢复归档对话，再继续运行 Agent。", status=409)
        row = connection.execute(
            "SELECT * FROM authorization_policies WHERE thread_id=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
            (thread["id"],),
        ).fetchone()
        if not row:
            raise DomainError("agent_policy_inactive", "当前对话没有有效的 Agent 授权。", status=403)
        policy = dict(row)
        expires_at = str(policy.get("expires_at") or "").strip()
        if expires_at:
            try:
                expired = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
            except ValueError as exc:
                raise DomainError("agent_policy_invalid", "Agent 授权的到期时间无效。", status=409) from exc
            if expired:
                raise DomainError("agent_policy_expired", "当前 Agent 授权已经到期。", status=403)
        try:
            actions = frozenset(json.loads(policy.get("allowed_actions_json") or "[]"))
        except json.JSONDecodeError as exc:
            raise DomainError("agent_policy_invalid", "Agent 授权操作列表无效。", status=409) from exc
        if "discuss" not in actions:
            raise DomainError("agent_action_denied", "当前 Agent 授权不允许继续讨论。", status=403)
        policy["allowed_actions"] = actions
        if not retry and policy.get("max_turns") is not None:
            used_turns = connection.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE thread_id=? AND role='user'",
                (thread["id"],),
            ).fetchone()[0]
            if used_turns >= int(policy["max_turns"]):
                raise DomainError(
                    "agent_turn_budget_exceeded",
                    "当前 Agent 授权轮次已用完，请切换为审核协作或重新授权。",
                    status=429,
                    details={"used_turns": used_turns, "max_turns": int(policy["max_turns"])},
                )
        if policy.get("max_cost") is not None:
            used_cost = connection.execute(
                """SELECT COALESCE(SUM(message.estimated_cost),0)
                   FROM conversation_messages AS message
                   WHERE message.thread_id=? AND message.role='assistant'""",
                (thread["id"],),
            ).fetchone()[0]
            if float(used_cost or 0) >= float(policy["max_cost"]):
                raise DomainError(
                    "agent_cost_budget_exceeded",
                    "当前 Agent 授权成本预算已经用完。",
                    status=429,
                    details={"used_cost": float(used_cost or 0), "max_cost": float(policy["max_cost"])},
                )
        return policy

    def _require_agent_policy_current(self, connection, work_id: str, thread_id: str, fixed_policy: dict):
        thread = connection.execute(
            "SELECT * FROM conversation_threads WHERE id=? AND work_id=?", (thread_id, work_id)
        ).fetchone()
        policy = connection.execute(
            "SELECT * FROM authorization_policies WHERE thread_id=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        changed = (
            not thread or thread["status"] != "active" or not policy
            or policy["id"] != fixed_policy.get("id")
            or int(policy["version"]) != int(fixed_policy.get("version", -1))
            or policy["mode"] != fixed_policy.get("mode")
            or thread["permission_mode"] != fixed_policy.get("mode")
        )
        if changed:
            raise DomainError(
                "agent_authorization_changed",
                "Agent 运行期间授权已变化，本轮已停止；不会按旧权限执行工具或创建候选。",
                status=409,
                details={"thread_id": thread_id},
            )
        return thread, self._conversation_policy(connection, thread, retry=True)

    def _cancel_agent_for_authorization_change(self, run_id: str, error: DomainError) -> None:
        failure = {"code": error.code, "type": type(error).__name__, "message": error.message}
        with self.repo.transaction() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='cancelled',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                (canonical_json(failure), now(), run_id),
            )

    @contextmanager
    def _authorized_agent_result_transaction(
        self, run_id: str, work_id: str, thread_id: str, fixed_policy: dict
    ):
        try:
            with self.repo.transaction() as connection:
                self._require_agent_policy_current(connection, work_id, thread_id, fixed_policy)
                yield connection
        except DomainError as exc:
            if exc.code == "agent_authorization_changed":
                self._cancel_agent_for_authorization_change(run_id, exc)
            raise

    def create_conversation_thread(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        scope_type = str(payload.get("scope_type", "work")).strip() or "work"
        scope_id = str(payload.get("scope_id", work_id)).strip() or work_id
        title = str(payload.get("title", "新对话")).strip() or "新对话"
        permission_mode = str(payload.get("permission_mode", "review")).strip() or "review"
        if scope_type not in {"work", "chapter", "scene"}:
            raise DomainError("validation_error", "对话作用域无效。", details={"field": "scope_type"})
        if permission_mode not in {"review", "managed"}:
            raise DomainError("validation_error", "Agent 授权模式无效。", details={"field": "permission_mode"})
        if len(title) > 80:
            raise DomainError("validation_error", "对话名称不能超过 80 个字符。", details={"field": "title"})
        thread_id = new_id("thread")
        timestamp = now()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            if scope_type == "work":
                scope_id = work_id
            elif scope_type == "chapter" and not connection.execute(
                "SELECT 1 FROM chapters WHERE id=? AND work_id=?", (scope_id, work_id)
            ).fetchone():
                raise NotFound("chapter", scope_id)
            elif scope_type == "scene" and not connection.execute(
                "SELECT 1 FROM scenes WHERE id=? AND work_id=?", (scope_id, work_id)
            ).fetchone():
                raise NotFound("scene", scope_id)
            connection.execute(
                "INSERT INTO conversation_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (thread_id, work_id, scope_type, scope_id, title, "active", "discuss", permission_mode, 1, "{}", 0, timestamp, timestamp),
            )
            allowed = ["read", "discuss"]
            if permission_mode == "managed":
                allowed.append("auto_create_low_risk_proposal")
            connection.execute(
                "INSERT INTO authorization_policies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("policy"), work_id, thread_id, scope_type, scope_id, permission_mode,
                 canonical_json(allowed), 12 if permission_mode == "managed" else None,
                 None, None, "active", 1, timestamp, timestamp),
            )
            self._append_conversation_message(
                connection, thread_id, "assistant", "notice",
                {"text": "新的讨论已经建立。我会读取当前作品的正式上下文，但不会把其他对话当作已经确认的事实。"},
            )
            self._bump_work(connection, work_id, version)
        return {"thread_id": thread_id, "work": self.get_work(work_id)}

    def update_conversation_thread(self, work_id: str, thread_id: str, payload: dict):
        expected = int(payload.get("expected_thread_version", -1))
        with self.repo.transaction() as connection:
            thread = self._check_thread_version(connection, work_id, thread_id, expected)
            title = str(payload.get("title", thread["title"])).strip() or thread["title"]
            status = str(payload.get("status", thread["status"])).strip() or thread["status"]
            if len(title) > 80:
                raise DomainError("validation_error", "对话名称不能超过 80 个字符。", details={"field": "title"})
            if status not in {"active", "archived"}:
                raise DomainError("validation_error", "对话状态无效。", details={"field": "status"})
            timestamp = now()
            connection.execute(
                "UPDATE conversation_threads SET title=?,status=?,version=version+1,updated_at=? WHERE id=?",
                (title, status, timestamp, thread_id),
            )
            connection.execute(
                "UPDATE authorization_policies SET status=?,version=version+1,updated_at=? WHERE thread_id=?",
                ("active" if status == "active" else "archived", timestamp, thread_id),
            )
        return {"thread_id": thread_id, "work": self.get_work(work_id)}

    @staticmethod
    def _validate_image_signature(media_type: str, content: bytes) -> bool:
        if media_type == "image/png":
            return content.startswith(b"\x89PNG\r\n\x1a\n")
        if media_type == "image/jpeg":
            return content.startswith(b"\xff\xd8\xff")
        if media_type == "image/gif":
            return content.startswith((b"GIF87a", b"GIF89a"))
        if media_type == "image/webp":
            return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
        return False

    @staticmethod
    def _normalize_document_text(text: str) -> tuple[str, int, bool]:
        return normalize_text(text)

    @classmethod
    def _extract_document_text(cls, suffix: str, content: bytes) -> tuple[str, int, bool]:
        try:
            if suffix in {".txt", ".md"}:
                for encoding in ("utf-8-sig", "gb18030"):
                    try:
                        text = content.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    raise DomainError("document_encoding_unsupported", "文本文件必须使用 UTF-8 或 GB18030 编码。", status=415)
            elif suffix == ".docx":
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    try:
                        document_info = archive.getinfo("word/document.xml")
                    except KeyError as exc:
                        raise DomainError("attachment_type_mismatch", "文件不是有效的 DOCX 文档。", status=415) from exc
                    if document_info.file_size > 8_000_000:
                        raise DomainError("document_too_complex", "DOCX 解压后的正文过大，无法安全读取。", status=413)
                    root = ElementTree.fromstring(archive.read(document_info))
                    paragraphs = []
                    for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                        line = "".join(
                            node.text or ""
                            for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                        ).strip()
                        if line:
                            paragraphs.append(line)
                    text = "\n\n".join(paragraphs)
            elif suffix == ".pdf":
                if not content.startswith(b"%PDF-"):
                    raise DomainError("attachment_type_mismatch", "文件不是有效的 PDF 文档。", status=415)
                try:
                    from pypdf import PdfReader
                except ImportError as exc:
                    raise DomainError("document_parser_unavailable", "当前服务缺少 PDF 文本解析组件。", status=503) from exc
                reader = PdfReader(io.BytesIO(content))
                if len(reader.pages) > 200:
                    raise DomainError("document_too_complex", "PDF 超过 200 页，请拆分后上传。", status=413)
                text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
            else:
                raise DomainError("unsupported_attachment_type", "不支持这种文档格式。", status=415)
        except DomainError:
            raise
        except (zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise DomainError("attachment_type_mismatch", "文档内容与声明格式不一致。", status=415) from exc
        except Exception as exc:
            raise DomainError("document_parse_failed", "文档文字提取失败，请检查文件是否损坏或加密。", status=422) from exc
        normalized, original_characters, truncated = cls._normalize_document_text(text)
        if not normalized:
            raise DomainError("document_text_empty", "没有提取到可读文字；扫描版 PDF 需要先进行 OCR。", status=422)
        return normalized, original_characters, truncated

    def _attachment_for_agent(self, attachment: dict) -> dict:
        result = {
            key: attachment[key]
            for key in ("id", "filename", "media_type", "byte_size", "status")
            if key in attachment
        }
        result["kind"] = "image" if str(attachment.get("media_type", "")).startswith("image/") else "document"
        if result["kind"] == "document":
            result["index_version"] = "document-chunks/1.0"
            result["context_policy"] = "task_relevant_retrieval"
        return result

    def create_conversation_attachment(self, work_id: str, thread_id: str, payload: dict):
        expected = int(payload.get("expected_thread_version", -1))
        filename = Path(str(payload.get("filename", "attachment"))).name[:120] or "attachment"
        media_type = str(payload.get("media_type", "")).strip().lower()
        encoded = str(payload.get("content_base64", ""))
        image_types = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
        document_types = {
            ".txt": {"", "text/plain"},
            ".md": {"", "text/plain", "text/markdown", "text/x-markdown"},
            ".pdf": {"", "application/pdf"},
            ".docx": {"", "application/zip", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        }
        suffix = Path(filename).suffix.lower()
        is_image = media_type in image_types
        is_document = suffix in document_types and media_type in document_types[suffix]
        if not is_image and not is_document:
            raise DomainError("unsupported_attachment_type", "支持 PNG、JPEG、WebP、GIF、TXT、Markdown、PDF 或 DOCX。", status=415)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DomainError("invalid_attachment", "附件内容不是有效的 Base64 数据。") from exc
        byte_limit = 5_000_000 if is_image else 10_000_000
        if not content or len(content) > byte_limit:
            limit_label = "5 MB" if is_image else "10 MB"
            raise DomainError("attachment_too_large", f"附件必须小于 {limit_label}。", status=413)
        if is_image and not self._validate_image_signature(media_type, content):
            raise DomainError("attachment_type_mismatch", "图片内容与声明格式不一致。", status=415)
        extracted_text = None
        if is_document:
            extracted_text, _, _ = self._extract_document_text(suffix, content)
        attachment_id = new_id("attachment")
        stored_suffix = image_types[media_type] if is_image else suffix
        with self.repo.transaction() as connection:
            self._check_thread_version(connection, work_id, thread_id, expected)
            uri, digest = self.repo.atomic_write_bytes(
                f"attachments/{work_id}/{attachment_id}{stored_suffix}", content
            )
            if extracted_text is not None:
                self.repo.atomic_write_text(uri + ".extracted.txt", extracted_text)
            timestamp = now()
            connection.execute(
                "INSERT INTO conversation_attachments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (attachment_id, work_id, thread_id, None, filename, media_type, uri, digest, len(content), "staged", timestamp),
            )
            if extracted_text is not None:
                index_attachment(
                    connection,
                    {"id": attachment_id, "work_id": work_id, "thread_id": thread_id},
                    extracted_text,
                )
            connection.execute(
                "UPDATE conversation_threads SET version=version+1,updated_at=? WHERE id=?",
                (timestamp, thread_id),
            )
        return {"attachment_id": attachment_id, "work": self.get_work(work_id)}

    def get_conversation_attachment(self, work_id: str, attachment_id: str):
        with self.repo.connect() as connection:
            row = connection.execute(
                "SELECT media_type,content_uri FROM conversation_attachments WHERE id=? AND work_id=?",
                (attachment_id, work_id),
            ).fetchone()
        if not row:
            raise NotFound("conversation_attachment", attachment_id)
        path = (self.repo.data_dir / row["content_uri"]).resolve()
        if self.repo.data_dir not in path.parents or not path.is_file():
            raise NotFound("conversation_attachment", attachment_id)
        return row["media_type"], path.read_bytes()

    def post_conversation_message(self, work_id: str, thread_id: str, payload: dict):
        expected = int(payload.get("expected_thread_version", -1))
        text = str(payload.get("text", "")).strip()
        if not text:
            raise DomainError("validation_error", "消息不能为空。", details={"field": "text"})
        decision_response = self._validate_decision_response(payload.get("decision_response"))
        retry_snapshot = payload.get("_retry_snapshot") if isinstance(payload.get("_retry_snapshot"), dict) else None
        attachment_ids = payload.get("attachment_ids", [])
        if retry_snapshot:
            attachment_ids = []
        if not isinstance(attachment_ids, list) or len(attachment_ids) > 4:
            raise DomainError("validation_error", "每条消息最多附带 4 个附件。", details={"field": "attachment_ids"})
        attachment_ids = [str(item).strip() for item in attachment_ids if str(item).strip()]
        retry_of = str(payload.get("retry_of") or "").strip() or None
        redirect_of = str(payload.get("redirect_of") or "").strip() or None
        run_id = new_id("agent")
        expected_provider = payload.get("_expected_provider")
        if not isinstance(expected_provider, dict) and retry_snapshot:
            expected_provider = retry_snapshot.get("provider_runtime")
        provider, provider_runtime = self._capture_provider(expected_provider)

        # Persist the fixed input and running state before any network call.
        with self.repo.transaction() as connection:
            thread = self._check_thread_version(connection, work_id, thread_id, expected)
            active = self._active_conversation_run(connection, work_id, thread_id)
            if active:
                raise DomainError(
                    "agent_run_active", "当前对话仍有一轮 Agent 在运行。", status=409,
                    details={"agent_run_id": active["id"]},
                )
            policy = self._conversation_policy(connection, thread, retry=bool(retry_snapshot))
            if retry_snapshot:
                history = retry_snapshot.get("history") if isinstance(retry_snapshot.get("history"), list) else []
                task_contract = retry_snapshot.get("task_contract") if isinstance(retry_snapshot.get("task_contract"), dict) else None
                if not history or not task_contract:
                    raise DomainError("agent_retry_context_missing", "失败运行缺少固定历史或任务契约。", status=409)
                attachments = retry_snapshot.get("attachments") if isinstance(retry_snapshot.get("attachments"), list) else []
                attachments = [
                    {key: item[key] for key in ("id", "filename", "media_type", "byte_size", "status", "kind", "index_version", "context_policy") if key in item}
                    for item in attachments if isinstance(item, dict)
                ]
                document_context = retry_snapshot.get("document_context") if isinstance(retry_snapshot.get("document_context"), dict) else None
                scene_memory_context = retry_snapshot.get("scene_memory_context") if isinstance(retry_snapshot.get("scene_memory_context"), dict) else None
                scene_conversation_context = retry_snapshot.get("scene_conversation_context") if isinstance(retry_snapshot.get("scene_conversation_context"), dict) else None
                conversation_summary = retry_snapshot.get("conversation_summary") if isinstance(retry_snapshot.get("conversation_summary"), dict) else {}
                validate_conversation_summary(
                    connection,
                    thread_id,
                    conversation_summary,
                    pinned=True,
                )
                first_idea = next((str(item.get("text") or "") for item in history if item.get("role") == "user"), text)
            else:
                attachments = []
                for attachment_id in attachment_ids:
                    attachment = connection.execute(
                        "SELECT id,filename,media_type,byte_size,status,content_uri FROM conversation_attachments WHERE id=? AND work_id=? AND thread_id=?",
                        (attachment_id, work_id, thread_id),
                    ).fetchone()
                    if not attachment or attachment["status"] != "staged":
                        raise DomainError(
                            "invalid_attachment", "附件不存在、已使用或不属于当前对话。", status=409,
                            details={"id": attachment_id},
                        )
                    attachments.append(self._attachment_for_agent(dict(attachment)))
                message_attachments = [
                    {key: item[key] for key in ("id", "filename", "media_type", "byte_size", "status", "kind") if key in item}
                    for item in attachments
                ]
                request_source = str(payload.get("request_source") or "user").strip()
                if request_source not in {"user", "scene_memory_action", "intent"}:
                    raise DomainError("validation_error", "对话请求来源无效。", details={"field": "request_source"})
                user_message_id = self._append_conversation_message(
                    connection, thread_id, "user", "text",
                    {
                        "text": text,
                        "attachments": message_attachments,
                        "retry_of": retry_of,
                        "redirect_of": redirect_of,
                        "request_source": request_source,
                        **({"decision_response": decision_response} if decision_response else {}),
                    },
                    agent_run_id=run_id,
                )
                if attachment_ids:
                    connection.executemany(
                        "UPDATE conversation_attachments SET message_id=?,status='attached' WHERE id=?",
                        [(user_message_id, attachment_id) for attachment_id in attachment_ids],
                    )
                history = recent_conversation_history(connection, thread_id)
                conversation_summary = self._conversation_summary(connection, thread_id)
                first_user = connection.execute(
                    """SELECT content_json FROM conversation_messages
                       WHERE thread_id=? AND role='user' ORDER BY ordinal LIMIT 1""",
                    (thread_id,),
                ).fetchone()
                first_idea = (
                    json.loads(first_user["content_json"]).get("text", text)
                    if first_user else text
                )
                effective_scope = self._effective_conversation_scope(thread, payload.get("task_scope"))
                task_contract = self._conversation_task_contract(connection, work_id, effective_scope)
                scene_memory_context = self._scene_memory_context(connection, work_id, task_contract)
                scene_conversation_context = self._scene_conversation_context(connection, work_id, task_contract)
                document_context = retrieve_context(
                    self.repo, connection, work_id, thread_id, text, attachment_ids
                )
            provider_context = {
                "work_id": work_id,
                "idea": first_idea,
                "task_contract": task_contract,
                "conversation_summary": conversation_summary,
                "attachments": attachments,
                "document_context": document_context,
            }
            if scene_memory_context:
                provider_context["scene_memory_context"] = scene_memory_context
            if scene_conversation_context:
                provider_context["scene_conversation_context"] = scene_conversation_context
            if document_context:
                provider_context["document_skill"] = DOCUMENT_SKILL
            snapshot = {
                "schema_version": "conversation-agent-input/1.2",
                "work_id": work_id,
                "thread_id": thread_id,
                "scope": {"type": thread["scope_type"], "id": thread["scope_id"]},
                "instruction": text,
                "task_contract": task_contract,
                "history": history,
                "conversation_summary": conversation_summary,
                "attachments": attachments,
                "document_context": document_context,
                "document_skill": DOCUMENT_SKILL if document_context else None,
                "scene_memory_context": scene_memory_context,
                "scene_conversation_context": scene_conversation_context,
                "permission_mode": thread["permission_mode"],
                "allowed_actions": sorted(policy["allowed_actions"]),
                "provider_runtime": provider_runtime,
                "retry_of": retry_of,
                "redirect_of": redirect_of,
            }
            snapshot_uri, input_digest = self.repo.atomic_write_text(
                f"agent-runs/{run_id}/input.json",
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            )
            timestamp = now()
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id, work_id, thread["scope_type"], thread["scope_id"], text, "running",
                    canonical_json({
                        "mode": thread["permission_mode"], "phase": thread["phase"],
                        "thread_id": thread_id,
                        "task_id": task_contract.get("id"), "write_boundary": "proposal_only",
                        "provider_runtime": provider_runtime,
                        "retry_of": retry_of, "redirect_of": redirect_of, "usage": {},
                    }),
                    snapshot_uri, input_digest, None, None, timestamp, None,
                ),
            )
            connection.execute(
                "UPDATE conversation_threads SET version=version+1,updated_at=? WHERE id=?",
                (timestamp, thread_id),
            )
            thread_snapshot = dict(thread)
            policy_snapshot = dict(policy)

        on_started = payload.get("_run_started_callback")
        if callable(on_started):
            on_started(run_id)

        provider_failure = None
        usage = {}
        tool_results = []
        try:
            with self._provider_lock:
                if not self._agent_run_is_running(run_id):
                    return {
                        "thread_id": thread_id, "agent_run_id": run_id,
                        "simulation": provider.is_simulation, "cancelled": True,
                        "work": self.get_work(work_id),
                    }
                reply = self._validate_discussion_reply(
                    provider.discuss_work(history, provider_context)
                )
                usage = self._provider_usage(provider)
        except Exception as exc:
            provider_failure = {
                "code": getattr(exc, "code", "provider_failed"),
                "type": type(exc).__name__,
                "message": getattr(exc, "message", "模型未能完成本轮对话。"),
            }
            failure_details = getattr(exc, "details", {})
            if isinstance(failure_details, dict) and failure_details.get("failure_kind"):
                provider_failure["failure_kind"] = failure_details["failure_kind"]
            reply = {
                "text": "本轮模型调用失败，没有生成候选，也没有修改任何正式资料。你可以检查模型设置后重试。",
                "questions": [], "ready_for_proposal": False,
                "reasoning_summary": "模型调用失败；服务保留了本轮输入与失败记录，正式资料保持不变。",
                "tool_activity": [{"tool": "provider_call", "label": "调用写作模型", "status": "failed"}],
            }

        if not self._agent_run_is_running(run_id):
            return {
                "thread_id": thread_id, "agent_run_id": run_id,
                "simulation": provider.is_simulation, "cancelled": True,
                "work": self.get_work(work_id),
            }

        if attachments:
            image_count = sum(item.get("kind") == "image" for item in attachments)
            document_count = sum(item.get("kind") == "document" for item in attachments)
            if image_count:
                reply["text"] += (
                    " 图片已随本轮保存；当前 Provider 不具备视觉理解能力，因此没有声称读取图片内容。"
                    if provider.is_simulation else " 图片已随本轮固定保存。"
                )
            if document_count:
                reply["text"] += (
                    " 文档文字已提取并固定到本轮上下文；当前为模拟 Provider，没有冒充完成语义分析。"
                    if provider.is_simulation else " 文档文字已提取并提供给本轮模型上下文。"
                )
            output_parts = []
            if image_count:
                output_parts.append(f"{image_count} 张图片")
            if document_count:
                output_parts.append(f"{document_count} 份文档")
            reply.setdefault("tool_activity", []).append({
                "tool": "store_conversation_attachments", "label": "保存对话附件",
                "status": "succeeded", "output": " · ".join(output_parts),
            })

        if not provider_failure:
            try:
                with self.repo.connect() as connection:
                    current_thread, current_policy = self._require_agent_policy_current(
                        connection, work_id, thread_id, policy_snapshot
                    )
                    tool_results = self._dispatch_agent_tools(
                        connection, work_id, thread_id, current_thread, history, task_contract, reply,
                        policy=current_policy, attachment_count=len(attachments),
                    )
            except DomainError as exc:
                if exc.code == "agent_authorization_changed":
                    self._cancel_agent_for_authorization_change(run_id, exc)
                raise
            if not provider.is_simulation and reply.get("tool_calls"):
                initial_reply = reply
                try:
                    with self._provider_lock:
                        if not self._agent_run_is_running(run_id):
                            return {
                                "thread_id": thread_id, "agent_run_id": run_id,
                                "simulation": provider.is_simulation, "cancelled": True,
                                "work": self.get_work(work_id),
                            }
                        followup = self._validate_discussion_reply(
                            provider.discuss_work(
                                history,
                                {**provider_context, "tool_followup": True, "tool_results": initial_reply.get("tool_results", [])},
                            )
                        )
                        usage = self._merge_usage(usage, self._provider_usage(provider))
                    followup["tool_activity"] = initial_reply.get("tool_activity", [])
                    followup["tool_results"] = initial_reply.get("tool_results", [])
                    if initial_reply.get("artifact_preview") and not followup.get("artifact_preview"):
                        followup["artifact_preview"] = initial_reply["artifact_preview"]
                    reply = followup
                except Exception as exc:
                    provider_failure = {
                        "code": getattr(exc, "code", "provider_failed"),
                        "type": type(exc).__name__,
                        "message": getattr(exc, "message", "模型未能根据工具结果完成本轮对话。"),
                    }
                    reply = {
                        **initial_reply,
                        "text": "工具已经按权限执行，但模型未能根据结果完成回复；正式资料没有改变。",
                        "ready_for_proposal": False,
                        "reasoning_summary": "工具执行结果已保存，模型后续回复失败，可从本轮运行记录重试。",
                    }

        if not self._agent_run_is_running(run_id):
            return {
                "thread_id": thread_id, "agent_run_id": run_id,
                "simulation": provider.is_simulation, "cancelled": True,
                "work": self.get_work(work_id),
            }

        if document_context:
            citations = document_context.get("citations") if isinstance(document_context.get("citations"), list) else []
            preview = reply.get("artifact_preview") if isinstance(reply.get("artifact_preview"), dict) else None
            if preview and preview.get("kind") in {"character_card", "world_card", "world_rule", "canon_fact"}:
                preview["sources"] = [
                    {
                        key: citation[key]
                        for key in (
                            "attachment_id", "filename", "chunk_id", "paragraph_ids",
                            "display_label", "quote", "content_hash",
                        )
                        if key in citation
                    }
                    for citation in citations
                    if isinstance(citation, dict)
                ]
            reply["document_context"] = {
                key: document_context[key]
                for key in (
                    "schema_version", "index_version", "query", "strategy", "selected_characters",
                    "max_characters", "trust", "write_boundary", "explanation",
                )
                if key in document_context
            }
            reply["citations"] = citations
            reply.setdefault("tool_activity", []).append({
                "tool": "document.retrieve",
                "label": "检索相关文档片段",
                "status": "succeeded",
                "output": f"{len(citations)} 个片段 · {document_context.get('selected_characters', 0)} 字符",
            })

        reply = self._finalize_agent_reply(task_contract, reply, provider)
        failed_tools = [item for item in tool_results if item.status == "failed"]
        denied_tools = [item for item in tool_results if item.status == "denied"]
        waiting_tools = [item for item in tool_results if item.status in {"waiting_user", "blocked"}]
        tool_failure = None
        if failed_tools:
            tool_failure = {
                "code": "agent_tool_failed",
                "message": "Agent 工具执行失败；本轮没有形成可提交候选。",
                "tools": [
                    {"tool": item.tool, "status": item.status, "error": item.error}
                    for item in failed_tools
                ],
            }
        elif denied_tools:
            tool_failure = {
                "code": "agent_tool_denied",
                "message": "Agent 工具调用不在当前授权范围内；本轮已停止。",
                "tools": [
                    {"tool": item.tool, "status": item.status, "error": item.error}
                    for item in denied_tools
                ],
            }
        if provider_failure:
            reply["agent_trace"]["status"] = "failed"
            reply["agent_trace"]["outcome"] = "模型调用失败；本轮没有生成候选，也没有写入正式资料。"
        elif tool_failure:
            reply.pop("artifact_preview", None)
            reply["ready_for_proposal"] = False
            reply["agent_trace"]["status"] = "failed" if failed_tools else "blocked"
            reply["agent_trace"]["outcome"] = tool_failure["message"]
        run_status = (
            "failed" if provider_failure or failed_tools
            else "blocked" if denied_tools
            else "waiting_user" if reply.get("ready_for_proposal") or reply.get("artifact_preview") or waiting_tools
            else "completed"
        )
        auto_propose_kind = None
        if not provider_failure and not tool_failure and thread_snapshot["permission_mode"] == "managed" and isinstance(reply.get("artifact_preview"), dict):
            preview_kind = reply["artifact_preview"].get("kind")
            if preview_kind in {"character_card", "world_card", "world_rule", "canon_fact"}:
                auto_propose_kind = preview_kind

        with self._authorized_agent_result_transaction(
            run_id, work_id, thread_id, policy_snapshot
        ) as connection:
            current_run = connection.execute("SELECT status FROM agent_runs WHERE id=?", (run_id,)).fetchone()
            if not current_run:
                raise DomainError("agent_run_missing", "Agent 运行记录不存在。", status=409)
            if current_run["status"] != "running":
                raise DomainError("agent_run_interrupted", "Agent 运行已被中断，不能覆盖其状态。", status=409)
            timestamp = now()
            for ordinal, result in enumerate(tool_results, start=1):
                activity = result.activity()
                status = str(activity.get("status") or "succeeded")
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("tool"), run_id, ordinal, result.tool, status,
                        result.input_digest or input_digest,
                        str(activity.get("output") or "").strip() or None,
                        canonical_json(result.error) if result.error else None,
                        timestamp, now() if status in {"succeeded", "failed", "waiting_user", "blocked", "denied"} else None,
                    ),
                )
            assistant_message_id = self._append_conversation_message(
                connection, thread_id, "assistant", "discussion", reply,
                provider=provider.descriptor(), agent_run_id=run_id, usage=usage,
            )
            connection.execute(
                "UPDATE agent_runs SET status=?,policy_json=?,failure_json=?,finished_at=? WHERE id=?",
                (
                    run_status,
                    canonical_json({
                        "mode": thread_snapshot["permission_mode"], "phase": thread_snapshot["phase"],
                        "thread_id": thread_id,
                        "task_id": task_contract.get("id"), "write_boundary": "proposal_only",
                        "provider_runtime": provider_runtime,
                        "retry_of": retry_of, "usage": usage,
                    }),
                    canonical_json(provider_failure or tool_failure) if provider_failure or tool_failure else None,
                    timestamp, run_id,
                ),
            )

        if provider_failure:
            raise DomainError(
                "agent_failed", "写作 Agent 未能完成本轮对话，失败记录已保存。", status=502,
                details={"agent_run_id": run_id, "failure": provider_failure},
            )
        if failed_tools:
            raise DomainError(
                "agent_tool_failed", "写作 Agent 的工具执行失败，失败记录已保存。", status=502,
                details={"agent_run_id": run_id, "failure": tool_failure},
            )
        if auto_propose_kind:
            current = self.get_work(work_id)
            current_thread = next(item for item in current["conversation_threads"] if item["id"] == thread_id)
            proposed = self.propose_conversation_knowledge(
                work_id, thread_id,
                {
                    "expected_version": current["version"],
                    "expected_thread_version": current_thread["version"],
                    "kind": auto_propose_kind,
                    "preview_message_id": assistant_message_id,
                    "agent_run_id": run_id,
                },
            )
            return {
                "thread_id": thread_id, "assistant_message_id": assistant_message_id,
                "agent_run_id": run_id, "simulation": provider.is_simulation,
                "auto_proposal_id": proposed["proposal_id"], "work": proposed["work"],
            }
        return {
            "thread_id": thread_id, "assistant_message_id": assistant_message_id,
            "agent_run_id": run_id, "simulation": provider.is_simulation,
            "work": self.get_work(work_id),
        }

    def generate_scene_proposal_from_conversation(self, work_id: str, thread_id: str, payload: dict):
        """Turn one persisted scene discussion into a reviewable scene Proposal."""
        expected_version = int(payload.get("expected_version", -1))
        expected_thread_version = int(payload.get("expected_thread_version", -1))
        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected_version)
            thread = self._check_thread_version(
                connection, work_id, thread_id, expected_thread_version
            )
            self._conversation_policy(connection, thread, retry=True)
            if thread["scope_type"] != "scene":
                raise DomainError(
                    "scene_conversation_required",
                    "只有绑定到具体场景的对话才能整理场景正文 Proposal。",
                    status=409,
                )
            task_contract = self._conversation_task_contract(
                connection,
                work_id,
                self._effective_conversation_scope(thread, None),
            )
            scene_context = self._scene_conversation_context(
                connection, work_id, task_contract
            )
            history = recent_conversation_history(connection, thread_id)
            conversation_summary = self._conversation_summary(connection, thread_id)

        user_messages = [
            {
                "message_id": item["id"],
                "text": " ".join(str(item.get("text") or "").split())[:2000],
            }
            for item in history
            if item.get("role") == "user" and str(item.get("text") or "").strip()
        ][-8:]
        if not user_messages:
            raise DomainError(
                "scene_conversation_empty",
                "请先在本场对话中说明写作目标或修改约束。",
                status=409,
            )
        discussion_constraints = {
            "schema_version": "scene-conversation-constraints/1.0",
            "thread_id": thread_id,
            "scene_id": thread["scope_id"],
            "messages": user_messages,
            "summary": conversation_summary,
            "write_boundary": "这些内容只约束候选生成；不得直接写回正式正文。",
        }
        instruction = (
            "根据本场持久化讨论形成一份可审查的正文候选。"
            "必须综合以下按时间排序的作者约束，并以较新的明确要求为准；"
            "未被后续消息否定的约束继续保留：\n"
            + "\n".join(f"- {item['text']}" for item in user_messages)
        )
        agent_payload = {
            "expected_version": expected_version,
            "instruction": instruction,
            "discussion_constraints": discussion_constraints,
            "scene_conversation_context": scene_context,
        }
        if task_contract["id"] == "scene.draft.rewrite":
            if "selection" in payload:
                agent_payload["selection"] = payload.get("selection")
            result = self.run_scene_rewrite_agent(
                work_id, thread["scope_id"], agent_payload
            )
        else:
            result = self.run_scene_agent(work_id, thread["scope_id"], agent_payload)

        with self.repo.transaction() as connection:
            current_thread = self._check_thread_version(
                connection, work_id, thread_id, expected_thread_version
            )
            proposal = connection.execute(
                "SELECT id,status,scope_type,scope_id FROM proposals WHERE id=? AND work_id=?",
                (result["proposal_id"], work_id),
            ).fetchone()
            agent_run = connection.execute(
                "SELECT id,scope_type,scope_id FROM agent_runs WHERE id=? AND work_id=?",
                (result["agent_run_id"], work_id),
            ).fetchone()
            if (
                not proposal
                or proposal["scope_type"] != "scene"
                or proposal["scope_id"] != current_thread["scope_id"]
                or not agent_run
                or agent_run["scope_type"] != "scene"
                or agent_run["scope_id"] != current_thread["scope_id"]
            ):
                raise DomainError(
                    "scene_proposal_link_invalid",
                    "生成结果与本场对话的作用域不一致。",
                    status=409,
                )
            assistant_message_id = self._append_conversation_message(
                connection,
                thread_id,
                "assistant",
                "notice",
                {
                    "schema_version": "scene-conversation-proposal-link/1.0",
                    "text": "已根据本场最近讨论生成正文 Proposal，正式正文尚未改变，等待用户审查。",
                    "task_contract": task_contract,
                    "discussion_constraints": discussion_constraints,
                    "proposal": {
                        "id": proposal["id"],
                        "status": proposal["status"],
                        "scope_type": proposal["scope_type"],
                        "scope_id": proposal["scope_id"],
                    },
                    "write_boundary": "Proposal 被用户采纳前，不得修改正式正文。",
                },
                provider=self.provider.descriptor(),
                proposal_id=result["proposal_id"],
                agent_run_id=result["agent_run_id"],
            )
            connection.execute(
                "UPDATE conversation_threads SET version=version+1,updated_at=? WHERE id=?",
                (now(), thread_id),
            )
        return {
            "thread_id": thread_id,
            "assistant_message_id": assistant_message_id,
            "agent_run_id": result["agent_run_id"],
            "proposal_id": result["proposal_id"],
            "simulation": result["simulation"],
            "work": self.get_work(work_id),
        }

    def _dispatch_agent_tools(
        self, connection, work_id: str, thread_id: str, thread, history: list[dict],
        task_contract: dict, reply: dict, *, policy: dict | None = None,
        attachment_count: int = 0,
    ):
        """Resolve Provider tool intents through the server-side registry.

        Providers may return standard ``tool_calls`` or the legacy activity
        list. Both paths are validated here so an unknown or unauthorized tool
        can never silently become a successful step.
        """
        raw_calls = reply.get("tool_calls")
        standard_calls = isinstance(raw_calls, list) and bool(raw_calls)
        if not standard_calls:
            raw_calls = reply.get("tool_activity")
        if not isinstance(raw_calls, list) or not raw_calls:
            raw_calls = [{"tool": "load_workflow_template"}, {"tool": "read_work_context"}]
        context = ToolExecutionContext(
            connection=connection,
            service=self,
            work_id=work_id,
            thread_id=thread_id,
            scope_type=str(thread["scope_type"]),
            scope_id=str(thread["scope_id"]),
            permission_mode=str(thread["permission_mode"]),
            history=history,
            allowed_actions=frozenset((policy or {}).get("allowed_actions") or {"read", "discuss"}),
            policy_status=str((policy or {}).get("status") or "active"),
        )
        results = []
        activities = []
        tool_results = []
        for item in raw_calls[:12]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("tool") or item.get("name") or "").strip()
            if not name:
                continue
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            preview = reply.get("artifact_preview") if isinstance(reply.get("artifact_preview"), dict) else {}
            content = preview.get("content") if isinstance(preview.get("content"), dict) else {}
            if not standard_calls and name == "draft_character_card":
                arguments = {"name": preview.get("title") or content.get("name"), "summary": content.get("summary", "")}
            elif not standard_calls and name == "draft_world_card":
                arguments = {"name": preview.get("title") or content.get("name"), "summary": content.get("summary", "")}
            elif not standard_calls and name == "draft_world_rule":
                arguments = {"name": preview.get("title") or content.get("name"), "text": content.get("text", "")}
            elif not standard_calls and name == "draft_canon_fact":
                arguments = {"text": content.get("text", "")}
            elif not standard_calls and name == "store_conversation_attachments":
                # Provider replies need not echo the input attachments. Use
                # the server-fixed input count so the public tool timeline
                # cannot claim that a persisted document was dropped.
                arguments = {"count": int(attachment_count)}
            result = self.agent_tools.execute(context, name, arguments)
            if result.status == "succeeded" and result.tool.startswith("draft_") and not reply.get("artifact_preview"):
                reply["artifact_preview"] = result.output
            label = str(item.get("label") or "").strip()
            activity = result.activity()
            if label:
                activity["label"] = label
            activities.append(activity)
            tool_results.append({"id": item.get("id"), "tool": result.tool, "status": result.status, "output": result.output, "error": result.error})
            results.append(result)
        preview = reply.get("artifact_preview") if isinstance(reply.get("artifact_preview"), dict) else None
        executed = {item.tool for item in results}
        if preview and preview.get("kind") in {"character_card", "world_card", "world_rule", "canon_fact"} and "check_knowledge_conflicts" not in executed:
            content = preview.get("content") if isinstance(preview.get("content"), dict) else {}
            conflict_result = self.agent_tools.execute(
                context, "check_knowledge_conflicts", {"kind": preview["kind"], "content": content}
            )
            activity = conflict_result.activity()
            activities.append(activity)
            tool_results.append({"id": None, "tool": conflict_result.tool, "status": conflict_result.status, "output": conflict_result.output, "error": conflict_result.error})
            results.append(conflict_result)
            if conflict_result.status == "succeeded" and isinstance(conflict_result.output, dict):
                preview["conflicts"] = conflict_result.output.get("conflicts", [])
        reply["tool_activity"] = activities
        reply["tool_results"] = tool_results
        return results

    def _finalize_agent_reply(self, task_contract: dict, reply: dict, provider=None) -> dict:
        """Attach a durable, user-facing execution trace without storing hidden chain-of-thought."""
        reply = dict(reply or {})
        # Some SDKs expose a private reasoning channel. It is never part of the
        # writing-domain contract: only an explicit, user-facing summary may be
        # persisted or projected into the workbench.
        reply.pop("reasoning_content", None)
        reply["task_contract"] = task_contract
        activity = reply.get("tool_activity")
        if not isinstance(activity, list) or not activity:
            activity = [
                {"tool": "load_workflow_template", "label": "加载任务契约", "status": "succeeded"},
                {"tool": "read_work_context", "label": "读取作品上下文", "status": "succeeded"},
            ]

        normalized_activity = []
        allowed_statuses = {"queued", "running", "succeeded", "failed", "waiting_user", "blocked", "denied"}
        for item in activity[:12]:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool") or "agent_step").strip()[:80]
            label = str(item.get("label") or tool).strip()[:120]
            status = str(item.get("status") or "succeeded").strip()
            output = str(item.get("output") or "").strip()[:240]
            normalized_activity.append(
                {
                    "tool": tool,
                    "label": label,
                    "status": status if status in allowed_statuses else "succeeded",
                    "output": output,
                }
            )
        reply["tool_activity"] = normalized_activity

        task_id = str(task_contract.get("id") or "brief.build")
        default_summaries = {
            "brief.build": "先确认作品想法与关键不确定项，再决定是否需要人物、世界观或方向草稿。",
            "blueprint.generate": "结合当前讨论与正式资料，判断是否已经足够形成全作方向候选。",
            "structure.plan": "以已确认的全作方向为边界，检查卷、章与场景结构需要怎样推进。",
            "chapter.plan": "只处理当前章节的目标、节拍与承接点，不改写全作方向。",
            "scene.draft.generate": "读取当前场景边界后，只提出候选或 Diff，不直接覆盖正文。",
            "release.review": "核对连续性、人物一致性与未决伏笔，再决定是否允许冻结发布。",
        }
        provider_reasoning = str(reply.get("reasoning_summary") or "").strip()
        summary = str(provider_reasoning or default_summaries.get(task_id) or task_contract.get("task") or "确认当前任务范围并选择下一步。")
        summary = " ".join(summary.split())[:300]
        preview = reply.get("artifact_preview") if isinstance(reply.get("artifact_preview"), dict) else None
        if preview:
            kind_label = {
                "character_card": "人物卡",
                "world_card": "世界观卡",
                "canon_fact": "作品事实",
            }.get(preview.get("kind"), "资料")
            outcome = f"已形成{kind_label}讨论草稿；正式资料尚未改变。"
        elif reply.get("ready_for_proposal") or reply.get("ready_to_organize"):
            outcome = "现有讨论已经可以整理为 Proposal；是否写入正式产物仍由用户决定。"
        else:
            outcome = "继续讨论并补齐关键约束；本轮没有写入正式产物。"
        reply["agent_trace"] = {
            "schema_version": "agent-trace/1.0",
            "visibility": "user_summary",
            "status": "completed",
            "task_id": task_id,
            "task": str(task_contract.get("task") or "继续当前创作任务")[:240],
            "scope": task_contract.get("task_scope") or {},
            "summary": summary,
            "reasoning": {
                "available": bool(provider_reasoning),
                "source": "provider" if provider_reasoning else "system",
                "is_simulation": bool((provider or self.provider).is_simulation) if provider_reasoning else False,
                "mode": "summary",
                "summary": summary,
            },
            "steps": normalized_activity,
            "outcome": outcome,
        }
        return reply

    @staticmethod
    def _validate_discussion_reply(value: dict) -> dict:
        """Keep a malformed discussion response from becoming a false success."""
        if not isinstance(value, dict):
            raise DomainError(
                "provider_output_invalid",
                "作品讨论模型返回的不是结构化对象。",
                status=502,
            )
        result = dict(value)
        text = result.get("text")
        tool_calls = result.get("tool_calls")
        if text is not None and not isinstance(text, str):
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 text 必须是字符串。",
                status=502,
                details={"field": "text"},
            )
        if not isinstance(tool_calls, list) and text is None:
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复缺少 text 或 tool_calls。",
                status=502,
            )
        questions = result.get("questions", [])
        if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 questions 必须是字符串数组。",
                status=502,
                details={"field": "questions"},
            )
        decision_card = result.get("decision_card")
        if decision_card is not None:
            result["decision_card"] = WritingService._validate_decision_card(decision_card)
        if "ready_for_proposal" in result and not isinstance(result["ready_for_proposal"], bool):
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 ready_for_proposal 必须是布尔值。",
                status=502,
                details={"field": "ready_for_proposal"},
            )
        preview = result.get("artifact_preview")
        if preview is not None:
            if not isinstance(preview, dict) or preview.get("kind") not in {"character_card", "world_card", "world_rule", "canon_fact"}:
                raise DomainError(
                    "provider_output_invalid",
                    "作品讨论回复的资料草稿类型无效。",
                    status=502,
                    details={"field": "artifact_preview.kind"},
                )
        return result

    @staticmethod
    def _validate_decision_card(value: dict) -> dict:
        """Validate the small, user-facing choice surface returned by an Agent."""
        if not isinstance(value, dict):
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 decision_card 必须是对象。",
                status=502,
                details={"field": "decision_card"},
            )
        raw_kind = str(value.get("kind") or "choose").strip().lower()
        # Providers occasionally use the OpenAI/UI vocabulary "choice" or
        # "options" for an ordinary bounded choice.  Normalize only these
        # unambiguous aliases; confirmation and proposal cards keep their
        # explicit kinds so their existing write boundaries remain intact.
        kind = {
            "choice": "choose",
            "choices": "choose",
            "options": "choose",
            "select": "choose",
            "selection": "choose",
        }.get(raw_kind, raw_kind)
        if kind not in {"choose", "confirm", "proposal"}:
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 decision_card 类型无效。",
                status=502,
                details={"field": "decision_card.kind", "value": raw_kind},
            )
        title = str(value.get("title") or "下一步怎么继续？").strip()
        if not title or len(title) > 160:
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 decision_card 标题无效。",
                status=502,
                details={"field": "decision_card.title"},
            )
        raw_options = value.get("options")
        if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 6:
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 decision_card 需要 2 至 6 个选项。",
                status=502,
                details={"field": "decision_card.options"},
            )
        options = []
        option_ids = set()
        for index, item in enumerate(raw_options):
            if not isinstance(item, dict):
                raise DomainError(
                    "provider_output_invalid",
                    "作品讨论回复的 decision_card 选项无效。",
                    status=502,
                    details={"field": f"decision_card.options[{index}]"},
                )
            option_id = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()
            description = str(item.get("description") or "").strip()
            if not option_id or len(option_id) > 80 or option_id in option_ids:
                raise DomainError(
                    "provider_output_invalid",
                    "作品讨论回复的 decision_card 选项 ID 无效或重复。",
                    status=502,
                    details={"field": f"decision_card.options[{index}].id"},
                )
            if not label or len(label) > 120 or len(description) > 280:
                raise DomainError(
                    "provider_output_invalid",
                    "作品讨论回复的 decision_card 选项文字过长或为空。",
                    status=502,
                    details={"field": f"decision_card.options[{index}]"},
                )
            option_ids.add(option_id)
            options.append({"id": option_id, "label": label, "description": description})
        submit_label = str(value.get("submit_label") or "提交").strip()
        if not submit_label or len(submit_label) > 40:
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 decision_card 提交按钮文字无效。",
                status=502,
                details={"field": "decision_card.submit_label"},
            )
        allow_custom = value.get("allow_custom", False)
        if not isinstance(allow_custom, bool):
            raise DomainError(
                "provider_output_invalid",
                "作品讨论回复的 decision_card.allow_custom 必须是布尔值。",
                status=502,
                details={"field": "decision_card.allow_custom"},
            )
        return {
            "kind": kind,
            "title": title,
            "options": options,
            "submit_label": submit_label,
            "allow_custom": allow_custom,
        }

    @staticmethod
    def _validate_decision_response(value: dict | None) -> dict | None:
        """Keep a submitted choice auditable without letting it write an artifact."""
        if value is None:
            return None
        if not isinstance(value, dict):
            raise DomainError(
                "validation_error",
                "决策卡提交记录无效。",
                details={"field": "decision_response"},
            )
        message_id = str(value.get("message_id") or "").strip()
        option_id = str(value.get("option_id") or "").strip()
        label = str(value.get("label") or "").strip()
        if not message_id or len(message_id) > 120 or not option_id or len(option_id) > 80:
            raise DomainError(
                "validation_error",
                "决策卡提交缺少有效的选项信息。",
                details={"field": "decision_response"},
            )
        if not label or len(label) > 120:
            raise DomainError(
                "validation_error",
                "决策卡提交的选项文字无效。",
                details={"field": "decision_response.label"},
            )
        custom_text = str(value.get("custom_text") or "").strip()
        if len(custom_text) > 1000:
            raise DomainError(
                "validation_error",
                "决策卡补充说明过长。",
                details={"field": "decision_response.custom_text"},
            )
        return {
            "message_id": message_id,
            "option_id": option_id,
            "label": label,
            **({"custom_text": custom_text} if custom_text else {}),
        }

    def update_conversation_settings(self, work_id: str, thread_id: str, payload: dict):
        expected = int(payload.get("expected_thread_version", -1))
        permission_mode = str(payload.get("permission_mode", "review")).strip()
        phase = str(payload.get("phase", "discuss")).strip()
        if permission_mode not in {"review", "managed"}:
            raise DomainError("validation_error", "Agent 授权模式无效。", details={"field": "permission_mode"})
        if phase not in {"discuss", "execute"}:
            raise DomainError("validation_error", "Agent 状态无效。", details={"field": "phase"})
        with self.repo.transaction() as connection:
            self._check_thread_version(connection, work_id, thread_id, expected)
            timestamp = now()
            connection.execute(
                "UPDATE conversation_threads SET permission_mode=?,phase=?,version=version+1,updated_at=? WHERE id=?",
                (permission_mode, phase, timestamp, thread_id),
            )
            actions = ["read", "discuss"]
            if permission_mode == "managed":
                actions.append("auto_create_low_risk_proposal")
            connection.execute(
                "UPDATE authorization_policies SET mode=?,allowed_actions_json=?,max_turns=?,version=version+1,updated_at=? WHERE thread_id=? AND status='active'",
                (permission_mode, canonical_json(actions), 12 if permission_mode == "managed" else None, timestamp, thread_id),
            )
        return {"thread_id": thread_id, "work": self.get_work(work_id)}

    @staticmethod
    def _knowledge_key(value: str) -> str:
        return "".join(str(value or "").casefold().split()).strip("。！？,.，；;：:")

    def _revision_content(self, connection, revision_id: str | None) -> dict:
        if not revision_id:
            return {}
        revision = connection.execute(
            "SELECT content_uri FROM revisions WHERE id=?", (revision_id,)
        ).fetchone()
        return json.loads(self.repo.read_text(revision["content_uri"])) if revision else {}

    @staticmethod
    def _merge_knowledge_content(existing: dict, update: dict) -> dict:
        """Overlay explicit, non-empty Agent fields without erasing known data."""
        merged = dict(existing or {})
        for key, value in (update or {}).items():
            if value is None or value == "" or value == []:
                continue
            merged[key] = value
        return merged

    @staticmethod
    def _merge_source_refs(*collections) -> list:
        merged = []
        seen = set()
        for collection in collections:
            for item in collection or []:
                marker = canonical_json(item) if isinstance(item, (dict, list)) else str(item)
                if marker in seen:
                    continue
                seen.add(marker)
                merged.append(item)
        return merged

    @staticmethod
    def _knowledge_field_changes(before: dict, after: dict) -> list[dict]:
        """Build an author-readable diff while preserving the raw candidate fields."""
        labels = {
            "name": "名称", "canonical_name": "标准名称", "aliases": "别名",
            "summary": "摘要", "role": "故事职责", "voice_anchors": "声音锚点",
            "knowledge_boundary": "知情边界", "ooc_constraints": "OOC 红线",
            "relationships": "人物关系", "source_refs": "来源", "source_type": "来源类型",
            "trust_status": "可信状态", "kind": "类别", "source": "出处",
            "confidence_status": "可信状态", "scope": "作用域", "participants": "参与者",
            "related_world_ids": "关联设定", "text": "规则或事实内容", "exceptions": "例外条件", "status": "状态",
        }
        changes = []
        for key in [*labels, *sorted(set(after).difference(labels))]:
            if key == "id" or key not in before and key not in after:
                continue
            previous = before.get(key)
            current = after.get(key)
            if canonical_json(previous) == canonical_json(current):
                continue
            if key not in before and current in (None, "", [], {}):
                continue
            changes.append({"field": labels.get(key, key), "key": key, "before": previous, "after": current})
        return changes

    def _knowledge_conflicts(self, connection, work_id: str, requested_kind: str, content: dict) -> list[dict]:
        conflicts = []
        if requested_kind == "character_card":
            candidate_names = {self._knowledge_key(content.get("name")), self._knowledge_key(content.get("canonical_name"))}
            candidate_names.update(self._knowledge_key(item) for item in content.get("aliases", []))
            candidate_names.discard("")
            rows = connection.execute(
                "SELECT scope_id,current_revision_id FROM artifacts WHERE work_id=? AND kind='character_card' AND current_revision_id IS NOT NULL",
                (work_id,),
            ).fetchall()
            for row in rows:
                revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
                current = json.loads(self.repo.read_text(revision["content_uri"])) if revision else {}
                names = {self._knowledge_key(current.get("name")), self._knowledge_key(current.get("canonical_name"))}
                names.update(self._knowledge_key(item) for item in current.get("aliases", []))
                if candidate_names.intersection(names):
                    conflicts.append({
                        "kind": "existing_character_update",
                        "existing_id": row["scope_id"],
                        "existing_revision_id": row["current_revision_id"],
                        "label": current.get("name") or row["scope_id"],
                        "blocking": False,
                        "resolution": "update_existing",
                    })
        elif requested_kind == "world_card":
            candidate_names = {self._knowledge_key(content.get("name"))}
            candidate_names.update(self._knowledge_key(item) for item in content.get("aliases", []))
            rows = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='world_bible' AND current_revision_id IS NOT NULL",
                (work_id,),
            ).fetchall()
            for row in rows:
                revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
                bible = json.loads(self.repo.read_text(revision["content_uri"])) if revision else {}
                for item in bible.get("entities", []):
                    names = {self._knowledge_key(item.get("name"))}
                    names.update(self._knowledge_key(alias) for alias in item.get("aliases", []))
                    if candidate_names.intersection(names):
                        conflicts.append({
                            "kind": "existing_world_entity_update",
                            "existing_id": item.get("id"),
                            "existing_revision_id": row["current_revision_id"],
                            "label": item.get("name"),
                            "blocking": False,
                            "resolution": "update_existing",
                        })
        elif requested_kind == "world_rule":
            candidate_names = {
                self._knowledge_key(content.get("name")),
                self._knowledge_key(content.get("text")),
            }
            candidate_names.discard("")
            rows = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='world_bible' AND current_revision_id IS NOT NULL",
                (work_id,),
            ).fetchall()
            for row in rows:
                revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
                bible = json.loads(self.repo.read_text(revision["content_uri"])) if revision else {}
                for item in bible.get("rules", []):
                    names = {
                        self._knowledge_key(item.get("name")),
                        self._knowledge_key(item.get("text")),
                    }
                    names.discard("")
                    if candidate_names.intersection(names):
                        conflicts.append({
                            "kind": "existing_world_rule_update",
                            "existing_id": item.get("id"),
                            "existing_revision_id": row["current_revision_id"],
                            "label": item.get("name") or item.get("text"),
                            "blocking": False,
                            "resolution": "update_existing",
                        })
        else:
            candidate_key = self._knowledge_key(content.get("text"))
            candidate_id = str(content.get("id") or "").strip()
            rows = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='work_canon' AND current_revision_id IS NOT NULL",
                (work_id,),
            ).fetchall()
            for row in rows:
                revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
                canon = json.loads(self.repo.read_text(revision["content_uri"])) if revision else {}
                for fact in canon.get("facts", []):
                    if candidate_id and candidate_id == str(fact.get("id") or ""):
                        conflicts.append({
                            "kind": "existing_canon_fact_update",
                            "existing_id": fact.get("id"),
                            "existing_revision_id": row["current_revision_id"],
                            "label": fact.get("text"),
                            "blocking": False,
                            "resolution": "update_existing",
                        })
                        continue
                    if candidate_key and candidate_key == self._knowledge_key(fact.get("text")):
                        conflicts.append({
                            "kind": "duplicate_canon_fact",
                            "existing_id": fact.get("id"),
                            "label": fact.get("text"),
                            "blocking": True,
                            "resolution": "keep_existing",
                        })
        return conflicts

    @staticmethod
    def _knowledge_decision_conflicts(candidate: dict, live_conflicts: list[dict]) -> list[dict]:
        """Return conflicts that make the pinned knowledge decision unsafe now."""
        blocking = [
            item for item in (candidate.get("conflicts") or [])
            if isinstance(item, dict) and item.get("blocking", True)
        ]
        operation = str(candidate.get("operation") or "create")
        scope_id = str(candidate.get("scope_id") or "")
        for item in live_conflicts:
            existing_id = str(item.get("existing_id") or "")
            unexpected_match = (
                item.get("blocking", True)
                or operation == "create"
                or (operation in {"update", "retire"} and existing_id != scope_id)
            )
            if not unexpected_match:
                continue
            marker = canonical_json(item)
            if all(canonical_json(existing) != marker for existing in blocking):
                blocking.append(item)
        return blocking

    def _knowledge_affected_refs(
        self,
        connection,
        work_id: str,
        kind: str,
        scope_id: str,
        content: dict,
    ) -> list[dict]:
        """Project concrete consumers without turning the projection into a fact source."""
        refs: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        def add(kind_value: str, ref_id: str, label: str, effect: str, status: str = "current"):
            marker = (kind_value, ref_id, effect)
            if not ref_id or marker in seen:
                return
            seen.add(marker)
            refs.append({
                "kind": kind_value,
                "id": ref_id,
                "label": label,
                "effect": effect,
                "status": status,
            })

        brief_names: set[str] = set()
        brief_artifact = connection.execute(
            "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='brief'",
            (work_id,),
        ).fetchone()
        if brief_artifact and brief_artifact["current_revision_id"]:
            brief = self._revision_content(connection, brief_artifact["current_revision_id"])
            brief_names = {self._knowledge_key(item) for item in brief.get("characters", [])}
        candidate_names = {
            self._knowledge_key(content.get("name")),
            self._knowledge_key(content.get("canonical_name")),
            *[self._knowledge_key(item) for item in content.get("aliases", [])],
        }
        candidate_names.discard("")

        affected_scene_ids: set[str] = set()
        scene_rows = connection.execute(
            "SELECT id,title,contract_json FROM scenes WHERE work_id=? ORDER BY stable_order_key,id",
            (work_id,),
        ).fetchall()
        for scene in scene_rows:
            contract = json.loads(scene["contract_json"] or "{}")
            selection = contract.get("context_selection") or {"mode": "legacy"}
            explicit = selection.get("mode") == "explicit"
            if kind == "character_card":
                affected = (
                    scope_id in selection.get("character_card_ids", [])
                    if explicit
                    else bool(candidate_names.intersection(brief_names))
                )
            elif kind in {"world_card", "world_rule"}:
                affected = (
                    scope_id in selection.get("world_item_ids", [])
                    if explicit
                    else True
                )
            else:
                affected = True
            if affected:
                affected_scene_ids.add(scene["id"])
                add("scene", scene["id"], f"场景《{scene['title']}》", "reassemble_context")

        latest_gates: dict[tuple[str, str], object] = {}
        for gate in connection.execute(
            "SELECT id,kind,scope_id,status,created_at FROM gates WHERE work_id=? ORDER BY created_at DESC,id DESC",
            (work_id,),
        ).fetchall():
            latest_gates.setdefault((gate["kind"], gate["scope_id"]), gate)
        gate_labels = {
            "scene.review": "场景审查",
            "continuity.review": "连续性审查",
            "release.review": "发布审查",
        }
        for gate in latest_gates.values():
            if gate["kind"] not in gate_labels:
                continue
            if gate["kind"] == "scene.review" and gate["scope_id"] not in affected_scene_ids:
                continue
            add(
                "gate",
                gate["id"],
                gate_labels[gate["kind"]],
                "review_required",
                gate["status"],
            )

        release = connection.execute(
            "SELECT id,display_version FROM script_releases WHERE work_id=? ORDER BY released_at DESC LIMIT 1",
            (work_id,),
        ).fetchone()
        if release:
            add(
                "script_release",
                release["id"],
                f"已冻结定稿 {release['display_version']}",
                "immutable_no_rewrite",
                "unaffected",
            )
        return refs

    def propose_conversation_knowledge(self, work_id: str, thread_id: str, payload: dict):
        """Turn an Agent discussion draft into an auditable knowledge Proposal."""
        _fallback_provider, proposal_provider = self._capture_provider()
        expected_work = int(payload.get("expected_version", -1))
        expected_thread = int(payload.get("expected_thread_version", -1))
        requested_kind = str(payload.get("kind", "")).strip()
        preview_message_id = str(payload.get("preview_message_id") or "").strip()
        requested_agent_run_id = str(payload.get("agent_run_id") or "").strip()
        if requested_kind not in {"character_card", "world_card", "world_rule", "canon_fact"}:
            raise DomainError("validation_error", "资料候选类型无效。", details={"field": "kind"})
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected_work)
            thread = self._check_thread_version(connection, work_id, thread_id, expected_thread)
            self._conversation_policy(connection, thread, retry=True)
            pending_kind = {
                "character_card": "character_card",
                "world_card": "world_entity",
                "world_rule": "world_rule",
                "canon_fact": "canon_fact",
            }[requested_kind]
            if connection.execute(
                "SELECT 1 FROM proposals WHERE work_id=? AND kind=? AND status='pending'",
                (work_id, pending_kind),
            ).fetchone():
                raise DomainError("proposal_waiting_user", "已有同类资料候选等待决定。", status=409)
            rows = connection.execute(
                "SELECT id,ordinal,role,content_json,agent_run_id FROM conversation_messages WHERE thread_id=? ORDER BY ordinal",
                (thread_id,),
            ).fetchall()
            messages = [(row, json.loads(row["content_json"])) for row in rows]
            # Older clients only sent the knowledge kind. Keep that path safe by
            # selecting the newest matching discussion draft; explicit identities
            # still use strict matching below.
            preview_entry = next((
                (row, content.get("artifact_preview"))
                for row, content in reversed(messages)
                if row["role"] == "assistant"
                and (not preview_message_id or row["id"] == preview_message_id)
                and (not requested_agent_run_id or row["agent_run_id"] == requested_agent_run_id)
                and isinstance(content.get("artifact_preview"), dict)
                and content["artifact_preview"].get("kind") == requested_kind
            ), None)
            if not preview_entry:
                raise DomainError("knowledge_draft_not_found", "指定的资料草稿不存在或不属于本次 Agent 运行。", status=409)
            preview_row, preview = preview_entry
            if preview.get("status") != "discussion_draft":
                raise DomainError("knowledge_draft_consumed", "这张资料草稿已经整理过，不能重复提交。", status=409)
            newer_user = next((
                row for row, _ in messages
                if row["role"] == "user" and row["ordinal"] > preview_row["ordinal"]
            ), None)
            if newer_user:
                raise DomainError(
                    "knowledge_draft_stale",
                    "这张草稿之后已有新的用户意见，请让 Agent 根据最新讨论重新整理。",
                    status=409,
                    details={"preview_message_id": preview_row["id"], "newer_message_id": newer_user["id"]},
                )
            consumed = False
            for proposal_row in connection.execute(
                "SELECT evidence_json,candidate_uri FROM proposals WHERE work_id=?",
                (work_id,),
            ).fetchall():
                evidence = json.loads(proposal_row["evidence_json"] or "{}")
                if evidence.get("source_preview_message_id") == preview_row["id"]:
                    consumed = True
                    break
                candidate = json.loads(self.repo.read_text(proposal_row["candidate_uri"]))
                if preview_row["id"] in candidate.get("source_message_ids", []):
                    consumed = True
                    break
            if consumed:
                raise DomainError("knowledge_draft_consumed", "这张资料草稿已经整理过，不能重复提交。", status=409)
            preview_content = preview.get("content") if isinstance(preview.get("content"), dict) else {}
            document_citations = [
                item for item in (preview.get("sources") or []) if isinstance(item, dict)
            ]
            title = str(payload.get("title") or preview.get("title") or "").strip()
            if requested_kind == "canon_fact":
                title = title or "作品事实"
            if not title or title in {"待命名角色", "待命名世界观", "世界观设定草稿"}:
                raise DomainError("knowledge_name_required", "请先在对话中明确资料名称。", status=409)
            user_notes = [
                str(content.get("text", "")).strip()
                for row, content in messages
                if row["role"] == "user" and str(content.get("text", "")).strip()
            ]
            source_user_row = next(
                (
                    row for row, _ in reversed(messages)
                    if row["role"] == "user" and row["ordinal"] < preview_row["ordinal"]
                ),
                None,
            )
            source_message_ids = [
                item for item in (
                    source_user_row["id"] if source_user_row else None,
                    preview_row["id"],
                )
                if item
            ]
            conversation_summary_digest = None
            if preview_row["agent_run_id"]:
                preview_run = connection.execute(
                    "SELECT input_snapshot_uri,input_digest FROM agent_runs WHERE id=? AND work_id=?",
                    (preview_row["agent_run_id"], work_id),
                ).fetchone()
                if preview_run and preview_run["input_snapshot_uri"]:
                    snapshot_text = self.repo.read_text(preview_run["input_snapshot_uri"])
                    if sha256_text(snapshot_text) != preview_run["input_digest"]:
                        raise DomainError(
                            "agent_snapshot_integrity_failed",
                            "资料草稿的 Agent 输入快照已损坏，不能建立正式资料候选。",
                            status=409,
                            details={"agent_run_id": preview_row["agent_run_id"]},
                        )
                    try:
                        preview_snapshot = json.loads(snapshot_text)
                    except json.JSONDecodeError as exc:
                        raise DomainError(
                            "agent_snapshot_integrity_failed",
                            "资料草稿的 Agent 输入快照无法读取，不能建立正式资料候选。",
                            status=409,
                            details={"agent_run_id": preview_row["agent_run_id"]},
                        ) from exc
                    pinned_summary = preview_snapshot.get("conversation_summary")
                    pinned_provider = preview_snapshot.get("provider_runtime")
                    if isinstance(pinned_provider, dict):
                        proposal_provider = pinned_provider
                    if isinstance(pinned_summary, dict):
                        summary_sources = conversation_summary_evidence_ids(
                            connection,
                            thread_id,
                            pinned_summary,
                            before_ordinal=preview_row["ordinal"],
                        )
                        source_message_ids = list(dict.fromkeys([
                            *summary_sources,
                            *source_message_ids,
                        ]))
                        conversation_summary_digest = pinned_summary.get("digest")
            source_refs = self._merge_source_refs(
                document_citations,
                preview_content.get("source_refs") if isinstance(preview_content.get("source_refs"), list) else [],
                [f"作品主对话 {thread_id}"],
            )
            scope_id = new_id(
                "character" if requested_kind == "character_card"
                else "world-card" if requested_kind == "world_card"
                else "world-rule" if requested_kind == "world_rule"
                else "fact"
            )
            base_revision_id = None
            operation = "create"
            base_content = {}
            if requested_kind == "character_card":
                proposed_content = {
                    "name": title,
                    **preview_content,
                }
                proposed_content["name"] = title
                conflicts = self._knowledge_conflicts(connection, work_id, requested_kind, proposed_content)
                updates = [item for item in conflicts if item.get("resolution") == "update_existing"]
                if len(updates) == 1:
                    operation = "update"
                    scope_id = updates[0]["existing_id"]
                    base_revision_id = updates[0].get("existing_revision_id")
                    existing = self._revision_content(connection, base_revision_id)
                    base_content = existing
                    content = self._merge_knowledge_content(existing, proposed_content)
                    content["source_refs"] = self._merge_source_refs(existing.get("source_refs"), source_refs)
                else:
                    if len(updates) > 1:
                        for item in updates:
                            item.update({"blocking": True, "resolution": "choose_existing_target"})
                    content = {
                        "canonical_name": title,
                        "aliases": [],
                        "source_type": "custom",
                        "role": str(preview_content.get("role") or preview_content.get("summary") or preview.get("summary") or (user_notes[-1] if user_notes else "")),
                        "voice_anchors": [],
                        "knowledge_boundary": "",
                        "ooc_constraints": [],
                        "relationships": [],
                        "trust_status": "confirmed",
                        **proposed_content,
                        "source_refs": source_refs,
                    }
            elif requested_kind == "world_card":
                world_artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='world_bible'",
                    (work_id,),
                ).fetchone()
                base_revision_id = world_artifact["current_revision_id"] if world_artifact else None
                proposed_content = {
                    "id": scope_id,
                    "name": title,
                    **preview_content,
                }
                proposed_content["name"] = title
                conflicts = self._knowledge_conflicts(connection, work_id, requested_kind, proposed_content)
                updates = [item for item in conflicts if item.get("resolution") == "update_existing"]
                if len(updates) == 1:
                    operation = "update"
                    scope_id = updates[0]["existing_id"]
                    base_revision_id = updates[0].get("existing_revision_id")
                    bible = self._revision_content(connection, base_revision_id)
                    existing = next(
                        (item for item in bible.get("entities", []) if item.get("id") == scope_id), {}
                    )
                    base_content = existing
                    content = self._merge_knowledge_content(existing, {**proposed_content, "id": scope_id})
                    content["source_refs"] = self._merge_source_refs(existing.get("source_refs"), source_refs)
                else:
                    if len(updates) > 1:
                        for item in updates:
                            item.update({"blocking": True, "resolution": "choose_existing_target"})
                    content = {
                        "kind": "custom",
                        "summary": str(preview_content.get("summary") or preview.get("summary") or (user_notes[-1] if user_notes else "")),
                        "aliases": [],
                        "source": f"作品主对话 {thread_id}",
                        "source_type": "custom",
                        "confidence_status": "confirmed",
                        "scope": "work",
                        "participants": [],
                        "related_world_ids": [],
                        "status": "active",
                        **proposed_content,
                        "source_refs": source_refs,
                    }
            elif requested_kind == "world_rule":
                world_artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='world_bible'",
                    (work_id,),
                ).fetchone()
                base_revision_id = world_artifact["current_revision_id"] if world_artifact else None
                proposed_content = {
                    "id": scope_id,
                    "name": title,
                    "text": str(payload.get("text") or preview_content.get("text") or preview.get("summary") or "").strip(),
                    "scope": str(preview_content.get("scope") or payload.get("scope") or "work").strip() or "work",
                    "exceptions": list(preview_content.get("exceptions") or []),
                    "source": str(preview_content.get("source") or f"作品主对话 {thread_id}"),
                    "confidence_status": str(preview_content.get("confidence_status") or "open"),
                    "status": "active",
                    "source_refs": source_refs,
                }
                if not proposed_content["text"]:
                    raise DomainError("knowledge_text_required", "世界规则需要具体内容。", status=409)
                conflicts = self._knowledge_conflicts(connection, work_id, requested_kind, proposed_content)
                updates = [item for item in conflicts if item.get("resolution") == "update_existing"]
                if len(updates) == 1:
                    operation = "update"
                    scope_id = updates[0]["existing_id"]
                    base_revision_id = updates[0].get("existing_revision_id")
                    bible = self._revision_content(connection, base_revision_id)
                    existing = next((item for item in bible.get("rules", []) if item.get("id") == scope_id), {})
                    base_content = existing
                    content = self._merge_knowledge_content(existing, {**proposed_content, "id": scope_id})
                    content["source_refs"] = self._merge_source_refs(existing.get("source_refs"), source_refs)
                else:
                    if len(updates) > 1:
                        for item in updates:
                            item.update({"blocking": True, "resolution": "choose_existing_target"})
                    content = proposed_content
            else:
                canon_artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='work_canon'",
                    (work_id,),
                ).fetchone()
                base_revision_id = canon_artifact["current_revision_id"] if canon_artifact else None
                requested_operation = str(
                    payload.get("operation") or preview_content.get("operation") or "create"
                ).strip()
                if requested_operation not in {"create", "update", "retire"}:
                    raise DomainError(
                        "validation_error", "作品事实操作无效。", details={"field": "operation"}
                    )
                operation = requested_operation
                requested_fact_id = str(
                    payload.get("fact_id") or preview_content.get("fact_id") or ""
                ).strip()
                current_canon = self._revision_content(connection, base_revision_id)
                existing_fact = None
                if operation in {"update", "retire"}:
                    if not requested_fact_id:
                        raise DomainError(
                            "knowledge_target_required",
                            "更新或退役作品事实时必须明确 fact_id。",
                            status=409,
                            details={"field": "fact_id", "operation": operation},
                        )
                    existing_fact = next(
                        (
                            item for item in current_canon.get("facts", [])
                            if str(item.get("id") or "") == requested_fact_id
                        ),
                        None,
                    )
                    if not existing_fact:
                        raise DomainError(
                            "knowledge_target_not_found",
                            "要更新或退役的作品事实不存在，请刷新资料后重试。",
                            status=409,
                            details={"fact_id": requested_fact_id, "operation": operation},
                        )
                    scope_id = requested_fact_id
                    base_content = dict(existing_fact)
                if operation == "retire":
                    content = {
                        **base_content,
                        "id": scope_id,
                        "status": "archived",
                        "confidence_status": "retired",
                    }
                elif operation == "update":
                    proposed_update = {
                        "text": str(payload.get("text") or preview_content.get("text") or "").strip(),
                        "source_refs": self._merge_source_refs(
                            base_content.get("source_refs"), source_refs
                        ),
                    }
                    for field_name in ("source", "confidence_status"):
                        if str(preview_content.get(field_name) or "").strip():
                            proposed_update[field_name] = str(preview_content[field_name]).strip()
                    requested_scope = payload.get("scope") or preview_content.get("scope")
                    if str(requested_scope or "").strip():
                        proposed_update["scope"] = str(requested_scope).strip()
                    content = self._merge_knowledge_content(base_content, proposed_update)
                    content["id"] = scope_id
                else:
                    content = {
                        "id": scope_id,
                        "text": str(payload.get("text") or preview_content.get("text") or preview.get("summary") or "").strip(),
                        "source": str(preview_content.get("source") or "作品主对话（待用户确认）").strip(),
                        "confidence_status": str(preview_content.get("confidence_status") or "open").strip(),
                        "scope": str(payload.get("scope") or preview_content.get("scope") or "work").strip() or "work",
                        "status": "active",
                        "source_refs": source_refs,
                    }
                if not str(content.get("text") or "").strip():
                    raise DomainError("knowledge_text_required", "作品事实需要具体内容。", status=409)
                conflicts = self._knowledge_conflicts(connection, work_id, requested_kind, content)
            field_changes = self._knowledge_field_changes(base_content, content)
            affected_refs = self._knowledge_affected_refs(
                connection,
                work_id,
                requested_kind,
                scope_id,
                content,
            )
            impact_preview = build_knowledge_impact_preview(
                work_id=work_id,
                work_version=version,
                kind=requested_kind,
                operation=operation,
                scope_id=scope_id,
                title=title,
                base_revision_id=base_revision_id,
                field_changes=field_changes,
                conflicts=conflicts,
                affected_refs=affected_refs,
            )
            candidate = {
                "schema_version": "conversation-knowledge-proposal/1.2",
                "kind": requested_kind,
                "operation": operation,
                "scope_id": scope_id,
                "base_revision_id": base_revision_id,
                "content": content,
                "source_thread_id": thread_id,
                "source_agent_run_id": preview_row["agent_run_id"],
                "source_preview_message_id": preview_row["id"],
                "source_message_ids": source_message_ids,
                "conversation_summary_digest": conversation_summary_digest,
                "document_citations": document_citations,
                "field_changes": field_changes,
                "conflicts": conflicts,
                "impact_preview": impact_preview,
            }
            proposal_id = new_id("proposal")
            candidate_uri, candidate_hash = self.repo.atomic_write_text(
                f"artifacts/proposals/{proposal_id}.json",
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            )
            timestamp = now()
            connection.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id, work_id, pending_kind,
                    "character" if requested_kind == "character_card" else "work", scope_id,
                    base_revision_id, candidate_uri, candidate_hash,
                    canonical_json({"format": "knowledge-fields/1.2", "operation": operation, "changes": field_changes}),
                    canonical_json({
                        "source_message_ids": source_message_ids,
                        "source_agent_run_id": preview_row["agent_run_id"],
                        "source_preview_message_id": preview_row["id"],
                        "document_citations": document_citations,
                        "conversation_summary_digest": conversation_summary_digest,
                        "summary_sources_rechecked": bool(conversation_summary_digest),
                    }),
                    "high" if any(item.get("blocking", True) for item in conflicts) else "medium", "pending",
                    canonical_json(proposal_provider), timestamp, None,
                ),
            )
            if preview_row["agent_run_id"]:
                connection.execute(
                    "UPDATE agent_runs SET proposal_id=? WHERE id=? AND work_id=? AND status='waiting_user'",
                    (proposal_id, preview_row["agent_run_id"], work_id),
                )
            proposal_preview = {
                **preview,
                "title": title,
                "status": "proposal",
                "operation": operation,
                "summary": "Agent 已把讨论整理成现有资料的更新候选。采纳后才会建立新修订。" if operation == "update" else "Agent 已把讨论整理成资料候选。采纳后才会建立正式修订。",
                "sources": document_citations,
                "field_changes": field_changes,
                "conflicts": conflicts,
                "impact_preview": impact_preview,
            }
            knowledge_label = {
                "character_card": "人物卡", "world_card": "世界观卡",
                "world_rule": "世界规则", "canon_fact": "作品事实",
            }[requested_kind]
            self._append_conversation_message(
                connection, thread_id, "assistant", "proposal",
                {
                    "text": f"我已把“{title}”整理成可审查的{knowledge_label}{'更新' if operation == 'update' else ''}候选。",
                    "artifact_preview": proposal_preview,
                    "proposal_id": proposal_id,
                    "tool_activity": [{"tool": "create_knowledge_proposal", "label": "创建资料 Proposal", "status": "succeeded", "output": proposal_id}],
                },
                provider=proposal_provider, proposal_id=proposal_id,
            )
            connection.execute(
                "UPDATE conversation_threads SET phase='execute',version=version+1,updated_at=? WHERE id=?",
                (timestamp, thread_id),
            )
            self._bump_work(connection, work_id, version)
        return {
            "proposal_id": proposal_id,
            "simulation": bool(proposal_provider.get("is_simulation", True)),
            "work": self.get_work(work_id),
        }

    def _create_background_canon_suggestions(
        self,
        connection,
        *,
        work_id: str,
        work_version: int,
        scene_id: str,
        scene_revision,
        agent_run_id: str,
        suggestions: list[dict],
        provider_descriptor: dict,
    ) -> list[str]:
        """Persist scene-derived facts as non-blocking, review-only Proposals."""

        if not suggestions:
            return []
        canon_artifact = connection.execute(
            "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='work_canon'",
            (work_id,),
        ).fetchone()
        base_revision_id = canon_artifact["current_revision_id"] if canon_artifact else None
        current_canon = self._revision_content(connection, base_revision_id)
        existing_keys = {
            self._knowledge_key(item.get("text"))
            for item in current_canon.get("facts", [])
            if str(item.get("status") or "active") != "archived"
        }
        pending_digests = set()
        for row in connection.execute(
            "SELECT evidence_json FROM proposals WHERE work_id=? AND kind='canon_fact' AND status='pending'",
            (work_id,),
        ).fetchall():
            try:
                evidence = json.loads(row["evidence_json"] or "{}")
            except json.JSONDecodeError:
                continue
            digest = str(evidence.get("suggestion_digest") or "")
            if digest:
                pending_digests.add(digest)

        created_ids = []
        for suggestion in suggestions:
            normalized_key = self._knowledge_key(suggestion["text"])
            if normalized_key in existing_keys:
                continue
            suggestion_digest = "sha256:" + sha256_text(canonical_json({
                "work_id": work_id,
                "base_revision_id": base_revision_id,
                "scene_revision_id": scene_revision["id"],
                "text": suggestion["text"],
                "scope": suggestion["scope"],
            }))
            if suggestion_digest in pending_digests:
                continue
            scope_id = new_id("fact")
            source_refs = [{
                "kind": "scene_revision",
                "scene_id": scene_id,
                "revision_id": scene_revision["id"],
                "content_hash": scene_revision["content_hash"],
                "block_ids": suggestion["source_block_ids"],
            }]
            content = {
                "id": scope_id,
                "text": suggestion["text"],
                "source": f"场景修订 {scene_revision['id']}",
                "confidence_status": suggestion["confidence_status"],
                "scope": suggestion["scope"],
                "status": "active",
                "source_refs": source_refs,
            }
            field_changes = self._knowledge_field_changes({}, content)
            conflicts = self._knowledge_conflicts(connection, work_id, "canon_fact", content)
            affected_refs = self._knowledge_affected_refs(
                connection, work_id, "canon_fact", scope_id, content
            )
            impact_preview = build_knowledge_impact_preview(
                work_id=work_id,
                work_version=work_version,
                kind="canon_fact",
                operation="create",
                scope_id=scope_id,
                title=suggestion["text"][:80],
                base_revision_id=base_revision_id,
                field_changes=field_changes,
                conflicts=conflicts,
                affected_refs=affected_refs,
            )
            candidate = {
                "schema_version": "conversation-knowledge-proposal/1.2",
                "kind": "canon_fact",
                "operation": "create",
                "scope_id": scope_id,
                "base_revision_id": base_revision_id,
                "content": content,
                "source_thread_id": None,
                "source_agent_run_id": agent_run_id,
                "source_preview_message_id": None,
                "source_message_ids": [],
                "conversation_summary_digest": None,
                "document_citations": [],
                "field_changes": field_changes,
                "conflicts": conflicts,
                "impact_preview": impact_preview,
                "maintenance_source": "scene_memory_extract",
            }
            proposal_id = new_id("proposal")
            candidate_uri, candidate_hash = self.repo.atomic_write_text(
                f"artifacts/proposals/{proposal_id}.json",
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            )
            connection.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id, work_id, "canon_fact", "work", scope_id,
                    base_revision_id, candidate_uri, candidate_hash,
                    canonical_json({
                        "format": "knowledge-fields/1.2",
                        "operation": "create",
                        "changes": field_changes,
                    }),
                    canonical_json({
                        "background_suggestion": True,
                        "suggestion_digest": suggestion_digest,
                        "source_agent_run_id": agent_run_id,
                        "scene_id": scene_id,
                        "scene_revision_id": scene_revision["id"],
                        "scene_revision_hash": scene_revision["content_hash"],
                        "source_block_ids": suggestion["source_block_ids"],
                    }),
                    "high" if any(item.get("blocking", True) for item in conflicts) else "medium",
                    "pending", canonical_json(provider_descriptor), now(), None,
                ),
            )
            created_ids.append(proposal_id)
            pending_digests.add(suggestion_digest)
        return created_ids

    def _supersede_background_knowledge_suggestions(
        self,
        connection,
        *,
        work_id: str,
        scene_id: str,
        current_revision_id: str,
        reason: str,
    ) -> list[str]:
        """Expire review-only facts and queued discovery pinned to an older scene revision."""

        timestamp = now()
        superseded_ids = []
        rows = connection.execute(
            "SELECT id,evidence_json FROM proposals WHERE work_id=? AND kind='canon_fact' AND status='pending'",
            (work_id,),
        ).fetchall()
        for row in rows:
            try:
                evidence = json.loads(row["evidence_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if (
                not evidence.get("background_suggestion")
                or evidence.get("scene_id") != scene_id
                or evidence.get("scene_revision_id") == current_revision_id
            ):
                continue
            connection.execute(
                "UPDATE proposals SET status='superseded',decided_at=? WHERE id=? AND status='pending'",
                (timestamp, row["id"]),
            )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"), work_id, "proposal", row["id"],
                    "superseded", reason, timestamp,
                ),
            )
            superseded_ids.append(row["id"])

        jobs = connection.execute(
            """SELECT id,payload_json FROM agent_dispatch_jobs
               WHERE operation='knowledge.discover' AND status='ready'"""
        ).fetchall()
        for job in jobs:
            try:
                queued = json.loads(job["payload_json"] or "{}")
            except json.JSONDecodeError:
                continue
            request = queued.get("request") if isinstance(queued.get("request"), dict) else {}
            if (
                queued.get("work_id") == work_id
                and queued.get("scope_id") == scene_id
                and request.get("_source_revision_id") != current_revision_id
            ):
                connection.execute(
                    """UPDATE agent_dispatch_jobs SET status='cancelled',cancel_requested_at=?,updated_at=?
                       WHERE id=? AND status='ready'""",
                    (timestamp, timestamp, job["id"]),
                )
        return superseded_ids

    def organize_conversation_proposal(self, work_id: str, thread_id: str, payload: dict):
        provider = self.provider
        with self.repo.connect() as connection:
            thread_scope = connection.execute(
                "SELECT id,work_id,scope_type,scope_id FROM conversation_threads WHERE id=? AND work_id=?",
                (thread_id, work_id),
            ).fetchone()
        if not thread_scope:
            raise NotFound("conversation_thread", thread_id)
        requested_scope = self._effective_conversation_scope(thread_scope, payload.get("task_scope"))
        if requested_scope.get("surface") == "chapter":
            return self._organize_chapter_plan_proposal(
                work_id, thread_id, payload, requested_scope, provider=provider
            )
        with self.repo.connect() as connection:
            task_contract = self._conversation_task_contract(connection, work_id, requested_scope)
        if task_contract["id"] == "structure.plan":
            return self._organize_structure_plan_proposal(
                work_id, thread_id, payload, task_contract, provider=provider
            )
        expected_work = int(payload.get("expected_version", -1))
        expected_thread = int(payload.get("expected_thread_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected_work)
            thread = self._check_thread_version(connection, work_id, thread_id, expected_thread)
            self._conversation_policy(connection, thread, retry=True)
            if thread["scope_type"] != "work" or thread["scope_id"] != work_id:
                raise DomainError("invalid_thread_scope", "只有作品主对话可以整理整体故事方案。", status=409)
            if connection.execute(
                "SELECT 1 FROM proposals WHERE work_id=? AND kind='brief_blueprint' AND status='pending'", (work_id,)
            ).fetchone():
                raise DomainError("proposal_waiting_user", "已有故事方案等待决定，请先采纳或退回。", status=409)
            messages = recent_conversation_history(connection, thread_id)
            conversation_summary = self._conversation_summary(connection, thread_id)
            first_user_row = connection.execute(
                """SELECT id,content_json FROM conversation_messages
                   WHERE thread_id=? AND role='user' ORDER BY ordinal LIMIT 1""",
                (thread_id,),
            ).fetchone()
            if not first_user_row:
                raise DomainError("discussion_required", "请先和创作导演讨论一句故事想法。", status=409)
            idea = str(json.loads(first_user_row["content_json"]).get("text") or "").strip()
            recent_user_notes = [
                item["text"] for item in messages
                if item["role"] == "user" and item["text"] and item["id"] != first_user_row["id"]
            ]
            discussion_notes = [conversation_summary.get("text", ""), *recent_user_notes]
            discussion_notes = [item for item in discussion_notes if item]
            brief = {
                "idea": idea,
                "mode": "pending_analysis",
                "story_modes": [],
                "characters": [],
                "character_card_ids": [],
                "target_length": "pending_analysis",
                "constraints": "\n".join(discussion_notes),
                "has_sensei": False,
                "sensei_decision": "pending_analysis",
                "status": "proposed",
            }
            analysis_context = {
                "character_cards": self._analysis_character_cards(connection, work_id),
                "world": self._analysis_world_summary(connection, work_id),
                "task_contract": self._conversation_task_contract(connection, work_id, {"surface": "work"}),
                "conversation_summary": conversation_summary,
            }
            blueprint = self._validate_story_blueprint(provider.generate_blueprint(brief, analysis_context))
            blueprint["status"] = "proposed"
            current_brief = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='brief'", (work_id,)
            ).fetchone()
            current_blueprint = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)
            ).fetchone()
            candidate = {
                "schema_version": "brief-blueprint-proposal/1.0",
                "brief": brief,
                "story_blueprint": blueprint,
                "base_brief_revision_id": current_brief["current_revision_id"] if current_brief else None,
                "base_blueprint_revision_id": current_blueprint["current_revision_id"] if current_blueprint else None,
                "source_thread_id": thread_id,
                "source_message_ids": [
                    row["id"] for row in connection.execute(
                        "SELECT id FROM conversation_messages WHERE thread_id=? ORDER BY ordinal", (thread_id,)
                    ).fetchall()
                ],
            }
            proposal_id = new_id("proposal")
            candidate_uri, candidate_hash = self.repo.atomic_write_text(
                f"artifacts/proposals/{proposal_id}.json",
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            )
            diff = {
                "format": "proposal-fields/1.0",
                "changes": [
                    {"field": "写作想法", "after": idea},
                    {"field": "故事前提", "after": blueprint.get("premise", "")},
                    {"field": "核心冲突", "after": blueprint.get("central_conflict", "")},
                    {"field": "讨论补充", "after": "\n".join(discussion_notes)},
                ],
            }
            timestamp = now()
            connection.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id, work_id, "brief_blueprint", "work", work_id,
                    candidate["base_blueprint_revision_id"], candidate_uri, candidate_hash,
                    canonical_json(diff), canonical_json(candidate["source_message_ids"]),
                    "medium", "pending", canonical_json(provider.descriptor()), timestamp, None,
                ),
            )
            self._append_conversation_message(
                connection, thread_id, "assistant", "proposal",
                {"text": "我已整理成可审查的写作想法与故事方向，采纳前不会写入正式产物。", "proposal_id": proposal_id},
                provider=provider.descriptor(), proposal_id=proposal_id,
            )
            connection.execute(
                "UPDATE conversation_threads SET phase='execute',version=version+1,updated_at=? WHERE id=?",
                (timestamp, thread_id),
            )
            self._bump_work(connection, work_id, version)
        return {"proposal_id": proposal_id, "simulation": provider.is_simulation, "work": self.get_work(work_id)}

    def _structure_snapshot(self, connection, work_id: str) -> dict:
        volumes = self.repo.rows(connection.execute(
            "SELECT id,stable_order_key,title,status,version FROM volumes WHERE work_id=? ORDER BY stable_order_key,id",
            (work_id,),
        ))
        chapters = self.repo.rows(connection.execute(
            "SELECT id,volume_id,stable_order_key,title,status,version FROM chapters WHERE work_id=? ORDER BY volume_id,stable_order_key,id",
            (work_id,),
        ))
        scenes = self.repo.rows(connection.execute(
            "SELECT id,chapter_id,stable_order_key,title,status,version,current_revision_id,contract_json FROM scenes WHERE work_id=? ORDER BY chapter_id,stable_order_key,id",
            (work_id,),
        ))
        for scene in scenes:
            scene["contract"] = json.loads(scene.pop("contract_json") or "{}")
        projection = {"volumes": volumes, "chapters": chapters, "scenes": scenes}
        return {"projection": projection, "digest": sha256_text(canonical_json(projection))}

    def _record_current_story_structure(
        self, connection, work_id: str, *, workflow: str, created_by: str = "user"
    ) -> str:
        snapshot = self._structure_snapshot(connection, work_id)["projection"]
        chapters_by_volume: dict[str, list[dict]] = {}
        scenes_by_chapter: dict[str, list[dict]] = {}
        for scene in snapshot["scenes"]:
            scenes_by_chapter.setdefault(scene["chapter_id"], []).append(
                {
                    "id": scene["id"],
                    "title": scene["title"],
                    "status": scene["status"],
                    "stable_order_key": scene["stable_order_key"],
                    "current_revision_id": scene["current_revision_id"],
                    "contract": scene["contract"],
                }
            )
        for chapter in snapshot["chapters"]:
            chapters_by_volume.setdefault(chapter["volume_id"], []).append(
                {
                    "id": chapter["id"],
                    "title": chapter["title"],
                    "status": chapter["status"],
                    "stable_order_key": chapter["stable_order_key"],
                    "scenes": scenes_by_chapter.get(chapter["id"], []),
                }
            )
        volumes = [
            {
                "id": volume["id"],
                "title": volume["title"],
                "status": volume["status"],
                "stable_order_key": volume["stable_order_key"],
                "chapters": chapters_by_volume.get(volume["id"], []),
            }
            for volume in snapshot["volumes"]
        ]
        artifact = self._artifact(connection, work_id, "story_structure", "work", work_id)
        return self._add_revision(
            connection,
            artifact,
            {
                "schema_version": "story-structure/1.0",
                "summary": "当前作品的卷、章与场景结构。",
                "volumes": volumes,
                "status": "accepted",
            },
            created_by,
            {"workflow": workflow, "pack": PACK_VERSION, "structure_digest": self._structure_snapshot(connection, work_id)["digest"]},
            schema_version="story-structure/1.0",
        )

    @staticmethod
    def _validate_structure_plan(value: dict) -> dict:
        if not isinstance(value, dict):
            raise DomainError("provider_output_invalid", "模型返回的作品结构不是对象。", status=502)
        volumes = value.get("volumes")
        if not isinstance(volumes, list) or not volumes or len(volumes) > 8:
            raise DomainError("provider_output_invalid", "作品结构必须包含 1 到 8 个卷。", status=502, details={"field": "volumes"})
        normalized_volumes = []
        chapter_count = 0
        scene_count = 0
        for volume_index, raw_volume in enumerate(volumes):
            if not isinstance(raw_volume, dict) or any(key in raw_volume for key in ("id", "operation", "stable_order_key")):
                raise DomainError("provider_output_invalid", "卷结构包含不允许的系统字段。", status=502, details={"volume_index": volume_index})
            title = str(raw_volume.get("title") or "").strip()
            purpose = str(raw_volume.get("purpose") or raw_volume.get("goal") or "").strip()
            chapters = raw_volume.get("chapters")
            if not title or len(title) > 120 or not purpose:
                raise DomainError("provider_output_invalid", "每个卷都需要标题和明确目标。", status=502, details={"volume_index": volume_index})
            if not isinstance(chapters, list) or not chapters:
                raise DomainError("provider_output_invalid", "每个卷至少需要一章。", status=502, details={"volume_index": volume_index, "field": "chapters"})
            normalized_chapters = []
            for chapter_index, raw_chapter in enumerate(chapters):
                chapter_count += 1
                if chapter_count > 60 or not isinstance(raw_chapter, dict) or any(key in raw_chapter for key in ("id", "operation", "stable_order_key")):
                    raise DomainError("provider_output_invalid", "章节数量过多或包含不允许的系统字段。", status=502)
                chapter_title = str(raw_chapter.get("title") or "").strip()
                chapter_goal = str(raw_chapter.get("goal") or raw_chapter.get("chapter_goal") or "").strip()
                raw_scenes = raw_chapter.get("scenes")
                if not chapter_title or len(chapter_title) > 120 or not chapter_goal:
                    raise DomainError("provider_output_invalid", "每章都需要标题和明确目标。", status=502, details={"volume_index": volume_index, "chapter_index": chapter_index})
                if not isinstance(raw_scenes, list) or not raw_scenes:
                    raise DomainError("provider_output_invalid", "每章至少需要一场。", status=502, details={"volume_index": volume_index, "chapter_index": chapter_index, "field": "scenes"})
                normalized_scenes = []
                for scene_index, raw_scene in enumerate(raw_scenes):
                    scene_count += 1
                    if scene_count > 200 or not isinstance(raw_scene, dict) or any(key in raw_scene for key in ("id", "operation", "stable_order_key")):
                        raise DomainError("provider_output_invalid", "场景数量过多或包含不允许的系统字段。", status=502)
                    scene_title = str(raw_scene.get("title") or "").strip()
                    goal = str(raw_scene.get("goal") or "").strip()
                    stop_boundary = str(raw_scene.get("stop_boundary") or "").strip()
                    mode = str(raw_scene.get("writing_mode") or "").strip()
                    if not scene_title or len(scene_title) > 120 or not goal or not stop_boundary:
                        raise DomainError("provider_output_invalid", "每场都需要标题、目标和停止边界。", status=502, details={"volume_index": volume_index, "chapter_index": chapter_index, "scene_index": scene_index})
                    if mode and mode not in MODE_SOURCES:
                        raise DomainError("provider_output_invalid", "场景返回了未知的 BA 写作模式。", status=502, details={"mode": mode})
                    normalized_scenes.append({
                        "title": scene_title,
                        "goal": goal[:1000],
                        "location": str(raw_scene.get("location") or "").strip()[:240],
                        "stop_boundary": stop_boundary[:500],
                        "writing_mode": mode,
                    })
                normalized_chapters.append({"title": chapter_title, "goal": chapter_goal[:1000], "scenes": normalized_scenes})
            normalized_volumes.append({"title": title, "purpose": purpose[:1200], "chapters": normalized_chapters})
        return {
            "schema_version": "story-structure-plan/1.0",
            "summary": str(value.get("summary") or "").strip()[:1600],
            "volumes": normalized_volumes,
            "status": "proposed",
        }

    def _fail_structure_work_item(
        self,
        work_item_id: str,
        attempt_id: str,
        run_id: str,
        agent_run_id: str,
        code: str,
        message: str,
        *,
        retryable: bool = True,
    ):
        error = {"code": code, "message": message, "retryable": retryable}
        timestamp = now()
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            connection.execute(
                "UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'",
                (code, timestamp, attempt_id),
            )
            connection.execute(
                "UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'",
                (canonical_json(error), timestamp, work_item_id),
            )
            connection.execute(
                "UPDATE production_runs SET status='failed',updated_at=? WHERE id=? AND status='running'",
                (timestamp, run_id),
            )
            connection.execute(
                "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                (canonical_json(error), timestamp, agent_run_id),
            )

    @contextmanager
    def _structure_persist_transaction(
        self, work_item_id: str, attempt_id: str, run_id: str, agent_run_id: str
    ):
        try:
            with self.repo.transaction() as connection:
                yield connection
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else "structure_plan_persist_failed"
            message = exc.message if isinstance(exc, DomainError) else "作品结构候选保存失败。"
            self._fail_structure_work_item(
                work_item_id, attempt_id, run_id, agent_run_id, code, message
            )
            raise

    def _organize_structure_plan_proposal(
        self, work_id: str, thread_id: str, payload: dict, task_contract: dict, provider=None
    ):
        provider = provider if provider is not None else self.provider
        expected_work = int(payload.get("expected_version", -1))
        expected_thread = int(payload.get("expected_thread_version", -1))
        timestamp = now()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected_work)
            thread = self._check_thread_version(connection, work_id, thread_id, expected_thread)
            self._conversation_policy(connection, thread, retry=True)
            if thread["scope_type"] != "work" or thread["scope_id"] != work_id:
                raise DomainError("invalid_thread_scope", "只有作品主对话可以整理全作结构。", status=409)
            if connection.execute(
                "SELECT 1 FROM proposals WHERE work_id=? AND kind='story_structure' AND status='pending'", (work_id,)
            ).fetchone():
                raise DomainError("proposal_waiting_user", "已有作品结构候选等待决定，请先采纳或退回。", status=409)
            snapshot = self._structure_snapshot(connection, work_id)
            if snapshot["projection"]["scenes"] or len(snapshot["projection"]["volumes"]) != 1 or len(snapshot["projection"]["chapters"]) != 1 or snapshot["projection"]["chapters"][0]["status"] != "placeholder":
                raise DomainError(
                    "structure_plan_requires_clean_skeleton",
                    "当前作品已经手工建立了正式结构，请在作品结构页继续维护，不能用整树候选覆盖。",
                    status=409,
                )
            blueprint_row = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)
            ).fetchone()
            blueprint_revision_id = blueprint_row["current_revision_id"] if blueprint_row else None
            if not blueprint_revision_id:
                raise DomainError("blueprint_required", "请先确认全作方向，再整理作品结构。", status=409)
            blueprint = self._revision_content(connection, blueprint_revision_id)
            messages = recent_conversation_history(connection, thread_id)
            conversation_summary = self._conversation_summary(connection, thread_id)
            structure_context = {
                "story_blueprint_revision_id": blueprint_revision_id,
                "story_blueprint": blueprint,
                "current_structure": snapshot["projection"],
                "task_contract": task_contract,
                "conversation_summary": conversation_summary,
            }
            agent_run_id = new_id("agent")
            agent_snapshot = {
                "schema_version": "structure-plan-agent-input/1.0",
                "work_id": work_id,
                "thread_id": thread_id,
                "thread_version": thread["version"],
                "messages": messages,
                "structure_context": structure_context,
                "structure_digest": snapshot["digest"],
            }
            snapshot_uri, snapshot_digest = self.repo.atomic_write_text(
                f"agent-runs/{agent_run_id}/input.json",
                json.dumps(agent_snapshot, ensure_ascii=False, indent=2) + "\n",
            )
            run = connection.execute(
                "SELECT id FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1", (work_id,)
            ).fetchone()
            run_id = run["id"] if run else new_id("run")
            if not run:
                connection.execute(
                    "INSERT INTO production_runs VALUES (?,?,?,?,?,?,?,?)",
                    (run_id, work_id, "creation", thread["permission_mode"], "running", "[]", timestamp, timestamp),
                )
            else:
                connection.execute("UPDATE production_runs SET status='running',updated_at=? WHERE id=?", (timestamp, run_id))
            work_item_id = new_id("item")
            attempt_id = new_id("attempt")
            input_refs = {
                "workflow": "structure.plan",
                "work_version": version,
                "thread_id": thread_id,
                "thread_version": thread["version"],
                "story_blueprint_revision_id": blueprint_revision_id,
                "structure_digest": snapshot["digest"],
                "agent_run_id": agent_run_id,
                "input_digest": snapshot_digest,
                "retry_of": str(payload.get("_retry_of") or "") or None,
            }
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_run_id, work_id, "work", work_id, "整理卷、章与场景结构候选。",
                    "running",
                    canonical_json({
                        "workflow": "structure.plan", "write_boundary": "proposal_only",
                        "thread_id": thread_id,
                        "story_blueprint_revision_id": blueprint_revision_id,
                        "structure_digest": snapshot["digest"],
                        "retry_of_agent_run_id": str(payload.get("_retry_of") or "") or None,
                    }),
                    snapshot_uri, snapshot_digest, None, None, timestamp, None,
                ),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("tool"), agent_run_id, 1, "load_workflow_template", "succeeded",
                    snapshot_digest, "structure.plan", None, timestamp, timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("tool"), agent_run_id, 2, "read_story_blueprint_and_structure", "succeeded",
                    snapshot_digest, blueprint_revision_id, None, timestamp, timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    work_item_id, run_id, "structure.plan", "work", work_id, "running",
                    canonical_json(input_refs), "[]",
                    canonical_json({
                        "proposal_required": True, "retryable": True, "agent_run_id": agent_run_id,
                    }),
                    1, None, timestamp, timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, work_item_id, 1, provider.kind, snapshot_digest, "started", None, None, timestamp, None),
            )
        try:
            with self._provider_lock:
                raw_plan = provider.generate_structure_plan(messages, structure_context)
                usage = self._provider_usage(provider)
            plan = self._validate_structure_plan(raw_plan)
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else "writing_provider_failed"
            message = exc.message if isinstance(exc, DomainError) else "模型未能生成作品结构，本次没有创建候选。"
            self._fail_structure_work_item(
                work_item_id, attempt_id, run_id, agent_run_id, code, message
            )
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                "writing_provider_failed",
                message,
                status=502,
                details={"operation": "structure.plan", "provider": provider.kind},
            ) from exc

        base_volume = snapshot["projection"]["volumes"][0]
        base_chapter = snapshot["projection"]["chapters"][0]
        default_mode = str(blueprint.get("mode") or "bond_short")
        if default_mode not in MODE_SOURCES:
            default_mode = "bond_short"
        candidate_volumes = []
        for volume_index, volume in enumerate(plan["volumes"], start=1):
            volume_id = base_volume["id"] if volume_index == 1 else new_id("volume")
            candidate_chapters = []
            for chapter_index, chapter in enumerate(volume["chapters"], start=1):
                reuse_placeholder = volume_index == 1 and chapter_index == 1
                chapter_id = base_chapter["id"] if reuse_placeholder else new_id("chapter")
                candidate_scenes = []
                for scene_index, scene in enumerate(chapter["scenes"], start=1):
                    candidate_scenes.append({
                        "id": new_id("scene"),
                        "operation": "create",
                        "stable_order_key": f"{scene_index:06d}",
                        "title": scene["title"],
                        "contract": {
                            "goal": scene["goal"],
                            "location": scene["location"],
                            "known_facts": [],
                            "forbidden_reveals": [],
                            "stop_boundary": scene["stop_boundary"],
                            "writing_mode": scene["writing_mode"] or default_mode,
                        },
                    })
                candidate_chapters.append({
                    "id": chapter_id,
                    "operation": "reuse_placeholder" if reuse_placeholder else "create",
                    "stable_order_key": f"{chapter_index:06d}",
                    "title": chapter["title"],
                    "goal": chapter["goal"],
                    "scenes": candidate_scenes,
                })
            candidate_volumes.append({
                "id": volume_id,
                "operation": "reuse_placeholder" if volume_index == 1 else "create",
                "stable_order_key": f"{volume_index:06d}",
                "title": volume["title"],
                "goal": volume["purpose"],
                "chapters": candidate_chapters,
            })
        skill = self.ba_skill.descriptor()
        candidate = {
            "schema_version": "structure-plan-proposal/1.0",
            "work_id": work_id,
            "base": {
                "story_blueprint_revision_id": blueprint_revision_id,
                "structure_digest": snapshot["digest"],
                "entity_versions": {base_volume["id"]: base_volume["version"], base_chapter["id"]: base_chapter["version"]},
            },
            "plan": {"summary": plan["summary"], "volumes": candidate_volumes},
            "source_thread_id": thread_id,
                "source_message_ids": [item["id"] for item in messages],
                "conversation_summary_digest": conversation_summary["digest"],
            "writing_pack": {
                "id": PACK_VERSION,
                "template_id": "structure.plan",
                "template_version": task_contract.get("version"),
                "source_digest": skill.get("source_digest"),
            },
        }
        proposal_id = new_id("proposal")
        candidate_uri, candidate_hash = self.repo.atomic_write_text(
            f"artifacts/proposals/{proposal_id}.json", json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"
        )
        conflict_error = None
        with self._structure_persist_transaction(
            work_item_id, attempt_id, run_id, agent_run_id
        ) as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            current_version = self._check_work_version(connection, work_id, expected_work)
            current_thread = self._check_thread_version(connection, work_id, thread_id, expected_thread)
            current_snapshot = self._structure_snapshot(connection, work_id)
            current_blueprint = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)
            ).fetchone()
            if current_snapshot["digest"] != snapshot["digest"] or (current_blueprint["current_revision_id"] if current_blueprint else None) != blueprint_revision_id:
                conflict_error = DomainError("structure_plan_inputs_changed", "生成期间作品方向或结构发生变化，请重新整理。", status=409)
                error = {"code": conflict_error.code, "message": conflict_error.message, "retryable": False}
                connection.execute("UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'", (error["code"], now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                connection.execute("UPDATE production_runs SET status='failed',updated_at=? WHERE id=?", (now(), run_id))
                connection.execute(
                    "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                    (canonical_json(error), now(), agent_run_id),
                )
            else:
                diff = {
                    "format": "structure-tree/1.0",
                    "changes": [
                        {"kind": "volume", "id": volume["id"], "operation": volume["operation"], "title": volume["title"]}
                        for volume in candidate_volumes
                    ] + [
                        {"kind": "chapter", "id": chapter["id"], "operation": chapter["operation"], "title": chapter["title"]}
                        for volume in candidate_volumes for chapter in volume["chapters"]
                    ] + [
                        {"kind": "scene", "id": scene["id"], "operation": "create", "title": scene["title"], "goal": scene["contract"]["goal"]}
                        for volume in candidate_volumes for chapter in volume["chapters"] for scene in chapter["scenes"]
                    ],
                }
                connection.execute(
                    "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        proposal_id, work_id, "story_structure", "work", work_id, blueprint_revision_id,
                        candidate_uri, candidate_hash, canonical_json(diff),
                        canonical_json({"source_message_ids": candidate["source_message_ids"], "story_blueprint_revision_id": blueprint_revision_id, "structure_digest": snapshot["digest"]}),
                        "high", "pending", canonical_json(provider.descriptor()), now(), None,
                    ),
                )
                self._append_conversation_message(
                    connection, thread_id, "assistant", "proposal",
                    {"text": "我已把讨论整理成卷、章与场景结构候选。稳定 ID 已由系统固定，采纳前不会建立任何场景。", "proposal_id": proposal_id},
                    provider=provider.descriptor(), proposal_id=proposal_id, usage=usage,
                )
                connection.execute("UPDATE conversation_threads SET phase='execute',version=version+1,updated_at=? WHERE id=?", (now(), current_thread["id"]))
                connection.execute("UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?", (proposal_id, now(), attempt_id))
                connection.execute(
                    "UPDATE work_items SET status='waiting_user',output_refs_json=?,acceptance_json=?,updated_at=? WHERE id=?",
                    (canonical_json([{"proposal_id": proposal_id}]), canonical_json({"proposal_required": True, "proposal_id": proposal_id, "usage": usage}), now(), work_item_id),
                )
                connection.execute("UPDATE production_runs SET status='waiting_user',updated_at=? WHERE id=?", (now(), run_id))
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("tool"), agent_run_id, 3, "create_structure_proposal", "succeeded",
                        snapshot_digest, proposal_id, None, now(), now(),
                    ),
                )
                connection.execute(
                    "UPDATE agent_runs SET status='waiting_user',proposal_id=?,policy_json=?,finished_at=? WHERE id=?",
                    (
                        proposal_id,
                        canonical_json({
                            "workflow": "structure.plan", "write_boundary": "proposal_only",
                            "thread_id": thread_id,
                            "story_blueprint_revision_id": blueprint_revision_id,
                            "structure_digest": snapshot["digest"], "usage": usage,
                            "retry_of_agent_run_id": str(payload.get("_retry_of") or "") or None,
                        }),
                        now(), agent_run_id,
                    ),
                )
                self._bump_work(connection, work_id, current_version)
        if conflict_error:
            raise conflict_error
        return {
            "agent_run_id": agent_run_id,
            "proposal_id": proposal_id,
            "work_item_id": work_item_id,
            "simulation": provider.is_simulation,
            "work": self.get_work(work_id),
        }

    def _organize_chapter_plan_proposal(
        self, work_id: str, thread_id: str, payload: dict, scope: dict, provider=None
    ):
        provider = provider if provider is not None else self.provider
        expected_work = int(payload.get("expected_version", -1))
        expected_thread = int(payload.get("expected_thread_version", -1))
        chapter_id = str(scope.get("chapter_id", "")).strip()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected_work)
            thread = self._check_thread_version(connection, work_id, thread_id, expected_thread)
            self._conversation_policy(connection, thread, retry=True)
            chapter = connection.execute(
                "SELECT id,title FROM chapters WHERE id=? AND work_id=?", (chapter_id, work_id)
            ).fetchone()
            if not chapter:
                raise DomainError("invalid_writing_target", "请先选择一章，再整理章内细纲。", status=409)
            if connection.execute(
                "SELECT 1 FROM proposals WHERE work_id=? AND kind='chapter_plan' AND scope_id=? AND status='pending'",
                (work_id, chapter_id),
            ).fetchone():
                raise DomainError("proposal_waiting_user", "本章已有细纲候选等待决定，请先采纳或退回。", status=409)
            messages = recent_conversation_history(connection, thread_id)
            if not any(item["role"] == "user" and item["text"] for item in messages):
                raise DomainError("discussion_required", "请先和 Agent 讨论本章要完成的变化。", status=409)
            target_revision = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='writing_target'", (work_id,)
            ).fetchone()
            blueprint_revision = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)
            ).fetchone()
            chapter_context = {
                "chapter_id": chapter_id,
                "chapter_title": chapter["title"],
                "story_blueprint_revision_id": blueprint_revision["current_revision_id"] if blueprint_revision else None,
                "writing_target_revision_id": target_revision["current_revision_id"] if target_revision else None,
                "task_contract": self._conversation_task_contract(
                    connection,
                    work_id,
                    {"surface": "chapter", "chapter_id": chapter_id},
                ),
                "conversation_summary": self._conversation_summary(connection, thread_id),
            }
            candidate_plan = provider.generate_chapter_plan(messages, chapter_context)
            candidate_plan = self._validate_chapter_plan(candidate_plan)
            candidate_plan["status"] = "proposed"
            candidate = {
                "schema_version": "chapter-plan-proposal/1.0",
                "chapter_id": chapter_id,
                "chapter_title": chapter["title"],
                "chapter_plan": candidate_plan,
                "story_blueprint_revision_id": chapter_context["story_blueprint_revision_id"],
                "writing_target_revision_id": chapter_context["writing_target_revision_id"],
                "base_revision_id": connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='chapter_plan' AND scope_id=?",
                    (work_id, chapter_id),
                ).fetchone()[0] if connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='chapter_plan' AND scope_id=?",
                    (work_id, chapter_id),
                ).fetchone() else None,
                "source_thread_id": thread_id,
                "source_message_ids": [
                    row["id"] for row in connection.execute(
                        "SELECT id FROM conversation_messages WHERE thread_id=? ORDER BY ordinal", (thread_id,)
                    ).fetchall()
                ],
            }
            proposal_id = new_id("proposal")
            candidate_uri, candidate_hash = self.repo.atomic_write_text(
                f"artifacts/proposals/{proposal_id}.json",
                json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            )
            diff = {
                "format": "chapter-plan-fields/1.0",
                "changes": [{"field": "章内细纲", "after": candidate_plan.get("chapter_goal", "")}],
            }
            timestamp = now()
            connection.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    proposal_id, work_id, "chapter_plan", "chapter", chapter_id,
                    candidate["base_revision_id"], candidate_uri, candidate_hash,
                    canonical_json(diff), canonical_json(candidate["source_message_ids"]),
                    "medium", "pending", canonical_json(provider.descriptor()), timestamp, None,
                ),
            )
            self._append_conversation_message(
                connection, thread_id, "assistant", "proposal",
                {"text": f"我已整理《{chapter['title']}》的章内细纲候选。它不会替换全作方向，先由你审查。", "proposal_id": proposal_id},
                provider=provider.descriptor(), proposal_id=proposal_id,
            )
            connection.execute(
                "UPDATE conversation_threads SET phase='execute',version=version+1,updated_at=? WHERE id=?",
                (timestamp, thread_id),
            )
            self._bump_work(connection, work_id, version)
        return {"proposal_id": proposal_id, "simulation": provider.is_simulation, "work": self.get_work(work_id)}

    @staticmethod
    def _validate_chapter_plan(value: dict) -> dict:
        if not isinstance(value, dict):
            raise DomainError("provider_output_invalid", "模型返回的章节细纲不是结构化对象。", status=502)
        goal = str(value.get("chapter_goal") or "").strip()
        beats = value.get("beats")
        notes = value.get("continuity_notes", [])
        if not goal:
            raise DomainError("provider_output_invalid", "章节细纲缺少明确的本章目标。", status=502, details={"field": "chapter_goal"})
        if not isinstance(beats, list) or not beats or any(not isinstance(item, str) or not item.strip() for item in beats):
            raise DomainError("provider_output_invalid", "章节细纲的场景节拍必须是非空有序列表。", status=502, details={"field": "beats"})
        if not isinstance(notes, list) or any(not isinstance(item, str) or not item.strip() for item in notes):
            raise DomainError("provider_output_invalid", "章节细纲的承接说明格式无效。", status=502, details={"field": "continuity_notes"})
        return {
            **value,
            "schema_version": str(value.get("schema_version") or "chapter-plan/1.0"),
            "title": str(value.get("title") or "章节细纲").strip() or "章节细纲",
            "chapter_goal": goal,
            "beats": [item.strip() for item in beats],
            "continuity_notes": [item.strip() for item in notes],
        }

    @staticmethod
    def _validate_story_blueprint(value: dict) -> dict:
        if not isinstance(value, dict):
            raise DomainError("provider_output_invalid", "模型返回的故事方向不是结构化对象。", status=502)
        required_text = {
            "title": "故事方向缺少标题。",
            "premise": "故事方向缺少明确的故事前提。",
            "central_conflict": "故事方向缺少核心冲突。",
        }
        normalized = dict(value)
        for field, message in required_text.items():
            text = str(value.get(field) or "").strip()
            if not text:
                raise DomainError("provider_output_invalid", message, status=502, details={"field": field})
            normalized[field] = text
        directions = value.get("direction")
        if not isinstance(directions, list) or not directions or any(
            not isinstance(item, str) or not item.strip() for item in directions
        ):
            raise DomainError(
                "provider_output_invalid", "故事方向必须包含非空的有序推进列表。", status=502,
                details={"field": "direction"},
            )
        characters = value.get("characters")
        if not isinstance(characters, list) or not characters or any(
            not isinstance(item, str) or not item.strip() for item in characters
        ):
            raise DomainError(
                "provider_output_invalid", "故事方向必须给出至少一个主要角色。", status=502,
                details={"field": "characters"},
            )
        mode_aliases = {
            "主线与战斗": "main_battle",
            "长篇喜剧": "long_comedy",
            "羁绊短场景": "bond_short",
            "小说化阅读": "text_reading",
        }
        mode = str(value.get("mode") or "").strip()
        mode = mode_aliases.get(mode, mode)
        if mode not in MODE_SOURCES:
            raise DomainError(
                "provider_output_invalid", "故事方向返回了未知的 BA 写作模式。", status=502,
                details={"field": "mode", "value": mode},
            )
        recommendations = value.get("recommendations")
        if recommendations is None:
            recommendations = {}
        if not isinstance(recommendations, dict):
            raise DomainError(
                "provider_output_invalid", "故事方向的推荐项格式无效。", status=502,
                details={"field": "recommendations"},
            )
        secondary_modes = recommendations.get("secondary_scene_modes", [])
        if isinstance(secondary_modes, list):
            secondary_modes = [mode_aliases.get(str(item).strip(), item) for item in secondary_modes]
        if not isinstance(secondary_modes, list) or any(item not in MODE_SOURCES for item in secondary_modes):
            raise DomainError(
                "provider_output_invalid", "故事方向包含未知的辅助写作模式。", status=502,
                details={"field": "recommendations.secondary_scene_modes"},
            )
        sensei_presence = str(recommendations.get("sensei_presence") or "auto")
        if sensei_presence not in {"auto", "present", "absent"}:
            raise DomainError(
                "provider_output_invalid", "老师出场建议无效。", status=502,
                details={"field": "recommendations.sensei_presence"},
            )
        normalized.update({
            "schema_version": str(value.get("schema_version") or "story-blueprint/1.0"),
            "theme": str(value.get("theme") or "").strip(),
            "direction": [item.strip() for item in directions],
            "characters": [item.strip() for item in characters],
            "mode": mode,
            "recommendations": {
                **recommendations,
                "primary_scene_mode": mode,
                "secondary_scene_modes": list(dict.fromkeys(secondary_modes)),
                "character_card_ids": [
                    str(item).strip() for item in recommendations.get("character_card_ids", [])
                    if str(item).strip()
                ],
                "sensei_presence": sensei_presence,
            },
        })
        return normalized

    def _artifact(self, connection, work_id: str, kind: str, scope_type: str, scope_id: str):
        row = connection.execute(
            "SELECT * FROM artifacts WHERE work_id=? AND kind=? AND scope_type=? AND scope_id=?",
            (work_id, kind, scope_type, scope_id),
        ).fetchone()
        if row:
            return dict(row)
        artifact_id = new_id("artifact")
        connection.execute(
            "INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)",
            (artifact_id, work_id, kind, scope_type, scope_id, None, now()),
        )
        return {"id": artifact_id, "current_revision_id": None}

    def _add_revision(
        self,
        connection,
        artifact: dict,
        content,
        created_by: str,
        provenance: dict,
        schema_version: str = "1.0",
    ):
        revision_id = new_id("revision")
        count = connection.execute("SELECT COUNT(*) FROM revisions WHERE artifact_id=?", (artifact["id"],)).fetchone()[0]
        text = canonical_json(content) + "\n"
        uri, digest = self.repo.atomic_write_text(f"artifacts/{artifact['id']}/{revision_id}.json", text)
        connection.execute(
            "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?,?)",
            (revision_id, artifact["id"], artifact.get("current_revision_id"), count + 1, schema_version, uri, digest, canonical_json(provenance), created_by, now()),
        )
        connection.execute("UPDATE artifacts SET current_revision_id=? WHERE id=?", (revision_id, artifact["id"]))
        return revision_id

    @staticmethod
    def _scene_blocks_from_text(text: str, namespace: str = "") -> list[dict]:
        blocks = []
        for index, raw_line in enumerate(str(text).splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            ascii_divider = line.find(":")
            chinese_divider = line.find("：")
            dividers = [value for value in (ascii_divider, chinese_divider) if value >= 0]
            divider = min(dividers) if dividers else -1
            digest = sha256_text(f"{namespace}:{index}:{line}").split(":", 1)[1][:12]
            block_id = f"block-{digest}"
            if divider > 0 and line[:divider].strip():
                speaker = line[:divider].strip()
                if speaker in {"旁白", "叙述"}:
                    blocks.append({"id": block_id, "type": "narration", "text": line[divider + 1:].strip()})
                else:
                    blocks.append({
                        "id": block_id,
                        "type": "dialogue",
                        "speaker": speaker,
                        "text": line[divider + 1:].strip(),
                    })
            else:
                blocks.append({"id": block_id, "type": "action", "text": line})
        return blocks

    @staticmethod
    def _scene_text_from_blocks(blocks: list[dict]) -> str:
        lines = []
        for block in blocks:
            if block["type"] == "dialogue":
                lines.append(f"{block['speaker']}: {block['text']}")
            elif block["type"] == "narration":
                lines.append(f"旁白: {block['text']}")
            else:
                lines.append(block["text"])
        return "\n".join(lines) + ("\n" if lines else "")

    def _normalize_scene_blocks(self, blocks) -> list[dict]:
        if not isinstance(blocks, list) or not blocks:
            raise DomainError("validation_error", "正文至少需要一个对白或动作块。", details={"field": "blocks"})
        normalized = []
        seen_ids = set()
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise DomainError("validation_error", "正文块格式无效。", details={"index": index})
            block_id = str(block.get("id", "")).strip()
            block_type = str(block.get("type", "")).strip()
            text = str(block.get("text", "")).strip()
            suffix = block_id[6:] if block_id.startswith("block-") else ""
            if (
                not suffix
                or len(block_id) > 96
                or not suffix.isascii()
                or any(not (char.isalnum() or char in "_-") for char in suffix)
            ):
                raise DomainError("validation_error", "正文块需要稳定且有效的 ID。", details={"index": index, "field": "id"})
            if block_id in seen_ids:
                raise DomainError("validation_error", "正文块 ID 不能重复。", details={"index": index, "id": block_id})
            if block_type not in {"action", "narration", "dialogue"}:
                raise DomainError("validation_error", "正文块类型只能是 action、narration 或 dialogue。", details={"index": index})
            if not text:
                raise DomainError("validation_error", "正文块内容不能为空。", details={"index": index, "field": "text"})
            item = {"id": block_id, "type": block_type, "text": text}
            if block_type == "dialogue":
                speaker = str(block.get("speaker", "")).strip()
                if not speaker:
                    raise DomainError("validation_error", "对白块必须填写说话人。", details={"index": index, "field": "speaker"})
                item["speaker"] = speaker
            normalized.append(item)
            seen_ids.add(block_id)
        return normalized

    def _scene_content_from_text(self, text: str, namespace: str = "") -> dict:
        blocks = self._scene_blocks_from_text(text, namespace)
        return {"schema_version": "scene-blocks/1.0", "blocks": blocks, "text": str(text)}

    @staticmethod
    def _scene_block_identity(block: dict) -> tuple[str, str, str]:
        return (
            str(block.get("type", "")),
            str(block.get("speaker", "")) if block.get("type") == "dialogue" else "",
            str(block.get("text", "")),
        )

    def _scene_content_preserving_unchanged_blocks(
        self,
        text: str,
        base_blocks: list[dict] | None,
    ) -> dict:
        """Parse candidate text while retaining identities of exact unchanged blocks."""
        candidate_blocks = self._scene_blocks_from_text(text)
        previous = [dict(block) for block in base_blocks or []]
        matcher = difflib.SequenceMatcher(
            a=[self._scene_block_identity(block) for block in previous],
            b=[self._scene_block_identity(block) for block in candidate_blocks],
            autojunk=False,
        )
        retained: dict[int, str] = {}
        used_ids: set[str] = set()
        for match in matcher.get_matching_blocks():
            for offset in range(match.size):
                block_id = str(previous[match.a + offset].get("id", "")).strip()
                if block_id and block_id not in used_ids:
                    retained[match.b + offset] = block_id
                    used_ids.add(block_id)

        for index, block in enumerate(candidate_blocks):
            block_id = retained.get(index)
            if not block_id:
                block_id = new_id("block")
                while block_id in used_ids:
                    block_id = new_id("block")
            block["id"] = block_id
            used_ids.add(block_id)
        return {"schema_version": "scene-blocks/1.0", "blocks": candidate_blocks, "text": str(text)}

    def _scene_block_change_plan(
        self,
        base_blocks: list[dict] | None,
        candidate_text: str,
        candidate_hash: str,
    ) -> list[dict]:
        previous = [dict(block) for block in base_blocks or []]
        candidate = self._scene_blocks_from_text(candidate_text)
        changes = []
        for ordinal, (kind, base_start, base_end, candidate_start, candidate_end) in enumerate(
            self._scene_block_alignment(previous, candidate)
        ):
            if kind == "equal":
                continue
            old_blocks = previous[base_start:base_end]
            new_blocks = candidate[candidate_start:candidate_end]
            digest = sha256_text(canonical_json({
                "candidate_hash": candidate_hash,
                "ordinal": ordinal,
                "kind": kind,
                "base_start": base_start,
                "base_end": base_end,
                "old": [self._scene_block_identity(block) for block in old_blocks],
                "new": [self._scene_block_identity(block) for block in new_blocks],
            })).split(":", 1)[1][:12]
            changes.append({
                "id": f"change-{digest}",
                "kind": kind,
                "base_start": base_start,
                "base_end": base_end,
                "old_blocks": old_blocks,
                "new_blocks": [
                    {key: value for key, value in block.items() if key != "id"}
                    for block in new_blocks
                ],
                # Keep a character-level, read-only explanation alongside the
                # block operation. The block plan remains authoritative for
                # partial acceptance; this is presentation evidence only.
                "inline_diff": self._scene_inline_diff(old_blocks, new_blocks),
            })
        return changes

    @classmethod
    def _scene_block_alignment(
        cls,
        previous: list[dict],
        candidate: list[dict],
    ) -> list[tuple[str, int, int, int, int]]:
        """Align changed script blocks without collapsing a rewritten scene."""
        old_count = len(previous)
        new_count = len(candidate)
        costs = [[0.0] * (new_count + 1) for _ in range(old_count + 1)]
        steps: list[list[str | None]] = [
            [None] * (new_count + 1) for _ in range(old_count + 1)
        ]
        for old_index in range(1, old_count + 1):
            costs[old_index][0] = float(old_index)
            steps[old_index][0] = "delete"
        for new_index in range(1, new_count + 1):
            costs[0][new_index] = float(new_index)
            steps[0][new_index] = "insert"

        def replacement_cost(old: dict, new: dict) -> float:
            if cls._scene_block_identity(old) == cls._scene_block_identity(new):
                return 0.0
            old_type = str(old.get("type", ""))
            new_type = str(new.get("type", ""))
            old_speaker = str(old.get("speaker", "")) if old_type == "dialogue" else ""
            new_speaker = str(new.get("speaker", "")) if new_type == "dialogue" else ""
            similarity = difflib.SequenceMatcher(
                a=str(old.get("text", "")),
                b=str(new.get("text", "")),
                autojunk=False,
            ).ratio()
            if (old_type, old_speaker) == (new_type, new_speaker):
                return 0.25 + (1.0 - similarity) * 0.5
            if old_type == new_type:
                return 1.05 + (1.0 - similarity) * 0.35
            return 1.45 + (1.0 - similarity) * 0.35

        for old_index in range(1, old_count + 1):
            for new_index in range(1, new_count + 1):
                replace = costs[old_index - 1][new_index - 1] + replacement_cost(
                    previous[old_index - 1], candidate[new_index - 1]
                )
                delete = costs[old_index - 1][new_index] + 1.0
                insert = costs[old_index][new_index - 1] + 1.0
                best_cost, _priority, best = min(
                    (replace, 0, "replace"),
                    (delete, 1, "delete"),
                    (insert, 2, "insert"),
                )
                costs[old_index][new_index] = best_cost
                steps[old_index][new_index] = best

        alignment = []
        old_index, new_index = old_count, new_count
        while old_index or new_index:
            step = steps[old_index][new_index]
            if step == "replace":
                old_start = old_index - 1
                new_start = new_index - 1
                kind = (
                    "equal"
                    if cls._scene_block_identity(previous[old_start])
                    == cls._scene_block_identity(candidate[new_start])
                    else "replace"
                )
                alignment.append((kind, old_start, old_index, new_start, new_index))
                old_index -= 1
                new_index -= 1
            elif step == "delete":
                alignment.append(("delete", old_index - 1, old_index, new_index, new_index))
                old_index -= 1
            elif step == "insert":
                alignment.append(("insert", old_index, old_index, new_index - 1, new_index))
                new_index -= 1
            else:
                raise RuntimeError("scene block alignment could not be reconstructed")
        alignment.reverse()
        return alignment

    @staticmethod
    def _scene_inline_diff(old_blocks: list[dict], new_blocks: list[dict]) -> list[dict]:
        """Return bounded character-level evidence for changed script blocks."""
        pairs = []
        count = max(len(old_blocks), len(new_blocks))
        for index in range(count):
            old = old_blocks[index] if index < len(old_blocks) else None
            new = new_blocks[index] if index < len(new_blocks) else None
            old_text = str((old or {}).get("text") or "")
            new_text = str((new or {}).get("text") or "")
            old_speaker = str((old or {}).get("speaker") or "")
            new_speaker = str((new or {}).get("speaker") or "")
            old_type = str((old or {}).get("type") or "")
            new_type = str((new or {}).get("type") or "")
            matcher = difflib.SequenceMatcher(a=old_text, b=new_text, autojunk=False)
            segments = []
            for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
                if tag == "equal":
                    segments.append({"kind": "equal", "text": old_text[old_start:old_end]})
                else:
                    if old_start != old_end:
                        segments.append({"kind": "delete", "text": old_text[old_start:old_end]})
                    if new_start != new_end:
                        segments.append({"kind": "insert", "text": new_text[new_start:new_end]})
            pairs.append({
                "index": index,
                "old_block_id": (old or {}).get("id"),
                "new_block_id": (new or {}).get("id"),
                "old_speaker": old_speaker,
                "new_speaker": new_speaker,
                "old_type": old_type,
                "new_type": new_type,
                "old_text": old_text,
                "new_text": new_text,
                "segments": segments,
            })
        return pairs

    def _apply_scene_block_changes(
        self,
        base_blocks: list[dict] | None,
        changes: list[dict],
        selected_change_ids: set[str],
    ) -> str:
        previous = [dict(block) for block in base_blocks or []]
        output = []
        cursor = 0
        for change in changes:
            base_start = int(change["base_start"])
            base_end = int(change["base_end"])
            output.extend(previous[cursor:base_start])
            if change["id"] in selected_change_ids:
                output.extend(dict(block) for block in change["new_blocks"])
            else:
                output.extend(previous[base_start:base_end])
            cursor = base_end
        output.extend(previous[cursor:])
        return self._scene_text_from_blocks(output)

    def _scene_revision_blocks(self, connection, revision_id: str | None) -> list[dict]:
        if not revision_id:
            return []
        revision = connection.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
        if not revision:
            return []
        content = json.loads(self.repo.read_text(revision["content_uri"]))
        blocks = content.get("blocks")
        if isinstance(blocks, list):
            return blocks
        return self._scene_blocks_from_text(str(content.get("text", "")), revision["id"])

    def _analysis_character_cards(self, connection, work_id: str) -> list[dict]:
        cards = []
        rows = connection.execute(
            "SELECT * FROM artifacts WHERE work_id=? AND kind='character_card' AND current_revision_id IS NOT NULL",
            (work_id,),
        ).fetchall()
        for row in rows:
            revision = connection.execute("SELECT * FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
            content = json.loads(self.repo.read_text(revision["content_uri"]))
            if content.get("status", "active") == "archived":
                continue
            cards.append({
                "id": row["scope_id"],
                "name": content.get("name", ""),
                "canonical_name": content.get("canonical_name", ""),
                "aliases": content.get("aliases", []),
                "source_type": content.get("source_type", "custom"),
                "trust_status": content.get("trust_status", "open"),
            })
        return cards

    def _analysis_world_summary(self, connection, work_id: str) -> dict:
        artifact = connection.execute(
            "SELECT * FROM artifacts WHERE work_id=? AND kind='world_bible'", (work_id,)
        ).fetchone()
        if not artifact or not artifact["current_revision_id"]:
            return {
                "label": "尚未建立世界观基础",
                "detail": "当前作品没有世界观条目；可以先分析想法，确认方向后再建立原创设定。",
                "source_type": "blank",
                "total_items": 0,
                "confirmed_items": 0,
            }
        revision = connection.execute("SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone()
        bible = json.loads(self.repo.read_text(revision["content_uri"]))
        entries = [
            item for collection in ("entities", "rules", "timeline")
            for item in bible.get(collection, [])
            if item.get("status", "active") != "archived"
        ]
        source_type = bible.get("source_type", "custom")
        if source_type == "ba_starter":
            label = "BA 起始架构"
        elif source_type == "mixed":
            label = "BA 起始架构 + 本作自定义设定"
        else:
            label = "本作自定义世界观"
        return {
            "label": label,
            "detail": f"当前资料库有 {len(entries)} 项设定，其中 {sum(item.get('confidence_status') == 'confirmed' for item in entries)} 项已确认。未确认条目不会被当作既定事实。",
            "source_type": source_type,
            "total_items": len(entries),
            "confirmed_items": sum(item.get("confidence_status") == "confirmed" for item in entries),
            "revision_id": revision["id"],
        }

    def save_brief(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        intent_only = bool(payload.get("intent_only", False))
        mode = "pending_analysis" if intent_only else payload.get("mode", "bond_short")
        if not intent_only and mode not in MODE_SOURCES:
            raise DomainError("validation_error", "未知写作模式。", details={"mode": mode})
        idea = str(payload.get("idea", "")).strip()
        if not idea:
            raise DomainError("validation_error", "一句想法不能为空。", details={"field": "idea"})
        brief = {
            "idea": idea,
            "mode": mode,
            "characters": [str(x).strip() for x in payload.get("characters", []) if str(x).strip()],
            "character_card_ids": [str(x).strip() for x in payload.get("character_card_ids", []) if str(x).strip()],
            "target_length": payload.get("target_length", "short"),
            "constraints": str(payload.get("constraints", "")).strip(),
            "has_sensei": bool(payload.get("has_sensei", False)),
            "sensei_decision": "manual" if not intent_only else "pending_analysis",
            "status": "analysis_pending" if intent_only else "confirmed",
        }
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            artifact = self._artifact(connection, work_id, "brief", "work", work_id)
            revision_id = self._add_revision(connection, artifact, brief, "user", {
                "workflow": "brief.intent" if intent_only else "brief.build",
                "pack": PACK_VERSION,
            })
            self._bump_work(connection, work_id, version)
        return {"revision_id": revision_id, "work": self.get_work(work_id)}

    def generate_blueprint(self, work_id: str, payload: dict):
        provider = self.provider
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            brief_artifact = connection.execute("SELECT * FROM artifacts WHERE work_id=? AND kind='brief'", (work_id,)).fetchone()
            if not brief_artifact or not brief_artifact["current_revision_id"]:
                raise DomainError("brief_required", "请先保存写作想法。", status=409)
            brief_revision = connection.execute("SELECT * FROM revisions WHERE id=?", (brief_artifact["current_revision_id"],)).fetchone()
            brief = json.loads(self.repo.read_text(brief_revision["content_uri"]))
            analysis_context = {
                "character_cards": self._analysis_character_cards(connection, work_id),
                "world": self._analysis_world_summary(connection, work_id),
                "task_contract": self._conversation_task_contract(connection, work_id, {"surface": "work"}),
            }
            blueprint = self._validate_story_blueprint(provider.generate_blueprint(brief, analysis_context))
            feedback = str(payload.get("feedback", "")).strip()
            if feedback:
                blueprint["feedback"] = feedback
            # Older direct API consumers already submit a fully formed Brief.
            # The product UI submits an intent-only Brief and must confirm this proposal.
            blueprint["status"] = "proposed" if brief.get("status") == "analysis_pending" or feedback else "accepted"
            artifact = self._artifact(connection, work_id, "story_blueprint", "work", work_id)
            revision_id = self._add_revision(connection, artifact, blueprint, "agent", {
                "workflow": "blueprint.generate", "pack": PACK_VERSION,
                "provider": provider.descriptor(), "input_revisions": [brief_revision["id"]],
                "feedback": feedback or None,
            })
            self._bump_work(connection, work_id, version)
        return {"revision_id": revision_id, "simulation": provider.is_simulation, "work": self.get_work(work_id)}

    def confirm_blueprint(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        mode = str(payload.get("mode", "")).strip()
        if mode not in MODE_SOURCES:
            raise DomainError("validation_error", "请选择本场起草规则包。", details={"field": "mode"})
        requested_ids = [str(value).strip() for value in payload.get("character_card_ids", []) if str(value).strip()]
        if not requested_ids:
            raise DomainError("validation_error", "请从人物库选择至少一张人物卡。", details={"field": "character_card_ids"})
        sensei_decision = str(payload.get("sensei_presence", "auto")).strip()
        if sensei_decision not in {"auto", "present", "absent"}:
            raise DomainError("validation_error", "老师出场选择无效。", details={"field": "sensei_presence"})
        feedback = str(payload.get("feedback", "")).strip()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            brief_artifact = connection.execute("SELECT * FROM artifacts WHERE work_id=? AND kind='brief'", (work_id,)).fetchone()
            blueprint_artifact = connection.execute("SELECT * FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)).fetchone()
            if not brief_artifact or not brief_artifact["current_revision_id"] or not blueprint_artifact or not blueprint_artifact["current_revision_id"]:
                raise DomainError("blueprint_required", "请先分析写作想法。", status=409)
            brief_revision = connection.execute("SELECT * FROM revisions WHERE id=?", (brief_artifact["current_revision_id"],)).fetchone()
            blueprint_revision = connection.execute("SELECT * FROM revisions WHERE id=?", (blueprint_artifact["current_revision_id"],)).fetchone()
            brief = json.loads(self.repo.read_text(brief_revision["content_uri"]))
            blueprint = json.loads(self.repo.read_text(blueprint_revision["content_uri"]))
            if blueprint.get("status", "accepted") != "proposed":
                raise DomainError("blueprint_not_pending", "当前故事方向没有等待确认的候选。", status=409)
            available_cards = {card["id"]: card for card in self._analysis_character_cards(connection, work_id)}
            invalid_ids = [card_id for card_id in requested_ids if card_id not in available_cards]
            if invalid_ids:
                raise DomainError("validation_error", "选择的人物卡不属于当前作品。", details={"character_card_ids": invalid_ids})
            recommendations = blueprint.get("recommendations", {})
            has_sensei = (
                recommendations.get("sensei_presence") == "present"
                if sensei_decision == "auto"
                else sensei_decision == "present"
            )
            secondary = [
                item for item in recommendations.get("secondary_scene_modes", [])
                if item in MODE_SOURCES and item != mode
            ]
            confirmed_brief = {
                **brief,
                "mode": mode,
                "story_modes": [mode, *secondary],
                "characters": [available_cards[card_id]["name"] for card_id in requested_ids],
                "character_card_ids": requested_ids,
                "has_sensei": has_sensei,
                "sensei_decision": sensei_decision,
                "status": "confirmed",
                "constraints": feedback or brief.get("constraints", ""),
            }
            confirmed_brief_revision = self._add_revision(connection, dict(brief_artifact), confirmed_brief, "user", {
                "workflow": "brief.confirm", "pack": PACK_VERSION,
                "blueprint_revision_id": blueprint_revision["id"],
                "character_card_ids": requested_ids,
            })
            accepted_blueprint = {
                **blueprint,
                "status": "accepted",
                "decision": {
                    "mode": mode,
                    "character_card_ids": requested_ids,
                    "sensei_presence": sensei_decision,
                    "feedback": feedback,
                    "brief_revision_id": confirmed_brief_revision,
                },
            }
            accepted_blueprint_revision = self._add_revision(connection, dict(blueprint_artifact), accepted_blueprint, "user", {
                "workflow": "blueprint.confirm", "pack": PACK_VERSION,
                "input_revisions": [brief_revision["id"], blueprint_revision["id"]],
            })
            self._bump_work(connection, work_id, version)
        return {
            "brief_revision_id": confirmed_brief_revision,
            "blueprint_revision_id": accepted_blueprint_revision,
            "work": self.get_work(work_id),
        }

    def save_work_canon(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        canon = self._normalize_work_canon_payload(payload)
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            artifact = self._artifact(connection, work_id, "work_canon", "work", work_id)
            revision_id = self._add_revision(connection, artifact, canon, "user", {"workflow": "canon.assemble", "pack": PACK_VERSION, "source_type": "user_confirmed"})
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {"revision_id": revision_id, "work": self.get_work(work_id)}

    def _normalize_work_canon_fact(self, fact: dict, *, index: int) -> dict:
        if not isinstance(fact, dict):
            raise DomainError("validation_error", "作品事实必须是对象。", details={"index": index})
        text = str(fact.get("text", "")).strip()
        source = str(fact.get("source", "")).strip()
        confidence = str(fact.get("confidence_status", "confirmed")).strip() or "confirmed"
        scope = str(fact.get("scope", "work")).strip() or "work"
        status = str(fact.get("status", "active")).strip() or "active"
        if not text:
            raise DomainError("validation_error", "每条事实都需要内容。", details={"index": index})
        if not source:
            raise DomainError("validation_error", "每条事实都需要来源。", details={"index": index})
        if confidence not in {"confirmed", "inferred", "open", "conflict", "retired"}:
            raise DomainError("validation_error", "事实可信状态无效。", details={"index": index})
        if scope not in {"work", "chapter", "scene"}:
            raise DomainError("validation_error", "事实作用域无效。", details={"index": index})
        if status not in {"active", "archived"}:
            raise DomainError("validation_error", "事实状态无效。", details={"index": index})
        return {
            "id": str(fact.get("id", "")).strip() or new_id("fact"),
            "text": text,
            "source": source,
            "source_refs": self._normalize_knowledge_source_refs(
                fact.get("source_refs", []), field="facts.source_refs", index=index
            ),
            "confidence_status": confidence,
            "scope": scope,
            "status": status,
        }

    def _normalize_work_canon_payload(self, payload: dict) -> dict:
        facts = payload.get("facts", [])
        if not isinstance(facts, list):
            raise DomainError("validation_error", "事实清单必须是数组。", details={"field": "facts"})
        normalized = [self._normalize_work_canon_fact(fact, index=index) for index, fact in enumerate(facts)]
        fact_ids = [fact["id"] for fact in normalized]
        if len(fact_ids) != len(set(fact_ids)):
            raise DomainError("validation_error", "事实清单包含重复 ID。", details={"field": "facts.id"})
        return {"facts": normalized}

    def _normalize_character_card_payload(self, payload: dict) -> dict:
        name = str(payload.get("name", "")).strip()
        if not name:
            raise DomainError("validation_error", "角色名称不能为空。", details={"field": "name"})
        source_refs = self._normalize_knowledge_source_refs(
            payload.get("source_refs", []), field="source_refs"
        )
        if not source_refs:
            raise DomainError("validation_error", "人物卡至少需要一条来源。", details={"field": "source_refs"})
        source_type = str(payload.get("source_type", "custom")).strip()
        if source_type not in {"official_reference", "custom"}:
            raise DomainError("validation_error", "人物卡来源类型无效。", details={"field": "source_type"})
        trust_status = str(payload.get("trust_status", "confirmed")).strip() or "confirmed"
        if trust_status not in {"confirmed", "inferred", "open", "unverified", "conflict"}:
            raise DomainError("validation_error", "人物卡采用状态无效。", details={"field": "trust_status"})
        ba_profile = payload.get("ba_profile")
        if ba_profile is not None and not isinstance(ba_profile, dict):
            raise DomainError("validation_error", "BA 人物主档必须是对象。", details={"field": "ba_profile"})
        status = str(payload.get("status", "active")).strip() or "active"
        if status not in {"active", "archived"}:
            raise DomainError("validation_error", "人物卡状态无效。", details={"field": "status"})
        profile_format = str(payload.get("profile_format", "halocue-character-card/1.1")).strip()
        source_hash = str(payload.get("source_hash", "")).strip()
        if not source_hash:
            source_hash = sha256_text(canonical_json(ba_profile or {
                "name": name,
                "voice_anchors": payload.get("voice_anchors", []),
                "ooc_constraints": payload.get("ooc_constraints", []),
                "relationships": payload.get("relationships", []),
            }))
        card = {
            "profile_format": profile_format,
            "name": name,
            "canonical_name": str(payload.get("canonical_name", name)).strip() or name,
            "aliases": [str(item).strip() for item in payload.get("aliases", []) if str(item).strip()],
            "source_type": source_type,
            "role": str(payload.get("role", "")).strip(),
            "voice_anchors": [str(item).strip() for item in payload.get("voice_anchors", []) if str(item).strip()],
            "knowledge_boundary": str(payload.get("knowledge_boundary", "")).strip(),
            "ooc_constraints": [str(item).strip() for item in payload.get("ooc_constraints", []) if str(item).strip()],
            "relationships": [
                {
                    **(
                        {"id": str(item.get("id")).strip()}
                        if str(item.get("id") or "").strip()
                        else {}
                    ),
                    **(
                        {"target_character_id": str(item.get("target_character_id")).strip()}
                        if str(item.get("target_character_id") or "").strip()
                        else {}
                    ),
                    "target": str(item.get("target", "")).strip(),
                    "kind": str(item.get("kind", "关系待定")).strip(),
                    "summary": str(item.get("summary", "")).strip(),
                    "status": str(item.get("status", "confirmed")).strip(),
                }
                for item in payload.get("relationships", [])
                if isinstance(item, dict)
                and (
                    str(item.get("target", "")).strip()
                    or str(item.get("target_character_id", "")).strip()
                )
            ],
            "source_refs": source_refs,
            "source_hash": source_hash,
            "extractor_version": str(payload.get("extractor_version", "halocue-runtime-character/1.1")).strip(),
            "trust_status": trust_status,
            "ba_profile": ba_profile,
            "status": status,
        }
        for key in (
            "validation_report", "import_id", "import_filename", "import_source_label",
            "raw_import_uri", "cleaned_import_uri", "raw_import_hash", "cleaned_import_hash",
        ):
            if payload.get(key) is not None:
                card[key] = payload[key]
        return card

    def _save_character_card_revision(
        self,
        connection,
        work_id: str,
        card_id: str,
        card: dict,
        *,
        created_by: str,
        provenance: dict,
    ) -> str:
        artifact = self._artifact(connection, work_id, "character_card", "character", card_id)
        return self._add_revision(connection, artifact, card, created_by, provenance)

    def save_character_card(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        card = self._normalize_character_card_payload(payload)
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            # Card identity remains stable even when the display name changes.
            card_id = str(payload.get("card_id", "")).strip() or new_id("character")
            revision_id = self._save_character_card_revision(
                connection,
                work_id,
                card_id,
                card,
                created_by="user",
                provenance={"workflow": "character.prepare", "pack": PACK_VERSION, "source_refs": card["source_refs"]},
            )
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {"card_id": card_id, "revision_id": revision_id, "work": self.get_work(work_id)}

    def validate_character_card_import(self, work_id: str, payload: dict) -> dict:
        # Resolve the work up front so validation never appears to succeed for a stale target.
        with self.repo.connect() as connection:
            if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
        parsed = parse_import_payload(payload)
        preview = parsed.public_preview()
        preview["can_import"] = parsed.report["status"] == "PASS"
        return preview

    def _matching_character_cards(self, connection, work_id: str, imported: dict) -> list[dict]:
        imported_tokens = identity_tokens(imported)
        matches = []
        rows = connection.execute(
            "SELECT * FROM artifacts WHERE work_id=? AND kind='character_card' AND current_revision_id IS NOT NULL",
            (work_id,),
        ).fetchall()
        for row in rows:
            revision = connection.execute("SELECT * FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
            if not revision:
                continue
            content = json.loads(self.repo.read_text(revision["content_uri"]))
            if imported_tokens.intersection(identity_tokens(content)):
                matches.append({"card_id": row["scope_id"], "name": content.get("name", ""), "revision_id": revision["id"]})
        return matches

    def import_character_card(self, work_id: str, payload: dict) -> dict:
        expected = int(payload.get("expected_version", -1))
        parsed = parse_import_payload(payload)
        if parsed.report["status"] != "PASS":
            raise validation_failure(parsed)
        source_label = str(payload.get("source_label", "用户导入的 BA 正式人物卡")).strip() or "用户导入的 BA 正式人物卡"
        import_id = new_id("character-import")
        import_mode = "created"
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            matches = self._matching_character_cards(connection, work_id, parsed.cleaned)
            if len(matches) > 1:
                raise DomainError(
                    "character_card_identity_conflict",
                    "人物卡名称或别名同时命中多张现有卡，请先在人物库处理重复身份。",
                    status=409,
                    details={"character": parsed.report["character"], "matches": matches},
                )
            if matches:
                card_id = matches[0]["card_id"]
                import_mode = "updated"
            else:
                card_id = new_id("character")
            prefix = f"imports/character-cards/{work_id}/{card_id}/{import_id}"
            raw_uri, raw_hash = self.repo.atomic_write_bytes(f"{prefix}/original.json", parsed.raw_bytes)
            cleaned_uri, cleaned_hash = self.repo.atomic_write_bytes(f"{prefix}/cleaned.json", parsed.cleaned_bytes)
            card_payload = build_character_card_payload(parsed, source_label)
            card_payload.update({
                "import_id": import_id,
                "import_source_label": source_label,
                "raw_import_uri": raw_uri,
                "cleaned_import_uri": cleaned_uri,
                "raw_import_hash": raw_hash,
                "cleaned_import_hash": cleaned_hash,
            })
            card = self._normalize_character_card_payload(card_payload)
            revision_id = self._save_character_card_revision(
                connection,
                work_id,
                card_id,
                card,
                created_by="user",
                provenance={
                    "workflow": "character.prepare",
                    "operation": "ba_character_card_import",
                    "pack": PACK_VERSION,
                    "import_id": import_id,
                    "source_hash": parsed.source_hash,
                    "validation_schema": parsed.report["schema_version"],
                },
            )
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {
            "card_id": card_id,
            "revision_id": revision_id,
            "validation_report": parsed.report,
            "import_mode": import_mode,
            "source_hash": parsed.source_hash,
            "work": self.get_work(work_id),
        }

    def archive_character_card(self, work_id: str, card_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            artifact = connection.execute(
                "SELECT * FROM artifacts WHERE work_id=? AND kind='character_card' AND scope_type='character' AND scope_id=?",
                (work_id, card_id),
            ).fetchone()
            if not artifact or not artifact["current_revision_id"]:
                raise NotFound("character_card", card_id)
            revision = connection.execute("SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone()
            card = json.loads(self.repo.read_text(revision["content_uri"]))
            if card.get("status") == "archived":
                raise DomainError("already_archived", "人物卡已经归档。", status=409)
            card["status"] = "archived"
            revision_id = self._add_revision(connection, dict(artifact), card, "user", {
                "workflow": "character.archive", "pack": PACK_VERSION, "source_revision_id": revision["id"],
            })
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {"card_id": card_id, "revision_id": revision_id, "work": self.get_work(work_id)}

    def _merge_world_source_type(self, source_types: list[str]) -> str:
        values = set(source_types)
        if "ba_starter" in values and len(values) == 1:
            return "ba_starter"
        if len(values) > 1 or "mixed" in values:
            return "mixed"
        return next(iter(values), "custom")

    @staticmethod
    def _normalize_knowledge_source_refs(value, *, field: str, index: int | None = None) -> list:
        if value is None:
            return []
        if not isinstance(value, list):
            details = {"field": field}
            if index is not None:
                details["index"] = index
            raise DomainError("validation_error", "资料来源引用必须是数组。", details=details)
        normalized = []
        for source_index, item in enumerate(value):
            if isinstance(item, dict):
                if not item:
                    continue
                normalized.append(dict(item))
                continue
            text = str(item).strip()
            if text:
                normalized.append(text)
                continue
            if item is not None:
                details = {"field": field, "source_index": source_index}
                if index is not None:
                    details["index"] = index
                raise DomainError("validation_error", "资料来源引用包含无效条目。", details=details)
        return normalized

    @staticmethod
    def _normalize_world_string_list(value, *, field: str, index: int) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise DomainError(
                "validation_error",
                "世界观条目的列表字段必须是数组。",
                details={"field": field, "index": index},
            )
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_world_entity(self, item: dict, *, index: int, source_type: str) -> dict:
        if not isinstance(item, dict):
            raise DomainError("validation_error", "世界观卡条目无效。", details={"index": index})
        name = str(item.get("name", "")).strip()
        source = str(item.get("source", "")).strip()
        if not name or not source:
            raise DomainError("validation_error", "每张世界观卡都需要名称和来源。", details={"index": index})
        confidence = str(item.get("confidence_status", "confirmed")).strip()
        if confidence not in {"confirmed", "inferred", "open", "conflict", "retired"}:
            raise DomainError("validation_error", "世界观卡可信状态无效。", details={"index": index})
        entity_source_type = str(item.get("source_type", source_type)).strip()
        if entity_source_type not in {"official_reference", "custom", "mixed", "ba_starter"}:
            raise DomainError("validation_error", "世界观卡来源类型无效。", details={"index": index})
        entity_status = str(item.get("status", "active")).strip() or "active"
        if entity_status not in {"active", "archived"}:
            raise DomainError("validation_error", "世界观卡状态无效。", details={"index": index})
        entity_scope = str(item.get("scope", "work")).strip() or "work"
        if entity_scope not in {"work", "chapter", "scene"}:
            raise DomainError("validation_error", "世界观卡作用域无效。", details={"index": index})
        entity_kind = str(item.get("kind", "custom")).strip() or "custom"
        if entity_kind not in {"place", "academy", "organization", "object", "technology", "custom"}:
            raise DomainError("validation_error", "世界观卡类型无效。", details={"index": index})
        normalized = {
            "id": str(item.get("id", "")).strip() or new_id("world-card"),
            "name": name,
            "kind": entity_kind,
            "summary": str(item.get("summary", "")).strip(),
            "aliases": self._normalize_world_string_list(item.get("aliases", []), field="aliases", index=index),
            "source": source,
            "source_refs": self._normalize_knowledge_source_refs(
                item.get("source_refs", []), field="entities.source_refs", index=index,
            ),
            "source_type": entity_source_type,
            "confidence_status": confidence,
            "scope": entity_scope,
            "participants": self._normalize_world_string_list(
                item.get("participants", []), field="participants", index=index,
            ),
            "related_world_ids": self._normalize_world_string_list(
                item.get("related_world_ids", []), field="related_world_ids", index=index,
            ),
            "status": entity_status,
        }
        if "participant_character_ids" in item:
            normalized["participant_character_ids"] = self._normalize_world_string_list(
                item.get("participant_character_ids", []),
                field="participant_character_ids",
                index=index,
            )
        return normalized

    def _normalize_world_item(self, item: dict, *, index: int, kind: str) -> dict:
        if not isinstance(item, dict):
            raise DomainError("validation_error", f"{kind}条目无效。", details={"index": index})
        text = str(item.get("text", item.get("label", ""))).strip()
        source = str(item.get("source", "")).strip()
        if not text or not source:
            raise DomainError("validation_error", f"每条{kind}都需要内容和来源。", details={"index": index})
        confidence = str(item.get("confidence_status", "confirmed")).strip()
        if confidence not in {"confirmed", "inferred", "open", "conflict", "retired"}:
            raise DomainError("validation_error", "可信状态无效。", details={"index": index})
        scope = str(item.get("scope", "work")).strip() or "work"
        if scope not in {"work", "chapter", "scene"}:
            raise DomainError("validation_error", f"{kind}作用域无效。", details={"index": index})
        item_status = str(item.get("status", "active")).strip() or "active"
        if item_status not in {"active", "archived"}:
            raise DomainError("validation_error", f"{kind}状态无效。", details={"index": index})
        normalized = {
            "id": str(item.get("id", "")).strip() or new_id("world" if kind == "世界规则" else "event"),
            "text": text,
            "category": str(item.get("category", "general")).strip() or "general",
            "source": source,
            "source_refs": self._normalize_knowledge_source_refs(
                item.get("source_refs", []),
                field="rules.source_refs" if kind == "世界规则" else "timeline.source_refs",
                index=index,
            ),
            "confidence_status": confidence,
            "scope": scope,
            "participants": self._normalize_world_string_list(
                item.get("participants", []), field="participants", index=index,
            ),
            "status": item_status,
        }
        if "participant_character_ids" in item:
            normalized["participant_character_ids"] = self._normalize_world_string_list(
                item.get("participant_character_ids", []),
                field="participant_character_ids",
                index=index,
            )
        if kind == "世界规则":
            normalized["name"] = str(item.get("name", "")).strip()
            normalized["exceptions"] = self._normalize_world_string_list(
                item.get("exceptions", []), field="exceptions", index=index,
            )
        return normalized

    def _normalize_world_bible_payload(self, payload: dict) -> dict:
        title = str(payload.get("title", "")).strip() or "作品世界观"
        source_type = str(payload.get("source_type", "custom")).strip()
        if source_type not in {"official_reference", "custom", "mixed", "ba_starter"}:
            raise DomainError("validation_error", "世界观来源类型无效。", details={"field": "source_type"})
        for field, label in (("entities", "世界观卡"), ("rules", "世界规则"), ("timeline", "时间线事件")):
            if not isinstance(payload.get(field, []), list):
                raise DomainError("validation_error", f"{label}必须是数组。", details={"field": field})
        entities = [
            self._normalize_world_entity(item, index=index, source_type=source_type)
            for index, item in enumerate(payload.get("entities", []))
        ]
        rules = [
            self._normalize_world_item(item, index=index, kind="世界规则")
            for index, item in enumerate(payload.get("rules", []))
        ]
        timeline = [
            self._normalize_world_item(item, index=index, kind="时间线事件")
            for index, item in enumerate(payload.get("timeline", []))
        ]
        entity_ids = {item["id"] for item in entities}
        for index, entity in enumerate(entities):
            related = list(dict.fromkeys(entity["related_world_ids"]))
            invalid = [item_id for item_id in related if item_id not in entity_ids or item_id == entity["id"]]
            if invalid:
                raise DomainError(
                    "validation_error",
                    "世界观卡关联必须指向当前作品中的其他世界观卡。",
                    details={"index": index, "field": "related_world_ids", "ids": invalid},
                )
            entity["related_world_ids"] = related
        effective_source_type = self._merge_world_source_type(
            [source_type, *(item["source_type"] for item in entities)]
        )
        bible = {
            "title": title,
            "source_type": effective_source_type,
            "entities": entities,
            "rules": rules,
            "timeline": timeline,
        }
        if isinstance(payload.get("import_metadata"), dict):
            bible["import_metadata"] = dict(payload["import_metadata"])
        return bible

    def save_world_bible(self, work_id: str, payload: dict):
        """Save world rules and timeline as a distinct versioned artifact, never as chat text."""
        expected = int(payload.get("expected_version", -1))
        bible = self._normalize_world_bible_payload(payload)
        effective_source_type = bible["source_type"]
        import_metadata = payload.get("import_metadata")
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            artifact = self._artifact(connection, work_id, "world_bible", "work", work_id)
            provenance = {
                "workflow": "world.assemble", "pack": PACK_VERSION, "source_type": effective_source_type,
            }
            if isinstance(import_metadata, dict):
                provenance.update({"operation": "ba_world_card_import", "import_id": import_metadata.get("import_id"), "source_hash": import_metadata.get("source_hash"), "validation_schema": import_metadata.get("validation_schema")})
            revision_id = self._add_revision(connection, artifact, bible, "user", provenance)
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {"revision_id": revision_id, "work": self.get_work(work_id)}

    def _current_world_bible(self, work_id: str) -> dict:
        work = self.get_work(work_id)
        for artifact in work.get("artifacts", []):
            if artifact.get("kind") == "world_bible" and artifact.get("current_revision"):
                return artifact["current_revision"].get("content", {})
        return {"title": "作品世界观", "source_type": "custom", "entities": [], "rules": [], "timeline": []}

    def _matching_world_entities(self, current: dict, imported_entities: list[dict]) -> list[dict]:
        existing = list(current.get("entities", []))
        matches: list[dict] = []
        for imported in imported_entities:
            imported_id = str(imported.get("id", "")).strip()
            candidates = [item for item in existing if imported_id and item.get("id") == imported_id]
            if not candidates:
                tokens = world_identity_tokens(imported)
                candidates = [item for item in existing if tokens.intersection(world_identity_tokens(item))]
            if len(candidates) > 1:
                matches.append({"incoming": imported.get("name", ""), "candidate_ids": [item.get("id") for item in candidates]})
            elif candidates:
                matches.append({"incoming": imported.get("name", ""), "card_id": candidates[0].get("id")})
        return matches

    def validate_world_card_import(self, work_id: str, payload: dict) -> dict:
        with self.repo.connect() as connection:
            if not connection.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone():
                raise NotFound("work", work_id)
        parsed = parse_world_import_payload(payload)
        preview = parsed.public_preview()
        preview["can_import"] = parsed.report["status"] == "PASS"
        return preview

    def import_world_card(self, work_id: str, payload: dict) -> dict:
        expected = int(payload.get("expected_version", -1))
        parsed = parse_world_import_payload(payload)
        if parsed.report["status"] != "PASS":
            raise world_import_validation_failure(parsed)
        current = self._current_world_bible(work_id)
        match_rows = self._matching_world_entities(current, parsed.cleaned.get("entities", []))
        conflicts = [row for row in match_rows if "candidate_ids" in row]
        if conflicts:
            raise DomainError(
                "world_card_identity_conflict",
                "世界观卡名称或 ID 同时命中多张现有卡，请先在资料库处理重复身份。",
                status=409,
                details={"matches": conflicts},
            )
        match_by_name = {row["incoming"]: row["card_id"] for row in match_rows if row.get("card_id")}
        existing_entities = list(current.get("entities", []))
        imported_entities = []
        for entity in parsed.cleaned.get("entities", []):
            item = dict(entity)
            incoming_name = item.get("name", "")
            if incoming_name in match_by_name:
                item["id"] = match_by_name[incoming_name]
            if not item.get("source_type"):
                item["source_type"] = parsed.cleaned.get("source_type", "custom")
            imported_entities.append(item)
        imported_ids = {item.get("id") for item in imported_entities if item.get("id")}
        merged_entities = [item for item in existing_entities if item.get("id") not in imported_ids]
        merged_entities.extend(imported_entities)
        import_id = new_id("world-import")
        prefix = f"imports/world-cards/{work_id}/{import_id}"
        raw_uri, raw_hash = self.repo.atomic_write_bytes(f"{prefix}/original.json", parsed.raw_bytes)
        cleaned_uri, cleaned_hash = self.repo.atomic_write_bytes(f"{prefix}/cleaned.json", parsed.cleaned_bytes)
        source_label = str(payload.get("source_label", "用户导入的 BA 世界观卡")).strip() or "用户导入的 BA 世界观卡"
        metadata = {
            "profile_format": WORLD_IMPORT_PROFILE_FORMAT,
            "extractor_version": WORLD_IMPORT_EXTRACTOR_VERSION,
            "import_id": import_id,
            "import_filename": parsed.filename,
            "import_source_label": source_label,
            "source_hash": parsed.source_hash,
            "raw_import_uri": raw_uri,
            "cleaned_import_uri": cleaned_uri,
            "raw_import_hash": raw_hash,
            "cleaned_import_hash": cleaned_hash,
            "validation_schema": parsed.report["schema_version"],
        }
        payload_for_save = {
            "expected_version": expected,
            "title": parsed.cleaned.get("title") or current.get("title") or "作品世界观",
            "source_type": parsed.cleaned.get("source_type", "custom"),
            "entities": merged_entities,
            "rules": [*current.get("rules", []), *parsed.cleaned.get("rules", [])],
            "timeline": [*current.get("timeline", []), *parsed.cleaned.get("timeline", [])],
            "import_metadata": metadata,
        }
        saved = self.save_world_bible(work_id, payload_for_save)
        return {
            "import_id": import_id,
            "import_mode": "updated" if match_rows else "created",
            "source_hash": parsed.source_hash,
            "validation_report": parsed.report,
            "work": saved["work"],
        }

    def apply_ba_world_starter(self, work_id: str, payload: dict):
        """Create a work-owned, editable BA setting starter at an explicit user action.

        The template is intentionally stored as open knowledge.  It must be
        reviewed, sourced and confirmed before scene assembly can use it.
        """
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            artifact = self._artifact(connection, work_id, "world_bible", "work", work_id)
            starter = starter_bible()
            if artifact.get("current_revision_id"):
                current_revision = connection.execute(
                    "SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)
                ).fetchone()
                current = json.loads(self.repo.read_text(current_revision["content_uri"]))
                existing_ids = {
                    item.get("id")
                    for collection in ("entities", "rules", "timeline")
                    for item in current.get(collection, [])
                }
                starter_ids = {item["id"] for item in starter["entities"]}
                if existing_ids & starter_ids:
                    raise DomainError(
                        "world_starter_already_applied",
                        "BA 世界观起始架构已在当前作品中。请直接修订这些卡片。",
                        status=409,
                    )
                bible = {
                    "title": current.get("title") or starter["title"],
                    "source_type": "mixed" if current.get("entities") or current.get("rules") or current.get("timeline") else "ba_starter",
                    "entities": [*current.get("entities", []), *starter["entities"]],
                    "rules": current.get("rules", []),
                    "timeline": current.get("timeline", []),
                }
                provenance_source_revision = current_revision["id"]
            else:
                bible = starter
                provenance_source_revision = None
            revision_id = self._add_revision(
                connection,
                artifact,
                bible,
                "user",
                {
                    "workflow": "world.starter.apply",
                    "pack": PACK_VERSION,
                    "starter_version": BA_WORLD_STARTER_VERSION,
                    "source": BA_WORLD_STARTER_SOURCE,
                    "source_revision_id": provenance_source_revision,
                    "disclosure": "这是待核对的产品起始架构，不是自动确认的 BA 原作事实。",
                },
            )
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {
            "revision_id": revision_id,
            "starter_version": BA_WORLD_STARTER_VERSION,
            "disclosure": "BA 世界观起始架构已复制到本作品；全部条目均为待核对，尚不会进入 Agent。",
            "work": self.get_work(work_id),
        }

    def create_reference_file(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        title = str(payload.get("title", "")).strip()
        content = str(payload.get("content", "")).strip()
        source_label = str(payload.get("source_label", "")).strip()
        if not title or not content or not source_label:
            raise DomainError("validation_error", "资料名称、内容和来源都不能为空。")
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            ref_id = new_id("reference")
            uri, digest = self.repo.atomic_write_text(f"references/{ref_id}.md", content + "\n")
            timestamp = now()
            connection.execute("INSERT INTO reference_files VALUES (?,?,?,?,?,?,?,?,?,?,?)", (ref_id, work_id, title, payload.get("kind", "note"), uri, digest, source_label, payload.get("trust_status", "unverified"), 1, timestamp, timestamp))
            self._bump_work(connection, work_id, version)
        return {"reference_file_id": ref_id, "work": self.get_work(work_id)}

    def import_official_reference(self, work_id: str, payload: dict):
        """Copy one selected corpus excerpt into the work-owned evidence library."""
        expected = int(payload.get("expected_version", -1))
        item = self.official_references.get(payload.get("record_uid", ""))
        title = str(payload.get("title", "")).strip() or " / ".join(
            value for value in (item.get("character_name"), item.get("story_title")) if value
        ) or item["record_uid"]
        ref_id = new_id("reference")
        content = self.official_references.render_import_excerpt(item)
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            uri, digest = self.repo.atomic_write_text(f"references/{ref_id}.md", content)
            timestamp = now()
            connection.execute(
                "INSERT INTO reference_files VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ref_id,
                    work_id,
                    title,
                    "official_excerpt",
                    uri,
                    digest,
                    f"official-corpus:{item['record_uid']}",
                    "official_reference",
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            self._bump_work(connection, work_id, version)
        return {"reference_file_id": ref_id, "record_uid": item["record_uid"], "work": self.get_work(work_id)}

    @staticmethod
    def _memory_maintenance_snapshot(connection, work_id: str, scenes: list[dict]) -> list[dict]:
        rows = connection.execute(
            """SELECT item.* FROM work_items AS item
               JOIN production_runs AS run ON run.id=item.run_id
               WHERE run.work_id=? AND item.type='memory.extract'
               ORDER BY item.created_at DESC""",
            (work_id,),
        ).fetchall()
        by_revision = {}
        for row in rows:
            try:
                refs = json.loads(row["input_refs_json"] or "{}")
                acceptance = json.loads(row["acceptance_json"] or "{}")
            except json.JSONDecodeError:
                continue
            revision_id = refs.get("scene_revision_id")
            if revision_id and revision_id not in by_revision:
                by_revision[revision_id] = {
                    "work_item_id": row["id"],
                    "status": row["status"],
                    "decision": acceptance.get("decision"),
                }
        result = []
        for scene in scenes:
            revision_id = scene.get("revision_id")
            task = by_revision.get(revision_id, {}) if revision_id else {}
            status = task.get("status") or "missing"
            result.append({
                "scene_id": scene["scene_id"],
                "revision_id": revision_id,
                "work_item_id": task.get("work_item_id"),
                "status": status,
                "decision": task.get("decision"),
                "complete": status in {"succeeded", "skipped"},
            })
        return result

    def _assemble_work_review_pack(self, work_id: str, workflow: str) -> dict:
        with self.repo.connect() as connection:
            work = connection.execute("SELECT id,title,version FROM works WHERE id=?", (work_id,)).fetchone()
            if not work:
                raise NotFound("work", work_id)
            values = {}
            character_cards = []
            dependency_refs = []
            artifacts = connection.execute(
                """SELECT * FROM artifacts
                   WHERE work_id=? AND kind IN ('brief','story_blueprint','work_canon','world_bible','character_card')
                   ORDER BY kind,scope_id""",
                (work_id,),
            ).fetchall()
            for artifact in artifacts:
                if not artifact["current_revision_id"]:
                    continue
                revision = connection.execute(
                    "SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)
                ).fetchone()
                content = json.loads(self.repo.read_text(revision["content_uri"]))
                if artifact["kind"] == "character_card":
                    character_cards.append({
                        "card_id": artifact["scope_id"],
                        "revision_id": revision["id"],
                        "content_hash": revision["content_hash"],
                        "content": content,
                    })
                else:
                    values[artifact["kind"]] = content
                dependency_refs.append({
                    "kind": artifact["kind"],
                    "scope_type": artifact["scope_type"],
                    "scope_id": artifact["scope_id"],
                    "revision_id": revision["id"],
                    "content_hash": revision["content_hash"],
                })
            scene_rows = connection.execute(
                """SELECT s.*,c.title AS chapter_title,c.stable_order_key AS chapter_order,
                          COALESCE(v.title,'') AS volume_title,COALESCE(v.stable_order_key,'') AS volume_order
                   FROM scenes s JOIN chapters c ON c.id=s.chapter_id
                   LEFT JOIN volumes v ON v.id=c.volume_id
                   WHERE s.work_id=?
                   ORDER BY volume_order,chapter_order,s.stable_order_key""",
                (work_id,),
            ).fetchall()
            scenes = []
            has_sensei = False
            for row in scene_rows:
                contract = json.loads(row["contract_json"])
                has_sensei = has_sensei or self._scene_has_sensei(contract, values.get("brief", {}))
                asset_references = self._scene_asset_reference_snapshot(
                    self._scene_asset_references(connection, work_id, row["id"])
                )
                item = {
                    "scene_id": row["id"],
                    "title": row["title"],
                    "chapter_id": row["chapter_id"],
                    "chapter_title": row["chapter_title"],
                    "volume_title": row["volume_title"],
                    "stable_order": [row["volume_order"], row["chapter_order"], row["stable_order_key"]],
                    "contract": contract,
                    "revision_id": row["current_revision_id"],
                    "revision_hash": None,
                    "text_excerpt": None,
                    "asset_references": asset_references,
                    "asset_reference_digest": sha256_text(canonical_json(asset_references)),
                }
                if row["current_revision_id"]:
                    revision = connection.execute(
                        "SELECT * FROM revisions WHERE id=?", (row["current_revision_id"],)
                    ).fetchone()
                    text = json.loads(self.repo.read_text(revision["content_uri"])).get("text", "")
                    excerpt = self._traceable_text_excerpt(
                        text,
                        max_chars=10000 if workflow == "release.review" else 7000,
                        include_start=True,
                    )
                    item.update({
                        "revision_hash": revision["content_hash"],
                        "text_excerpt": excerpt["text"],
                        "excerpt_segments": excerpt["segments"],
                        "text_truncated": excerpt["truncated"],
                    })
                scenes.append(item)
            memories = self.repo.rows(connection.execute(
                """SELECT id,kind,scope_type,scope_id,content,source_revision_id,confidence_status,version
                   FROM memories WHERE work_id=? AND confidence_status='confirmed'
                   ORDER BY created_at""",
                (work_id,),
            ))
            open_findings = self.repo.rows(connection.execute(
                """SELECT id,scene_id,revision_id,scope_type,scope_id,kind,severity,message,evidence_json
                   FROM review_findings WHERE work_id=? AND status='open' ORDER BY created_at""",
                (work_id,),
            ))
            for finding in open_findings:
                finding["evidence"] = json.loads(finding.pop("evidence_json"))
            memory_maintenance = self._memory_maintenance_snapshot(connection, work_id, scenes)
        pack = {
            "schema_version": "work-review-pack/1.0",
            "workflow": workflow,
            "work_id": work_id,
            "work_title": work["title"],
            "mode_key": values.get("brief", {}).get("mode"),
            "has_sensei": has_sensei,
            "brief": values.get("brief"),
            "story_blueprint": values.get("story_blueprint"),
            "work_canon": values.get("work_canon"),
            "world_bible": values.get("world_bible"),
            "character_cards": character_cards,
            "confirmed_memories": memories,
            "memory_maintenance": memory_maintenance,
            "open_findings": open_findings,
            "scenes": scenes,
            "dependency_refs": dependency_refs,
            "writing_pack_version": PACK_VERSION,
            "ba_writing_source_digest": self._ba_writing_source_digest(),
        }
        pack["digest"] = sha256_text(canonical_json(pack))
        return pack

    def _persist_review_agent_failure(
        self,
        run_id: str,
        attempt_id: str,
        work_item_id: str,
        error: dict,
        *,
        tool_name: str,
        input_digest: str,
        ordinal: int = 2,
    ) -> None:
        timestamp = now()
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, run_id)
            connection.execute(
                "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                (canonical_json(error), timestamp, run_id),
            )
            connection.execute(
                "UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'",
                (error.get("code", "review_failed"), timestamp, attempt_id),
            )
            connection.execute(
                "UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'",
                (canonical_json(error), timestamp, work_item_id),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), run_id, ordinal, tool_name, "failed", input_digest, None,
                 canonical_json(error), timestamp, timestamp),
            )

    def _run_work_review_agent(
        self,
        work_id: str,
        payload: dict,
        workflow: str,
        *,
        review_pack: dict | None = None,
        retry_of: str | None = None,
        provider=None,
    ):
        provider = provider if provider is not None else self.provider
        expected = int(payload.get("expected_version", -1))
        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected)
        review_pack = review_pack or self._assemble_work_review_pack(work_id, workflow)
        run_id = new_id("agent")
        policy = {
            "workflow": workflow,
            "pack_version": PACK_VERSION,
            "write_policy": "findings_and_gate_only_formal_artifacts_read_only",
            "tool_allowlist": ["assemble_work_review_pack", "create_review_findings", "evaluate_review_gate"],
            "tool_denied": ["write_scene_revision", "mutate_work_canon", "mutate_character_card", "internet_search"],
            "fingerprints": {
                "work_review_pack": review_pack["digest"],
                "writing_pack_version": PACK_VERSION,
            },
        }
        if retry_of:
            policy["retry_of_agent_run_id"] = retry_of
        snapshot = {"review_pack": review_pack, "policy": policy}
        snapshot_uri, digest = self.repo.atomic_write_text(
            f"agent-runs/{run_id}/input.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )
        timestamp = now()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, work_id, "work", work_id, "跨场景连续性审查" if workflow == "continuity.review" else "全篇发布审查",
                 "running", canonical_json(policy), snapshot_uri, digest, None, None, timestamp, None),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), run_id, 1, "assemble_work_review_pack", "succeeded", review_pack["digest"], snapshot_uri, None, timestamp, now()),
            )
            production_run = connection.execute(
                "SELECT * FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1",
                (work_id,),
            ).fetchone()
            work_item_id = new_id("item")
            current_refs = [item["revision_id"] for item in review_pack["scenes"] if item["revision_id"]]
            connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (work_item_id, production_run["id"], f"agent.{workflow}", "work", work_id, "running",
                 canonical_json(current_refs), "[]", canonical_json({"formal_artifacts_read_only": True, "agent_run_id": run_id}),
                 1, None, timestamp, timestamp),
            )
            attempt_id = new_id("attempt")
            connection.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, work_item_id, 1, provider.kind, digest, "started", None, None, timestamp, None),
            )

        self._notify_agent_run_started(payload, run_id)
        try:
            if not review_pack["scenes"] or any(not item["revision_id"] for item in review_pack["scenes"]):
                provider_findings = []
            elif workflow == "continuity.review":
                provider_findings = provider.review_continuity(review_pack)
            else:
                provider_findings = provider.review_release(review_pack)
        except Exception as exc:
            error_code = exc.code if isinstance(exc, DomainError) else "provider_failed"
            error = {"code": error_code, "type": type(exc).__name__}
            self._persist_review_agent_failure(
                run_id, attempt_id, work_item_id, error,
                tool_name="create_review_findings", input_digest=digest,
            )
            if isinstance(exc, DomainError):
                raise
            raise DomainError("review_failed", "作品级审查 Agent 未能完成本次运行。", status=502, details=error) from exc

        provider_usage = self._provider_usage(provider)

        scene_index = {item["scene_id"]: item for item in review_pack["scenes"] if item["revision_id"]}
        normalized_findings = []
        for index, item in enumerate(provider_findings):
            scene = scene_index.get(str(item.get("scene_id", "")))
            if not scene or scene["revision_id"] != item.get("revision_id"):
                error = {"code": "provider_output_invalid", "index": index, "reason": "unknown_or_stale_revision"}
                self._persist_review_agent_failure(
                    run_id, attempt_id, work_item_id, error,
                    tool_name="create_review_findings", input_digest=digest,
                )
                raise DomainError("provider_output_invalid", "作品级审查引用了不存在或已过期的场景修订。", status=502, details=error)
            refs = item.get("evidence", {}).get("revision_refs")
            if not isinstance(refs, list) or not refs:
                refs = [{
                    "scene_id": scene["scene_id"],
                    "revision_id": scene["revision_id"],
                    "content_hash": scene["revision_hash"],
                }]
            valid_refs = []
            for ref in refs:
                ref_scene = scene_index.get(str(ref.get("scene_id", ""))) if isinstance(ref, dict) else None
                if not ref_scene or ref_scene["revision_id"] != ref.get("revision_id"):
                    error = {"code": "provider_output_invalid", "index": index, "reason": "invalid_revision_refs"}
                    self._persist_review_agent_failure(
                        run_id, attempt_id, work_item_id, error,
                        tool_name="create_review_findings", input_digest=digest,
                    )
                    raise DomainError("provider_output_invalid", "作品级审查的跨场景证据引用无效。", status=502, details=error)
                valid_refs.append({
                    "scene_id": ref_scene["scene_id"],
                    "revision_id": ref_scene["revision_id"],
                    "content_hash": ref_scene["revision_hash"],
                })
            normalized_findings.append({**item, "revision_refs": valid_refs})

        conflict_actual = None
        created = []
        gate_id = None
        gate_status = "blocked"
        gate_snapshot = {}
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, run_id)
            version_row = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            current_rows = connection.execute(
                """SELECT s.id,s.current_revision_id FROM scenes s JOIN chapters c ON c.id=s.chapter_id
                   LEFT JOIN volumes v ON v.id=c.volume_id WHERE s.work_id=?
                   ORDER BY COALESCE(v.stable_order_key,''),c.stable_order_key,s.stable_order_key""",
                (work_id,),
            ).fetchall()
            current_refs = []
            for row in current_rows:
                asset_references = self._scene_asset_reference_snapshot(
                    self._scene_asset_references(connection, work_id, row["id"])
                )
                current_refs.append(
                    (
                        row["id"],
                        row["current_revision_id"],
                        sha256_text(canonical_json(asset_references)),
                    )
                )
            pinned_refs = [
                (item["scene_id"], item["revision_id"], item["asset_reference_digest"])
                for item in review_pack["scenes"]
            ]
            if not version_row or version_row["version"] != expected or current_refs != pinned_refs:
                conflict_actual = version_row["version"] if version_row else -1
            else:
                prior_rows = connection.execute(
                    "SELECT id,agent_run_id FROM review_findings WHERE work_id=? AND scope_type='work' AND status='open'",
                    (work_id,),
                ).fetchall()
                for prior in prior_rows:
                    prior_run = connection.execute("SELECT policy_json FROM agent_runs WHERE id=?", (prior["agent_run_id"],)).fetchone()
                    if prior_run and json.loads(prior_run["policy_json"]).get("workflow") == workflow:
                        connection.execute("UPDATE review_findings SET status='superseded',resolved_at=? WHERE id=?", (now(), prior["id"]))
                for item in normalized_findings:
                    finding_id = new_id("finding")
                    anchor = scene_index[item["scene_id"]]
                    evidence = {**item["evidence"], "source": "provider", "agent_workflow": workflow, "agent_run_id": run_id}
                    connection.execute(
                        """INSERT INTO review_findings
                           (id,work_id,scene_id,revision_id,scope_type,scope_id,revision_refs_json,agent_run_id,
                            kind,severity,status,message,evidence_json,created_at,resolved_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (finding_id, work_id, anchor["scene_id"], anchor["revision_id"], "work", work_id,
                         canonical_json(item["revision_refs"]), run_id, item["kind"], item["severity"], "open",
                         item["message"], canonical_json(evidence), now(), None),
                    )
                    created.append({"id": finding_id, **item, "evidence": evidence})
                all_revision_ids = [item["revision_id"] for item in review_pack["scenes"] if item["revision_id"]]
                missing = [item["scene_id"] for item in review_pack["scenes"] if not item["revision_id"]]
                reviewed_revision_ids = set()
                for gate in connection.execute("SELECT result_json FROM gates WHERE work_id=? AND kind='scene.review'", (work_id,)).fetchall():
                    revision_id = json.loads(gate["result_json"]).get("revision_id")
                    if revision_id:
                        reviewed_revision_ids.add(revision_id)
                unreviewed = [revision_id for revision_id in all_revision_ids if revision_id not in reviewed_revision_ids]
                open_blockers = []
                if all_revision_ids:
                    placeholders = ",".join("?" for _ in all_revision_ids)
                    open_blockers = connection.execute(
                        f"SELECT id FROM review_findings WHERE revision_id IN ({placeholders}) AND severity='blocking' AND status='open'",
                        all_revision_ids,
                    ).fetchall()
                provider_blockers = [item["id"] for item in created if item["severity"] == "blocking"]
                incomplete_memory = [
                    item for item in review_pack.get("memory_maintenance", [])
                    if not item.get("complete")
                ]
                deterministic_ready = bool(review_pack["scenes"]) and not missing
                if workflow == "release.review":
                    deterministic_ready = deterministic_ready and not unreviewed and not incomplete_memory
                gate_status = "passed" if deterministic_ready and not open_blockers and not provider_blockers else "blocked"
                gate_id = new_id("gate")
                gate_snapshot = {
                    "schema_version": "work-review-gate/1.0",
                    "workflow": workflow,
                    "checked_scene_count": len(review_pack["scenes"]),
                    "no_scenes": not bool(review_pack["scenes"]),
                    "scene_revision_ids": all_revision_ids,
                    "scene_revision_refs": [
                        {
                            "scene_id": item["scene_id"],
                            "revision_id": item["revision_id"],
                            "content_hash": item["revision_hash"],
                            "asset_references": item["asset_references"],
                            "asset_reference_digest": item["asset_reference_digest"],
                        }
                        for item in review_pack["scenes"] if item["revision_id"]
                    ],
                    "missing_scene_ids": missing,
                    "unreviewed_revision_ids": unreviewed,
                    "memory_maintenance": review_pack.get("memory_maintenance", []),
                    "incomplete_memory_scene_ids": [item["scene_id"] for item in incomplete_memory],
                    "blocking_finding_ids": [row["id"] for row in open_blockers],
                    "provider_finding_ids": [item["id"] for item in created],
                    "agent_run_id": run_id,
                    "work_review_pack_digest": review_pack["digest"],
                    "dependency_refs": review_pack["dependency_refs"],
                    "writing_pack_version": PACK_VERSION,
                    "ba_writing_source_digest": review_pack["ba_writing_source_digest"],
                    "provider": provider.descriptor(),
                    "provider_usage": provider_usage,
                }
                connection.execute(
                    "INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)",
                    (gate_id, work_id, workflow, "work", work_id, gate_status, canonical_json(gate_snapshot), now()),
                )
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), run_id, 2, "create_review_findings", "succeeded", digest,
                     canonical_json([item["id"] for item in created]), None, timestamp, now()),
                )
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), run_id, 3, "evaluate_review_gate", "succeeded",
                     sha256_text(canonical_json(gate_snapshot)), gate_id, None, timestamp, now()),
                )
                connection.execute(
                    "UPDATE agent_runs SET status='succeeded',policy_json=?,finished_at=? WHERE id=?",
                    (canonical_json({**policy, "usage": provider_usage}), now(), run_id),
                )
                connection.execute("UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?", (gate_id, now(), attempt_id))
                connection.execute(
                    "UPDATE work_items SET status='succeeded',output_refs_json=?,acceptance_json=?,updated_at=? WHERE id=?",
                    (canonical_json([gate_id, *[item["id"] for item in created]]),
                     canonical_json({"agent_run_id": run_id, "provider_usage": provider_usage, "work_review_pack": review_pack["digest"]}),
                     now(), work_item_id),
                )
                self._bump_work(connection, work_id, expected)
        if conflict_actual is not None:
            error = {"code": "revision_conflict", "expected_version": expected, "actual_version": conflict_actual}
            self._persist_review_agent_failure(
                run_id, attempt_id, work_item_id, error,
                tool_name="create_review_findings", input_digest=digest,
            )
            raise RevisionConflict(expected, conflict_actual)
        return {
            "gate_id": gate_id,
            "agent_run_id": run_id,
            "status": gate_status,
            "simulation": provider.is_simulation,
            "findings": created,
            "snapshot": gate_snapshot,
            "work": self.get_work(work_id),
        }

    @staticmethod
    def _scene_review_metrics(text: str) -> dict:
        blocks = []
        current_speaker = None
        current_streak = 0
        max_speaker_streak = 0
        for line_number, raw_line in enumerate(str(text).splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            ascii_divider = line.find(":")
            chinese_divider = line.find("：")
            dividers = [value for value in (ascii_divider, chinese_divider) if value >= 0]
            divider = min(dividers) if dividers else -1
            speaker = line[:divider].strip() if divider > 0 else ""
            content = line[divider + 1:].strip() if divider > 0 else line
            block_type = "dialogue" if speaker and speaker not in {"旁白", "叙述"} else "narration"
            character_count = len("".join(content.split()))
            blocks.append({
                "line": line_number,
                "type": block_type,
                "speaker": speaker or None,
                "characters": character_count,
            })
            if block_type == "dialogue":
                if speaker == current_speaker:
                    current_streak += 1
                else:
                    current_speaker = speaker
                    current_streak = 1
                max_speaker_streak = max(max_speaker_streak, current_streak)
            else:
                current_speaker = None
                current_streak = 0

        narration = [block for block in blocks if block["type"] == "narration"]
        dialogue = [block for block in blocks if block["type"] == "dialogue"]
        total_characters = sum(block["characters"] for block in blocks)
        narration_characters = sum(block["characters"] for block in narration)
        long_blocks = [block for block in blocks if block["characters"] >= 140]
        return {
            "schema_version": "scene-review-metrics/1.0",
            "block_count": len(blocks),
            "dialogue_block_count": len(dialogue),
            "narration_block_count": len(narration),
            "total_characters": total_characters,
            "narration_characters": narration_characters,
            "narration_ratio": round(narration_characters / total_characters, 4) if total_characters else 0.0,
            "average_block_characters": round(total_characters / len(blocks), 2) if blocks else 0.0,
            "long_blocks": long_blocks,
            "max_same_speaker_turns": max_speaker_streak,
        }

    def review_scene(self, work_id: str, scene_id: str, payload: dict):
        provider = self.provider
        expected = int(payload.get("expected_version", -1))
        context = self.assemble_context(work_id, scene_id)
        if not provider.is_simulation and context["readiness"]["real_ba_writing"] != "ready_for_provider":
            raise DomainError(
                "review_blocked",
                "真实 BA 场景审查需要本场已确认的人物卡和完整 Skill 规则源。",
                status=409,
                details={"readiness": context["readiness"]},
            )
        with self.repo.connect() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute("SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if not scene["current_revision_id"]:
                raise DomainError("review_blocked", "当前场景还没有已采纳正文。", status=409)
            revision = connection.execute("SELECT * FROM revisions WHERE id=?", (scene["current_revision_id"],)).fetchone()
            text = json.loads(self.repo.read_text(revision["content_uri"])).get("text", "")
            review_metrics = self._scene_review_metrics(text)

        run_id = new_id("agent")
        policy = {
            "workflow": "scene.review",
            "pack_version": PACK_VERSION,
            "write_policy": "findings_and_gate_only_manuscript_read_only",
            "tool_allowlist": ["assemble_scene_context", "read_pinned_scene_revision", "create_review_findings", "evaluate_scene_gate"],
            "tool_denied": ["write_scene_revision", "mutate_work_canon", "mutate_character_card", "internet_search"],
            "fingerprints": context["fingerprints"],
        }
        if payload.get("_retry_of"):
            policy["retry_of_agent_run_id"] = str(payload["_retry_of"])
        snapshot = {
            "schema_version": "scene-review-input/1.0",
            "scene_id": scene_id,
            "revision_id": revision["id"],
            "revision_hash": revision["content_hash"],
            "text": text,
            "scene_contract": context["scene_contract"],
            "brief": context["brief"],
            "work_canon": context["work_canon"],
            "world_bible": context["world_bible"],
            "runtime_character_cards": context["runtime_character_cards"],
            "reference_file_refs": context["reference_file_refs"],
            "rules": context["rules"],
            "policy": policy,
        }
        snapshot_uri, digest = self.repo.atomic_write_text(
            f"agent-runs/{run_id}/input.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )
        timestamp = now()
        with self.repo.transaction() as connection:
            actual = self._check_work_version(connection, work_id, expected)
            current_scene = connection.execute("SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if not current_scene:
                raise NotFound("scene", scene_id)
            if current_scene["current_revision_id"] != revision["id"]:
                raise RevisionConflict(expected, actual)
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, work_id, "scene", scene_id, "审查当前场景", "running", canonical_json(policy), snapshot_uri, digest, None, None, timestamp, None),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), run_id, 1, "assemble_scene_context", "succeeded", context["fingerprints"]["scene_writing_pack"], snapshot_uri, None, timestamp, now()),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), run_id, 2, "read_pinned_scene_revision", "succeeded", revision["content_hash"], revision["id"], None, timestamp, now()),
            )
            production_run = connection.execute("SELECT * FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1", (work_id,)).fetchone()
            work_item_id = new_id("item")
            connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (work_item_id, production_run["id"], "agent.scene.review", "scene", scene_id, "running", canonical_json([revision["id"], *context["source_revision_ids"]]), "[]", canonical_json({"manuscript_read_only": True, "agent_run_id": run_id}), 1, None, timestamp, timestamp),
            )
            attempt_id = new_id("attempt")
            connection.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, work_item_id, 1, provider.kind, digest, "started", None, None, timestamp, None),
            )

        self._notify_agent_run_started(payload, run_id)
        try:
            provider_findings = provider.review_scene(context, text)
        except Exception as exc:
            error_code = exc.code if isinstance(exc, DomainError) else "provider_failed"
            error = {"code": error_code, "type": type(exc).__name__}
            with self.repo.transaction() as connection:
                self._require_agent_run_committable(connection, run_id)
                connection.execute("UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), run_id))
                connection.execute("UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'", (error_code, now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), run_id, 3, "create_review_findings", "failed", digest, None, canonical_json(error), timestamp, now()),
                )
            if isinstance(exc, DomainError):
                raise
            raise DomainError("review_failed", "场景审查 Agent 未能完成本次运行。", status=502, details=error) from exc

        provider_usage = self._provider_usage(provider)

        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, run_id)
            version_row = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            if not version_row:
                raise NotFound("work", work_id)
            version = version_row["version"]
            current_scene = connection.execute("SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if version != expected or not current_scene or current_scene["current_revision_id"] != revision["id"]:
                error = {"code": "revision_conflict", "expected_version": expected, "actual_version": version}
                connection.execute("UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), run_id))
                connection.execute("UPDATE job_attempts SET status='failed',error_code='revision_conflict',finished_at=? WHERE id=? AND status='started'", (now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), run_id, 3, "create_review_findings", "failed", digest, None, canonical_json(error), timestamp, now()),
                )
                # Persist the terminal failure before surfacing the optimistic-lock error.
                connection.commit()
                raise RevisionConflict(expected, version)
            connection.execute("UPDATE review_findings SET status='superseded', resolved_at=? WHERE scene_id=? AND revision_id=? AND status='open'", (now(), scene_id, revision["id"]))
            findings = []
            meta_terms = ["作者", "读者", "观众", "这一话", "第1章", "第一周目", "第二周目", "按设定", "这是故事"]
            for term in meta_terms:
                if term in text:
                    findings.append({"kind": "meta_boundary", "severity": "blocking", "message": f"正文包含元叙事词“{term}”。", "evidence": {"term": term}, "source": "deterministic"})
            contract = json.loads(current_scene["contract_json"])
            for term in contract.get("forbidden_reveals", []):
                if str(term).strip() and str(term).strip() in text:
                    findings.append({"kind": "forbidden_reveal", "severity": "blocking", "message": f"正文出现本场禁止揭示项“{term}”。", "evidence": {"term": term}, "source": "deterministic"})
            card_names = {
                str(card.get("name", "")).strip()
                for card in context["runtime_character_cards"]
                if str(card.get("name", "")).strip()
            }
            speakers = {line.split(":", 1)[0].strip() for line in text.splitlines() if ":" in line}
            missing_cards = sorted(speaker for speaker in speakers if speaker not in {"旁白", "老师", "Sensei"} and speaker not in card_names)
            if missing_cards:
                findings.append({"kind": "character_card_missing", "severity": "warning", "message": "以下说话者没有可追溯人物卡：" + "、".join(missing_cards), "evidence": {"speakers": missing_cards}, "source": "deterministic"})
            if review_metrics["block_count"] >= 6 and review_metrics["narration_ratio"] >= 0.7:
                findings.append({
                    "kind": "narration_ratio",
                    "severity": "warning",
                    "message": "本场旁白占比较高，可能压缩角色之间的可见互动。",
                    "evidence": {
                        "narration_ratio": review_metrics["narration_ratio"],
                        "narration_block_count": review_metrics["narration_block_count"],
                        "block_count": review_metrics["block_count"],
                    },
                    "source": "deterministic",
                })
            if review_metrics["long_blocks"]:
                findings.append({
                    "kind": "pacing_long_block",
                    "severity": "warning",
                    "message": "本场存在过长的单块内容，阅读节奏可能停滞。",
                    "evidence": {"long_blocks": review_metrics["long_blocks"]},
                    "source": "deterministic",
                })
            if review_metrics["max_same_speaker_turns"] >= 5:
                findings.append({
                    "kind": "pacing_turn_density",
                    "severity": "info",
                    "message": "同一角色连续发言较多，建议确认这是否符合本场节奏意图。",
                    "evidence": {"max_same_speaker_turns": review_metrics["max_same_speaker_turns"]},
                    "source": "deterministic",
                })
            findings.extend({**item, "source": "provider"} for item in provider_findings)
            unique = []
            seen = set()
            for item in findings:
                identity = (item["kind"], item["severity"], item["message"])
                if identity not in seen:
                    unique.append(item)
                    seen.add(identity)
            created = []
            for item in unique:
                finding_id = new_id("finding")
                evidence = {**item["evidence"], "source": item["source"], "agent_run_id": run_id}
                revision_refs = [{"scene_id": scene_id, "revision_id": revision["id"], "content_hash": revision["content_hash"]}]
                connection.execute(
                    """INSERT INTO review_findings
                       (id,work_id,scene_id,revision_id,scope_type,scope_id,revision_refs_json,agent_run_id,
                        kind,severity,status,message,evidence_json,created_at,resolved_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (finding_id, work_id, scene_id, revision["id"], "scene", scene_id, canonical_json(revision_refs), run_id,
                     item["kind"], item["severity"], "open", item["message"], canonical_json(evidence), now(), None),
                )
                created.append({"id": finding_id, "kind": item["kind"], "severity": item["severity"], "message": item["message"], "evidence": evidence})
            gate_id = new_id("gate")
            blockers = [item for item in created if item["severity"] == "blocking"]
            gate_snapshot = {
                "revision_id": revision["id"],
                "finding_ids": [item["id"] for item in created],
                "blocker_count": len(blockers),
                "agent_run_id": run_id,
                "provider": provider.descriptor(),
                "provider_usage": provider_usage,
                "fingerprints": context["fingerprints"],
                "metrics": review_metrics,
            }
            connection.execute("INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)", (gate_id, work_id, "scene.review", "scene", scene_id, "blocked" if blockers else "passed", canonical_json(gate_snapshot), now()))
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), run_id, 3, "create_review_findings", "succeeded", digest, canonical_json([item["id"] for item in created]), None, timestamp, now()),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), run_id, 4, "evaluate_scene_gate", "succeeded", sha256_text(canonical_json(gate_snapshot)), gate_id, None, timestamp, now()),
            )
            connection.execute(
                "UPDATE agent_runs SET status='succeeded',policy_json=?,finished_at=? WHERE id=?",
                (canonical_json({**policy, "usage": provider_usage}), now(), run_id),
            )
            connection.execute("UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?", (gate_id, now(), attempt_id))
            connection.execute(
                "UPDATE work_items SET status='succeeded',output_refs_json=?,acceptance_json=?,updated_at=? WHERE id=?",
                (
                    canonical_json([gate_id, *[item["id"] for item in created]]),
                    canonical_json({
                        "manuscript_read_only": True,
                        "agent_run_id": run_id,
                        "provider_usage": provider_usage,
                        "fingerprints": context["fingerprints"],
                    }),
                    now(),
                    work_item_id,
                ),
            )
            self._bump_work(connection, work_id, version)
        return {"gate_id": gate_id, "agent_run_id": run_id, "simulation": provider.is_simulation, "metrics": review_metrics, "findings": created, "work": self.get_work(work_id)}

    def review_release(self, work_id: str, payload: dict):
        """Run the read-only semantic review, then evaluate the immutable release gate."""
        provider = self.provider
        return self._run_work_review_agent(
            work_id, payload, "release.review", provider=provider
        )

    def review_continuity(self, work_id: str, payload: dict):
        """Review ordered scene revisions without mutating manuscript or formal knowledge."""
        provider = self.provider
        return self._run_work_review_agent(
            work_id, payload, "continuity.review", provider=provider
        )

    def resolve_review_finding(self, work_id: str, finding_id: str, payload: dict):
        """Record a human decision for a finding; never silently removes audit evidence."""
        expected = int(payload.get("expected_version", -1))
        note = str(payload.get("note", "")).strip()
        if not note:
            raise DomainError("validation_error", "处理审查发现时必须说明理由。", details={"field": "note"})
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            finding = connection.execute(
                "SELECT * FROM review_findings WHERE id=? AND work_id=?", (finding_id, work_id)
            ).fetchone()
            if not finding:
                raise NotFound("review_finding", finding_id)
            if finding["status"] != "open":
                raise DomainError("finding_not_open", "该审查发现已经处理或被新审查替代。", status=409)
            connection.execute(
                "UPDATE review_findings SET status='resolved', resolved_at=? WHERE id=?", (now(), finding_id)
            )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (new_id("decision"), work_id, "review_finding", finding_id, "resolved", note, now()),
            )
            self._bump_work(connection, work_id, version)
        return {"finding_id": finding_id, "work": self.get_work(work_id)}

    def create_chapter(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        title = str(payload.get("title", "")).strip() or "第一章"
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            blueprint_artifact = connection.execute(
                "SELECT * FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)
            ).fetchone()
            if not blueprint_artifact or not blueprint_artifact["current_revision_id"]:
                raise DomainError("blueprint_required", "请先分析并确认故事方向。", status=409)
            blueprint_revision = connection.execute(
                "SELECT * FROM revisions WHERE id=?", (blueprint_artifact["current_revision_id"],)
            ).fetchone()
            blueprint = json.loads(self.repo.read_text(blueprint_revision["content_uri"]))
            if blueprint.get("status", "accepted") != "accepted":
                raise DomainError("blueprint_unconfirmed", "请先确认故事方向候选，再建立章节。", status=409)
            requested_volume_id = str(payload.get("volume_id", "")).strip()
            if requested_volume_id:
                volume = connection.execute(
                    "SELECT id FROM volumes WHERE id=? AND work_id=?", (requested_volume_id, work_id)
                ).fetchone()
            else:
                volume = connection.execute(
                    "SELECT id FROM volumes WHERE work_id=? ORDER BY stable_order_key LIMIT 1", (work_id,)
                ).fetchone()
            if not volume:
                raise DomainError("volume_required", "请先建立一个卷。", status=409)
            placeholder = connection.execute(
                "SELECT id FROM chapters WHERE work_id=? AND volume_id=? AND status='placeholder' ORDER BY stable_order_key LIMIT 1",
                (work_id, volume["id"]),
            ).fetchone()
            timestamp = now()
            if placeholder:
                chapter_id = placeholder["id"]
                connection.execute(
                    "UPDATE chapters SET title=?,status='planned',version=version+1,updated_at=? WHERE id=?",
                    (title, timestamp, chapter_id),
                )
            else:
                count = connection.execute(
                    "SELECT COUNT(*) FROM chapters WHERE volume_id=?", (volume["id"],)
                ).fetchone()[0]
                chapter_id = new_id("chapter")
                connection.execute(
                    "INSERT INTO chapters (id,work_id,volume_id,stable_order_key,title,status,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (chapter_id, work_id, volume["id"], f"{count + 1:06d}", title, "planned", 1, timestamp, timestamp),
                )
            self._record_current_story_structure(
                connection, work_id, workflow="structure.chapter.create"
            )
            self._bump_work(connection, work_id, version)
        return {"chapter_id": chapter_id, "work": self.get_work(work_id)}

    def set_writing_target(self, work_id: str, payload: dict):
        """Persist the chapter the Writing surface is currently responsible for."""
        expected = int(payload.get("expected_version", -1))
        chapter_id = str(payload.get("chapter_id", "")).strip()
        anchor_scene_id = str(payload.get("anchor_scene_id", "")).strip() or None
        if not chapter_id:
            raise DomainError("validation_error", "请选择当前要写作的章节。", details={"field": "chapter_id"})
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            chapter = connection.execute(
                "SELECT id,title FROM chapters WHERE id=? AND work_id=?", (chapter_id, work_id)
            ).fetchone()
            if not chapter:
                raise DomainError("invalid_writing_target", "当前写作章节不存在。", status=409)
            if anchor_scene_id:
                scene = connection.execute(
                    "SELECT id FROM scenes WHERE id=? AND chapter_id=? AND work_id=?",
                    (anchor_scene_id, chapter_id, work_id),
                ).fetchone()
                if not scene:
                    raise DomainError("invalid_writing_target", "承接场景不属于当前章节。", status=409)
            artifact = self._artifact(connection, work_id, "writing_target", "work", work_id)
            revision_id = self._add_revision(
                connection,
                artifact,
                {
                    "schema_version": "writing-target/1.0",
                    "surface": "chapter",
                    "chapter_id": chapter_id,
                    "chapter_title": chapter["title"],
                    "anchor_scene_id": anchor_scene_id,
                    "status": "active",
                },
                "user",
                {"workflow": "writing.target.select", "pack": PACK_VERSION, "chapter_id": chapter_id, "anchor_scene_id": anchor_scene_id},
            )
            self._bump_work(connection, work_id, version)
        return {"revision_id": revision_id, "work": self.get_work(work_id)}

    def create_volume(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        title = str(payload.get("title", "")).strip() or "未命名卷"
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            blueprint_artifact = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'",
                (work_id,),
            ).fetchone()
            if not blueprint_artifact or not blueprint_artifact["current_revision_id"]:
                raise DomainError("blueprint_required", "请先分析并确认故事方向。", status=409)
            blueprint_revision = connection.execute(
                "SELECT content_uri FROM revisions WHERE id=?",
                (blueprint_artifact["current_revision_id"],),
            ).fetchone()
            blueprint = json.loads(self.repo.read_text(blueprint_revision["content_uri"]))
            if blueprint.get("status", "accepted") != "accepted":
                raise DomainError("blueprint_unconfirmed", "请先确认故事方向候选，再建立卷。", status=409)
            count = connection.execute(
                "SELECT COUNT(*) FROM volumes WHERE work_id=?", (work_id,)
            ).fetchone()[0]
            volume_id = new_id("volume")
            chapter_id = new_id("chapter")
            timestamp = now()
            connection.execute(
                "INSERT INTO volumes VALUES (?,?,?,?,?,?,?,?)",
                (volume_id, work_id, f"{count + 1:06d}", title, "active", 1, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO chapters (id,work_id,volume_id,stable_order_key,title,status,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (chapter_id, work_id, volume_id, "000001", "第一章", "placeholder", 1, timestamp, timestamp),
            )
            self._record_current_story_structure(
                connection, work_id, workflow="structure.volume.create"
            )
            self._bump_work(connection, work_id, version)
        return {"volume_id": volume_id, "chapter_id": chapter_id, "work": self.get_work(work_id)}

    @staticmethod
    def _normalize_scene_asset_references(payload: dict) -> list[dict]:
        references = payload.get("references")
        if not isinstance(references, list):
            raise DomainError(
                "validation_error",
                "场景素材引用必须以列表提交。",
                details={"field": "references"},
            )
        if len(references) > 24:
            raise DomainError(
                "validation_error",
                "单个场景最多引用 24 个素材。",
                details={"field": "references", "max": 24},
            )
        normalized: list[dict] = []
        identities: set[tuple[str, str, str]] = set()
        exclusive_kinds: set[str] = set()
        for index, raw in enumerate(references):
            if not isinstance(raw, dict):
                raise DomainError(
                    "validation_error",
                    "场景素材引用条目必须是对象。",
                    details={"field": "references", "index": index},
                )
            asset_kind = str(raw.get("asset_kind") or "").strip()
            source_type = str(raw.get("source_type") or "").strip()
            source_asset_id = str(raw.get("source_asset_id") or "").strip()
            display_name = str(raw.get("display_name") or "").strip()
            source_version = str(raw.get("source_version") or "").strip()
            content_hash = str(raw.get("content_hash") or "").strip()
            content_hash_kind = str(raw.get("content_hash_kind") or "").strip()
            snapshot = raw.get("source_snapshot")
            if asset_kind not in {"background", "character", "sound", "cg"}:
                raise DomainError(
                    "validation_error",
                    "场景素材类型必须是背景、角色、音效或 CG。",
                    details={"field": "references", "index": index, "asset_kind": asset_kind},
                )
            if source_type not in {"resource_index", "custom_library"}:
                raise DomainError(
                    "validation_error",
                    "场景素材必须来自 AA 资源索引或我的素材库。",
                    details={"field": "references", "index": index, "source_type": source_type},
                )
            if not all((source_asset_id, display_name, source_version, content_hash, content_hash_kind)):
                raise DomainError(
                    "validation_error",
                    "场景素材引用缺少来源标识、版本或内容 Hash。",
                    details={"field": "references", "index": index},
                )
            if len(source_asset_id) > 300 or len(display_name) > 300 or len(source_version) > 160:
                raise DomainError(
                    "validation_error",
                    "场景素材引用字段过长。",
                    details={"field": "references", "index": index},
                )
            if not isinstance(snapshot, dict) or len(canonical_json(snapshot)) > 24_000:
                raise DomainError(
                    "validation_error",
                    "场景素材来源快照无效或过大。",
                    details={"field": "references", "index": index},
                )
            if source_type == "custom_library":
                if (
                    str(snapshot.get("source") or "") != "custom_library"
                    or str(snapshot.get("asset_id") or "") != source_asset_id
                    or str(snapshot.get("kind") or "") != asset_kind
                ):
                    raise DomainError(
                        "validation_error",
                        "自定义素材类型与场景引用不一致，未保存本次选择。",
                        details={"field": "references", "index": index, "asset_kind": asset_kind},
                    )
            if source_type == "resource_index" and str(snapshot.get("source") or "") == "writing_catalog":
                snapshot_key = str(snapshot.get("key") or snapshot.get("asset_id") or "")
                if snapshot_key != source_asset_id or str(snapshot.get("kind") or "") != asset_kind:
                    raise DomainError(
                        "validation_error",
                        "写作资源类型与场景引用不一致，未保存本次选择。",
                        details={"field": "references", "index": index, "asset_kind": asset_kind},
                    )
            identity = (asset_kind, source_type, source_asset_id)
            if identity in identities:
                raise DomainError(
                    "validation_error",
                    "同一素材不能在同一场景重复引用。",
                    details={"field": "references", "index": index},
                )
            if asset_kind in {"background", "sound", "cg"} and asset_kind in exclusive_kinds:
                raise DomainError(
                    "validation_error",
                    "每个场景只能选择一个背景、音效和 CG 引用。",
                    details={"field": "references", "index": index, "asset_kind": asset_kind},
                )
            identities.add(identity)
            exclusive_kinds.add(asset_kind)
            normalized.append(
                {
                    "asset_kind": asset_kind,
                    "source_type": source_type,
                    "source_asset_id": source_asset_id,
                    "display_name": display_name,
                    "source_version": source_version,
                    "content_hash": content_hash,
                    "content_hash_kind": content_hash_kind,
                    "source_snapshot": snapshot,
                }
            )
        return normalized

    def set_scene_asset_references(self, work_id: str, scene_id: str, payload: dict):
        """Replace the user-selected asset references for one Scene.

        This changes only the Scene's production-facing context. It never edits
        manuscript text, formal knowledge, or an existing ScriptRelease.
        """

        expected = int(payload.get("expected_version", -1))
        requested = self._normalize_scene_asset_references(payload)
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                "SELECT id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            current = self._scene_asset_references(connection, work_id, scene_id)
            current_comparable = [
                {
                    key: item[key]
                    for key in (
                        "asset_kind", "source_type", "source_asset_id", "display_name",
                        "source_version", "content_hash", "content_hash_kind", "source_snapshot",
                    )
                }
                for item in current
            ]
            if canonical_json(current_comparable) == canonical_json(requested):
                return {"changed": False, "invalidated_proposal_ids": [], "work": self.get_work(work_id)}

            timestamp = now()
            connection.execute(
                "DELETE FROM scene_asset_references WHERE work_id=? AND scene_id=?",
                (work_id, scene_id),
            )
            for reference in requested:
                connection.execute(
                    """INSERT INTO scene_asset_references
                       (id,work_id,scene_id,asset_kind,source_type,source_asset_id,
                        display_name,source_version,content_hash,content_hash_kind,
                        source_snapshot_json,production_copy_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id("scene_asset_ref"), work_id, scene_id,
                        reference["asset_kind"], reference["source_type"], reference["source_asset_id"],
                        reference["display_name"], reference["source_version"],
                        reference["content_hash"], reference["content_hash_kind"],
                        canonical_json(reference["source_snapshot"]), None, timestamp, timestamp,
                    ),
                )
            invalidated = self.repo.rows(
                connection.execute(
                    """SELECT id FROM proposals
                       WHERE work_id=? AND scope_type='scene' AND scope_id=?
                         AND kind='scene_script' AND status='pending'""",
                    (work_id, scene_id),
                )
            )
            if invalidated:
                connection.execute(
                    """UPDATE proposals SET status='superseded', decided_at=?
                       WHERE work_id=? AND scope_type='scene' AND scope_id=?
                         AND kind='scene_script' AND status='pending'""",
                    (timestamp, work_id, scene_id),
                )
            connection.execute(
                "UPDATE scenes SET version=version+1,updated_at=? WHERE id=?",
                (timestamp, scene_id),
            )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"), work_id, "scene_asset_references", scene_id,
                    "selected", f"用户更新了本场 {len(requested)} 个素材引用；正文与正式资料未改动。", timestamp,
                ),
            )
            self._bump_work(connection, work_id, version)
        return {
            "changed": True,
            "invalidated_proposal_ids": [item["id"] for item in invalidated],
            "work": self.get_work(work_id),
        }

    def suggest_scene_assets(self, work_id: str, scene_id: str) -> dict:
        """Return read-only, local-rule suggestions for the current scene.

        Suggestions describe missing asset slots and search terms only. They do
        not register an asset, change a Scene, or call a Provider.
        """
        with self.repo.connect() as connection:
            scene = connection.execute(
                "SELECT id,title,contract_json FROM scenes WHERE id=? AND work_id=?",
                (scene_id, work_id),
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            contract = json.loads(scene["contract_json"] or "{}")
            references = self._scene_asset_references(connection, work_id, scene_id)
            selected_kinds = {item["asset_kind"] for item in references}
            suggestions = []

            location = str(contract.get("location") or "").strip()
            if "background" not in selected_kinds:
                suggestions.append({
                    "asset_kind": "background",
                    "label": "本场背景",
                    "query": location or str(scene["title"]),
                    "reason": f"场景地点为“{location}”。" if location else "场景还没有背景引用。",
                })

            selection = contract.get("context_selection") if isinstance(contract.get("context_selection"), dict) else {}
            character_ids = selection.get("character_card_ids") if isinstance(selection.get("character_card_ids"), list) else []
            if "character" not in selected_kinds and character_ids:
                cards = {}
                for row in connection.execute(
                    "SELECT scope_id,current_revision_id FROM artifacts WHERE work_id=? AND kind='character_card'",
                    (work_id,),
                ).fetchall():
                    if not row["current_revision_id"]:
                        continue
                    revision = connection.execute(
                        "SELECT content_uri FROM revisions WHERE id=?", (row["current_revision_id"],)
                    ).fetchone()
                    if revision:
                        content = json.loads(self.repo.read_text(revision["content_uri"]))
                        cards[row["scope_id"]] = str(content.get("name") or row["scope_id"])
                names = [cards[item] for item in character_ids if item in cards]
                suggestions.append({
                    "asset_kind": "character",
                    "label": "本场角色",
                    "query": names[0] if names else "",
                    "reason": f"上下文已固定 {len(names) or len(character_ids)} 张人物卡。",
                })

            trigger = str(contract.get("external_trigger") or contract.get("scene_type") or contract.get("goal") or "").strip()
            if "sound" not in selected_kinds and trigger:
                suggestions.append({
                    "asset_kind": "sound",
                    "label": "本场音效",
                    "query": trigger,
                    "reason": "场景合同包含外部触发或动作线索，可先检查对应音效。",
                })

            render_mode = str(contract.get("render_mode") or "").strip().casefold()
            if "cg" not in selected_kinds and render_mode in {"cg", "illustration", "插图", "立绘"}:
                suggestions.append({
                    "asset_kind": "cg",
                    "label": "本场 CG",
                    "query": str(scene["title"]),
                    "reason": "场景合同明确要求插图或 CG 表现。",
                })

            return {
                "schema_version": "scene-asset-suggestions/1.0",
                "scene_id": scene_id,
                "source": "local-rules",
                "provider": "fake / local-rules",
                "can_call_model": False,
                "existing_references": self._scene_asset_reference_snapshot(references),
                "suggestions": suggestions,
            }

    def create_scene(self, work_id: str, chapter_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        title = str(payload.get("title", "")).strip() or "未命名场景"
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            chapter = connection.execute("SELECT id FROM chapters WHERE id=? AND work_id=?", (chapter_id, work_id)).fetchone()
            if not chapter:
                raise NotFound("chapter", chapter_id)
            brief_artifact = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='brief'", (work_id,)
            ).fetchone()
            brief_mode = "bond_short"
            if brief_artifact and brief_artifact["current_revision_id"]:
                brief_revision = connection.execute(
                    "SELECT content_uri FROM revisions WHERE id=?", (brief_artifact["current_revision_id"],)
                ).fetchone()
                saved_brief = json.loads(self.repo.read_text(brief_revision["content_uri"]))
                if saved_brief.get("mode") in MODE_SOURCES:
                    brief_mode = saved_brief["mode"]
            writing_mode = str(payload.get("writing_mode") or brief_mode).strip()
            if writing_mode not in MODE_SOURCES:
                raise DomainError("validation_error", "本场起草规则包无效。", details={"field": "writing_mode", "mode": writing_mode})
            contract = {
                "location": str(payload.get("location", "")).strip(),
                "goal": str(payload.get("goal", "")).strip(),
                "known_facts": payload.get("known_facts", []),
                "forbidden_reveals": payload.get("forbidden_reveals", []),
                "stop_boundary": str(payload.get("stop_boundary", "必要事实成立后停止")).strip(),
                # A Work may mix directions. A single provider call may not.
                "writing_mode": writing_mode,
            }
            for field in (
                "scene_type", "external_trigger", "hidden_expectation", "defense", "choice",
                "plot_delta", "emotion_delta", "residue", "ending_payoff", "sensei_scene_function",
                "render_mode",
            ):
                if field in payload:
                    contract[field] = str(payload.get(field, "")).strip()
            if "has_sensei" in payload:
                contract["has_sensei"] = bool(payload.get("has_sensei"))
            if "information_ownership" in payload:
                contract["information_ownership"] = self._contract_mapping(payload, "information_ownership")
            if "exchange_chain" in payload:
                contract["exchange_chain"] = self._contract_sequence(payload, "exchange_chain")
            if "character_phase" in payload:
                contract["character_phase"] = self._contract_mapping(payload, "character_phase")
            if "emotion_states" in payload:
                emotion_states = payload.get("emotion_states")
                if not isinstance(emotion_states, (dict, list)):
                    raise DomainError("validation_error", "场景情绪状态必须是对象或数组。", details={"field": "emotion_states"})
                contract["emotion_states"] = emotion_states
            count = connection.execute("SELECT COUNT(*) FROM scenes WHERE chapter_id=?", (chapter_id,)).fetchone()[0]
            scene_id = new_id("scene")
            timestamp = now()
            connection.execute("INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?,?,?)", (scene_id, work_id, chapter_id, f"{count + 1:06d}", title, "planned", 1, None, canonical_json(contract), timestamp, timestamp))
            self._record_current_story_structure(
                connection, work_id, workflow="structure.scene.create"
            )
            self._bump_work(connection, work_id, version)
        return {"scene_id": scene_id, "work": self.get_work(work_id)}

    def reorder_structure(self, work_id: str, payload: dict):
        """Persist chapter order and scene placement without changing scene identity.

        Structure is part of a release's meaning, so the operation is versioned
        at the Work level. It deliberately leaves SceneContract, manuscript
        Revisions and Proposal contents alone: only parent chapter and order are
        updated. A release review snapshot becomes stale naturally because it
        records scene revision IDs in structural order.
        """
        expected = int(payload.get("expected_version", -1))
        chapter_ids = payload.get("chapter_ids")
        placements = payload.get("scene_placements")
        if not isinstance(chapter_ids, list) or not isinstance(placements, list):
            raise DomainError(
                "validation_error",
                "章节顺序和场景安排必须以数组提交。",
                details={"fields": ["chapter_ids", "scene_placements"]},
            )
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            chapters = connection.execute(
                "SELECT id,stable_order_key FROM chapters WHERE work_id=? ORDER BY stable_order_key",
                (work_id,),
            ).fetchall()
            scenes = connection.execute(
                "SELECT id,chapter_id,stable_order_key FROM scenes WHERE work_id=?",
                (work_id,),
            ).fetchall()
            current_chapter_ids = {chapter["id"] for chapter in chapters}
            requested_chapter_ids = [str(value).strip() for value in chapter_ids]
            if len(requested_chapter_ids) != len(chapters) or set(requested_chapter_ids) != current_chapter_ids:
                raise DomainError(
                    "invalid_structure_order",
                    "章节顺序必须恰好包含当前作品的全部章节。",
                    details={"expected_chapter_ids": sorted(current_chapter_ids)},
                )
            if len(set(requested_chapter_ids)) != len(requested_chapter_ids):
                raise DomainError("invalid_structure_order", "章节顺序不能包含重复章节。")

            requested_scene_ids = []
            grouped = {chapter_id: [] for chapter_id in requested_chapter_ids}
            for index, placement in enumerate(placements):
                if not isinstance(placement, dict):
                    raise DomainError("validation_error", "场景安排条目无效。", details={"index": index})
                scene_id = str(placement.get("scene_id", "")).strip()
                chapter_id = str(placement.get("chapter_id", "")).strip()
                if not scene_id or not chapter_id:
                    raise DomainError("validation_error", "场景安排需要场景和目标章节。", details={"index": index})
                if chapter_id not in grouped:
                    raise DomainError(
                        "invalid_structure_order",
                        "场景不能移动到当前作品以外的章节。",
                        details={"index": index, "chapter_id": chapter_id},
                    )
                requested_scene_ids.append(scene_id)
                grouped[chapter_id].append(scene_id)

            current_scene_ids = {scene["id"] for scene in scenes}
            if len(requested_scene_ids) != len(scenes) or set(requested_scene_ids) != current_scene_ids:
                raise DomainError(
                    "invalid_structure_order",
                    "场景安排必须恰好包含当前作品的全部场景。",
                    details={"expected_scene_ids": sorted(current_scene_ids)},
                )
            if len(set(requested_scene_ids)) != len(requested_scene_ids):
                raise DomainError("invalid_structure_order", "场景安排不能包含重复场景。")

            current_chapter_order = [chapter["id"] for chapter in chapters]
            current_scene_state = {
                scene["id"]: (scene["chapter_id"], scene["stable_order_key"])
                for scene in scenes
            }
            changed = current_chapter_order != requested_chapter_ids
            for chapter_id, scene_ids in grouped.items():
                for index, scene_id in enumerate(scene_ids, start=1):
                    if current_scene_state[scene_id] != (chapter_id, f"{index:06d}"):
                        changed = True

            if not changed:
                return {"changed": False, "work": self.get_work(work_id)}

            timestamp = now()
            for index, chapter_id in enumerate(requested_chapter_ids, start=1):
                connection.execute(
                    "UPDATE chapters SET stable_order_key=?, version=version+1, updated_at=? WHERE id=?",
                    (f"{index:06d}", timestamp, chapter_id),
                )
            for chapter_id, scene_ids in grouped.items():
                for index, scene_id in enumerate(scene_ids, start=1):
                    connection.execute(
                        "UPDATE scenes SET chapter_id=?, stable_order_key=?, version=version+1, updated_at=? WHERE id=?",
                        (chapter_id, f"{index:06d}", timestamp, scene_id),
                    )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"),
                    work_id,
                    "structure",
                    work_id,
                    "reordered",
                    "用户调整了章节或场景顺序；正文修订保持不变，需重新运行全篇审查。",
                    timestamp,
                ),
            )
            self._record_current_story_structure(
                connection, work_id, workflow="structure.reorder"
            )
            self._bump_work(connection, work_id, version)
        return {"changed": True, "work": self.get_work(work_id)}

    @staticmethod
    def _contract_lines(payload: dict, field: str) -> list[str]:
        values = payload.get(field, [])
        if not isinstance(values, list):
            raise DomainError("validation_error", "场景契约中的列表必须是数组。", details={"field": field})
        return [item for item in (str(value).strip() for value in values) if item]

    @staticmethod
    def _contract_mapping(payload: dict, field: str) -> dict:
        value = payload.get(field, {})
        if not isinstance(value, dict):
            raise DomainError("validation_error", "场景契约中的映射必须是对象。", details={"field": field})
        return value

    @staticmethod
    def _contract_sequence(payload: dict, field: str) -> list:
        value = payload.get(field, [])
        if not isinstance(value, list):
            raise DomainError("validation_error", "场景契约中的序列必须是数组。", details={"field": field})
        return value

    @staticmethod
    def _scene_has_sensei(scene_contract: dict, brief: dict) -> bool:
        if "has_sensei" in scene_contract:
            return bool(scene_contract["has_sensei"])
        return bool(brief.get("has_sensei", False))

    @staticmethod
    def _normalize_official_script(text: str, context: dict, *, allow_brief_speakers: bool = False) -> str:
        allowed = {"旁白"}
        for card in context.get("runtime_character_cards", []):
            for value in [card.get("name"), card.get("canonical_name"), *card.get("aliases", [])]:
                if str(value or "").strip():
                    allowed.add(str(value).strip())
        if allow_brief_speakers:
            allowed.update(str(item).strip() for item in context.get("brief", {}).get("characters", []) if str(item).strip())
        if WritingService._scene_has_sensei(context.get("scene_contract", {}), context.get("brief", {})):
            allowed.update({"老师", "Sensei"})

        normalized = []
        invalid = []
        for line_number, raw_line in enumerate(str(text).splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            ascii_divider = line.find(":")
            chinese_divider = line.find("：")
            dividers = [value for value in (ascii_divider, chinese_divider) if value >= 0]
            divider = min(dividers) if dividers else -1
            if divider <= 0:
                invalid.append({"line": line_number, "reason": "missing_speaker_separator", "text": line[:160]})
                continue
            speaker = line[:divider].strip()
            content = line[divider + 1:].strip()
            if not speaker or not content:
                invalid.append({"line": line_number, "reason": "empty_speaker_or_content", "text": line[:160]})
                continue
            if speaker not in allowed:
                invalid.append({"line": line_number, "reason": "unknown_speaker", "speaker": speaker})
                continue
            normalized.append(f"{speaker}: {content}")
        if invalid:
            raise DomainError(
                "provider_output_invalid",
                "模型返回的正文不符合官方剧本文本格式，未创建 Proposal。",
                status=502,
                details={"invalid_lines": invalid, "allowed_speakers": sorted(allowed)},
            )
        if not normalized:
            raise DomainError("provider_output_invalid", "模型没有返回可用正文，未创建 Proposal。", status=502)
        return "\n".join(normalized) + "\n"

    def update_scene_contract(self, work_id: str, scene_id: str, payload: dict):
        """Revise one Scene's generative boundary without editing manuscript text."""
        expected = int(payload.get("expected_version", -1))
        title = str(payload.get("title", "")).strip()
        location = str(payload.get("location", "")).strip()
        goal = str(payload.get("goal", "")).strip()
        known_facts = self._contract_lines(payload, "known_facts")
        forbidden_reveals = self._contract_lines(payload, "forbidden_reveals")
        stop_boundary = str(payload.get("stop_boundary", "")).strip()
        requested_mode = str(payload.get("writing_mode", "")).strip()
        if not title:
            raise DomainError("validation_error", "场景标题不能为空。", details={"field": "title"})
        if not goal:
            raise DomainError("validation_error", "场景目标不能为空。", details={"field": "goal"})
        if not stop_boundary:
            raise DomainError("validation_error", "停止边界不能为空。", details={"field": "stop_boundary"})
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute("SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            contract = json.loads(scene["contract_json"])
            writing_mode = requested_mode or contract.get("writing_mode")
            if not writing_mode:
                brief_artifact = connection.execute(
                    "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='brief'", (work_id,)
                ).fetchone()
                if brief_artifact and brief_artifact["current_revision_id"]:
                    brief_revision = connection.execute(
                        "SELECT content_uri FROM revisions WHERE id=?", (brief_artifact["current_revision_id"],)
                    ).fetchone()
                    writing_mode = json.loads(self.repo.read_text(brief_revision["content_uri"])).get("mode")
            if writing_mode not in MODE_SOURCES:
                raise DomainError("validation_error", "本场起草规则包无效。", details={"field": "writing_mode", "mode": writing_mode})
            contract.update({
                "location": location,
                "goal": goal,
                "known_facts": known_facts,
                "forbidden_reveals": forbidden_reveals,
                "stop_boundary": stop_boundary,
                "writing_mode": writing_mode,
                "title_source": "manual",
            })
            for field in (
                "scene_type", "external_trigger", "hidden_expectation", "defense", "choice",
                "plot_delta", "emotion_delta", "residue", "ending_payoff", "sensei_scene_function",
                "render_mode",
            ):
                if field in payload:
                    contract[field] = str(payload.get(field, "")).strip()
            for field in ("information_ownership", "character_phase"):
                if field in payload:
                    contract[field] = self._contract_mapping(payload, field)
            if "exchange_chain" in payload:
                contract["exchange_chain"] = self._contract_sequence(payload, "exchange_chain")
            if "emotion_states" in payload:
                emotion_states = payload.get("emotion_states")
                if not isinstance(emotion_states, (dict, list)):
                    raise DomainError("validation_error", "场景情绪状态必须是对象或数组。", details={"field": "emotion_states"})
                contract["emotion_states"] = emotion_states
            if "has_sensei" in payload:
                contract["has_sensei"] = bool(payload.get("has_sensei"))
            timestamp = now()
            pending = connection.execute(
                "SELECT id FROM proposals WHERE work_id=? AND scope_type='scene' AND scope_id=? AND status='pending'",
                (work_id, scene_id),
            ).fetchall()
            if pending:
                connection.execute(
                    "UPDATE proposals SET status='superseded', decided_at=? WHERE work_id=? AND scope_type='scene' AND scope_id=? AND status='pending'",
                    (timestamp, work_id, scene_id),
                )
                for proposal in pending:
                    connection.execute(
                        "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                        (new_id("decision"), work_id, "proposal", proposal["id"], "superseded", "场景契约已更新，候选不再适用。", timestamp),
                    )
            connection.execute(
                "UPDATE scenes SET title=?, contract_json=?, version=version+1, updated_at=? WHERE id=?",
                (title, canonical_json(contract), timestamp, scene_id),
            )
            self._bump_work(connection, work_id, version)
        return {"scene_id": scene_id, "superseded_proposal_ids": [row["id"] for row in pending], "work": self.get_work(work_id)}

    @staticmethod
    def _context_selection_ids(payload: dict, field: str) -> list[str]:
        values = payload.get(field, [])
        if not isinstance(values, list):
            raise DomainError("validation_error", "场景上下文选择必须是数组。", details={"field": field})
        result = []
        seen = set()
        for value in values:
            item_id = str(value).strip()
            if not item_id:
                raise DomainError("validation_error", "场景上下文不能包含空白 ID。", details={"field": field})
            if item_id in seen:
                raise DomainError("validation_error", "场景上下文不能重复选择同一条资料。", details={"field": field, "id": item_id})
            seen.add(item_id)
            result.append(item_id)
        return result

    def configure_scene_context(self, work_id: str, scene_id: str, payload: dict):
        """Persist the exact work-owned inputs a scene is allowed to assemble.

        The selection does not change manuscript text or a pending Proposal. It
        only constrains future context snapshots and therefore stays auditable
        in the Scene contract itself.
        """
        expected = int(payload.get("expected_version", -1))
        character_card_ids = self._context_selection_ids(payload, "character_card_ids")
        world_item_ids = self._context_selection_ids(payload, "world_item_ids")
        reference_file_ids = self._context_selection_ids(payload, "reference_file_ids")
        if not character_card_ids:
            raise DomainError(
                "validation_error",
                "本场上下文至少需要选择一张已确认的人物卡。",
                details={"field": "character_card_ids"},
            )
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                "SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)

            cards = {}
            for artifact in connection.execute(
                "SELECT * FROM artifacts WHERE work_id=? AND kind='character_card'", (work_id,)
            ).fetchall():
                if not artifact["current_revision_id"]:
                    continue
                revision = connection.execute(
                    "SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)
                ).fetchone()
                cards[artifact["scope_id"]] = json.loads(self.repo.read_text(revision["content_uri"]))
            for card_id in character_card_ids:
                card = cards.get(card_id)
                if not card:
                    raise DomainError("invalid_context_selection", "选择的人物卡不属于当前作品。", details={"field": "character_card_ids", "id": card_id})
                if card.get("status", "active") != "active" or card.get("trust_status") != "confirmed":
                    raise DomainError(
                        "invalid_context_selection",
                        "本场只能选择已确认且未归档的人物卡。",
                        details={"field": "character_card_ids", "id": card_id},
                    )

            world_items = {}
            world_artifact = connection.execute(
                "SELECT * FROM artifacts WHERE work_id=? AND kind='world_bible'", (work_id,)
            ).fetchone()
            if world_artifact and world_artifact["current_revision_id"]:
                world_revision = connection.execute(
                    "SELECT * FROM revisions WHERE id=?", (world_artifact["current_revision_id"],)
                ).fetchone()
                world = json.loads(self.repo.read_text(world_revision["content_uri"]))
                for collection in ("entities", "rules", "timeline"):
                    for item in world.get(collection, []):
                        world_items[item.get("id")] = item
            for item_id in world_item_ids:
                item = world_items.get(item_id)
                if not item:
                    raise DomainError("invalid_context_selection", "选择的世界观条目不属于当前作品。", details={"field": "world_item_ids", "id": item_id})
                if item.get("status", "active") != "active" or item.get("confidence_status") != "confirmed":
                    raise DomainError(
                        "invalid_context_selection",
                        "本场只能选择已确认且未归档的世界观条目。",
                        details={"field": "world_item_ids", "id": item_id},
                    )

            reference_rows = connection.execute(
                "SELECT id FROM reference_files WHERE work_id=?", (work_id,)
            ).fetchall()
            reference_ids = {row["id"] for row in reference_rows}
            for reference_id in reference_file_ids:
                if reference_id not in reference_ids:
                    raise DomainError("invalid_context_selection", "选择的证据资料不属于当前作品。", details={"field": "reference_file_ids", "id": reference_id})

            contract = json.loads(scene["contract_json"])
            contract["context_selection"] = {
                "mode": "explicit",
                "character_card_ids": character_card_ids,
                "world_item_ids": world_item_ids,
                "reference_file_ids": reference_file_ids,
            }
            connection.execute(
                "UPDATE scenes SET contract_json=?, version=version+1, updated_at=? WHERE id=?",
                (canonical_json(contract), now(), scene_id),
            )
            self._bump_work(connection, work_id, version)
        return {
            "scene_id": scene_id,
            "context_selection": contract["context_selection"],
            "work": self.get_work(work_id),
        }

    def _configure_intent_scene_context(
        self,
        work_id: str,
        scene_id: str,
        *,
        expected_version: int,
        character_card_ids: list[str],
        world_item_ids: list[str],
        reference_file_ids: list[str],
    ) -> dict:
        """Persist an automatic selection, including a fail-closed empty cast."""
        target = {
            "mode": "explicit",
            "source": "intent_auto",
            "character_card_ids": list(character_card_ids),
            "world_item_ids": list(world_item_ids),
            "reference_file_ids": list(reference_file_ids),
        }
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected_version)
            scene = connection.execute(
                "SELECT contract_json FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            contract = json.loads(scene["contract_json"] or "{}")
            if contract.get("context_selection") == target:
                return {"scene_id": scene_id, "context_selection": target, "work": self.get_work(work_id)}
            pending = connection.execute(
                "SELECT id FROM proposals WHERE work_id=? AND scope_type='scene' AND scope_id=? AND status='pending'",
                (work_id, scene_id),
            ).fetchall()
            timestamp = now()
            for proposal in pending:
                connection.execute("UPDATE proposals SET status='superseded',decided_at=? WHERE id=? AND status='pending'", (timestamp, proposal["id"]))
                connection.execute(
                    "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                    (new_id("decision"), work_id, "proposal", proposal["id"], "superseded", "自然语言场景的人物上下文已重新匹配，旧候选不再适用。", timestamp),
                )
            contract["context_selection"] = target
            connection.execute("UPDATE scenes SET contract_json=?,version=version+1,updated_at=? WHERE id=?", (canonical_json(contract), timestamp, scene_id))
            self._bump_work(connection, work_id, version)
        return {"scene_id": scene_id, "context_selection": target, "superseded_proposal_ids": [row["id"] for row in pending], "work": self.get_work(work_id)}

    @staticmethod
    def _runtime_character_card(
        content: dict,
        revision_id: str,
        scene_contract: dict,
        active_names: list[str],
        has_sensei: bool,
    ) -> dict:
        profile = content.get("ba_profile") if isinstance(content.get("ba_profile"), dict) else content
        speech = profile.get("speech") if isinstance(profile.get("speech"), dict) else {}
        scene_text = " ".join(
            str(scene_contract.get(key, ""))
            for key in ("scene_type", "goal", "location", "external_trigger", "private_pressure")
        ).casefold()

        decisions = profile.get("decision_patterns") if isinstance(profile.get("decision_patterns"), dict) else {}
        requested_decision = str(scene_contract.get("decision_mode", "")).strip()
        selected_decisions = {}
        if requested_decision and requested_decision in decisions:
            selected_decisions[requested_decision] = decisions[requested_decision]
        elif decisions:
            scored = sorted(
                decisions.items(),
                key=lambda item: (
                    0 if str(item[0]).casefold() in scene_text else 1,
                    list(decisions).index(item[0]),
                ),
            )
            selected_decisions[scored[0][0]] = scored[0][1]

        emotions = profile.get("emotions") if isinstance(profile.get("emotions"), dict) else {}
        requested_states = scene_contract.get("emotion_states", [])
        if isinstance(requested_states, dict):
            requested_states = requested_states.get(content.get("name"), [])
        if isinstance(requested_states, str):
            requested_states = [requested_states]
        selected_state_names = [
            str(item).strip() for item in requested_states
            if str(item).strip() in emotions
        ][:2]
        if not selected_state_names and emotions:
            matched = [name for name in emotions if str(name).casefold() in scene_text]
            selected_state_names = (matched or list(emotions))[:2]
        selected_states = {
            name: emotions[name] for name in selected_state_names if name in emotions
        }

        raw_examples = speech.get("voice_examples", [])
        if isinstance(raw_examples, str):
            raw_examples = [raw_examples]
        voice_examples = []
        for item in raw_examples if isinstance(raw_examples, list) else []:
            if isinstance(item, str):
                item = {"line": item}
            if not isinstance(item, dict) or not str(item.get("line", "")).strip():
                continue
            evidence_status = str(item.get("evidence_status", "user_confirmed")).strip()
            if evidence_status == "external_unverified":
                continue
            voice_examples.append({
                "line": str(item["line"]).strip(),
                "source_id": str(item.get("source_id") or f"character-card:{revision_id}"),
                "evidence_status": evidence_status,
                "state": str(item.get("state", "")).strip(),
                "function": str(item.get("function", "")).strip(),
                "phase": str(item.get("phase", "")).strip(),
            })
        if not voice_examples:
            voice_examples = [
                {
                    "line": str(line).strip(),
                    "source_id": f"character-card:{revision_id}",
                    "evidence_status": "user_confirmed",
                    "state": "",
                    "function": "人物卡声音锚点",
                    "phase": "",
                }
                for line in content.get("voice_anchors", [])
                if str(line).strip()
            ]
        voice_examples = voice_examples[:8]

        raw_sequences = speech.get("voice_sequences", [])
        voice_sequences = []
        for item in raw_sequences if isinstance(raw_sequences, list) else []:
            if not isinstance(item, dict) or not str(item.get("source_id", "")).strip():
                continue
            turns = item.get("turns")
            if not isinstance(turns, list) or not 3 <= len(turns) <= 8:
                continue
            normalized_turns = [
                {"speaker": str(turn.get("speaker", "")).strip(), "line": str(turn.get("line", "")).strip()}
                for turn in turns if isinstance(turn, dict)
            ]
            if len(normalized_turns) != len(turns) or any(not turn["speaker"] or not turn["line"] for turn in normalized_turns):
                continue
            speakers = {turn["speaker"] for turn in normalized_turns}
            if not speakers.intersection(active_names + (["老师", "Sensei"] if has_sensei else [])):
                continue
            voice_sequences.append({
                "source_id": str(item["source_id"]).strip(),
                "context": str(item.get("context", "")).strip(),
                "function": str(item.get("function", "")).strip(),
                "turns": normalized_turns,
                "phase": str(item.get("phase", "")).strip(),
            })
        voice_sequences = voice_sequences[:3]

        relations = profile.get("relations") if isinstance(profile.get("relations"), dict) else {}
        if not relations:
            relations = {
                "peers": {
                    item["target"]: {
                        "kind": item.get("kind", "关系待定"),
                        "summary": item.get("summary", ""),
                        "status": item.get("status", "confirmed"),
                    }
                    for item in content.get("relationships", [])
                    if item.get("target") in active_names
                }
            }
        address_patterns = speech.get("address_patterns") if isinstance(speech.get("address_patterns"), dict) else {}
        ooc_constraints = profile.get("ooc_constraints") or profile.get("ooc") or content.get("ooc_constraints", [])
        if isinstance(ooc_constraints, str):
            ooc_constraints = [ooc_constraints]

        runtime = {
            "schema_version": "runtime-character-card/1.1",
            "name": content.get("name"),
            "canonical_name": content.get("canonical_name") or content.get("name"),
            "aliases": content.get("aliases", []),
            "source_revision_id": revision_id,
            "source_hash": content.get("source_hash") or sha256_text(canonical_json(profile)),
            "extractor_version": content.get("extractor_version") or "halocue-runtime-character/1.1",
            "current_phase": str(scene_contract.get("character_phase", {}).get(content.get("name"), ""))
            if isinstance(scene_contract.get("character_phase"), dict) else "",
            "core": profile.get("core") or {"summary": content.get("summary", ""), "role": content.get("role", "")},
            "decision_patterns": selected_decisions,
            "emotion_states": selected_states,
            "relations": relations,
            "address_patterns": address_patterns,
            "knowledge_boundary": content.get("knowledge_boundary") or profile.get("knowledge_boundary", ""),
            "ooc_constraints": [str(item).strip() for item in ooc_constraints if str(item).strip()][:4],
            "voice_anchors": [item["line"] for item in voice_examples[:4]],
            "speech": {
                "sentence_traits": speech.get("sentence_traits", {}),
                "voice_examples": voice_examples,
                "voice_sequences": voice_sequences,
            },
            "special_mechanisms": profile.get("special_mechanisms", {}),
            "source_refs": content.get("source_refs", []),
            "trust_status": content.get("trust_status", "open"),
        }
        runtime["runtime_hash"] = sha256_text(canonical_json(runtime))
        runtime["validation"] = {
            "voice_evidence": "ready" if voice_examples or voice_sequences else "missing",
            "ooc_constraints": "ready" if runtime["ooc_constraints"] else "missing",
        }
        return runtime

    @staticmethod
    def _traceable_text_excerpt(text: str, *, max_chars: int = 6000, include_start: bool = True) -> dict:
        value = str(text or "")
        if len(value) <= max_chars:
            return {
                "text": value,
                "truncated": False,
                "segments": [{"label": "full", "char_start": 0, "char_end": len(value), "text": value}],
            }
        segment_size = max(400, max_chars // (3 if include_start else 2))
        spans = []
        if include_start:
            spans.append(("start", 0, min(len(value), segment_size)))
        middle_start = max(0, len(value) // 2 - segment_size // 2)
        spans.append(("middle", middle_start, min(len(value), middle_start + segment_size)))
        tail_start = max(0, len(value) - segment_size)
        spans.append(("tail", tail_start, len(value)))
        unique = []
        seen = set()
        for label, start, end in spans:
            key = (start, end)
            if key in seen:
                continue
            seen.add(key)
            unique.append({"label": label, "char_start": start, "char_end": end, "text": value[start:end]})
        return {
            "text": "\n\n".join(f"[{item['label']}]\n{item['text']}" for item in unique),
            "truncated": True,
            "segments": unique,
        }

    def assemble_context(self, work_id: str, scene_id: str):
        with self.repo.connect() as connection:
            scene = connection.execute("SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            scene_contract = json.loads(scene["contract_json"])
            scene_asset_references = self._scene_asset_references(connection, work_id, scene_id)
            scene_asset_reference_digest = sha256_text(canonical_json(scene_asset_references))
            selection = scene_contract.get("context_selection") or {"mode": "legacy"}
            explicit_selection = selection.get("mode") == "explicit"
            artifacts = connection.execute("SELECT * FROM artifacts WHERE work_id=? AND kind IN ('brief','story_blueprint','story_structure','work_canon','world_bible')", (work_id,)).fetchall()
            values = {}
            revision_refs = []
            for artifact in artifacts:
                if artifact["current_revision_id"]:
                    revision = connection.execute("SELECT * FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone()
                    values[artifact["kind"]] = json.loads(self.repo.read_text(revision["content_uri"]))
                    revision_refs.append(revision["id"])
            if "brief" not in values or "story_blueprint" not in values:
                raise DomainError("context_incomplete", "请先保存写作想法并建立故事方向。", status=409)
            if values["brief"].get("status", "confirmed") != "confirmed" or values["story_blueprint"].get("status", "accepted") != "accepted":
                raise DomainError("context_incomplete", "请先确认故事方向候选，再装配场景上下文。", status=409)
            scene_mode = scene_contract.get("writing_mode") or values["brief"].get("mode")
            if scene_mode not in MODE_SOURCES:
                raise DomainError(
                    "context_incomplete",
                    "本场尚未确定可用的起草规则包。",
                    status=409,
                    details={"field": "writing_mode", "mode": scene_mode},
                )
            has_sensei = self._scene_has_sensei(scene_contract, values["brief"])
            skill_runtime = self.ba_skill.compile(scene_mode, has_sensei, task_id="scene.draft.generate")
            skill_ready = skill_runtime["status"] == "ready"
            reference_rows = connection.execute(
                "SELECT id,title,kind,content_uri,content_hash,source_label,trust_status,version FROM reference_files WHERE work_id=? ORDER BY updated_at DESC",
                (work_id,),
            ).fetchall()
            selected_reference_ids = set(selection.get("reference_file_ids", [])) if explicit_selection else None
            reference_files = []
            for reference in reference_rows:
                if selected_reference_ids is not None and reference["id"] not in selected_reference_ids:
                    continue
                full_text = self.repo.read_text(reference["content_uri"])
                excerpt = self._traceable_text_excerpt(full_text)
                reference_files.append({
                    "id": reference["id"],
                    "title": reference["title"],
                    "kind": reference["kind"],
                    "source_label": reference["source_label"],
                    "trust_status": reference["trust_status"],
                    "version": reference["version"],
                    "content_hash": reference["content_hash"],
                    "content": excerpt["text"],
                    "content_truncated": excerpt["truncated"],
                    "excerpt_segments": excerpt["segments"],
                })
            brief_characters = values["brief"].get("characters", [])
            card_rows = connection.execute("SELECT * FROM artifacts WHERE work_id=? AND kind='character_card'", (work_id,)).fetchall()
            cards = {}
            cards_by_name = {}
            unverified_cards = {}
            for card_artifact in card_rows:
                if card_artifact["current_revision_id"]:
                    card_revision = connection.execute("SELECT * FROM revisions WHERE id=?", (card_artifact["current_revision_id"],)).fetchone()
                    card_content = json.loads(self.repo.read_text(card_revision["content_uri"]))
                    if card_content.get("status", "active") != "archived":
                        card_name = card_content.get("name")
                        if card_content.get("trust_status", "confirmed") == "confirmed":
                            card = {"revision_id": card_revision["id"], "content": card_content}
                            cards[card_artifact["scope_id"]] = card
                            cards_by_name[card_name] = card
                        else:
                            unverified_cards[card_name] = card_content.get("trust_status", "open")
            selected_card_ids = selection.get("character_card_ids", []) if explicit_selection else []
            selected_cards = []
            if explicit_selection:
                for card_id in selected_card_ids:
                    selected = cards.get(card_id)
                    if selected:
                        selected_cards.append((card_id, selected))
            else:
                selected_cards = [
                    (card_id, card)
                    for card_id, card in cards.items()
                    if card["content"].get("name") in brief_characters
                ]
            missing_cards = []
            if explicit_selection:
                missing_cards = [card_id for card_id in selected_card_ids if card_id not in cards]
            else:
                missing_cards = [name for name in brief_characters if name not in cards_by_name]
            active_names = [
                card["content"].get("name")
                for _, card in selected_cards
                if card["content"].get("name")
            ]
            runtime_cards = []
            for _, card in selected_cards:
                runtime_cards.append(self._runtime_character_card(
                    card["content"],
                    card["revision_id"],
                    scene_contract,
                    active_names,
                    has_sensei,
                ))
                revision_refs.append(card["revision_id"])
            runtime_card_warnings = [
                {
                    "name": card["name"],
                    "missing": [key for key, value in card["validation"].items() if value != "ready"],
                }
                for card in runtime_cards
                if any(value != "ready" for value in card["validation"].values())
            ]
            work_canon = values.get("work_canon")
            if work_canon:
                # Draft, inferred, conflicted, and archived memories are visible in the library,
                # but may not be asserted as facts in a new scene prompt.
                work_canon = {
                    **work_canon,
                    "facts": [
                        fact for fact in work_canon.get("facts", [])
                        if fact.get("status", "active") != "archived" and fact.get("confidence_status") == "confirmed"
                    ],
                }
            world_bible = values.get("world_bible")
            unverified_world_items = []
            if world_bible:
                for collection in ("entities", "rules", "timeline"):
                    for item in world_bible.get(collection, []):
                        if item.get("status", "active") != "archived" and item.get("confidence_status") != "confirmed":
                            unverified_world_items.append({
                                "id": item.get("id"),
                                "kind": collection,
                                "label": item.get("name") or item.get("text"),
                                "confidence_status": item.get("confidence_status", "open"),
                            })
                # Draft and archived world knowledge remains in immutable history, but is not
                # asserted as established setting in a new scene prompt.
                world_bible = {
                    **world_bible,
                    "entities": [
                        item for item in world_bible.get("entities", [])
                        if item.get("status", "active") != "archived" and item.get("confidence_status") == "confirmed"
                    ],
                    "rules": [
                        item for item in world_bible.get("rules", [])
                        if item.get("status", "active") != "archived" and item.get("confidence_status") == "confirmed"
                    ],
                    "timeline": [
                        item for item in world_bible.get("timeline", [])
                        if item.get("status", "active") != "archived" and item.get("confidence_status") == "confirmed"
                    ],
                }
                if explicit_selection:
                    selected_world_ids = set(selection.get("world_item_ids", []))
                    world_bible = {
                        **world_bible,
                        "entities": [item for item in world_bible["entities"] if item.get("id") in selected_world_ids],
                        "rules": [item for item in world_bible["rules"] if item.get("id") in selected_world_ids],
                        "timeline": [item for item in world_bible["timeline"] if item.get("id") in selected_world_ids],
                    }
            previous_scene_context = None
            ordered_scenes = connection.execute(
                """SELECT s.id,s.title,s.current_revision_id
                   FROM scenes s
                   JOIN chapters c ON c.id=s.chapter_id
                   LEFT JOIN volumes v ON v.id=c.volume_id
                   WHERE s.work_id=?
                   ORDER BY COALESCE(v.stable_order_key,''),c.stable_order_key,s.stable_order_key""",
                (work_id,),
            ).fetchall()
            current_index = next((index for index, item in enumerate(ordered_scenes) if item["id"] == scene_id), -1)
            long_term_memories = relevant_memories(
                connection,
                work_id,
                chapter_id=scene["chapter_id"],
                scene_ids=[item["id"] for item in ordered_scenes[:max(0, current_index)]],
                character_ids=[card_id for card_id, _ in selected_cards],
            )
            revision_refs.extend(
                item["current_revision_id"] for item in long_term_memories
                if item.get("current_revision_id")
            )
            if current_index > 0:
                previous = next(
                    (item for item in reversed(ordered_scenes[:current_index]) if item["current_revision_id"]),
                    None,
                )
                if previous:
                    previous_revision = connection.execute(
                        "SELECT * FROM revisions WHERE id=?", (previous["current_revision_id"],)
                    ).fetchone()
                    previous_text = json.loads(self.repo.read_text(previous_revision["content_uri"])).get("text", "")
                    excerpt = self._traceable_text_excerpt(previous_text, max_chars=4200, include_start=False)
                    previous_scene_context = {
                        "scene_id": previous["id"],
                        "title": previous["title"],
                        "revision_id": previous_revision["id"],
                        "revision_hash": previous_revision["content_hash"],
                        "excerpt": excerpt["text"],
                        "excerpt_segments": excerpt["segments"],
                        "truncated": excerpt["truncated"],
                    }
                    revision_refs.append(previous_revision["id"])
            context = {
                "scene_id": scene_id,
                "scene_contract": scene_contract,
                "scene_asset_references": scene_asset_references,
                "scene_asset_reference_digest": scene_asset_reference_digest,
                "context_selection": selection,
                "brief": values["brief"],
                "story_blueprint": values["story_blueprint"],
                "story_structure": values.get("story_structure"),
                "work_canon": work_canon,
                "world_bible": world_bible,
                "reference_files": reference_files,
                "reference_file_refs": [
                    f"reference:{item['id']}@v{item['version']}:{item['content_hash']}" for item in reference_files
                ],
                "previous_scene_context": previous_scene_context,
                "long_term_memories": long_term_memories,
                "rules": {
                    "pack_version": PACK_VERSION,
                    "common": ["agents/writer.md", "knowledge/写作内核.md", "knowledge/人味对话机制.md"],
                    "mode_key": scene_mode,
                    "mode": MODE_SOURCES[scene_mode],
                    "sensei": "knowledge/老师在场规则.md" if has_sensei else None,
                    "evidence_contract": "资料文件是可追溯证据，不会自动升级为 WorkCanon；只有已确认且未归档的 WorkCanon 条目可以被表述为确定事实。",
                },
                "skill_runtime": skill_runtime,
                "runtime_character_cards": runtime_cards,
                "source_revision_ids": revision_refs + [item["content_hash"] for item in reference_files],
                "readiness": {
                    **build_scene_readiness(
                        provider=self.provider.descriptor(),
                        skill_runtime=skill_runtime,
                        runtime_character_cards=runtime_cards,
                        missing_runtime_character_cards=missing_cards,
                        explicit_character_selection=explicit_selection,
                    ),
                    "unverified_character_cards": {
                        key: unverified_cards[key]
                        for key in missing_cards if key in unverified_cards
                    },
                    "unverified_world_items": unverified_world_items,
                    "runtime_character_card_warnings": runtime_card_warnings,
                },
            }
            scene_writing_pack = {
                "schema_version": "scene-writing-pack/1.0",
                "workflow": "scene.draft.generate",
                "scene_id": scene_id,
                "mode_key": scene_mode,
                "has_sensei": has_sensei,
                "scene_contract": scene_contract,
                "scene_asset_references": scene_asset_references,
                "scene_asset_reference_digest": scene_asset_reference_digest,
                "brief": values["brief"],
                "story_blueprint": values["story_blueprint"],
                "story_structure": values.get("story_structure"),
                "work_canon": work_canon,
                "world_bible": world_bible,
                "runtime_character_cards": runtime_cards,
                "reference_files": reference_files,
                "previous_scene_context": previous_scene_context,
                "long_term_memories": long_term_memories,
                "source_revision_ids": context["source_revision_ids"],
                "static_rule_source_digest": skill_runtime["source_digest"],
            }
            scene_writing_pack["digest"] = sha256_text(canonical_json(scene_writing_pack))
            context["scene_writing_pack"] = scene_writing_pack
            context["fingerprints"] = {
                "static_rule_pack": (
                    skill_runtime["source_digest"]
                    if str(skill_runtime["source_digest"]).startswith("sha256:")
                    else f"sha256:{skill_runtime['source_digest']}"
                ),
                "scene_writing_pack": scene_writing_pack["digest"],
            }
            return context

    @staticmethod
    def _scene_provider_failure(
        exc: Exception,
        fallback_message: str,
        *,
        fallback_details: dict | None = None,
    ) -> dict:
        is_domain_error = isinstance(exc, DomainError)
        details = dict(exc.details) if is_domain_error and isinstance(exc.details, dict) else {}
        if not details and fallback_details:
            details = dict(fallback_details)
        code = exc.code if is_domain_error else "writing_provider_failed"
        message = exc.message if is_domain_error else fallback_message
        status = exc.status if is_domain_error else 502
        retryable = details.get("retryable")
        if not isinstance(retryable, bool):
            retryable = code == "writing_provider_failed"
        failure = {
            "code": code,
            "type": type(exc).__name__,
            "message": message,
            "status": status,
            "retryable": retryable,
            "details": details,
        }
        failure_kind = details.get("failure_kind")
        if failure_kind:
            failure["failure_kind"] = failure_kind
        return failure

    def _fail_scene_candidate_work_item(
        self,
        work_item_id: str,
        attempt_id: str,
        production_run_id: str,
        agent_run_id: str,
        failure: dict,
    ) -> None:
        timestamp = now()
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            connection.execute(
                "UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'",
                (failure["code"], timestamp, attempt_id),
            )
            connection.execute(
                "UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'",
                (canonical_json(failure), timestamp, work_item_id),
            )
            connection.execute(
                "UPDATE production_runs SET status='failed',updated_at=? WHERE id=? AND status='running'",
                (timestamp, production_run_id),
            )
            connection.execute(
                "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                (canonical_json(failure), timestamp, agent_run_id),
            )

    def generate_scene_candidate(self, work_id: str, scene_id: str, payload: dict):
        """Compatibility scene candidate flow backed by a durable AgentRun."""
        expected = int(payload.get("expected_version", -1))
        provider, provider_runtime = self._provider_for_request(payload)
        context = self.assemble_context(work_id, scene_id)
        if not provider.is_simulation and context["readiness"]["real_ba_writing"] != "ready_for_provider":
            raise DomainError(
                "agent_blocked",
                "真实模型生成必须经过 BA Skill 和本场运行时人物卡门禁。",
                status=409,
                details={
                    "missing_runtime_character_cards": context["readiness"]["missing_runtime_character_cards"],
                    "skill_source": context["readiness"]["skill_source"],
                },
            )

        with self.repo.connect() as connection:
            pinned_scene = connection.execute(
                "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
        if not pinned_scene:
            raise NotFound("scene", scene_id)
        agent_run_id = new_id("agent")
        snapshot = {
            "schema_version": "scene-candidate-agent-input/1.0",
            "work_id": work_id,
            "scene_id": scene_id,
            "base_revision_id": pinned_scene["current_revision_id"],
            "context": context,
            "provider_runtime": provider_runtime,
        }
        snapshot_uri, context_digest = self.repo.atomic_write_text(
            f"agent-runs/{agent_run_id}/input.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        )
        policy = {
            "workflow": "scene.candidate.generate",
            "write_boundary": "proposal_only",
            "simulation": provider.is_simulation,
            "provider_runtime": provider_runtime,
            "fingerprints": context.get("fingerprints", {}),
            "retry_of_agent_run_id": str(payload.get("_retry_of") or "") or None,
        }
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                "SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if scene["current_revision_id"] != snapshot["base_revision_id"]:
                raise DomainError(
                    "agent_input_stale", "场景正文已经变化，请重新生成候选。", status=409
                )
            production_run = connection.execute(
                "SELECT * FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1",
                (work_id,),
            ).fetchone()
            if not production_run:
                raise DomainError("creation_run_missing", "作品缺少创作运行记录。", status=409)
            timestamp = now()
            connection.execute(
                "UPDATE production_runs SET status='running',updated_at=? WHERE id=?",
                (timestamp, production_run["id"]),
            )
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_run_id, work_id, "scene", scene_id, "生成场景正文候选。", "running",
                    canonical_json(policy), snapshot_uri, context_digest, None, None, timestamp, None,
                ),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("tool"), agent_run_id, 1, "assemble_scene_context", "succeeded",
                    context_digest, snapshot_uri, None, timestamp, timestamp,
                ),
            )
            work_item_id = new_id("item")
            connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    work_item_id, production_run["id"], "scene.draft.generate", "scene", scene_id,
                    "running", canonical_json(context["source_revision_ids"]), "[]",
                    canonical_json({
                        "proposal_only": True, "agent_run_id": agent_run_id, "retryable": True,
                    }),
                    1, None, timestamp, timestamp,
                ),
            )
            attempt_id = new_id("attempt")
            connection.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id, work_item_id, 1, provider.kind, context_digest,
                    "started", None, None, timestamp, None,
                ),
            )
            production_run_id = production_run["id"]

        self._notify_agent_run_started(payload, agent_run_id)
        try:
            with self._provider_lock:
                candidate = self._normalize_official_script(
                    provider.generate_scene(context),
                    context,
                    allow_brief_speakers=provider.is_simulation,
                )
                usage = self._provider_usage(provider)
        except Exception as exc:
            failure = self._scene_provider_failure(
                exc,
                "模型未能生成场景候选。",
                fallback_details={"operation": "scene.draft.generate", "provider": provider.kind},
            )
            self._fail_scene_candidate_work_item(
                work_item_id, attempt_id, production_run_id, agent_run_id,
                failure,
            )
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                failure["code"], failure["message"], status=failure["status"],
                details=failure["details"],
            ) from exc

        proposal_id = new_id("proposal")
        candidate_uri, candidate_hash = self.repo.atomic_write_text(
            f"artifacts/proposals/{proposal_id}.txt", candidate
        )
        conflict = None
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            current = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            scene = connection.execute(
                "SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if (
                not current or int(current["version"]) != version or not scene
                or scene["current_revision_id"] != snapshot["base_revision_id"]
            ):
                conflict = DomainError(
                    "agent_input_stale", "模型生成期间作品或场景正文已经变化，请重新运行。", status=409
                )
                failure = {"code": conflict.code, "message": conflict.message, "retryable": False}
                timestamp = now()
                connection.execute(
                    "UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'",
                    (conflict.code, timestamp, attempt_id),
                )
                connection.execute(
                    "UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'",
                    (canonical_json(failure), timestamp, work_item_id),
                )
                connection.execute(
                    "UPDATE production_runs SET status='failed',updated_at=? WHERE id=? AND status='running'",
                    (timestamp, production_run_id),
                )
                connection.execute(
                    "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                    (canonical_json(failure), timestamp, agent_run_id),
                )
            else:
                base_text = ""
                if scene["current_revision_id"]:
                    base_revision = connection.execute(
                        "SELECT content_uri FROM revisions WHERE id=?", (scene["current_revision_id"],)
                    ).fetchone()
                    base_content = json.loads(self.repo.read_text(base_revision["content_uri"]))
                    base_text = base_content.get("text", "")
                diff = list(difflib.unified_diff(
                    base_text.splitlines(), candidate.splitlines(),
                    fromfile="当前稿件", tofile="模拟候选" if provider.is_simulation else "Agent 候选",
                    lineterm="",
                ))
                timestamp = now()
                connection.execute(
                    "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        proposal_id, work_id, "scene_script", "scene", scene_id,
                        scene["current_revision_id"], candidate_uri, candidate_hash,
                        canonical_json(diff), canonical_json(context["source_revision_ids"]),
                        "medium", "pending", canonical_json(provider_runtime), timestamp, None,
                    ),
                )
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("tool"), agent_run_id, 2, "generate_single_proposal", "succeeded",
                        context_digest, proposal_id, None, timestamp, timestamp,
                    ),
                )
                connection.execute(
                    "UPDATE agent_runs SET status='waiting_user',proposal_id=?,policy_json=?,finished_at=? WHERE id=?",
                    (proposal_id, canonical_json({**policy, "usage": usage}), timestamp, agent_run_id),
                )
                connection.execute(
                    "UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?",
                    (proposal_id, timestamp, attempt_id),
                )
                connection.execute(
                    "UPDATE work_items SET status='waiting_user',output_refs_json=?,updated_at=? WHERE id=?",
                    (canonical_json([proposal_id]), timestamp, work_item_id),
                )
                connection.execute(
                    "UPDATE production_runs SET status='waiting_user',updated_at=? WHERE id=?",
                    (timestamp, production_run_id),
                )
                self._bump_work(connection, work_id, version)
        if conflict:
            raise conflict
        return {
            "agent_run_id": agent_run_id,
            "proposal_id": proposal_id,
            "simulation": provider.is_simulation,
            "work": self.get_work(work_id),
        }

    def run_scene_agent(self, work_id: str, scene_id: str, payload: dict):
        """Run one constrained ba-writing Agent turn and return a Proposal, never a direct edit."""
        expected = int(payload.get("expected_version", -1))
        provider, provider_runtime = self._provider_for_request(payload)
        instruction = str(payload.get("instruction", "")).strip()
        if not instruction:
            raise DomainError("validation_error", "请说明希望 Agent 对当前场景做什么。", details={"field": "instruction"})
        context = self.assemble_context(work_id, scene_id)
        if context["readiness"]["real_ba_writing"] != "ready_for_provider":
            raise DomainError(
                "agent_blocked",
                "BA 写作 Agent 的 Skill 规则源或本场运行时人物卡未就绪，不能降级生成。",
                status=409,
                details={
                    "missing_runtime_character_cards": context["readiness"]["missing_runtime_character_cards"],
                    "skill_source": context["readiness"]["skill_source"],
                    "missing_skill_files": context["skill_runtime"]["missing_files"],
                },
            )
        scene_contract = context["scene_contract"]
        discussion_constraints = (
            payload.get("discussion_constraints")
            if isinstance(payload.get("discussion_constraints"), dict)
            else None
        )
        scene_conversation_context = (
            payload.get("scene_conversation_context")
            if isinstance(payload.get("scene_conversation_context"), dict)
            else None
        )
        policy = {
            "workflow": "scene.draft.generate",
            "pack_version": PACK_VERSION,
            "mode_source": context["rules"]["mode"],
            "tool_allowlist": ["assemble_scene_context", "validate_runtime_character_cards", "generate_single_proposal"],
            "tool_denied": ["read_previous_script", "write_scene_revision", "mutate_work_canon", "mutate_character_card", "internet_search"],
            "write_policy": "one_candidate_zero_edit_proposal_only",
            "skill_contract": {
                "single_mode": True,
                "runtime_cards_only": True,
                "has_sensei": self._scene_has_sensei(scene_contract, context["brief"]),
                "output_mode": "official_script",
                "source_digest": context["skill_runtime"]["source_digest"],
                "source_status": context["skill_runtime"]["status"],
            },
            "fingerprints": context["fingerprints"],
            "provider_runtime": provider_runtime,
        }
        if payload.get("_retry_of"):
            policy["retry_of_agent_run_id"] = str(payload["_retry_of"])
        snapshot = {
            "instruction": instruction,
            "scene_id": scene_id,
            "scene_contract": scene_contract,
            "brief": context["brief"],
            "work_canon": context["work_canon"],
            "world_bible": context["world_bible"],
            "runtime_character_cards": context["runtime_character_cards"],
            "reference_files": context["reference_files"],
            "reference_file_refs": context["reference_file_refs"],
            "source_revision_ids": context["source_revision_ids"],
            "rules": context["rules"],
            "discussion_constraints": discussion_constraints,
            "scene_conversation_context": scene_conversation_context,
            "provider_runtime": provider_runtime,
            "policy": policy,
        }
        snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        run_id = new_id("agent")
        snapshot_uri, digest = self.repo.atomic_write_text(f"agent-runs/{run_id}/input.json", snapshot_text)
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute("SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if scene["current_revision_id"]:
                raise DomainError(
                    "agent_scope_blocked",
                    "首次 BA 场景 Agent 只处理尚无正文的场景；已有正文请走后续的受控复写 Proposal 工作流。",
                    status=409,
                )
            if connection.execute("SELECT 1 FROM proposals WHERE work_id=? AND scope_id=? AND status='pending'", (work_id, scene_id)).fetchone():
                raise DomainError("agent_waiting_user", "当前场景已有待决定的 Proposal，请先采纳或退回。", status=409)
            timestamp = now()
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, work_id, "scene", scene_id, instruction, "running", canonical_json(policy), snapshot_uri, digest, None, None, timestamp, None),
            )
            tool_call_id = new_id("tool")
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tool_call_id, run_id, 1, "assemble_scene_context", "succeeded", digest, snapshot_uri, None, timestamp, now()),
            )
            card_call_id = new_id("tool")
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (card_call_id, run_id, 2, "validate_runtime_character_cards", "succeeded", sha256_text(canonical_json(context["runtime_character_cards"])), None, None, timestamp, now()),
            )
            work_item_id = new_id("item")
            run = connection.execute("SELECT * FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1", (work_id,)).fetchone()
            connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (work_item_id, run["id"], "agent.scene.draft.generate", "scene", scene_id, "running", canonical_json(context["source_revision_ids"]), "[]", canonical_json({"proposal_only": True, "agent_run_id": run_id}), 1, None, timestamp, timestamp),
            )
            attempt_id = new_id("attempt")
            connection.execute("INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)", (attempt_id, work_item_id, 1, provider.kind, digest, "started", None, None, timestamp, None))
            connection.commit()
            self._notify_agent_run_started(payload, run_id)
            try:
                provider_context = {
                    **context,
                    "instruction": instruction,
                    "discussion_constraints": discussion_constraints,
                    "scene_conversation_context": scene_conversation_context,
                }
                with self._provider_lock:
                    candidate = self._normalize_official_script(
                        provider.generate_scene(provider_context),
                        context,
                        allow_brief_speakers=provider.is_simulation,
                    )
                    usage = self._provider_usage(provider)
            except Exception as exc:
                error = self._scene_provider_failure(
                    exc,
                    "模型未能生成场景候选。",
                    fallback_details={"operation": "scene.draft.generate", "provider": provider.kind},
                )
                self._require_agent_run_committable(connection, run_id)
                connection.execute("UPDATE agent_runs SET status='failed', failure_json=?, finished_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), run_id))
                connection.execute("UPDATE job_attempts SET status='failed', error_code=?, finished_at=? WHERE id=? AND status='started'", (error["code"], now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed', error_json=?, updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                self._bump_work(connection, work_id, version)
                connection.commit()
                raise DomainError(
                    "agent_failed",
                    "写作 Agent 未能完成本次运行。",
                    status=error["status"],
                    details={"agent_run_id": run_id, "failure": error},
                ) from exc
            connection.execute("BEGIN IMMEDIATE")
            self._require_agent_run_committable(connection, run_id)
            actual_version = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()[0]
            if actual_version != version:
                error = {"code": "revision_conflict", "expected_version": version, "actual_version": actual_version}
                connection.execute("UPDATE agent_runs SET status='failed', failure_json=?, finished_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), run_id))
                connection.execute("UPDATE job_attempts SET status='failed', error_code='revision_conflict', finished_at=? WHERE id=? AND status='started'", (now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed', error_json=?, updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                connection.commit()
                raise RevisionConflict(version, actual_version)
            proposal_id = new_id("proposal")
            candidate_uri, candidate_hash = self.repo.atomic_write_text(f"artifacts/proposals/{proposal_id}.txt", candidate)
            diff = list(difflib.unified_diff([], candidate.splitlines(), fromfile="空白正文", tofile="Agent 候选", lineterm=""))
            connection.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (proposal_id, work_id, "scene_script", "scene", scene_id, None, candidate_uri, candidate_hash, canonical_json(diff), canonical_json(context["source_revision_ids"]), "medium", "pending", canonical_json(provider_runtime), now(), None),
            )
            proposal_call_id = new_id("tool")
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (proposal_call_id, run_id, 3, "generate_single_proposal", "succeeded", digest, proposal_id, None, timestamp, now()),
            )
            connection.execute(
                "UPDATE agent_runs SET status='waiting_user', proposal_id=?, policy_json=?, finished_at=? WHERE id=?",
                (proposal_id, canonical_json({**policy, "usage": usage}), now(), run_id),
            )
            connection.execute("UPDATE job_attempts SET status='succeeded', output_ref=?, finished_at=? WHERE id=?", (proposal_id, now(), attempt_id))
            connection.execute("UPDATE work_items SET status='waiting_user', output_refs_json=?, updated_at=? WHERE id=?", (canonical_json([proposal_id]), now(), work_item_id))
            connection.execute("UPDATE production_runs SET status='waiting_user', updated_at=? WHERE id=?", (now(), run["id"]))
            self._bump_work(connection, work_id, version)
        return {"agent_run_id": run_id, "proposal_id": proposal_id, "simulation": provider.is_simulation, "work": self.get_work(work_id)}

    @staticmethod
    def _scene_block_text_spans(base_text: str, blocks: list[dict]) -> dict[str, tuple[int, int]]:
        """Map each stable SceneBlock ID to its text span in the revision text."""
        lines = []
        cursor = 0
        for raw_line in base_text.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")
            if line.strip():
                lines.append((cursor, line))
            cursor += len(raw_line)
        if len(lines) != len(blocks):
            raise DomainError(
                "stale_text_selection",
                "当前正文块与修订文本不一致，请重新载入后再选择。",
                status=409,
            )

        spans = {}
        for block, (line_start, line) in zip(blocks, lines):
            leading = len(line) - len(line.lstrip())
            normalized_line = line.strip()
            block_text = str(block.get("text", ""))
            block_type = block.get("type")
            if block_type in {"dialogue", "narration"}:
                ascii_divider = normalized_line.find(":")
                chinese_divider = normalized_line.find("：")
                dividers = [value for value in (ascii_divider, chinese_divider) if value >= 0]
                divider = min(dividers) if dividers else -1
                prefix = normalized_line[:divider].strip() if divider > 0 else ""
                prefix_matches = (
                    prefix == str(block.get("speaker", ""))
                    if block_type == "dialogue"
                    else prefix in {"旁白", "叙述"}
                )
                if divider <= 0 or not prefix_matches:
                    raise DomainError(
                        "stale_text_selection",
                        "当前对白或旁白块与修订文本不一致，请重新载入后再选择。",
                        status=409,
                    )
                raw_body = normalized_line[divider + 1:]
                body_leading = len(raw_body) - len(raw_body.lstrip())
                if raw_body.strip() != block_text:
                    raise DomainError(
                        "stale_text_selection",
                        "当前对白或旁白块与修订文本不一致，请重新载入后再选择。",
                        status=409,
                    )
                text_start = line_start + leading + divider + 1 + body_leading
            else:
                if normalized_line != block_text:
                    raise DomainError(
                        "stale_text_selection",
                        "当前动作块与修订文本不一致，请重新载入后再选择。",
                        status=409,
                    )
                text_start = line_start + leading
            spans[str(block.get("id", ""))] = (text_start, text_start + len(block_text))
        return spans

    @classmethod
    def _normalize_text_selection(
        cls,
        selection,
        base_text: str,
        *,
        blocks: list[dict] | None = None,
        current_revision_id: str | None = None,
    ) -> dict | None:
        """Pin a user-selected excerpt to the exact manuscript revision.

        A quote is user-owned manuscript content, not an instruction.  It is
        accepted only when it still exists verbatim in the pinned revision so
        a stale browser selection cannot silently target newer text.
        """
        if selection in (None, ""):
            return None
        if not isinstance(selection, dict):
            raise DomainError("invalid_text_selection", "选中的正文范围无效。", status=422)
        quote = str(selection.get("quote", ""))
        if not quote.strip() or len(quote) > 12000:
            raise DomainError("invalid_text_selection", "选中的正文不能为空且不能超过 12000 个字符。", status=422)

        local_keys = {"block_id", "local_start", "local_end"}
        if any(key in selection for key in local_keys):
            if not all(key in selection for key in local_keys):
                raise DomainError("invalid_text_selection", "块内正文范围缺少必要位置。", status=422)
            revision_id = str(selection.get("revision_id", "")).strip()
            if not revision_id:
                raise DomainError("invalid_text_selection", "块内正文范围缺少基准修订。", status=422)
            if not current_revision_id or revision_id != current_revision_id:
                raise DomainError("stale_text_selection", "选中的正文来自旧修订，请重新选择后再试。", status=409)
            block_id = str(selection.get("block_id", "")).strip()
            block = next(
                (item for item in blocks or [] if str(item.get("id", "")) == block_id),
                None,
            )
            if not block:
                raise DomainError("stale_text_selection", "选中的正文块已不存在，请重新选择后再试。", status=409)
            local_start = selection.get("local_start")
            local_end = selection.get("local_end")
            if isinstance(local_start, bool) or isinstance(local_end, bool):
                raise DomainError("invalid_text_selection", "选中的块内位置无效。", status=422)
            try:
                local_start, local_end = int(local_start), int(local_end)
            except (TypeError, ValueError) as exc:
                raise DomainError("invalid_text_selection", "选中的块内位置无效。", status=422) from exc
            block_text = str(block.get("text", ""))
            if local_start < 0 or local_end <= local_start or local_end > len(block_text):
                raise DomainError("invalid_text_selection", "选中的块内位置超出正文范围。", status=422)
            if block_text[local_start:local_end] != quote:
                raise DomainError("stale_text_selection", "选中的正文已发生变化，请重新选择后再试。", status=409)
            block_start, _ = cls._scene_block_text_spans(base_text, blocks or [])[block_id]
            start = block_start + local_start
            end = block_start + local_end
            if base_text[start:end] != quote:
                raise DomainError("stale_text_selection", "选中的正文已不是当前修订，请重新选择后再试。", status=409)
            return {
                "revision_id": revision_id,
                "block_id": block_id,
                "local_start": local_start,
                "local_end": local_end,
                "quote": quote,
                "start": start,
                "end": end,
            }

        start = selection.get("start")
        end = selection.get("end")
        if isinstance(start, bool) or isinstance(end, bool):
            raise DomainError("invalid_text_selection", "选中的正文位置无效。", status=422)
        if start is None or end is None:
            start = base_text.find(quote)
            end = start + len(quote) if start >= 0 else -1
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError) as exc:
            raise DomainError("invalid_text_selection", "选中的正文位置无效。", status=422) from exc
        if start < 0 or end <= start or end > len(base_text) or base_text[start:end] != quote:
            raise DomainError("stale_text_selection", "选中的正文已不是当前修订，请重新选择后再试。", status=409)
        return {"quote": quote, "start": start, "end": end}

    def run_scene_rewrite_agent(self, work_id: str, scene_id: str, payload: dict):
        """Create a full-scene rewrite Proposal from a pinned accepted revision.

        The provider receives the accepted manuscript as a fixed input and can
        only return a candidate. Acceptance is still the only way to create a
        new ScriptRevision.
        """
        expected = int(payload.get("expected_version", -1))
        provider, provider_runtime = self._provider_for_request(payload)
        instruction = str(payload.get("instruction", "")).strip()
        if not instruction:
            raise DomainError("validation_error", "请说明希望如何调整当前正文。", details={"field": "instruction"})
        context = self.assemble_context(work_id, scene_id)
        if context["readiness"]["real_ba_writing"] != "ready_for_provider":
            raise DomainError(
                "agent_blocked",
                "BA 写作 Agent 缺少本场运行时人物卡，不能降级改写正文。",
                status=409,
                details={"missing_runtime_character_cards": context["readiness"]["missing_runtime_character_cards"]},
            )

        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute("SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if not scene["current_revision_id"]:
                raise DomainError("rewrite_requires_manuscript", "当前场景还没有已采纳正文，请先生成第一份候选。", status=409)
            if connection.execute("SELECT 1 FROM proposals WHERE work_id=? AND scope_id=? AND status='pending'", (work_id, scene_id)).fetchone():
                raise DomainError("agent_waiting_user", "当前场景已有待决定的 Proposal，请先采纳或退回。", status=409)

            base_revision = connection.execute("SELECT * FROM revisions WHERE id=?", (scene["current_revision_id"],)).fetchone()
            base_content = json.loads(self.repo.read_text(base_revision["content_uri"]))
            base_text = str(base_content.get("text", ""))
            selection = self._normalize_text_selection(
                payload.get("selection"),
                base_text,
                blocks=base_content.get("blocks"),
                current_revision_id=base_revision["id"],
            )
            discussion_constraints = (
                payload.get("discussion_constraints")
                if isinstance(payload.get("discussion_constraints"), dict)
                else None
            )
            scene_conversation_context = (
                payload.get("scene_conversation_context")
                if isinstance(payload.get("scene_conversation_context"), dict)
                else None
            )
            policy = {
                "workflow": "scene.draft.rewrite",
                "pack_version": PACK_VERSION,
                "mode_source": context["rules"]["mode"],
                "tool_allowlist": ["assemble_scene_context", "validate_runtime_character_cards", "read_pinned_scene_revision", "generate_single_proposal"],
                "tool_denied": ["write_scene_revision", "mutate_work_canon", "mutate_character_card", "internet_search"],
                "write_policy": "one_full_scene_candidate_zero_edit_proposal_only",
                "skill_contract": {"single_mode": True, "runtime_cards_only": True, "base_revision_pinned": True, "output_mode": "official_script"},
                "selection_scope": "selected_excerpt_only" if selection else "full_scene",
                "fingerprints": context["fingerprints"],
                "provider_runtime": provider_runtime,
            }
            if payload.get("_retry_of"):
                policy["retry_of_agent_run_id"] = str(payload["_retry_of"])
            snapshot = {
                "instruction": instruction,
                "selection": selection,
                "scene_id": scene_id,
                "base_revision_id": base_revision["id"],
                "base_text": base_text,
                "scene_contract": context["scene_contract"],
                "brief": context["brief"],
                "work_canon": context["work_canon"],
                "world_bible": context["world_bible"],
                "runtime_character_cards": context["runtime_character_cards"],
                "reference_files": context["reference_files"],
                "reference_file_refs": context["reference_file_refs"],
                "source_revision_ids": context["source_revision_ids"],
                "rules": context["rules"],
                "discussion_constraints": discussion_constraints,
                "scene_conversation_context": scene_conversation_context,
                "provider_runtime": provider_runtime,
                "policy": policy,
            }
            run_id = new_id("agent")
            snapshot_uri, digest = self.repo.atomic_write_text(f"agent-runs/{run_id}/input.json", json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
            timestamp = now()
            connection.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, work_id, "scene", scene_id, instruction, "running", canonical_json(policy), snapshot_uri, digest, None, None, timestamp, None))
            context_call_id = new_id("tool")
            connection.execute("INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)", (context_call_id, run_id, 1, "assemble_scene_context", "succeeded", digest, snapshot_uri, None, timestamp, now()))
            card_call_id = new_id("tool")
            connection.execute("INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)", (card_call_id, run_id, 2, "validate_runtime_character_cards", "succeeded", sha256_text(canonical_json(context["runtime_character_cards"])), None, None, timestamp, now()))
            revision_call_id = new_id("tool")
            connection.execute("INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)", (revision_call_id, run_id, 3, "read_pinned_scene_revision", "succeeded", base_revision["content_hash"], base_revision["id"], None, timestamp, now()))
            run = connection.execute("SELECT * FROM production_runs WHERE work_id=? AND kind='creation' ORDER BY created_at LIMIT 1", (work_id,)).fetchone()
            work_item_id = new_id("item")
            input_refs = [*context["source_revision_ids"], base_revision["id"]]
            connection.execute("INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (work_item_id, run["id"], "agent.scene.draft.rewrite", "scene", scene_id, "running", canonical_json(input_refs), "[]", canonical_json({"proposal_only": True, "agent_run_id": run_id, "base_revision_id": base_revision["id"]}), 1, None, timestamp, timestamp))
            attempt_id = new_id("attempt")
            connection.execute("INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)", (attempt_id, work_item_id, 1, provider.kind, digest, "started", None, None, timestamp, None))
            connection.commit()
            self._notify_agent_run_started(payload, run_id)
            try:
                provider_context = {
                    **context,
                    "selection": selection,
                    "instruction": instruction,
                    "discussion_constraints": discussion_constraints,
                    "scene_conversation_context": scene_conversation_context,
                }
                with self._provider_lock:
                    candidate = self._normalize_official_script(
                        provider.rewrite_scene(provider_context, base_text, instruction),
                        provider_context,
                        allow_brief_speakers=provider.is_simulation,
                    )
                    usage = self._provider_usage(provider)
            except Exception as exc:
                error = self._scene_provider_failure(
                    exc,
                    "模型未能完成场景改写。",
                    fallback_details={"operation": "scene.draft.rewrite", "provider": provider.kind},
                )
                self._require_agent_run_committable(connection, run_id)
                connection.execute("UPDATE agent_runs SET status='failed', failure_json=?, finished_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), run_id))
                connection.execute("UPDATE job_attempts SET status='failed', error_code=?, finished_at=? WHERE id=? AND status='started'", (error["code"], now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed', error_json=?, updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                self._bump_work(connection, work_id, version)
                connection.commit()
                raise DomainError(
                    "agent_failed",
                    "写作 Agent 未能完成本次改写。",
                    status=error["status"],
                    details={"agent_run_id": run_id, "failure": error},
                ) from exc
            connection.execute("BEGIN IMMEDIATE")
            self._require_agent_run_committable(connection, run_id)
            actual_version = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()[0]
            if actual_version != version:
                error = {"code": "revision_conflict", "expected_version": version, "actual_version": actual_version}
                connection.execute("UPDATE agent_runs SET status='failed', failure_json=?, finished_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), run_id))
                connection.execute("UPDATE job_attempts SET status='failed', error_code='revision_conflict', finished_at=? WHERE id=? AND status='started'", (now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed', error_json=?, updated_at=? WHERE id=? AND status='running'", (canonical_json(error), now(), work_item_id))
                connection.commit()
                raise RevisionConflict(version, actual_version)
            proposal_id = new_id("proposal")
            candidate_uri, candidate_hash = self.repo.atomic_write_text(f"artifacts/proposals/{proposal_id}.txt", candidate)
            diff = list(difflib.unified_diff(base_text.splitlines(), candidate.splitlines(), fromfile="当前正文", tofile="Agent 改写候选", lineterm=""))
            evidence = [*context["source_revision_ids"], base_revision["id"]]
            connection.execute(
                "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (proposal_id, work_id, "scene_script", "scene", scene_id, base_revision["id"], candidate_uri, candidate_hash, canonical_json(diff), canonical_json(evidence), "medium", "pending", canonical_json(provider_runtime), now(), None),
            )
            proposal_call_id = new_id("tool")
            connection.execute("INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)", (proposal_call_id, run_id, 4, "generate_single_proposal", "succeeded", digest, proposal_id, None, timestamp, now()))
            connection.execute(
                "UPDATE agent_runs SET status='waiting_user', proposal_id=?, policy_json=?, finished_at=? WHERE id=?",
                (proposal_id, canonical_json({**policy, "usage": usage}), now(), run_id),
            )
            connection.execute("UPDATE job_attempts SET status='succeeded', output_ref=?, finished_at=? WHERE id=?", (proposal_id, now(), attempt_id))
            connection.execute("UPDATE work_items SET status='waiting_user', output_refs_json=?, updated_at=? WHERE id=?", (canonical_json([proposal_id]), now(), work_item_id))
            connection.execute("UPDATE production_runs SET status='waiting_user', updated_at=? WHERE id=?", (now(), run["id"]))
            self._bump_work(connection, work_id, version)
        return {"agent_run_id": run_id, "proposal_id": proposal_id, "simulation": provider.is_simulation, "work": self.get_work(work_id)}

    def _fail_memory_work_item(
        self,
        work_item_id: str,
        attempt_id: str,
        run_id: str,
        agent_run_id: str,
        code: str,
        message: str,
        *,
        retryable: bool = True,
    ) -> None:
        timestamp = now()
        failure = {"code": code, "message": message, "retryable": retryable}
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            connection.execute(
                "UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=? AND status='started'",
                (code, timestamp, attempt_id),
            )
            connection.execute(
                "UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=? AND status='running'",
                (canonical_json(failure), timestamp, work_item_id),
            )
            connection.execute(
                "UPDATE production_runs SET status='failed',updated_at=? WHERE id=? AND status='running'",
                (timestamp, run_id),
            )
            connection.execute(
                "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                (canonical_json(failure), timestamp, agent_run_id),
            )

    def _ensure_memory_extract_work_item(
        self, connection, work_id: str, scene_id: str, revision_id: str
    ) -> tuple[str, str]:
        """Create one durable memory-maintenance checkpoint per SceneRevision."""
        timestamp = now()
        current = None
        rows = connection.execute(
            """SELECT item.* FROM work_items AS item
               JOIN production_runs AS run ON run.id=item.run_id
               WHERE run.work_id=? AND item.type='memory.extract'
                 AND item.scope_type='scene' AND item.scope_id=?
                 AND item.status IN ('ready','running','waiting_user','failed')
               ORDER BY item.created_at DESC""",
            (work_id, scene_id),
        ).fetchall()
        for row in rows:
            try:
                refs = json.loads(row["input_refs_json"] or "{}")
            except json.JSONDecodeError:
                refs = {}
            if refs.get("scene_revision_id") == revision_id and current is None:
                current = row
                continue
            connection.execute(
                "UPDATE work_items SET status='cancelled',error_json=?,updated_at=? WHERE id=?",
                (
                    canonical_json({
                        "code": "memory_source_superseded",
                        "message": "场景产生了新正文修订，旧记忆维护任务已取消。",
                        "retryable": False,
                    }),
                    timestamp,
                    row["id"],
                ),
            )
        if current:
            return current["id"], current["run_id"]
        run_id = new_id("run")
        work_item_id = new_id("item")
        refs = {"scene_revision_id": revision_id, "scheduled_by": "scene_revision"}
        connection.execute(
            "INSERT INTO production_runs VALUES (?,?,?,?,?,?,?,?)",
            (run_id, work_id, "memory", "review", "running", canonical_json(refs), timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                work_item_id, run_id, "memory.extract", "scene", scene_id, "ready",
                canonical_json(refs), "[]",
                canonical_json({
                    "proposal_required": True,
                    "retryable": True,
                    "maintenance_state": "pending",
                }),
                0, None, timestamp, timestamp,
            ),
        )
        return work_item_id, run_id

    def _assemble_chapter_memory_sweep_input(self, work_id: str, chapter_id: str) -> dict:
        with self.repo.connect() as connection:
            chapter = connection.execute(
                "SELECT id,title FROM chapters WHERE id=? AND work_id=?",
                (chapter_id, work_id),
            ).fetchone()
            if not chapter:
                raise NotFound("chapter", chapter_id)
            rows = connection.execute(
                """SELECT id,title,stable_order_key,contract_json,current_revision_id
                   FROM scenes WHERE chapter_id=? AND work_id=? ORDER BY stable_order_key""",
                (chapter_id, work_id),
            ).fetchall()
            if not rows:
                raise DomainError(
                    "memory_sweep_requires_scenes", "章节中还没有场景，不能运行记忆清扫。", status=409
                )
            missing = [row["id"] for row in rows if not row["current_revision_id"]]
            if missing:
                raise DomainError(
                    "memory_sweep_requires_revisions",
                    "章节中的每个场景都需要先形成正式正文修订。",
                    status=409,
                    details={"scene_ids": missing},
                )
            scenes = []
            for row in rows:
                revision = connection.execute(
                    "SELECT id,content_uri,content_hash FROM revisions WHERE id=?",
                    (row["current_revision_id"],),
                ).fetchone()
                if not revision:
                    raise DomainError(
                        "memory_sweep_source_missing", "章节场景引用的正文修订不存在。", status=409
                    )
                scenes.append({
                    "id": row["id"],
                    "title": row["title"],
                    "stable_order_key": row["stable_order_key"],
                    "contract": json.loads(row["contract_json"]),
                    "revision_id": revision["id"],
                    "revision_hash": revision["content_hash"],
                    "manuscript": json.loads(self.repo.read_text(revision["content_uri"])),
                })
            memories = [
                {
                    "memory_id": item["id"],
                    "kind": item["kind"],
                    "scope_type": item["scope_type"],
                    "scope_id": item["scope_id"],
                    "content": item["content"],
                    "confidence_status": item["confidence_status"],
                    "lifecycle_status": item["lifecycle_status"],
                    "current_revision_id": item["current_revision_id"],
                }
                for item in memory_projection_rows(connection, work_id)
            ]
        sweep_input = {
            "schema_version": "memory-sweep-input/1.0",
            "work_id": work_id,
            "workflow": template_contract("memory.sweep"),
            "chapter": {"id": chapter["id"], "title": chapter["title"]},
            "scenes": scenes,
            "existing_memories": memories,
            "write_boundary": "proposal_only",
        }
        sweep_input["digest"] = sha256_text(canonical_json(sweep_input))
        return sweep_input

    def sweep_chapter_memory(self, work_id: str, chapter_id: str, payload: dict):
        provider = self.provider
        return self._run_chapter_memory_sweep(
            work_id, chapter_id, payload, provider=provider
        )

    def _run_chapter_memory_sweep(
        self,
        work_id: str,
        chapter_id: str,
        payload: dict,
        *,
        sweep_input: dict | None = None,
        provider=None,
    ):
        provider = provider if provider is not None else self.provider
        expected = int(payload.get("expected_version", -1))
        with self.repo.connect() as connection:
            self._check_work_version(connection, work_id, expected)
        sweep_input = sweep_input or self._assemble_chapter_memory_sweep_input(work_id, chapter_id)
        timestamp = now()
        agent_run_id = new_id("agent-run")
        production_run_id = new_id("run")
        work_item_id = new_id("item")
        attempt_id = new_id("attempt")
        snapshot_uri, snapshot_digest = self.repo.atomic_write_text(
            f"agent-runs/{agent_run_id}/input.json",
            json.dumps(sweep_input, ensure_ascii=False, indent=2) + "\n",
        )
        scene_refs = [
            {"scene_id": item["id"], "revision_id": item["revision_id"], "content_hash": item["revision_hash"]}
            for item in sweep_input["scenes"]
        ]
        input_refs = {
            "chapter_id": chapter_id,
            "scene_revisions": scene_refs,
            "work_version": expected,
            "agent_run_id": agent_run_id,
            "input_digest": snapshot_digest,
            "retry_of": str(payload.get("_retry_of") or "") or None,
        }
        policy = {
            "workflow": "memory.sweep",
            "write_boundary": "proposal_only",
            "chapter_id": chapter_id,
            "input_digest": sweep_input["digest"],
            "usage": {},
            "retry_of_agent_run_id": str(payload.get("_retry_of") or "") or None,
        }
        with self.repo.transaction() as connection:
            self._check_work_version(connection, work_id, expected)
            if connection.execute(
                "SELECT 1 FROM proposals WHERE work_id=? AND kind='memory_bundle' AND scope_type='chapter' AND scope_id=? AND status='pending'",
                (work_id, chapter_id),
            ).fetchone():
                raise DomainError("proposal_waiting_user", "本章已有记忆清扫候选等待决定。", status=409)
            connection.execute(
                "INSERT INTO production_runs VALUES (?,?,?,?,?,?,?,?)",
                (production_run_id, work_id, "memory", "review", "running", canonical_json(input_refs), timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    work_item_id, production_run_id, "memory.sweep", "chapter", chapter_id, "running",
                    canonical_json(input_refs), "[]",
                    canonical_json({"proposal_required": True, "retryable": True, "agent_run_id": agent_run_id}),
                    1, None, timestamp, timestamp,
                ),
            )
            connection.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, work_item_id, 1, provider.kind, snapshot_digest, "started", None, None, timestamp, None),
            )
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_run_id, work_id, "chapter", chapter_id,
                    "清扫当前章节的跨场景长期记忆候选。", "running", canonical_json(policy),
                    snapshot_uri, snapshot_digest, None, None, timestamp, None,
                ),
            )
            connection.execute(
                "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id("tool"), agent_run_id, 1, "read_chapter_scene_revisions", "succeeded", snapshot_digest, sweep_input["digest"], None, timestamp, timestamp),
            )

        self._notify_agent_run_started(payload, agent_run_id)
        try:
            with self._provider_lock:
                raw_bundle = provider.sweep_memory_bundle(sweep_input)
                usage = self._provider_usage(provider)
            block_index = {
                scene["id"]: {
                    str(block.get("id")) for block in scene["manuscript"].get("blocks", [])
                    if isinstance(block, dict) and block.get("id")
                }
                for scene in sweep_input["scenes"]
            }
            bundle = validate_provider_chapter_memory_bundle(
                raw_bundle, chapter_id=chapter_id, scene_block_ids=block_index
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else "writing_provider_failed"
            message = exc.message if isinstance(exc, DomainError) else "模型未能完成章节记忆清扫，本次没有创建候选。"
            self._fail_memory_work_item(
                work_item_id, attempt_id, production_run_id, agent_run_id, code, message
            )
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                "writing_provider_failed", message, status=502,
                details={"operation": "memory.sweep", "provider": provider.kind},
            ) from exc

        scene_index = {scene["id"]: scene for scene in sweep_input["scenes"]}
        candidate_items = []
        with self.repo.connect() as connection:
            for item in bundle["items"]:
                target = None
                if item["operation"] != "create":
                    target = connection.execute(
                        "SELECT * FROM memories WHERE id=? AND work_id=?",
                        (item["target_memory_id"], work_id),
                    ).fetchone()
                    if not target:
                        self._fail_memory_work_item(
                            work_item_id, attempt_id, production_run_id, agent_run_id,
                            "memory_target_not_found", "模型引用的已有长期记忆不存在。", retryable=False,
                        )
                        raise DomainError("provider_output_invalid", "模型引用的已有长期记忆不存在。", status=502)
                source_refs = []
                for ref in item.pop("source_refs"):
                    scene = scene_index[ref["scene_id"]]
                    source_refs.append({
                        "kind": "scene_revision",
                        "scene_id": scene["id"],
                        "revision_id": scene["revision_id"],
                        "content_hash": scene["revision_hash"],
                        "block_ids": ref["source_block_ids"],
                    })
                candidate_items.append({
                    **item,
                    "id": target["id"] if target else new_id("memory"),
                    "base_revision_id": target["current_revision_id"] if target else None,
                    "source_refs": source_refs,
                })

        candidate = {
            "schema_version": "memory-bundle-proposal/1.0",
            "work_id": work_id,
            "source_chapter_id": chapter_id,
            "source_scene_revisions": scene_refs,
            "summary": bundle["summary"],
            "items": candidate_items,
            "agent_run_id": agent_run_id,
        }
        proposal_id = new_id("proposal")
        candidate_uri, candidate_hash = self.repo.atomic_write_text(
            f"artifacts/proposals/{proposal_id}.json",
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        )
        conflict = None
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            current_work = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            current_rows = connection.execute(
                "SELECT id,current_revision_id FROM scenes WHERE chapter_id=? AND work_id=? ORDER BY stable_order_key",
                (chapter_id, work_id),
            ).fetchall()
            current_refs = [(row["id"], row["current_revision_id"]) for row in current_rows]
            pinned_refs = [(item["scene_id"], item["revision_id"]) for item in scene_refs]
            if not current_work or current_work["version"] != expected or current_refs != pinned_refs:
                conflict = DomainError(
                    "memory_sweep_inputs_changed",
                    "清扫期间章节结构、正文或长期记忆已经变化，请重新运行。",
                    status=409,
                )
                failure = {"code": conflict.code, "message": conflict.message, "retryable": False}
                connection.execute("UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=?", (conflict.code, now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=?", (canonical_json(failure), now(), work_item_id))
                connection.execute("UPDATE production_runs SET status='failed',updated_at=? WHERE id=?", (now(), production_run_id))
                connection.execute("UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'", (canonical_json(failure), now(), agent_run_id))
            else:
                diff = {
                    "format": "memory-bundle/1.0",
                    "changes": [
                        {"id": item["id"], "kind": item["kind"], "operation": item["operation"], "title": item["title"]}
                        for item in candidate_items
                    ],
                }
                connection.execute(
                    "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        proposal_id, work_id, "memory_bundle", "chapter", chapter_id, None,
                        candidate_uri, candidate_hash, canonical_json(diff), canonical_json({"scene_revisions": scene_refs}),
                        "medium", "pending", canonical_json(provider.descriptor()), now(), None,
                    ),
                )
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), agent_run_id, 2, "create_memory_bundle_proposal", "succeeded", snapshot_digest, proposal_id, None, now(), now()),
                )
                policy["usage"] = usage
                connection.execute("UPDATE agent_runs SET status='waiting_user',proposal_id=?,policy_json=?,finished_at=? WHERE id=?", (proposal_id, canonical_json(policy), now(), agent_run_id))
                connection.execute("UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?", (proposal_id, now(), attempt_id))
                connection.execute(
                    "UPDATE work_items SET status='waiting_user',output_refs_json=?,acceptance_json=?,updated_at=? WHERE id=?",
                    (canonical_json([{"proposal_id": proposal_id}]), canonical_json({"proposal_required": True, "proposal_id": proposal_id, "usage": usage}), now(), work_item_id),
                )
                connection.execute("UPDATE production_runs SET status='waiting_user',updated_at=? WHERE id=?", (now(), production_run_id))
                self._bump_work(connection, work_id, expected)
        if conflict:
            raise conflict
        return {
            "agent_run_id": agent_run_id,
            "work_item_id": work_item_id,
            "proposal_id": proposal_id,
            "simulation": provider.is_simulation,
            "work": self.get_work(work_id),
        }

    def discover_scene_knowledge(self, work_id: str, scene_id: str, payload: dict):
        """Discover review-only WorkCanon suggestions without opening a user task."""

        provider = payload.get("_provider_instance") or self.provider
        expected = int(payload.get("expected_version", -1))
        pinned_revision_id = str(payload.get("_source_revision_id") or "")
        timestamp = now()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                """SELECT scene.*,chapter.title AS chapter_title
                   FROM scenes AS scene JOIN chapters AS chapter ON chapter.id=scene.chapter_id
                   WHERE scene.id=? AND scene.work_id=?""",
                (scene_id, work_id),
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            revision_id = scene["current_revision_id"]
            if not revision_id:
                raise DomainError(
                    "knowledge_discovery_requires_revision",
                    "场景还没有正式正文修订，不能运行后台资料整理。",
                    status=409,
                )
            if pinned_revision_id and revision_id != pinned_revision_id:
                raise DomainError(
                    "knowledge_discovery_source_superseded",
                    "场景已经产生新的正文修订，旧的后台资料整理不会继续运行。",
                    status=409,
                    details={
                        "expected_revision_id": pinned_revision_id,
                        "actual_revision_id": revision_id,
                    },
                )
            source_revision = connection.execute(
                "SELECT * FROM revisions WHERE id=?", (revision_id,)
            ).fetchone()
            manuscript_text = self.repo.read_text(source_revision["content_uri"])
            if sha256_text(manuscript_text) != source_revision["content_hash"]:
                raise DomainError(
                    "revision_integrity_failed",
                    "后台资料整理的场景修订校验失败。",
                    status=409,
                    details={"revision_id": revision_id},
                )
            manuscript = json.loads(manuscript_text)
            discovery_input = {
                "schema_version": "knowledge-discovery-input/1.0",
                "work_id": work_id,
                "workflow": template_contract("canon.assemble"),
                "scene": {
                    "id": scene_id,
                    "title": scene["title"],
                    "chapter_id": scene["chapter_id"],
                    "chapter_title": scene["chapter_title"],
                    "revision_id": revision_id,
                    "revision_hash": source_revision["content_hash"],
                    "contract": json.loads(scene["contract_json"]),
                },
                "manuscript": manuscript,
                "write_boundary": "background_proposal_only",
            }
            snapshot_text = json.dumps(discovery_input, ensure_ascii=False, indent=2) + "\n"
            agent_run_id = new_id("agent-run")
            snapshot_uri, snapshot_digest = self.repo.atomic_write_text(
                f"agent-runs/{agent_run_id}/input.json", snapshot_text
            )
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_run_id, work_id, "scene", scene_id,
                    "从当前正式场景修订发现待整理的作品事实。", "running",
                    canonical_json({
                        "workflow": "knowledge.discover",
                        "write_boundary": "background_proposal_only",
                        "scene_revision_id": revision_id,
                        "usage": {},
                    }),
                    snapshot_uri, snapshot_digest, None, None, timestamp, None,
                ),
            )
            for ordinal, (tool_name, output_ref) in enumerate((
                ("load_workflow_template", "canon.assemble"),
                ("read_scene_revision", revision_id),
            ), start=1):
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("tool"), agent_run_id, ordinal, tool_name, "succeeded",
                        snapshot_digest, output_ref, None, timestamp, timestamp,
                    ),
                )

        self._notify_agent_run_started(payload, agent_run_id)
        try:
            with self._provider_lock:
                raw_bundle = provider.extract_memory_bundle(discovery_input)
                usage = self._provider_usage(provider)
            scene_block_ids = {
                str(item.get("id"))
                for item in manuscript.get("blocks", [])
                if isinstance(item, dict) and item.get("id")
            }
            suggestions = validate_provider_knowledge_suggestions(
                raw_bundle,
                scene_id=scene_id,
                scene_block_ids=scene_block_ids,
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else "writing_provider_failed"
            message = exc.message if isinstance(exc, DomainError) else "模型未能完成后台资料整理，本次没有创建建议。"
            with self.repo.transaction() as connection:
                connection.execute(
                    "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                    (
                        canonical_json({"code": code, "message": message, "retryable": True}),
                        now(), agent_run_id,
                    ),
                )
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                "writing_provider_failed", message, status=502,
                details={"operation": "knowledge.discover", "provider": provider.kind},
            ) from exc

        conflict = None
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            current_work = connection.execute(
                "SELECT version FROM works WHERE id=?", (work_id,)
            ).fetchone()
            current_scene = connection.execute(
                "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?",
                (scene_id, work_id),
            ).fetchone()
            if (
                not current_work
                or current_work["version"] != version
                or not current_scene
                or current_scene["current_revision_id"] != revision_id
            ):
                failure = {
                    "code": "knowledge_discovery_inputs_changed",
                    "message": "后台整理期间作品或场景正文已经变化，本轮结果没有保存。",
                    "retryable": False,
                }
                connection.execute(
                    "UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'",
                    (canonical_json(failure), now(), agent_run_id),
                )
                conflict = DomainError(
                    failure["code"], failure["message"], status=409,
                    details={"scene_id": scene_id, "revision_id": revision_id},
                )
                suggestion_ids = []
            else:
                suggestion_ids = self._create_background_canon_suggestions(
                    connection,
                    work_id=work_id,
                    work_version=version,
                    scene_id=scene_id,
                    scene_revision=source_revision,
                    agent_run_id=agent_run_id,
                    suggestions=suggestions,
                    provider_descriptor=provider.descriptor(),
                )
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("tool"), agent_run_id, 3,
                        "discover_background_knowledge", "succeeded", snapshot_digest,
                        canonical_json(suggestion_ids), None, now(), now(),
                    ),
                )
                connection.execute(
                    "UPDATE agent_runs SET status='completed',proposal_id=?,policy_json=?,finished_at=? WHERE id=?",
                    (
                        suggestion_ids[0] if suggestion_ids else None,
                        canonical_json({
                            "workflow": "knowledge.discover",
                            "write_boundary": "background_proposal_only",
                            "scene_revision_id": revision_id,
                            "background_suggestion_ids": suggestion_ids,
                            "usage": usage,
                        }),
                        now(), agent_run_id,
                    ),
                )
                if suggestion_ids:
                    self._bump_work(connection, work_id, version)
        if conflict:
            raise conflict
        return {
            "agent_run_id": agent_run_id,
            "background_suggestion_ids": suggestion_ids,
            "simulation": provider.is_simulation,
        }

    def generate_memory_proposal(self, work_id: str, scene_id: str, payload: dict):
        provider = self.provider
        expected = int(payload.get("expected_version", -1))
        timestamp = now()
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                """SELECT scene.*,chapter.title AS chapter_title
                   FROM scenes AS scene JOIN chapters AS chapter ON chapter.id=scene.chapter_id
                   WHERE scene.id=? AND scene.work_id=?""",
                (scene_id, work_id),
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if not scene["current_revision_id"]:
                raise DomainError("scene_memory_requires_revision", "请先保存或采纳本场正文，再提取长期记忆。", status=409)
            pinned_revision_id = str(payload.get("_source_revision_id") or "")
            if pinned_revision_id and scene["current_revision_id"] != pinned_revision_id:
                raise DomainError(
                    "memory_source_superseded",
                    "场景已经产生新的正文修订，旧的后台资料整理不会继续运行。",
                    status=409,
                    details={
                        "expected_revision_id": pinned_revision_id,
                        "actual_revision_id": scene["current_revision_id"],
                    },
                )
            if connection.execute(
                "SELECT 1 FROM proposals WHERE work_id=? AND kind='memory_bundle' AND scope_id=? AND status='pending'",
                (work_id, scene_id),
            ).fetchone():
                raise DomainError("proposal_waiting_user", "本场已有长期记忆候选等待决定。", status=409)
            source_revision = connection.execute(
                "SELECT * FROM revisions WHERE id=?", (scene["current_revision_id"],)
            ).fetchone()
            manuscript = json.loads(self.repo.read_text(source_revision["content_uri"]))
            existing_memories = memory_projection_rows(connection, work_id)
            memory_context = {
                "schema_version": "memory-extract-input/1.0",
                "work_id": work_id,
                "workflow": template_contract("canon.assemble"),
                "scene": {
                    "id": scene_id,
                    "title": scene["title"],
                    "chapter_id": scene["chapter_id"],
                    "chapter_title": scene["chapter_title"],
                    "revision_id": source_revision["id"],
                    "revision_hash": source_revision["content_hash"],
                    "contract": json.loads(scene["contract_json"]),
                },
                "manuscript": manuscript,
                "existing_memories": [
                    {
                        "memory_id": item["id"],
                        "kind": item["kind"],
                        "scope_type": item["scope_type"],
                        "scope_id": item["scope_id"],
                        "content": item["content"],
                        "confidence_status": item["confidence_status"],
                        "lifecycle_status": item["lifecycle_status"],
                        "current_revision_id": item["current_revision_id"],
                    }
                    for item in existing_memories
                ],
                "write_boundary": "proposal_only",
            }
            snapshot_text = json.dumps(memory_context, ensure_ascii=False, indent=2) + "\n"
            attempt_id = new_id("attempt")
            agent_run_id = new_id("agent-run")
            snapshot_uri, snapshot_digest = self.repo.atomic_write_text(
                f"agent-runs/{agent_run_id}/input.json", snapshot_text
            )
            input_refs = {
                "scene_revision_id": source_revision["id"],
                "scene_revision_hash": source_revision["content_hash"],
                "work_version": version,
                "agent_run_id": agent_run_id,
                "input_digest": snapshot_digest,
                "retry_of": str(payload.get("_retry_of") or "") or None,
            }
            work_item_id, run_id = self._ensure_memory_extract_work_item(
                connection, work_id, scene_id, source_revision["id"]
            )
            previous_attempt = connection.execute(
                "SELECT COALESCE(MAX(ordinal),0) FROM job_attempts WHERE work_item_id=?",
                (work_item_id,),
            ).fetchone()[0]
            attempt_number = int(previous_attempt) + 1
            connection.execute(
                "UPDATE production_runs SET status='running',pinned_input_refs_json=?,updated_at=? WHERE id=?",
                (canonical_json(input_refs), timestamp, run_id),
            )
            connection.execute(
                """UPDATE work_items SET status='running',input_refs_json=?,output_refs_json='[]',
                   acceptance_json=?,attempt_count=?,error_json=NULL,updated_at=? WHERE id=?""",
                (
                    canonical_json(input_refs),
                    canonical_json({
                        "proposal_required": True, "agent_run_id": agent_run_id, "retryable": True,
                    }),
                    attempt_number, timestamp, work_item_id,
                ),
            )
            connection.execute(
                "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id, work_item_id, attempt_number, provider.kind,
                    snapshot_digest, "started", None, None, timestamp, None,
                ),
            )
            connection.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_run_id, work_id, "scene", scene_id,
                    "从当前正式场景修订提取长期记忆候选。", "running",
                    canonical_json({
                        "workflow": "memory.extract", "write_boundary": "proposal_only",
                        "scene_revision_id": source_revision["id"], "usage": {},
                        "retry_of_agent_run_id": str(payload.get("_retry_of") or "") or None,
                    }),
                    snapshot_uri, snapshot_digest, None, None, timestamp, None,
                ),
            )
            for ordinal, (tool_name, output_ref) in enumerate((
                ("load_workflow_template", "canon.assemble"),
                ("read_scene_revision", source_revision["id"]),
            ), start=1):
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), agent_run_id, ordinal, tool_name, "succeeded", snapshot_digest, output_ref, None, timestamp, timestamp),
                )

        self._notify_agent_run_started(payload, agent_run_id)
        try:
            with self._provider_lock:
                raw_bundle = provider.extract_memory_bundle(memory_context)
                usage = self._provider_usage(provider)
            bundle = validate_provider_memory_bundle(raw_bundle, scene_id=scene_id)
            scene_block_ids = {
                str(item.get("id"))
                for item in manuscript.get("blocks", [])
                if isinstance(item, dict) and item.get("id")
            }
            knowledge_suggestions = validate_provider_knowledge_suggestions(
                raw_bundle,
                scene_id=scene_id,
                scene_block_ids=scene_block_ids,
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else "writing_provider_failed"
            message = exc.message if isinstance(exc, DomainError) else "模型未能提取长期记忆，本次没有创建候选。"
            self._fail_memory_work_item(work_item_id, attempt_id, run_id, agent_run_id, code, message)
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                "writing_provider_failed", message, status=502,
                details={"operation": "memory.extract", "provider": provider.kind},
            ) from exc

        candidate_items = []
        with self.repo.connect() as connection:
            for item in bundle["items"]:
                target = None
                if item["operation"] != "create":
                    target = connection.execute(
                        "SELECT * FROM memories WHERE id=? AND work_id=?",
                        (item["target_memory_id"], work_id),
                    ).fetchone()
                    if not target:
                        self._fail_memory_work_item(
                            work_item_id, attempt_id, run_id, agent_run_id,
                            "memory_target_not_found", "模型引用的已有长期记忆不存在。",
                            retryable=False,
                        )
                        raise DomainError("provider_output_invalid", "模型引用的已有长期记忆不存在。", status=502)
                memory_id = target["id"] if target else new_id("memory")
                source_refs = [{
                    "kind": "scene_revision",
                    "scene_id": scene_id,
                    "revision_id": source_revision["id"],
                    "content_hash": source_revision["content_hash"],
                    "block_ids": item["source_block_ids"],
                }]
                candidate_items.append({
                    **item,
                    "id": memory_id,
                    "base_revision_id": target["current_revision_id"] if target else None,
                    "source_refs": source_refs,
                })
        candidate = {
            "schema_version": "memory-bundle-proposal/1.0",
            "work_id": work_id,
            "source_scene_id": scene_id,
            "source_scene_revision_id": source_revision["id"],
            "source_scene_revision_hash": source_revision["content_hash"],
            "summary": bundle["summary"],
            "items": candidate_items,
            "agent_run_id": agent_run_id,
        }
        proposal_id = new_id("proposal")
        candidate_uri, candidate_hash = self.repo.atomic_write_text(
            f"artifacts/proposals/{proposal_id}.json",
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        )
        conflict = None
        with self.repo.transaction() as connection:
            self._require_agent_run_committable(connection, agent_run_id)
            current_work = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            current_scene = connection.execute(
                "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not current_work or current_work["version"] != expected or not current_scene or current_scene["current_revision_id"] != source_revision["id"]:
                conflict = DomainError(
                    "memory_extract_inputs_changed",
                    "提取期间作品或场景正文已经变化，请从当前修订重新运行。",
                    status=409,
                )
                failure = {"code": conflict.code, "message": conflict.message, "retryable": False}
                connection.execute("UPDATE job_attempts SET status='failed',error_code=?,finished_at=? WHERE id=?", (conflict.code, now(), attempt_id))
                connection.execute("UPDATE work_items SET status='failed',error_json=?,updated_at=? WHERE id=?", (canonical_json(failure), now(), work_item_id))
                connection.execute("UPDATE production_runs SET status='failed',updated_at=? WHERE id=?", (now(), run_id))
                connection.execute("UPDATE agent_runs SET status='failed',failure_json=?,finished_at=? WHERE id=? AND status='running'", (canonical_json(failure), now(), agent_run_id))
            else:
                diff = {
                    "format": "memory-bundle/1.0",
                    "changes": [
                        {"id": item["id"], "kind": item["kind"], "operation": item["operation"], "title": item["title"]}
                        for item in candidate_items
                    ],
                }
                connection.execute(
                    "INSERT INTO proposals (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        proposal_id, work_id, "memory_bundle", "scene", scene_id, source_revision["id"],
                        candidate_uri, candidate_hash, canonical_json(diff),
                        canonical_json({"scene_revision_id": source_revision["id"], "scene_revision_hash": source_revision["content_hash"]}),
                        "medium", "pending", canonical_json(provider.descriptor()), now(), None,
                    ),
                )
                connection.execute(
                    "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("tool"), agent_run_id, 3, "create_memory_bundle_proposal", "succeeded", snapshot_digest, proposal_id, None, now(), now()),
                )
                background_suggestion_ids = self._create_background_canon_suggestions(
                    connection,
                    work_id=work_id,
                    work_version=expected,
                    scene_id=scene_id,
                    scene_revision=source_revision,
                    agent_run_id=agent_run_id,
                    suggestions=knowledge_suggestions,
                    provider_descriptor=provider.descriptor(),
                )
                if background_suggestion_ids:
                    connection.execute(
                        "INSERT INTO agent_tool_calls VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            new_id("tool"), agent_run_id, 4,
                            "create_background_knowledge_suggestions", "succeeded",
                            snapshot_digest, canonical_json(background_suggestion_ids),
                            None, now(), now(),
                        ),
                    )
                connection.execute("UPDATE agent_runs SET status='waiting_user',proposal_id=?,policy_json=?,finished_at=? WHERE id=?", (
                    proposal_id,
                    canonical_json({
                        "workflow": "memory.extract", "write_boundary": "proposal_only",
                        "scene_revision_id": source_revision["id"], "usage": usage,
                        "retry_of_agent_run_id": str(payload.get("_retry_of") or "") or None,
                    }),
                    now(), agent_run_id,
                ))
                connection.execute("UPDATE job_attempts SET status='succeeded',output_ref=?,finished_at=? WHERE id=?", (proposal_id, now(), attempt_id))
                connection.execute(
                    "UPDATE work_items SET status='waiting_user',output_refs_json=?,acceptance_json=?,updated_at=? WHERE id=?",
                    (
                        canonical_json([
                            {"proposal_id": proposal_id, "role": "memory_bundle"},
                            *[
                                {"proposal_id": item_id, "role": "background_knowledge_suggestion"}
                                for item_id in background_suggestion_ids
                            ],
                        ]),
                        canonical_json({
                            "proposal_required": True,
                            "proposal_id": proposal_id,
                            "background_suggestion_ids": background_suggestion_ids,
                            "usage": usage,
                        }),
                        now(), work_item_id,
                    ),
                )
                connection.execute("UPDATE production_runs SET status='waiting_user',updated_at=? WHERE id=?", (now(), run_id))
                self._bump_work(connection, work_id, expected)
        if conflict:
            raise conflict
        return {
            "agent_run_id": agent_run_id,
            "work_item_id": work_item_id,
            "proposal_id": proposal_id,
            "background_suggestion_ids": background_suggestion_ids,
            "simulation": provider.is_simulation,
            "work": self.get_work(work_id),
        }

    def accept_proposal(self, work_id: str, proposal_id: str, payload: dict):
        try:
            result = self._accept_proposal(work_id, proposal_id, payload)
            self._complete_agent_runs_for_proposal(work_id, proposal_id)
            if isinstance(result, dict) and "work" in result:
                result["work"] = self.get_work(work_id)
            return result
        except _ProposalAcceptanceStopped as stopped:
            self._persist_stopped_proposal(work_id, proposal_id, stopped)
            raise stopped.error

    def _complete_agent_runs_for_proposal(self, work_id: str, proposal_id: str) -> None:
        with self.repo.transaction() as connection:
            connection.execute(
                "UPDATE agent_runs SET status='completed',finished_at=COALESCE(finished_at,?) WHERE work_id=? AND proposal_id=? AND status='waiting_user'",
                (now(), work_id, proposal_id),
            )

    def _persist_stopped_proposal(
        self,
        work_id: str,
        proposal_id: str,
        stopped: _ProposalAcceptanceStopped,
    ):
        with self.repo.transaction() as connection:
            proposal = connection.execute(
                "SELECT status FROM proposals WHERE id=? AND work_id=?",
                (proposal_id, work_id),
            ).fetchone()
            if not proposal or proposal["status"] != "pending":
                return
            work = connection.execute("SELECT version FROM works WHERE id=?", (work_id,)).fetchone()
            timestamp = now()
            connection.execute(
                "UPDATE proposals SET status=?, decided_at=? WHERE id=?",
                (stopped.status, timestamp, proposal_id),
            )
            connection.execute(
                "UPDATE agent_runs SET status='completed',finished_at=COALESCE(finished_at,?) WHERE work_id=? AND proposal_id=? AND status='waiting_user'",
                (timestamp, work_id, proposal_id),
            )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"), work_id, "proposal", proposal_id,
                    stopped.decision, stopped.note, timestamp,
                ),
            )
            connection.execute(
                "UPDATE work_items SET status='cancelled',acceptance_json=?,updated_at=? WHERE output_refs_json LIKE ? AND status='waiting_user'",
                (canonical_json({"decision": stopped.decision, "proposal_id": proposal_id}), timestamp, f'%{proposal_id}%'),
            )
            connection.execute(
                "UPDATE production_runs SET status='running',updated_at=? WHERE id IN (SELECT run_id FROM work_items WHERE output_refs_json LIKE ?)",
                (timestamp, f'%{proposal_id}%'),
            )
            if work:
                self._bump_work(connection, work_id, work["version"])

    def _verified_proposal_candidate(self, proposal) -> str:
        actual_hash = None
        try:
            candidate = self.repo.read_text(proposal["candidate_uri"])
            actual_hash = sha256_text(candidate)
        except (OSError, UnicodeError, ValueError):
            candidate = None
        if candidate is None or actual_hash != proposal["candidate_hash"]:
            raise _ProposalAcceptanceStopped(
                status="rejected",
                decision="integrity_failed",
                note="候选文件缺失、损坏或内容哈希与 Proposal 记录不一致。",
                error=DomainError(
                    "proposal_integrity_failed",
                    "候选内容已损坏或被修改，不能采纳。",
                    status=409,
                    details={
                        "proposal_id": proposal["id"],
                        "expected_hash": proposal["candidate_hash"],
                        "actual_hash": actual_hash,
                    },
                ),
            )
        return candidate

    @staticmethod
    def _proposal_superseded(message: str) -> _ProposalAcceptanceStopped:
        return _ProposalAcceptanceStopped(
            status="superseded",
            decision="superseded",
            note=message,
            error=DomainError("proposal_superseded", message, status=409),
        )

    def _accept_proposal(self, work_id: str, proposal_id: str, payload: dict):
        with self.repo.connect() as connection:
            proposal = connection.execute(
                "SELECT kind FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
        if not proposal:
            raise NotFound("proposal", proposal_id)
        if proposal["kind"] == "brief_blueprint":
            return self._accept_brief_blueprint_proposal(work_id, proposal_id, payload)
        if proposal["kind"] == "chapter_plan":
            return self._accept_chapter_plan_proposal(work_id, proposal_id, payload)
        if proposal["kind"] == "story_structure":
            return self._accept_structure_plan_proposal(work_id, proposal_id, payload)
        if proposal["kind"] == "memory_bundle":
            return self._accept_memory_bundle_proposal(work_id, proposal_id, payload)
        if proposal["kind"] in {"character_card", "world_entity", "world_rule", "canon_fact"}:
            return self._accept_knowledge_proposal(work_id, proposal_id, payload)

        expected = int(payload.get("expected_version", -1))
        selected_text = payload.get("text")
        requested_change_ids = payload.get("selected_change_ids")
        if selected_text is not None and requested_change_ids is not None:
            raise DomainError(
                "validation_error",
                "逐项应用与手工编辑候选不能同时提交。",
                details={"fields": ["text", "selected_change_ids"]},
            )
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            proposal = connection.execute("SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)).fetchone()
            if proposal["status"] != "pending":
                raise DomainError("proposal_not_pending", "候选方案已经处理。", status=409)
            scene = connection.execute("SELECT * FROM scenes WHERE id=?", (proposal["scope_id"],)).fetchone()
            if not scene:
                raise NotFound("scene", proposal["scope_id"])
            if scene["current_revision_id"] != proposal["base_revision_id"]:
                raise self._proposal_superseded("当前正文已经变化，请重新生成差异。")
            candidate_text = self._verified_proposal_candidate(proposal)
            artifact = self._artifact(connection, work_id, "scene_script", "scene", scene["id"])
            if artifact.get("current_revision_id") != scene["current_revision_id"]:
                artifact["current_revision_id"] = scene["current_revision_id"]
            base_blocks = self._scene_revision_blocks(connection, proposal["base_revision_id"])
            selected_change_ids = None
            if requested_change_ids is not None:
                if not isinstance(requested_change_ids, list):
                    raise DomainError(
                        "validation_error",
                        "selected_change_ids 必须是数组。",
                        details={"field": "selected_change_ids"},
                    )
                selected_change_ids = {
                    str(change_id).strip()
                    for change_id in requested_change_ids
                    if str(change_id).strip()
                }
                if not selected_change_ids:
                    raise DomainError(
                        "validation_error",
                        "请至少选择一项正文修改。",
                        details={"field": "selected_change_ids"},
                    )
                changes = self._scene_block_change_plan(
                    base_blocks,
                    candidate_text,
                    proposal["candidate_hash"],
                )
                known_ids = {change["id"] for change in changes}
                unknown_ids = sorted(selected_change_ids.difference(known_ids))
                if unknown_ids:
                    raise DomainError(
                        "proposal_change_unknown",
                        "选择的正文修改已不存在，请重新检查候选。",
                        status=409,
                        details={"unknown_change_ids": unknown_ids},
                    )
                text = self._apply_scene_block_changes(base_blocks, changes, selected_change_ids)
            else:
                text = str(selected_text) if selected_text is not None else candidate_text
            scene_content = self._scene_content_preserving_unchanged_blocks(text, base_blocks)
            revision_id = self._add_revision(connection, artifact, scene_content, "user", {
                "workflow": "scene.review", "proposal_id": proposal_id, "pack": PACK_VERSION,
                "provider": json.loads(proposal["provider_json"]),
                "partial_accept": selected_text is not None or selected_change_ids is not None,
                "selected_change_ids": sorted(selected_change_ids) if selected_change_ids is not None else None,
            }, schema_version="scene-blocks/1.0")
            connection.execute("UPDATE scenes SET current_revision_id=?, status='review', version=version+1, updated_at=? WHERE id=?", (revision_id, now(), scene["id"]))
            connection.execute("UPDATE proposals SET status='accepted', decided_at=? WHERE id=?", (now(), proposal_id))
            connection.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", (new_id("decision"), work_id, "proposal", proposal_id, "accepted", str(payload.get("note", "")), now()))
            connection.execute("UPDATE work_items SET status='succeeded', updated_at=? WHERE output_refs_json LIKE ?", (now(), f'%{proposal_id}%'))
            connection.execute(
                "UPDATE production_runs SET status='running',updated_at=? WHERE id IN (SELECT run_id FROM work_items WHERE output_refs_json LIKE ?)",
                (now(), f'%{proposal_id}%'),
            )
            self._ensure_memory_extract_work_item(
                connection, work_id, scene["id"], revision_id
            )
            self._supersede_background_knowledge_suggestions(
                connection,
                work_id=work_id,
                scene_id=scene["id"],
                current_revision_id=revision_id,
                reason="场景产生了新的正文修订，旧的后台资料建议不再适用。",
            )
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {"revision_id": revision_id, "work": self.get_work(work_id)}

    def _accept_memory_bundle_proposal(self, work_id: str, proposal_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        requested_ids = payload.get("selected_item_ids")
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
            if not proposal or proposal["kind"] != "memory_bundle":
                raise NotFound("proposal", proposal_id)
            if proposal["status"] != "pending":
                raise DomainError("proposal_not_pending", "长期记忆候选已经处理。", status=409)
            candidate = json.loads(self._verified_proposal_candidate(proposal))
            items = candidate.get("items") if isinstance(candidate.get("items"), list) else []
            item_ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
            if not items or any(not item for item in item_ids) or len(item_ids) != len(set(item_ids)):
                raise DomainError("proposal_candidate_invalid", "长期记忆候选的条目 ID 无效。", status=409)
            if requested_ids is None:
                selected_ids = set(item_ids)
            elif isinstance(requested_ids, list):
                selected_ids = {str(item).strip() for item in requested_ids if str(item).strip()}
            else:
                raise DomainError("validation_error", "selected_item_ids 必须是数组。", details={"field": "selected_item_ids"})
            unknown_ids = sorted(selected_ids.difference(item_ids))
            if unknown_ids:
                raise DomainError("validation_error", "选择了不属于本候选的长期记忆。", details={"ids": unknown_ids})
            if not selected_ids:
                raise DomainError("validation_error", "请至少选择一条长期记忆。", details={"field": "selected_item_ids"})
            source_revision_id = candidate.get("source_scene_revision_id")
            source_scene_revisions = candidate.get("source_scene_revisions")
            if isinstance(source_scene_revisions, list):
                chapter_id = str(candidate.get("source_chapter_id") or "")
                pinned = [
                    (str(item.get("scene_id") or ""), str(item.get("revision_id") or ""))
                    for item in source_scene_revisions if isinstance(item, dict)
                ]
                current = connection.execute(
                    "SELECT id,current_revision_id FROM scenes WHERE chapter_id=? AND work_id=? ORDER BY stable_order_key",
                    (chapter_id, work_id),
                ).fetchall()
                if not pinned or [(row["id"], row["current_revision_id"]) for row in current] != pinned:
                    raise self._proposal_superseded("章节场景或正文已经变化，请重新运行记忆清扫。")
                source_revision_id = pinned[-1][1]
            else:
                source_scene = connection.execute(
                    "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?",
                    (candidate.get("source_scene_id"), work_id),
                ).fetchone()
                if not source_scene or source_scene["current_revision_id"] != source_revision_id:
                    raise self._proposal_superseded("来源场景正文已经变化，请重新提取长期记忆。")

            selected = [item for item in items if item["id"] in selected_ids]
            current_rows = {}
            for item in selected:
                operation = str(item.get("operation") or "")
                if operation not in {"create", "update", "retire"}:
                    raise DomainError("proposal_candidate_invalid", "长期记忆候选包含无效操作。", status=409)
                row = connection.execute(
                    "SELECT * FROM memories WHERE id=? AND work_id=?", (item["id"], work_id)
                ).fetchone()
                current_rows[item["id"]] = row
                if operation == "create" and row:
                    raise self._proposal_superseded("候选中的长期记忆 ID 已被占用，请重新提取。")
                if operation != "create" and (
                    not row or row["current_revision_id"] != item.get("base_revision_id")
                ):
                    raise self._proposal_superseded("已有长期记忆已经变化，请重新提取。")

            accepted_ids = []
            timestamp = now()
            for item in selected:
                existing = current_rows[item["id"]]
                operation = item["operation"]
                confidence = "retired" if operation == "retire" else "confirmed"
                lifecycle = existing["lifecycle_status"] if existing else "active"
                content = {
                    "schema_version": "long-term-memory/1.0",
                    "memory_id": item["id"],
                    "kind": item["kind"],
                    "title": item["title"],
                    "summary": item["summary"],
                    "details": item.get("details") if isinstance(item.get("details"), dict) else {},
                    "scope_type": item["scope_type"],
                    "scope_id": item["scope_id"],
                    "confidence_status": confidence,
                    "lifecycle_status": lifecycle,
                    "source_refs": item.get("source_refs") or [],
                }
                artifact = self._artifact(connection, work_id, "long_term_memory", item["kind"], item["id"])
                if existing and artifact.get("current_revision_id") != existing["current_revision_id"]:
                    raise self._proposal_superseded("长期记忆 Artifact 与检索投影不一致，请重新提取。")
                revision_id = self._add_revision(
                    connection,
                    artifact,
                    content,
                    "user",
                    {
                        "workflow": "memory.sweep" if candidate.get("source_chapter_id") else "canon.assemble",
                        "proposal_id": proposal_id,
                        "source_scene_revision_id": source_revision_id,
                        "operation": operation,
                        "pack": PACK_VERSION,
                    },
                    schema_version="long-term-memory/1.0",
                )
                source_refs_json = canonical_json(content["source_refs"])
                if existing:
                    connection.execute(
                        """UPDATE memories
                           SET kind=?,scope_type=?,scope_id=?,content=?,source_revision_id=?,
                               confidence_status=?,version=version+1,current_revision_id=?,
                               source_refs_json=?,lifecycle_status=?,last_verified_at=?,updated_at=?
                           WHERE id=? AND work_id=?""",
                        (
                            item["kind"], item["scope_type"], item["scope_id"], canonical_json(content),
                            source_revision_id, confidence, revision_id,
                            source_refs_json, lifecycle, timestamp, timestamp, item["id"], work_id,
                        ),
                    )
                else:
                    connection.execute(
                        """INSERT INTO memories
                           (id,work_id,kind,scope_type,scope_id,content,source_revision_id,
                            confidence_status,version,created_by,created_at,last_verified_at,
                            artifact_id,current_revision_id,source_refs_json,lifecycle_status,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            item["id"], work_id, item["kind"], item["scope_type"], item["scope_id"],
                            canonical_json(content), source_revision_id, confidence,
                            1, "user", timestamp, timestamp, artifact["id"], revision_id,
                            source_refs_json, lifecycle, timestamp,
                        ),
                    )
                accepted_ids.append(item["id"])

            decision = "accepted" if len(accepted_ids) == len(items) else "partially_accepted"
            connection.execute("UPDATE proposals SET status=?,decided_at=? WHERE id=?", (decision, timestamp, proposal_id))
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"), work_id, "proposal", proposal_id, decision,
                    canonical_json({"selected_item_ids": accepted_ids, "note": str(payload.get("note") or "")}), timestamp,
                ),
            )
            connection.execute(
                "UPDATE work_items SET status='succeeded',acceptance_json=?,updated_at=? WHERE output_refs_json LIKE ?",
                (canonical_json({"decision": decision, "selected_item_ids": accepted_ids}), timestamp, f'%{proposal_id}%'),
            )
            connection.execute(
                "UPDATE production_runs SET status='completed',updated_at=? WHERE id IN (SELECT run_id FROM work_items WHERE output_refs_json LIKE ?)",
                (timestamp, f'%{proposal_id}%'),
            )
            self._bump_work(connection, work_id, version)
        return {"memory_ids": accepted_ids, "decision": decision, "work": self.get_work(work_id)}

    @staticmethod
    def _knowledge_acceptance_fields(proposal_kind: str, candidate: dict, payload: dict) -> tuple[list[str], bool]:
        requested_fields = payload.get("selected_fields")
        changed_fields = [
            str(item.get("key") or "") for item in (candidate.get("field_changes") or [])
            if isinstance(item, dict) and str(item.get("key") or "")
        ]
        if requested_fields is None:
            return changed_fields, False
        if proposal_kind not in {"character_card", "world_entity", "world_rule", "canon_fact"} or candidate.get("operation") != "update":
            raise DomainError(
                "partial_accept_unsupported",
                "只有已有的人物卡、世界观条目、世界规则或作品事实更新候选可以部分采纳。",
                status=409,
            )
        if not isinstance(requested_fields, list) or not requested_fields:
            raise DomainError("partial_accept_fields_required", "请至少选择一项要采用的变更。", status=409)
        requested = [str(item).strip() for item in requested_fields if str(item).strip()]
        if len(requested) != len(requested_fields) or len(requested) != len(set(requested)):
            raise DomainError("partial_accept_invalid_field", "所选变更与当前候选不一致，请刷新后重试。", status=409)
        requested_set = set(requested)
        if any(item not in changed_fields for item in requested_set):
            raise DomainError("partial_accept_invalid_field", "所选变更与当前候选不一致，请刷新后重试。", status=409)
        return [item for item in changed_fields if item in requested_set], True

    def _accepted_knowledge_result(
        self,
        connection,
        work_id: str,
        proposal,
        candidate: dict,
        impact_digest: str,
        applied_fields: list[str],
        partial_accept: bool,
    ) -> dict:
        rows = connection.execute(
            """SELECT revisions.id,revisions.provenance_json
               FROM revisions JOIN artifacts ON artifacts.id=revisions.artifact_id
               WHERE artifacts.work_id=? ORDER BY revisions.created_at DESC""",
            (work_id,),
        ).fetchall()
        accepted_revision = None
        accepted_provenance = None
        for row in rows:
            provenance = json.loads(row["provenance_json"] or "{}")
            if provenance.get("proposal_id") == proposal["id"]:
                accepted_revision = row["id"]
                accepted_provenance = provenance
                break
        if not accepted_revision or not accepted_provenance:
            raise DomainError(
                "proposal_decision_inconsistent",
                "资料候选已标记为采纳，但找不到对应修订。",
                status=409,
                details={"proposal_id": proposal["id"]},
            )
        same_decision = (
            accepted_provenance.get("impact_digest") == impact_digest
            and bool(accepted_provenance.get("partial_accept")) == partial_accept
            and list(accepted_provenance.get("applied_fields") or []) == applied_fields
        )
        if not same_decision:
            raise DomainError(
                "proposal_decision_mismatch",
                "资料候选已经按另一组修改项处理，不能用不同决定重复采纳。",
                status=409,
                details={
                    "proposal_id": proposal["id"],
                    "accepted_fields": accepted_provenance.get("applied_fields") or [],
                    "requested_fields": applied_fields,
                },
            )
        result_key = {
            "character_card": "card_id",
            "world_entity": "world_id",
            "world_rule": "world_rule_id",
            "canon_fact": "fact_id",
        }[proposal["kind"]]
        return {
            result_key: candidate["scope_id"],
            "revision_id": accepted_revision,
            "idempotent": True,
            "work": self.get_work(work_id),
        }

    def _accept_knowledge_proposal(self, work_id: str, proposal_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
            if not proposal or proposal["kind"] not in {"character_card", "world_entity", "world_rule", "canon_fact"}:
                raise NotFound("proposal", proposal_id)
            candidate = json.loads(self._verified_proposal_candidate(proposal))
            expected_impact_digest = str(payload.get("expected_impact_digest") or "").strip()
            actual_impact_digest = str((candidate.get("impact_preview") or {}).get("digest") or "").strip()
            if not expected_impact_digest:
                raise DomainError(
                    "proposal_impact_required",
                    "采纳资料候选前必须确认当前影响预览。",
                    status=409,
                    details={"proposal_id": proposal_id},
                )
            if expected_impact_digest != actual_impact_digest:
                raise DomainError(
                    "proposal_impact_mismatch",
                    "候选影响范围与用户审查的版本不一致，请刷新后重试。",
                    status=409,
                    details={
                        "expected_impact_digest": expected_impact_digest,
                        "actual_impact_digest": actual_impact_digest,
                    },
                )
            applied_fields, partial_accept = self._knowledge_acceptance_fields(
                proposal["kind"], candidate, payload
            )
            if proposal["status"] != "pending":
                if proposal["status"] == "accepted":
                    return self._accepted_knowledge_result(
                        connection,
                        work_id,
                        proposal,
                        candidate,
                        actual_impact_digest,
                        applied_fields,
                        partial_accept,
                    )
                raise DomainError("proposal_not_pending", "资料候选已经处理。", status=409)
            version = self._check_work_version(connection, work_id, expected)
            live_conflicts = self._knowledge_conflicts(
                connection,
                work_id,
                str(candidate.get("kind") or ""),
                candidate.get("content") or {},
            )
            blocking_conflicts = self._knowledge_decision_conflicts(candidate, live_conflicts)
            if blocking_conflicts:
                raise DomainError(
                    "knowledge_conflict",
                    "资料候选与现有正式资料重复或冲突，请退回 Agent 合并后重新整理。",
                    status=409,
                    details={"conflicts": blocking_conflicts},
                )
            live_affected_refs = self._knowledge_affected_refs(
                connection,
                work_id,
                str(candidate.get("kind") or ""),
                str(candidate.get("scope_id") or ""),
                candidate.get("content") or {},
            )
            if canonical_json(live_affected_refs) != canonical_json(
                (candidate.get("impact_preview") or {}).get("affected_refs") or []
            ):
                raise DomainError(
                    "proposal_impact_changed",
                    "资料候选影响的场景或审查状态已经变化，请刷新影响预览后重新整理。",
                    status=409,
                    details={"affected_refs": live_affected_refs},
                )
            document_citations = [
                item for item in (candidate.get("document_citations") or []) if isinstance(item, dict)
            ]
            provenance = {
                "pack": PACK_VERSION,
                "proposal_id": proposal_id,
                "thread_id": candidate["source_thread_id"],
                "source_message_ids": candidate.get("source_message_ids", []),
                "document_citations": document_citations,
                "operation": candidate.get("operation", "create"),
                "applied_fields": applied_fields,
                "partial_accept": partial_accept,
                "impact_digest": actual_impact_digest,
            }
            if proposal["kind"] == "character_card":
                artifact = self._artifact(connection, work_id, "character_card", "character", candidate["scope_id"])
                if artifact.get("current_revision_id") != candidate.get("base_revision_id"):
                    raise self._proposal_superseded("人物卡已经变化，请重新整理。")
                accepted_content = candidate["content"]
                if partial_accept:
                    existing = self._revision_content(connection, artifact.get("current_revision_id"))
                    accepted_content = {**existing, **{key: candidate["content"].get(key) for key in applied_fields}}
                accepted_content = self._normalize_character_card_payload(accepted_content)
                revision_id = self._add_revision(
                    connection, artifact, accepted_content, "user",
                    {"workflow": "character.from_conversation", **provenance},
                )
                result_key = "card_id"
            elif proposal["kind"] == "world_entity":
                artifact = self._artifact(connection, work_id, "world_bible", "work", work_id)
                if artifact.get("current_revision_id") != candidate.get("base_revision_id"):
                    raise self._proposal_superseded("世界观已经变化，请重新整理。")
                if artifact.get("current_revision_id"):
                    revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone()
                    bible = json.loads(self.repo.read_text(revision["content_uri"]))
                else:
                    bible = {"title": "作品世界观", "source_type": "custom", "entities": [], "rules": [], "timeline": []}
                entities = list(bible.get("entities") or [])
                if candidate.get("operation") == "update":
                    replaced = False
                    for index, item in enumerate(entities):
                        if item.get("id") == candidate["scope_id"]:
                            entities[index] = (
                                {**item, **{key: candidate["content"].get(key) for key in applied_fields}}
                                if partial_accept else candidate["content"]
                            )
                            replaced = True
                            break
                    if not replaced:
                        raise self._proposal_superseded("要更新的世界观条目已经不存在，请重新整理。")
                else:
                    entities.append(candidate["content"])
                bible = {**bible, "entities": entities}
                bible["source_type"] = self._merge_world_source_type([bible.get("source_type", "custom"), "custom"])
                bible = self._normalize_world_bible_payload(bible)
                revision_id = self._add_revision(
                    connection, artifact, bible, "user",
                    {"workflow": "world.from_conversation", **provenance},
                )
                result_key = "world_id"
            elif proposal["kind"] == "world_rule":
                artifact = self._artifact(connection, work_id, "world_bible", "work", work_id)
                if artifact.get("current_revision_id") != candidate.get("base_revision_id"):
                    raise self._proposal_superseded("世界观已经变化，请重新整理。")
                if artifact.get("current_revision_id"):
                    revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone()
                    bible = json.loads(self.repo.read_text(revision["content_uri"]))
                else:
                    bible = {"title": "作品世界观", "source_type": "custom", "entities": [], "rules": [], "timeline": []}
                rules = list(bible.get("rules") or [])
                if candidate.get("operation") == "update":
                    replaced = False
                    for index, item in enumerate(rules):
                        if item.get("id") == candidate["scope_id"]:
                            rules[index] = (
                                {**item, **{key: candidate["content"].get(key) for key in applied_fields}}
                                if partial_accept else candidate["content"]
                            )
                            replaced = True
                            break
                    if not replaced:
                        raise self._proposal_superseded("要更新的世界规则已经不存在，请重新整理。")
                else:
                    rules.append(candidate["content"])
                bible = {**bible, "rules": rules}
                bible["source_type"] = self._merge_world_source_type([bible.get("source_type", "custom"), "custom"])
                bible = self._normalize_world_bible_payload(bible)
                revision_id = self._add_revision(
                    connection, artifact, bible, "user",
                    {"workflow": "world-rule.from_conversation", **provenance},
                )
                result_key = "world_rule_id"
            else:
                artifact = self._artifact(connection, work_id, "work_canon", "work", work_id)
                if artifact.get("current_revision_id") != candidate.get("base_revision_id"):
                    raise self._proposal_superseded("作品事实已经变化，请重新整理。")
                if artifact.get("current_revision_id"):
                    revision = connection.execute("SELECT content_uri FROM revisions WHERE id=?", (artifact["current_revision_id"],)).fetchone()
                    canon = json.loads(self.repo.read_text(revision["content_uri"])) if revision else {"facts": []}
                else:
                    canon = {"facts": []}
                readable_sources = [
                    str(item.get("display_label") or item.get("filename") or "").strip()
                    for item in document_citations
                    if str(item.get("display_label") or item.get("filename") or "").strip()
                ]
                operation = str(candidate.get("operation") or "create")
                facts = list(canon.get("facts") or [])
                if operation in {"update", "retire"}:
                    replaced = False
                    for index, item in enumerate(facts):
                        if item.get("id") != candidate["scope_id"]:
                            continue
                        facts[index] = (
                            {**item, **{key: candidate["content"].get(key) for key in applied_fields}}
                            if partial_accept else candidate["content"]
                        )
                        facts[index]["id"] = candidate["scope_id"]
                        replaced = True
                        break
                    if not replaced:
                        raise self._proposal_superseded("要更新或退役的作品事实已经不存在，请重新整理。")
                else:
                    accepted_fact = {
                        **candidate["content"],
                        "source": (
                            "用户采纳自 " + "；".join(readable_sources)
                            if readable_sources
                            else (
                                str(candidate["content"].get("source"))
                                if str(candidate["content"].get("source") or "").startswith("场景修订 ")
                                else f"用户采纳自作品主对话 {candidate['source_thread_id']}"
                            )
                        ),
                        "confidence_status": "confirmed",
                    }
                    facts.append(accepted_fact)
                canon = self._normalize_work_canon_payload({**canon, "facts": facts})
                revision_id = self._add_revision(
                    connection, artifact, canon, "user",
                    {"workflow": "canon.assemble", **provenance},
                )
                result_key = "fact_id"
            connection.execute("UPDATE proposals SET status='accepted',decided_at=? WHERE id=?", (now(), proposal_id))
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"), work_id, "proposal", proposal_id, "accepted",
                    canonical_json({
                        "impact_digest": actual_impact_digest,
                        "applied_fields": applied_fields,
                        "partial_accept": partial_accept,
                        "note": str(payload.get("note", "")),
                    }),
                    now(),
                ),
            )
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {result_key: candidate["scope_id"], "revision_id": revision_id, "work": self.get_work(work_id)}

    def _accept_brief_blueprint_proposal(self, work_id: str, proposal_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
            if not proposal or proposal["kind"] != "brief_blueprint":
                raise NotFound("proposal", proposal_id)
            if proposal["status"] != "pending":
                raise DomainError("proposal_not_pending", "候选方案已经处理。", status=409)
            candidate = json.loads(self._verified_proposal_candidate(proposal))
            brief_artifact = self._artifact(connection, work_id, "brief", "work", work_id)
            blueprint_artifact = self._artifact(connection, work_id, "story_blueprint", "work", work_id)
            if (
                brief_artifact.get("current_revision_id") != candidate.get("base_brief_revision_id")
                or blueprint_artifact.get("current_revision_id") != candidate.get("base_blueprint_revision_id")
            ):
                raise self._proposal_superseded("正式故事方案已经变化，请基于最新版本重新整理。")
            brief_revision_id = self._add_revision(
                connection, brief_artifact, {**candidate["brief"], "status": "confirmed"}, "user",
                {"workflow": "brief.from_conversation", "pack": PACK_VERSION, "proposal_id": proposal_id, "thread_id": candidate["source_thread_id"]},
            )
            blueprint_revision_id = self._add_revision(
                connection, blueprint_artifact,
                {**candidate["story_blueprint"], "status": "accepted", "decision": {"proposal_id": proposal_id, "brief_revision_id": brief_revision_id}},
                "user",
                {"workflow": "blueprint.from_conversation", "pack": PACK_VERSION, "proposal_id": proposal_id, "thread_id": candidate["source_thread_id"]},
            )
            connection.execute("UPDATE proposals SET status='accepted',decided_at=? WHERE id=?", (now(), proposal_id))
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (new_id("decision"), work_id, "proposal", proposal_id, "accepted", str(payload.get("note", "")), now()),
            )
            self._bump_work(connection, work_id, version)
        return {
            "revision_id": blueprint_revision_id,
            "brief_revision_id": brief_revision_id,
            "blueprint_revision_id": blueprint_revision_id,
            "work": self.get_work(work_id),
        }

    def _accept_structure_plan_proposal(self, work_id: str, proposal_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
            if not proposal or proposal["kind"] != "story_structure":
                raise NotFound("proposal", proposal_id)
            if proposal["status"] != "pending":
                raise DomainError("proposal_not_pending", "候选方案已经处理。", status=409)
            candidate = json.loads(self._verified_proposal_candidate(proposal))
            if candidate.get("schema_version") != "structure-plan-proposal/1.0" or candidate.get("work_id") != work_id:
                raise DomainError("proposal_candidate_invalid", "作品结构候选格式无效。", status=409)
            base = candidate.get("base") if isinstance(candidate.get("base"), dict) else {}
            current_blueprint = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'", (work_id,)
            ).fetchone()
            current_snapshot = self._structure_snapshot(connection, work_id)
            if (
                (current_blueprint["current_revision_id"] if current_blueprint else None) != base.get("story_blueprint_revision_id")
                or current_snapshot["digest"] != base.get("structure_digest")
            ):
                raise self._proposal_superseded("作品方向或结构已经变化，请基于最新状态重新整理。")
            entity_versions = base.get("entity_versions") if isinstance(base.get("entity_versions"), dict) else {}
            for entity in current_snapshot["projection"]["volumes"] + current_snapshot["projection"]["chapters"]:
                if entity["id"] in entity_versions and int(entity_versions[entity["id"]]) != int(entity["version"]):
                    raise self._proposal_superseded("要复用的占位结构已经变化，请重新整理。")
            if current_snapshot["projection"]["scenes"] or len(current_snapshot["projection"]["volumes"]) != 1 or len(current_snapshot["projection"]["chapters"]) != 1:
                raise self._proposal_superseded("当前结构已不再是可安全初始化的占位骨架。")
            base_volume = current_snapshot["projection"]["volumes"][0]
            base_chapter = current_snapshot["projection"]["chapters"][0]
            if base_chapter["status"] != "placeholder":
                raise self._proposal_superseded("第一章占位已经被手工规划，请重新整理。")
            plan = candidate.get("plan") if isinstance(candidate.get("plan"), dict) else {}
            volumes = plan.get("volumes")
            if not isinstance(volumes, list) or not volumes:
                raise DomainError("proposal_candidate_invalid", "作品结构候选没有可采纳的卷。", status=409)
            all_ids: list[str] = []
            for volume in volumes:
                if not isinstance(volume, dict) or not isinstance(volume.get("chapters"), list) or not volume["chapters"]:
                    raise DomainError("proposal_candidate_invalid", "作品结构候选的卷或章节格式无效。", status=409)
                all_ids.append(str(volume.get("id") or ""))
                for chapter in volume["chapters"]:
                    if not isinstance(chapter, dict) or not isinstance(chapter.get("scenes"), list) or not chapter["scenes"]:
                        raise DomainError("proposal_candidate_invalid", "作品结构候选的章节或场景格式无效。", status=409)
                    all_ids.append(str(chapter.get("id") or ""))
                    for scene in chapter["scenes"]:
                        if not isinstance(scene, dict) or not isinstance(scene.get("contract"), dict):
                            raise DomainError("proposal_candidate_invalid", "作品结构候选的场景合同无效。", status=409)
                        all_ids.append(str(scene.get("id") or ""))
                        contract = scene["contract"]
                        if not str(contract.get("goal") or "").strip() or not str(contract.get("stop_boundary") or "").strip() or contract.get("writing_mode") not in MODE_SOURCES:
                            raise DomainError("proposal_candidate_invalid", "作品结构候选包含不完整的场景边界。", status=409)
            if any(not item for item in all_ids) or len(all_ids) != len(set(all_ids)):
                raise DomainError("proposal_candidate_invalid", "作品结构候选包含空 ID 或重复 ID。", status=409)
            if volumes[0].get("id") != base_volume["id"] or volumes[0].get("operation") != "reuse_placeholder":
                raise DomainError("proposal_candidate_invalid", "作品结构候选没有安全复用初始卷。", status=409)
            if volumes[0]["chapters"][0].get("id") != base_chapter["id"] or volumes[0]["chapters"][0].get("operation") != "reuse_placeholder":
                raise DomainError("proposal_candidate_invalid", "作品结构候选没有安全复用初始章节。", status=409)
            existing_ids = {
                row[0]
                for table in ("volumes", "chapters", "scenes")
                for row in connection.execute(f"SELECT id FROM {table}").fetchall()
            }
            allowed_existing = {base_volume["id"], base_chapter["id"]}
            if any(item in existing_ids and item not in allowed_existing for item in all_ids):
                raise DomainError("proposal_candidate_invalid", "作品结构候选中的新 ID 已被占用。", status=409)

            timestamp = now()
            structure_artifact = self._artifact(connection, work_id, "story_structure", "work", work_id)
            structure_revision_id = self._add_revision(
                connection,
                structure_artifact,
                {
                    "schema_version": "story-structure/1.0",
                    "summary": str(plan.get("summary") or ""),
                    "volumes": volumes,
                    "status": "accepted",
                },
                "user",
                {
                    "workflow": "structure.plan",
                    "pack": PACK_VERSION,
                    "proposal_id": proposal_id,
                    "story_blueprint_revision_id": base.get("story_blueprint_revision_id"),
                },
                schema_version="story-structure/1.0",
            )
            for volume_index, volume in enumerate(volumes, start=1):
                volume_id = volume["id"]
                order = f"{volume_index:06d}"
                if volume.get("operation") == "reuse_placeholder":
                    connection.execute(
                        "UPDATE volumes SET stable_order_key=?,title=?,status='active',version=version+1,updated_at=? WHERE id=? AND work_id=?",
                        (order, str(volume.get("title") or "未命名卷"), timestamp, volume_id, work_id),
                    )
                elif volume.get("operation") == "create":
                    connection.execute(
                        "INSERT INTO volumes VALUES (?,?,?,?,?,?,?,?)",
                        (volume_id, work_id, order, str(volume.get("title") or "未命名卷"), "active", 1, timestamp, timestamp),
                    )
                else:
                    raise DomainError("proposal_candidate_invalid", "作品结构候选包含未知卷操作。", status=409)
                for chapter_index, chapter in enumerate(volume["chapters"], start=1):
                    chapter_id = chapter["id"]
                    chapter_order = f"{chapter_index:06d}"
                    if chapter.get("operation") == "reuse_placeholder":
                        connection.execute(
                            "UPDATE chapters SET volume_id=?,stable_order_key=?,title=?,status='planned',version=version+1,updated_at=? WHERE id=? AND work_id=? AND status='placeholder'",
                            (volume_id, chapter_order, str(chapter.get("title") or "未命名章"), timestamp, chapter_id, work_id),
                        )
                    elif chapter.get("operation") == "create":
                        connection.execute(
                            "INSERT INTO chapters (id,work_id,volume_id,stable_order_key,title,status,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            (chapter_id, work_id, volume_id, chapter_order, str(chapter.get("title") or "未命名章"), "planned", 1, timestamp, timestamp),
                        )
                    else:
                        raise DomainError("proposal_candidate_invalid", "作品结构候选包含未知章节操作。", status=409)
                    for scene_index, scene in enumerate(chapter["scenes"], start=1):
                        if scene.get("operation") != "create":
                            raise DomainError("proposal_candidate_invalid", "作品结构候选包含未知场景操作。", status=409)
                        connection.execute(
                            "INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                scene["id"], work_id, chapter_id, f"{scene_index:06d}",
                                str(scene.get("title") or "未命名场景"), "planned", 1, None,
                                canonical_json(scene["contract"]), timestamp, timestamp,
                            ),
                        )
            connection.execute("UPDATE proposals SET status='accepted',decided_at=? WHERE id=?", (timestamp, proposal_id))
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (new_id("decision"), work_id, "proposal", proposal_id, "accepted", str(payload.get("note", "")), timestamp),
            )
            connection.execute("UPDATE work_items SET status='succeeded',updated_at=? WHERE output_refs_json LIKE ?", (timestamp, f'%{proposal_id}%'))
            connection.execute(
                "UPDATE production_runs SET status='running',updated_at=? WHERE id IN (SELECT run_id FROM work_items WHERE output_refs_json LIKE ?)",
                (timestamp, f'%{proposal_id}%'),
            )
            self._bump_work(connection, work_id, version)
        return {
            "revision_id": structure_revision_id,
            "volume_ids": [volume["id"] for volume in volumes],
            "chapter_ids": [chapter["id"] for volume in volumes for chapter in volume["chapters"]],
            "scene_ids": [scene["id"] for volume in volumes for chapter in volume["chapters"] for scene in chapter["scenes"]],
            "work": self.get_work(work_id),
        }

    def _accept_chapter_plan_proposal(self, work_id: str, proposal_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)
            ).fetchone()
            if not proposal or proposal["kind"] != "chapter_plan":
                raise NotFound("proposal", proposal_id)
            if proposal["status"] != "pending":
                raise DomainError("proposal_not_pending", "候选方案已经处理。", status=409)
            candidate = json.loads(self._verified_proposal_candidate(proposal))
            candidate_plan = self._validate_chapter_plan(candidate.get("chapter_plan"))
            artifact = self._artifact(connection, work_id, "chapter_plan", "chapter", candidate["chapter_id"])
            blueprint_artifact = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='story_blueprint'",
                (work_id,),
            ).fetchone()
            target_artifact = connection.execute(
                "SELECT current_revision_id FROM artifacts WHERE work_id=? AND kind='writing_target'",
                (work_id,),
            ).fetchone()
            if (
                artifact.get("current_revision_id") != candidate.get("base_revision_id")
                or (blueprint_artifact["current_revision_id"] if blueprint_artifact else None) != candidate.get("story_blueprint_revision_id")
                or (target_artifact["current_revision_id"] if target_artifact else None) != candidate.get("writing_target_revision_id")
            ):
                raise self._proposal_superseded("本章细纲已经变化，请基于最新讨论重新整理。")
            revision_id = self._add_revision(
                connection, artifact, {**candidate_plan, "status": "accepted"}, "user",
                {"workflow": "chapter.plan", "pack": PACK_VERSION, "proposal_id": proposal_id, "thread_id": candidate["source_thread_id"], "chapter_id": candidate["chapter_id"]},
            )
            connection.execute("UPDATE proposals SET status='accepted',decided_at=? WHERE id=?", (now(), proposal_id))
            connection.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", (new_id("decision"), work_id, "proposal", proposal_id, "accepted", str(payload.get("note", "")), now()))
            self._bump_work(connection, work_id, version)
        return {"revision_id": revision_id, "work": self.get_work(work_id)}

    def save_scene_manuscript(self, work_id: str, scene_id: str, payload: dict):
        """Create a manuscript Revision from user-edited stable SceneBlocks."""
        expected = int(payload.get("expected_version", -1))
        expected_base = payload.get("expected_base_revision_id") or None
        blocks = self._normalize_scene_blocks(payload.get("blocks"))
        text = self._scene_text_from_blocks(blocks)
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                "SELECT * FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if scene["current_revision_id"] != expected_base:
                raise DomainError(
                    "manuscript_conflict",
                    "正文已经产生新修订，请重新载入后再保存。",
                    status=409,
                    details={
                        "expected_base_revision_id": expected_base,
                        "actual_revision_id": scene["current_revision_id"],
                    },
                )
            artifact = self._artifact(connection, work_id, "scene_script", "scene", scene_id)
            if artifact.get("current_revision_id") != scene["current_revision_id"]:
                artifact["current_revision_id"] = scene["current_revision_id"]
            content = {"schema_version": "scene-blocks/1.0", "blocks": blocks, "text": text}
            revision_id = self._add_revision(
                connection,
                artifact,
                content,
                "user",
                {
                    "workflow": "scene.manuscript.edit",
                    "pack": PACK_VERSION,
                    "base_revision_id": expected_base,
                    "editor": "scene-blocks",
                },
                schema_version="scene-blocks/1.0",
            )
            timestamp = now()
            pending = connection.execute(
                "SELECT id FROM proposals WHERE work_id=? AND scope_type='scene' AND scope_id=? AND status='pending'",
                (work_id, scene_id),
            ).fetchall()
            if pending:
                connection.execute(
                    "UPDATE proposals SET status='superseded', decided_at=? WHERE work_id=? AND scope_type='scene' AND scope_id=? AND status='pending'",
                    (timestamp, work_id, scene_id),
                )
                for proposal in pending:
                    connection.execute(
                        "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                        (new_id("decision"), work_id, "proposal", proposal["id"], "superseded", "用户保存了新的正文修订，旧候选不再适用。", timestamp),
                    )
            connection.execute(
                "UPDATE scenes SET current_revision_id=?, status='draft', version=version+1, updated_at=? WHERE id=?",
                (revision_id, timestamp, scene_id),
            )
            background_superseded = self._supersede_background_knowledge_suggestions(
                connection,
                work_id=work_id,
                scene_id=scene_id,
                current_revision_id=revision_id,
                reason="用户保存了新的正文修订，旧的后台资料建议不再适用。",
            )
            self._ensure_memory_extract_work_item(
                connection, work_id, scene_id, revision_id
            )
            self._bump_work(connection, work_id, version)
        self._schedule_commit_projection(work_id, revision_id)
        return {
            "revision_id": revision_id,
            "superseded_proposal_ids": [row["id"] for row in pending] + background_superseded,
            "work": self.get_work(work_id),
        }

    def _set_memory_lifecycle(self, work_id: str, memory_id: str, payload: dict, lifecycle: str):
        expected = int(payload.get("expected_version", -1))
        if lifecycle not in {"active", "archived"}:
            raise DomainError("validation_error", "长期记忆生命周期无效。")
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            memory = connection.execute(
                "SELECT * FROM memories WHERE id=? AND work_id=?", (memory_id, work_id)
            ).fetchone()
            if not memory:
                raise NotFound("memory", memory_id)
            if memory["lifecycle_status"] == lifecycle:
                raise DomainError("memory_state_unchanged", "长期记忆已经处于该状态。", status=409)
            artifact = connection.execute(
                "SELECT * FROM artifacts WHERE id=? AND work_id=?", (memory["artifact_id"], work_id)
            ).fetchone()
            if not artifact or artifact["current_revision_id"] != memory["current_revision_id"]:
                raise DomainError("memory_projection_conflict", "长期记忆投影与修订历史不一致。", status=409)
            content = self._revision_content(connection, memory["current_revision_id"])
            content["lifecycle_status"] = lifecycle
            revision_id = self._add_revision(
                connection,
                dict(artifact),
                content,
                "user",
                {
                    "workflow": "memory.lifecycle",
                    "operation": "archive" if lifecycle == "archived" else "restore",
                    "base_revision_id": memory["current_revision_id"],
                },
                schema_version="long-term-memory/1.0",
            )
            timestamp = now()
            connection.execute(
                "UPDATE memories SET content=?,current_revision_id=?,lifecycle_status=?,version=version+1,updated_at=? WHERE id=?",
                (canonical_json(content), revision_id, lifecycle, timestamp, memory_id),
            )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (new_id("decision"), work_id, "memory", memory_id, lifecycle, str(payload.get("note") or ""), timestamp),
            )
            self._bump_work(connection, work_id, version)
        return {"memory_id": memory_id, "lifecycle_status": lifecycle, "work": self.get_work(work_id)}

    def archive_memory(self, work_id: str, memory_id: str, payload: dict):
        return self._set_memory_lifecycle(work_id, memory_id, payload, "archived")

    def restore_memory(self, work_id: str, memory_id: str, payload: dict):
        return self._set_memory_lifecycle(work_id, memory_id, payload, "active")

    def skip_scene_memory_maintenance(self, work_id: str, scene_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        note = str(payload.get("note") or "本场没有需要沉淀的长期记忆。").strip()
        if not note:
            raise DomainError("validation_error", "跳过记忆维护时必须说明理由。", details={"field": "note"})
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scene = connection.execute(
                "SELECT current_revision_id FROM scenes WHERE id=? AND work_id=?", (scene_id, work_id)
            ).fetchone()
            if not scene:
                raise NotFound("scene", scene_id)
            if not scene["current_revision_id"]:
                raise DomainError("scene_memory_requires_revision", "当前场景还没有正式正文修订。", status=409)
            work_item_id, run_id = self._ensure_memory_extract_work_item(
                connection, work_id, scene_id, scene["current_revision_id"]
            )
            work_item = connection.execute(
                "SELECT status FROM work_items WHERE id=?", (work_item_id,)
            ).fetchone()
            if work_item["status"] in {"running", "waiting_user"}:
                raise DomainError(
                    "memory_maintenance_in_progress",
                    "记忆提取正在运行或已有候选等待决定，请先完成或退回。",
                    status=409,
                )
            timestamp = now()
            decision = {
                "decision": "skipped",
                "scene_revision_id": scene["current_revision_id"],
                "note": note,
            }
            connection.execute(
                "UPDATE work_items SET status='skipped',acceptance_json=?,error_json=NULL,updated_at=? WHERE id=?",
                (canonical_json(decision), timestamp, work_item_id),
            )
            connection.execute(
                "UPDATE production_runs SET status='completed',updated_at=? WHERE id=?",
                (timestamp, run_id),
            )
            connection.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,?,?,?)",
                (
                    new_id("decision"), work_id, "memory_maintenance",
                    scene["current_revision_id"], "skipped", note, timestamp,
                ),
            )
            self._bump_work(connection, work_id, version)
        return {
            "scene_id": scene_id,
            "scene_revision_id": scene["current_revision_id"],
            "work_item_id": work_item_id,
            "status": "skipped",
            "work": self.get_work(work_id),
        }

    def reject_proposal(self, work_id: str, proposal_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            proposal = connection.execute("SELECT * FROM proposals WHERE id=? AND work_id=?", (proposal_id, work_id)).fetchone()
            if not proposal:
                raise NotFound("proposal", proposal_id)
            if proposal["status"] != "pending":
                raise DomainError("proposal_not_pending", "候选方案已经处理。", status=409)
            connection.execute("UPDATE proposals SET status='rejected', decided_at=? WHERE id=?", (now(), proposal_id))
            connection.execute(
                "UPDATE agent_runs SET status='completed',finished_at=COALESCE(finished_at,?) WHERE work_id=? AND proposal_id=? AND status='waiting_user'",
                (now(), work_id, proposal_id),
            )
            connection.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", (new_id("decision"), work_id, "proposal", proposal_id, "rejected", str(payload.get("note", "")), now()))
            connection.execute(
                "UPDATE work_items SET status='cancelled',acceptance_json=?,updated_at=? WHERE output_refs_json LIKE ? AND status='waiting_user'",
                (canonical_json({"decision": "rejected", "proposal_id": proposal_id}), now(), f'%{proposal_id}%'),
            )
            connection.execute(
                "UPDATE production_runs SET status='running',updated_at=? WHERE id IN (SELECT run_id FROM work_items WHERE output_refs_json LIKE ?)",
                (now(), f'%{proposal_id}%'),
            )
            self._bump_work(connection, work_id, version)
        return {"work": self.get_work(work_id)}

    def freeze_release(self, work_id: str, payload: dict):
        expected = int(payload.get("expected_version", -1))
        with self.repo.transaction() as connection:
            version = self._check_work_version(connection, work_id, expected)
            scenes = connection.execute(
                """SELECT s.* FROM scenes s JOIN chapters c ON c.id=s.chapter_id
                   LEFT JOIN volumes v ON v.id=c.volume_id WHERE s.work_id=?
                   ORDER BY COALESCE(v.stable_order_key,''),c.stable_order_key,s.stable_order_key""",
                (work_id,),
            ).fetchall()
            if not scenes:
                raise DomainError("release_blocked", "作品还没有场景。", status=409)
            missing = [scene["id"] for scene in scenes if not scene["current_revision_id"]]
            if missing:
                raise DomainError("release_blocked", "所有场景都需要有已采纳正文。", status=409, details={"scene_ids": missing})
            source_ids = [scene["current_revision_id"] for scene in scenes]
            placeholders = ",".join("?" for _ in source_ids)
            blocking_rows = connection.execute(
                f"SELECT id FROM review_findings WHERE revision_id IN ({placeholders}) AND severity='blocking' AND status='open' ORDER BY created_at",
                source_ids,
            ).fetchall()
            if blocking_rows:
                raise DomainError(
                    "release_blocked",
                    "发布前审查仍有未处理的阻塞项。",
                    status=409,
                    details={"finding_ids": [row["id"] for row in blocking_rows]},
                )
            latest_gate = connection.execute(
                "SELECT * FROM gates WHERE work_id=? AND kind='release.review' ORDER BY created_at DESC LIMIT 1",
                (work_id,),
            ).fetchone()
            if not latest_gate:
                raise DomainError("release_blocked", "请先运行全篇审查。", status=409, details={"reason": "release_review_missing"})
            gate_snapshot = json.loads(latest_gate["result_json"])
            current_scene_refs = []
            for scene in scenes:
                revision = connection.execute("SELECT content_hash FROM revisions WHERE id=?", (scene["current_revision_id"],)).fetchone()
                asset_references = self._scene_asset_reference_snapshot(
                    self._scene_asset_references(connection, work_id, scene["id"])
                )
                current_scene_refs.append({
                    "scene_id": scene["id"],
                    "revision_id": scene["current_revision_id"],
                    "content_hash": revision["content_hash"],
                    "asset_references": asset_references,
                    "asset_reference_digest": sha256_text(canonical_json(asset_references)),
                })
            current_memory_maintenance = self._memory_maintenance_snapshot(
                connection,
                work_id,
                [
                    {"scene_id": item["scene_id"], "revision_id": item["revision_id"]}
                    for item in current_scene_refs
                ],
            )
            current_dependency_refs = []
            for artifact in connection.execute(
                """SELECT kind,scope_type,scope_id,current_revision_id FROM artifacts
                   WHERE work_id=? AND kind IN ('brief','story_blueprint','work_canon','world_bible','character_card')
                     AND current_revision_id IS NOT NULL ORDER BY kind,scope_id""",
                (work_id,),
            ).fetchall():
                revision = connection.execute(
                    "SELECT content_hash FROM revisions WHERE id=?", (artifact["current_revision_id"],)
                ).fetchone()
                current_dependency_refs.append({
                    "kind": artifact["kind"],
                    "scope_type": artifact["scope_type"],
                    "scope_id": artifact["scope_id"],
                    "revision_id": artifact["current_revision_id"],
                    "content_hash": revision["content_hash"],
                })
            review_is_current = (
                latest_gate["status"] == "passed"
                and gate_snapshot.get("scene_revision_ids") == source_ids
                and gate_snapshot.get("scene_revision_refs") == current_scene_refs
                and gate_snapshot.get("dependency_refs") == current_dependency_refs
                and gate_snapshot.get("memory_maintenance") == current_memory_maintenance
                and gate_snapshot.get("writing_pack_version") == PACK_VERSION
                and gate_snapshot.get("ba_writing_source_digest")
                    == self._ba_writing_source_digest()
            )
            if not review_is_current:
                raise DomainError(
                    "release_blocked",
                    "全篇审查尚未通过，或正文修订已在审查后变更。",
                    status=409,
                    details={"gate_id": latest_gate["id"], "reason": "release_review_not_current"},
                )
            continuity_gate = connection.execute(
                "SELECT * FROM gates WHERE work_id=? AND kind='continuity.review' ORDER BY created_at DESC LIMIT 1",
                (work_id,),
            ).fetchone()
            if not continuity_gate:
                raise DomainError(
                    "release_blocked",
                    "请先运行跨场景连续性审查。",
                    status=409,
                    details={"reason": "continuity_review_missing"},
                )
            continuity_snapshot = json.loads(continuity_gate["result_json"])
            continuity_is_current = (
                continuity_gate["status"] == "passed"
                and continuity_snapshot.get("scene_revision_refs") == current_scene_refs
                and continuity_snapshot.get("dependency_refs") == current_dependency_refs
                and continuity_snapshot.get("writing_pack_version") == PACK_VERSION
                and continuity_snapshot.get("ba_writing_source_digest")
                    == self._ba_writing_source_digest()
            )
            if not continuity_is_current:
                raise DomainError(
                    "release_blocked",
                    "跨场景连续性审查尚未通过，或其依赖已发生变化。",
                    status=409,
                    details={"gate_id": continuity_gate["id"], "reason": "continuity_review_not_current"},
                )
            current_gate_ids = [continuity_gate["id"], latest_gate["id"]]
            release_id = new_id("release")
            chunks = []
            manifest_scenes = []
            manifest_asset_references = []
            for scene in scenes:
                revision = connection.execute("SELECT * FROM revisions WHERE id=?", (scene["current_revision_id"],)).fetchone()
                content = json.loads(self.repo.read_text(revision["content_uri"]))
                chunks.append(f"## {scene['title']}\n{content['text'].rstrip()}\n")
                manifest_scenes.append({"scene_id": scene["id"], "revision_id": revision["id"], "title": scene["title"], "content_hash": revision["content_hash"]})
                asset_references = self._scene_asset_reference_snapshot(
                    self._scene_asset_references(connection, work_id, scene["id"])
                )
                manifest_asset_references.append({
                    "scene_id": scene["id"],
                    "references": asset_references,
                    "digest": sha256_text(canonical_json(asset_references)),
                })
            release_text = "\n".join(chunks)
            content_uri, content_hash = self.repo.atomic_write_text(f"releases/{release_id}/script.txt", release_text)
            number = connection.execute("SELECT COUNT(*) FROM script_releases WHERE work_id=?", (work_id,)).fetchone()[0] + 1
            manifest = {
                "schema_version": "script-release/1.0", "release_id": release_id, "work_id": work_id,
                "display_version": f"v{number}", "content_hash": content_hash,
                "writing_pack_version": PACK_VERSION,
                "ba_writing_source_digest": self._ba_writing_source_digest(),
                "scenes": manifest_scenes,
                "asset_references": manifest_asset_references,
                "dependency_refs": current_dependency_refs,
                "memory_maintenance": current_memory_maintenance,
                "gate_snapshot_ids": current_gate_ids,
                "released_by": "user",
                "released_at": now(),
            }
            manifest["source_set_digest"] = source_set_digest(manifest)
            manifest_uri, _ = self.repo.atomic_write_text(f"releases/{release_id}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            connection.execute(
                "INSERT INTO script_releases VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (release_id, work_id, f"v{number}", manifest_uri, content_uri, content_hash, canonical_json(source_ids), canonical_json(current_gate_ids), PACK_VERSION, None, "user", manifest["released_at"]),
            )
            connection.execute("UPDATE scenes SET status='released', updated_at=? WHERE work_id=?", (now(), work_id))
            self._bump_work(connection, work_id, version)
        return {"release_id": release_id, "manifest": manifest, "work": self.get_work(work_id)}

    def _read_release_material(self, release: dict) -> tuple[dict, str]:
        verified = verify_script_release(self.repo, release)
        return verified["manifest"], verified["text"]

    def handoff_release(self, release_id: str):
        with self._release_handoff_lock:
            return self._handoff_release_locked(release_id)

    def production_asset_capabilities(self) -> dict:
        """Probe the production service without claiming that asset copies exist."""
        request = urllib.request.Request(self.production_url + "/api/v1/capabilities", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {
                    "schema_version": "production-asset-capabilities/1.0",
                    "status": "unsupported",
                    "capability": "scene_asset_handoff",
                    "reason": "capability_endpoint_missing",
                    "url": self.production_url,
                }
            return {
                "schema_version": "production-asset-capabilities/1.0",
                "status": "offline",
                "capability": "scene_asset_handoff",
                "reason": f"http_{exc.code}",
                "url": self.production_url,
            }
        except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {
                "schema_version": "production-asset-capabilities/1.0",
                "status": "offline",
                "capability": "scene_asset_handoff",
                "reason": str(exc),
                "url": self.production_url,
            }

        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        capabilities = data.get("capabilities", []) if isinstance(data, dict) else []
        marker = "scene_asset_handoff"
        supported = marker in capabilities
        capability_map = data.get("production_asset_handoff") if isinstance(data, dict) else None
        if isinstance(capability_map, dict):
            supported = supported or capability_map.get("supported") is True
        return {
            "schema_version": "production-asset-capabilities/1.0",
            "status": "supported" if supported else "unsupported",
            "capability": marker,
            "reason": None if supported else "production_service_does_not_advertise_scene_asset_handoff",
            "url": self.production_url,
            "upstream_schema_version": data.get("schema_version") if isinstance(data, dict) else None,
        }

    def production_asset_status(self, release_id: str) -> dict:
        with self.repo.connect() as connection:
            release = self.repo.row(connection.execute("SELECT * FROM script_releases WHERE id=?", (release_id,)).fetchone())
        if not release:
            raise NotFound("script_release", release_id)
        verified = verify_script_release(self.repo, release)
        manifest = verified["manifest"]
        expected = [
            (group.get("scene_id"), reference)
            for group in manifest.get("asset_references", [])
            for reference in group.get("references", [])
        ]
        expected_ids = [reference.get("reference_id") for _, reference in expected]
        with self.repo.connect() as connection:
            copied = connection.execute(
                "SELECT COUNT(*) FROM scene_asset_references WHERE work_id=? AND id IN ({}) AND production_copy_json IS NOT NULL".format(",".join("?" for _ in expected_ids)),
                [release["work_id"], *expected_ids],
            ).fetchone()[0]
        capability = self.production_asset_capabilities() if expected else {
            "schema_version": "production-asset-capabilities/1.0",
            "status": "not_required",
            "capability": "scene_asset_handoff",
            "reason": None,
            "url": self.production_url,
        }
        if not expected:
            status = "not_required"
        elif not release.get("production_run_id"):
            status = "not_handed_off"
        elif copied >= len(expected):
            status = "complete"
        else:
            status = "pending"
        return {
            "schema_version": "production-asset-status/1.0",
            "release_id": release_id,
            "production_run_id": release.get("production_run_id"),
            "status": status,
            "expected_count": len(expected),
            "copied_count": min(copied, len(expected)),
            "capability": capability,
        }

    def reconcile_production_asset_copies(self, release_id: str, usage: dict | None = None) -> dict:
        """Persist only an explicit, identity-matched ProductionRun asset receipt."""
        with self.repo.connect() as connection:
            release = self.repo.row(connection.execute("SELECT * FROM script_releases WHERE id=?", (release_id,)).fetchone())
        if not release:
            raise NotFound("script_release", release_id)
        verified = verify_script_release(self.repo, release)
        manifest = verified["manifest"]
        expected = {
            (group.get("scene_id"), reference.get("reference_id")): reference
            for group in manifest.get("asset_references", [])
            for reference in group.get("references", [])
        }
        if not expected:
            return {
                "schema_version": "production-asset-reconciliation/1.0",
                "status": "not_required",
                "release_id": release_id,
                "production_run_id": release.get("production_run_id"),
                "confirmed_count": 0,
                "expected_count": 0,
            }
        run_id = str(release.get("production_run_id") or "")
        if not run_id:
            raise DomainError("production_run_missing", "发布版本尚未关联 ProductionRun，无法接收素材副本回执。", status=409)
        fetched = usage is None
        if usage is None:
            request = urllib.request.Request(
                f"{self.production_url}/api/v1/production-runs/{run_id}/resource-usage", method="GET"
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    usage = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in {404, 501}:
                    usage = None
                else:
                    usage = None
            except (urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError):
                usage = None
        if not isinstance(usage, dict) or usage.get("schema_version") != "production-asset-usage/1.0":
            return {
                "schema_version": "production-asset-reconciliation/1.0",
                "status": "pending",
                "release_id": release_id,
                "production_run_id": run_id,
                "confirmed_count": 0,
                "expected_count": len(expected),
                "reason": "asset_usage_receipt_unavailable" if fetched else "asset_usage_receipt_contract_invalid",
            }
        if usage.get("production_run_id") != run_id:
            raise DomainError("production_asset_usage_mismatch", "素材回执所属 ProductionRun 与发布版本不一致。", status=409, details={"expected_production_run_id": run_id, "actual_production_run_id": usage.get("production_run_id")})
        receipts = usage.get("references")
        if not isinstance(receipts, list):
            raise DomainError("production_asset_usage_invalid", "素材回执缺少 references 数组。", status=409)
        updates = []
        seen = set()
        for receipt in receipts:
            if not isinstance(receipt, dict):
                raise DomainError("production_asset_usage_invalid", "素材回执条目格式无效。", status=409)
            key = (receipt.get("scene_id"), receipt.get("reference_id"))
            source = expected.get(key)
            if source is None or key in seen:
                raise DomainError("production_asset_usage_mismatch", "素材回执引用了未知或重复的场景素材。", status=409, details={"scene_id": key[0], "reference_id": key[1]})
            if any(receipt.get(field) != source.get(field) for field in ("source_asset_id", "source_version", "content_hash")):
                raise DomainError("production_asset_usage_mismatch", "素材回执的原件身份或 Hash 与发布快照不一致。", status=409, details={"scene_id": key[0], "reference_id": key[1]})
            copy = receipt.get("production_copy")
            if not isinstance(copy, dict) or not copy.get("copy_id") or not copy.get("content_hash"):
                raise DomainError("production_asset_usage_invalid", "素材回执缺少任务副本 ID 或 Hash。", status=409)
            seen.add(key)
            updates.append((key, copy))
        with self.repo.transaction() as connection:
            for (scene_id, reference_id), copy in updates:
                row = connection.execute(
                    "SELECT id, source_asset_id, source_version, content_hash FROM scene_asset_references WHERE work_id=? AND scene_id=? AND id=?",
                    (release["work_id"], scene_id, reference_id),
                ).fetchone()
                if not row or any(row[field] != expected[(scene_id, reference_id)].get(field) for field in ("source_asset_id", "source_version", "content_hash")):
                    raise DomainError("production_asset_usage_mismatch", "数据库中的场景素材已与发布快照不一致。", status=409, details={"scene_id": scene_id, "reference_id": reference_id})
                connection.execute(
                    "UPDATE scene_asset_references SET production_copy_json=?, updated_at=? WHERE id=?",
                    (canonical_json(copy), now(), reference_id),
                )
        expected_ids = list(expected)
        with self.repo.connect() as connection:
            confirmed_count = connection.execute(
                "SELECT COUNT(*) FROM scene_asset_references WHERE work_id=? AND id IN ({}) AND production_copy_json IS NOT NULL".format(",".join("?" for _ in expected_ids)),
                [release["work_id"], *[reference_id for _, reference_id in expected_ids]],
            ).fetchone()[0]
        status = "complete" if confirmed_count == len(expected) else "pending"
        return {
            "schema_version": "production-asset-reconciliation/1.0",
            "status": status,
            "release_id": release_id,
            "production_run_id": run_id,
            "confirmed_count": confirmed_count,
            "expected_count": len(expected),
        }

    def _handoff_release_locked(self, release_id: str):
        with self.repo.connect() as connection:
            release = self.repo.row(connection.execute("SELECT * FROM script_releases WHERE id=?", (release_id,)).fetchone())
            if not release:
                raise NotFound("script_release", release_id)
            verified_release = verify_script_release(self.repo, release)
            has_asset_references = any(
                group.get("references")
                for group in verified_release["manifest"].get("asset_references", [])
                if isinstance(group, dict)
            )
            if release["production_run_id"]:
                response = {"release_id": release_id, "production_run_id": release["production_run_id"], "idempotent": True}
                if has_asset_references:
                    response["asset_handoff"] = self.reconcile_production_asset_copies(release_id)
                return response
            work = connection.execute("SELECT title FROM works WHERE id=?", (release["work_id"],)).fetchone()
        project_name = f"{work['title']} · {release['display_version']}"
        contract_hash = release["content_hash"].removeprefix("sha256:")
        existing_run_id = self._find_production_run(release_id, contract_hash)
        if existing_run_id:
            with self.repo.transaction() as connection:
                connection.execute("UPDATE script_releases SET production_run_id=? WHERE id=?", (existing_run_id, release_id))
            response = {"release_id": release_id, "production_run_id": existing_run_id, "idempotent": True, "recovered": True}
            if has_asset_references:
                response["asset_handoff"] = self.reconcile_production_asset_copies(release_id)
            return response
        if has_asset_references:
            capability = self.production_asset_capabilities()
            if capability["status"] != "supported":
                code = "production_asset_handoff_unavailable" if capability["status"] == "offline" else "production_asset_handoff_unsupported"
                message = "AA 制作服务当前不可用，场景素材副本交接保持阻塞。" if capability["status"] == "offline" else "AA 制作服务未声明场景素材副本交接能力，系统不会把普通 ScriptRelease 交接冒充素材已消费。"
                raise DomainError(code, message, status=503 if capability["status"] == "offline" else 409, details={"capability": capability})
        handoff = build_production_handoff(verified_release, project_name)
        body = canonical_json(handoff).encode("utf-8")
        request = urllib.request.Request(self.production_url + "/api/v1/production-runs", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                upstream = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                upstream = {}
            error = upstream.get("error", {})
            raise DomainError(
                str(error.get("code") or "production_rejected"),
                str(error.get("message") or "AA 制作后端拒绝了这份发布版本。"),
                status=exc.code,
                details={"upstream": error.get("details", {}), "url": self.production_url},
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise DomainError("production_unavailable", "AA 制作后端当前不可用，发布版本仍安全保留。", status=503, details={"url": self.production_url, "reason": str(exc)}) from exc
        run_id = (
            result.get("run_id")
            or result.get("id")
            or result.get("run", {}).get("run_id")
            or result.get("production_run", {}).get("id")
        )
        if not run_id:
            raise DomainError("production_contract_error", "制作后端未返回 ProductionRun ID。", status=502, details={"response": result})
        with self.repo.transaction() as connection:
            connection.execute("UPDATE script_releases SET production_run_id=? WHERE id=?", (run_id, release_id))
        response = {"release_id": release_id, "production_run_id": run_id, "response": result}
        if has_asset_references:
            response["asset_handoff"] = self.reconcile_production_asset_copies(release_id)
        return response

    def _find_production_run(self, release_id: str, content_hash: str):
        request = urllib.request.Request(self.production_url + "/api/v1/production-runs", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return None
        for item in result.get("items", []):
            origin = item.get("source_summary", {}).get("upstream_release", {})
            if (
                origin.get("release_id") == release_id
                and origin.get("content_hash") == content_hash
                and item.get("run_id")
            ):
                return item["run_id"]
        return None

    def get_release(self, release_id: str):
        with self.repo.connect() as connection:
            release = self.repo.row(connection.execute("SELECT * FROM script_releases WHERE id=?", (release_id,)).fetchone())
            if not release:
                raise NotFound("script_release", release_id)
            release["manifest"], release["text"] = self._read_release_material(release)
            return release

    def writing_model_settings_public(self) -> dict:
        return self.model_settings.public()

    def configure_writing_model(self, payload: dict) -> dict:
        with self._provider_lock:
            result = self.model_settings.save(payload)
            self.provider = make_writing_provider(self.model_settings, self.ba_prompt_assembler)
        return result

    def activate_writing_model(self, payload: dict) -> dict:
        """Test and activate one exact candidate without exposing a half-applied state."""
        tested = self.model_settings.test_connection(payload)
        with self._provider_lock:
            result = self.model_settings.save(payload, connection_test=tested)
            self.provider = make_writing_provider(self.model_settings, self.ba_prompt_assembler)
        return {**result, "test": tested, "runtime": self.provider.descriptor()}

    def fetch_writing_models(self, payload: dict | None = None) -> list[str]:
        return self.model_settings.fetch_models(payload)

    def test_writing_model(self, payload: dict | None = None) -> dict:
        return self.model_settings.test_connection(payload)

    def user_preferences(self) -> dict:
        return {"ok": True, "preferences": self.preferences.load()}

    def save_user_preferences(self, payload: dict) -> dict:
        return {"ok": True, "preferences": self.preferences.save(payload)}

    def system_diagnostics(self) -> dict:
        provider_runtime = self.provider.descriptor()
        real_provider_ready = bool(provider_runtime.get("can_call_model")) and not bool(
            provider_runtime.get("is_simulation")
        )
        prod_health = False
        try:
            req = urllib.request.Request(self.production_url + "/api/v1/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                prod_health = (resp.status == 200)
        except Exception:
            pass

        corpus_count = 0
        if self.official_references.available:
            try:
                corpus_count = len(list(self.official_references.corpus_dir.glob("*.json")))
            except Exception:
                pass

        return {
            "ok": True,
            "writing_service": {
                "status": "online",
                "data_dir": str(self.repo.data_dir),
                "model_configured": self.model_settings.public()["model"]["configured"],
                "dpapi_available": os.name == "nt",
            },
            "real_provider_run": {
                "schema_version": "real-provider-run-readiness/1.0",
                "status": "ready" if real_provider_ready else "blocked",
                "blocking_reasons": [] if real_provider_ready else [{
                    "code": "real_provider_credentials_missing",
                    "message": "请先在设置中测试并激活一个真实写作模型。",
                }],
                "provider": provider_runtime,
                "acceptance_completed": False,
            },
            "production_service": {
                "status": "online" if prod_health else "offline",
                "url": self.production_url,
            },
            "corpus_status": {
                "available": self.official_references.available,
                "count": corpus_count,
            },
        }

    def export_writing_backup(self) -> tuple[str, bytes, dict]:
        with self._data_maintenance_lock:
            return WritingBackupManager(self.repo.data_dir).export()

    def inspect_writing_backup(self, payload: dict) -> dict:
        _, summary = WritingBackupManager(self.repo.data_dir).inspect_payload(payload)
        return summary

    def restore_writing_backup(self, payload: dict) -> dict:
        if payload.get("replace_all_works") is not True:
            raise DomainError(
                "backup_restore_confirmation_required",
                "恢复会替换当前全部作品，必须经过明确确认。",
                status=409,
            )
        with self._agent_threads_lock:
            active_runs = [run_id for run_id, thread in self._agent_threads.items() if thread.is_alive()]
        if active_runs:
            raise DomainError(
                "backup_restore_busy",
                "仍有 Agent 任务正在运行，请等待任务结束后再恢复备份。",
                status=409,
                details={"active_agent_run_ids": active_runs},
            )
        manager = WritingBackupManager(self.repo.data_dir)
        content, summary = manager.inspect_payload(payload)
        expected_hash = str(payload.get("expected_backup_hash") or "")
        if expected_hash != summary["backup_hash"]:
            raise DomainError("backup_changed", "备份内容与刚才预检的文件不一致，请重新选择。", status=409)
        with self._data_maintenance_lock:
            result = manager.restore(content, expected_hash)
            # Connections are short lived, so swapping the database is safe once
            # active Agent threads have drained. Recreate repository-owned runtime
            # material after the replacement.
            self.repo = Repository(self.repo.data_dir)
            self.ba_skill_pack = self.ba_skill.materialize(self.repo)
        return result
