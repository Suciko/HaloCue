from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


COMMIT_PROJECTION_KINDS = (
    "summary",
    "search",
    "memory_followup",
    "review_followup",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


class Repository:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir = self.data_dir / "artifacts"
        self.release_dir = self.data_dir / "releases"
        self.attachment_dir = self.data_dir / "attachments"
        self.artifact_dir.mkdir(exist_ok=True)
        self.release_dir.mkdir(exist_ok=True)
        self.attachment_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "writing.db"
        self._init_schema()
        self.recover_attempts()

    def connect(self):
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self):
        schema = """
        CREATE TABLE IF NOT EXISTS works (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
          version INTEGER NOT NULL, active_writing_pack_version TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS volumes (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          stable_order_key TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
          version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chapters (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          volume_id TEXT NOT NULL REFERENCES volumes(id),
          stable_order_key TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
          version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scenes (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          chapter_id TEXT NOT NULL REFERENCES chapters(id), stable_order_key TEXT NOT NULL,
          title TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
          current_revision_id TEXT, contract_json TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scene_asset_references (
          id TEXT PRIMARY KEY,
          work_id TEXT NOT NULL REFERENCES works(id),
          scene_id TEXT NOT NULL REFERENCES scenes(id),
          asset_kind TEXT NOT NULL CHECK(asset_kind IN ('background','character','sound','cg')),
          source_type TEXT NOT NULL CHECK(source_type IN ('resource_index','custom_library')),
          source_asset_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          source_version TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          content_hash_kind TEXT NOT NULL,
          source_snapshot_json TEXT NOT NULL,
          production_copy_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(scene_id, asset_kind, source_type, source_asset_id)
        );
        CREATE TABLE IF NOT EXISTS artifacts (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          kind TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
          current_revision_id TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS revisions (
          id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
          parent_revision_id TEXT, ordinal INTEGER NOT NULL, schema_version TEXT NOT NULL,
          content_uri TEXT NOT NULL, content_hash TEXT NOT NULL, provenance_json TEXT NOT NULL,
          created_by TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          kind TEXT NOT NULL DEFAULT 'scene_script',
          scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, base_revision_id TEXT,
          candidate_uri TEXT NOT NULL, candidate_hash TEXT NOT NULL, diff_json TEXT NOT NULL,
          evidence_json TEXT NOT NULL, risk TEXT NOT NULL, status TEXT NOT NULL,
          provider_json TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS production_runs (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          kind TEXT NOT NULL, automation_level TEXT NOT NULL, status TEXT NOT NULL,
          pinned_input_refs_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS work_items (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES production_runs(id),
          type TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
          status TEXT NOT NULL, input_refs_json TEXT NOT NULL, output_refs_json TEXT NOT NULL,
          acceptance_json TEXT NOT NULL, attempt_count INTEGER NOT NULL,
          error_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_attempts (
          id TEXT PRIMARY KEY, work_item_id TEXT NOT NULL REFERENCES work_items(id),
          ordinal INTEGER NOT NULL, provider TEXT NOT NULL, request_digest TEXT NOT NULL,
          status TEXT NOT NULL, output_ref TEXT, error_code TEXT,
          started_at TEXT NOT NULL, finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, instruction TEXT NOT NULL,
          status TEXT NOT NULL, policy_json TEXT NOT NULL, input_snapshot_uri TEXT NOT NULL,
          input_digest TEXT NOT NULL, proposal_id TEXT, failure_json TEXT,
          created_at TEXT NOT NULL, finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_tool_calls (
          id TEXT PRIMARY KEY, agent_run_id TEXT NOT NULL REFERENCES agent_runs(id),
          ordinal INTEGER NOT NULL, tool_name TEXT NOT NULL, status TEXT NOT NULL,
          input_digest TEXT NOT NULL, output_ref TEXT, error_json TEXT,
          created_at TEXT NOT NULL, finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS agent_dispatch_jobs (
          id TEXT PRIMARY KEY,
          agent_run_id TEXT REFERENCES agent_runs(id),
          work_item_id TEXT REFERENCES work_items(id),
          operation TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('ready','running','succeeded','failed','cancelled')),
          lease_owner TEXT,
          lease_token TEXT,
          lease_expires_at TEXT,
          available_at TEXT NOT NULL,
          cancel_requested_at TEXT,
          retry_of TEXT REFERENCES agent_dispatch_jobs(id),
          error_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_retry_requests (
          original_agent_run_id TEXT NOT NULL REFERENCES agent_runs(id),
          idempotency_key TEXT NOT NULL,
          claim_token TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')),
          new_agent_run_id TEXT REFERENCES agent_runs(id),
          result_json TEXT,
          error_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (original_agent_run_id,idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS commit_projections (
          id TEXT PRIMARY KEY,
          work_id TEXT NOT NULL REFERENCES works(id),
          revision_id TEXT NOT NULL UNIQUE REFERENCES revisions(id),
          status TEXT NOT NULL CHECK(status IN ('pending','running','completed','partial','failed')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          input_digest TEXT NOT NULL,
          output_ref TEXT,
          output_hash TEXT,
          error_json TEXT,
          decision_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS commit_projection_items (
          id TEXT PRIMARY KEY,
          projection_id TEXT NOT NULL REFERENCES commit_projections(id),
          kind TEXT NOT NULL CHECK(kind IN ('summary','search','memory_followup','review_followup')),
          status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed','skipped')),
          attempt_count INTEGER NOT NULL DEFAULT 0,
          input_digest TEXT NOT NULL,
          output_ref TEXT,
          output_hash TEXT,
          error_json TEXT,
          decision_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT,
          UNIQUE(projection_id,kind)
        );
        CREATE TABLE IF NOT EXISTS gates (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          kind TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
          status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS script_releases (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          display_version TEXT NOT NULL, manifest_uri TEXT NOT NULL, content_uri TEXT NOT NULL,
          content_hash TEXT NOT NULL, source_revision_ids_json TEXT NOT NULL,
          gate_snapshot_ids_json TEXT NOT NULL, writing_pack_version TEXT NOT NULL,
          production_run_id TEXT, released_by TEXT NOT NULL, released_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS decisions (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          kind TEXT NOT NULL, target_id TEXT NOT NULL, decision TEXT NOT NULL,
          note TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS staged_imports (
          import_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL CHECK(kind IN ('aap','story')),
          filename TEXT NOT NULL,
          source_digest TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('staged','adopted')),
          work_id TEXT REFERENCES works(id),
          result_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_threads (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, title TEXT NOT NULL,
          status TEXT NOT NULL, phase TEXT NOT NULL, permission_mode TEXT NOT NULL,
          version INTEGER NOT NULL, summary_json TEXT NOT NULL,
          archived_message_count INTEGER NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_messages (
          id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
          ordinal INTEGER NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL,
          content_json TEXT NOT NULL, status TEXT NOT NULL, provider_json TEXT,
          agent_run_id TEXT, proposal_id TEXT,
          input_tokens INTEGER, output_tokens INTEGER,
          cache_read_tokens INTEGER, cache_write_tokens INTEGER,
          estimated_cost REAL, created_at TEXT NOT NULL, archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS conversation_attachments (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
          message_id TEXT REFERENCES conversation_messages(id),
          filename TEXT NOT NULL, media_type TEXT NOT NULL, content_uri TEXT NOT NULL,
          content_hash TEXT NOT NULL, byte_size INTEGER NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS document_chunks (
          id TEXT PRIMARY KEY,
          attachment_id TEXT NOT NULL REFERENCES conversation_attachments(id),
          work_id TEXT NOT NULL REFERENCES works(id),
          thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
          ordinal INTEGER NOT NULL,
          paragraph_start INTEGER NOT NULL,
          paragraph_end INTEGER NOT NULL,
          content TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          search_terms_json TEXT NOT NULL,
          character_count INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS authorization_policies (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
          scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, mode TEXT NOT NULL,
          allowed_actions_json TEXT NOT NULL, max_turns INTEGER,
          max_cost REAL, expires_at TEXT, status TEXT NOT NULL,
          version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback_reports (
          id TEXT PRIMARY KEY, work_id TEXT REFERENCES works(id),
          category TEXT NOT NULL, summary TEXT NOT NULL, details TEXT NOT NULL,
          context_json TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'minor',
          error_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
          remote_status TEXT NOT NULL DEFAULT 'disabled', remote_id TEXT,
          remote_error TEXT, last_sync_at TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intent_plans (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
          idempotency_key TEXT NOT NULL UNIQUE, original_message TEXT NOT NULL,
          target_json TEXT NOT NULL, read_refs_json TEXT NOT NULL,
          actions_json TEXT NOT NULL, risk_level TEXT NOT NULL,
          requires_confirmation INTEGER NOT NULL, status TEXT NOT NULL,
          result_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          kind TEXT NOT NULL, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
          content TEXT NOT NULL, source_revision_id TEXT NOT NULL,
          confidence_status TEXT NOT NULL, version INTEGER NOT NULL,
          created_by TEXT NOT NULL, created_at TEXT NOT NULL, last_verified_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reference_files (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          title TEXT NOT NULL, kind TEXT NOT NULL, content_uri TEXT NOT NULL,
          content_hash TEXT NOT NULL, source_label TEXT NOT NULL,
          trust_status TEXT NOT NULL, version INTEGER NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_findings (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id),
          scene_id TEXT NOT NULL REFERENCES scenes(id), revision_id TEXT NOT NULL,
          scope_type TEXT NOT NULL DEFAULT 'scene', scope_id TEXT NOT NULL DEFAULT '',
          revision_refs_json TEXT NOT NULL DEFAULT '[]', agent_run_id TEXT,
          kind TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
          message TEXT NOT NULL, evidence_json TEXT NOT NULL,
          created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_volumes_work ON volumes(work_id, stable_order_key);
        CREATE INDEX IF NOT EXISTS idx_chapters_work ON chapters(work_id, stable_order_key);
        CREATE INDEX IF NOT EXISTS idx_scenes_chapter ON scenes(chapter_id, stable_order_key);
        CREATE INDEX IF NOT EXISTS idx_scene_asset_references_scene
          ON scene_asset_references(scene_id, asset_kind, created_at);
        CREATE INDEX IF NOT EXISTS idx_artifacts_scope ON artifacts(work_id, kind, scope_type, scope_id);
        CREATE INDEX IF NOT EXISTS idx_work_items_run ON work_items(run_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_work ON agent_runs(work_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_tool_calls_run ON agent_tool_calls(agent_run_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_agent_dispatch_claim ON agent_dispatch_jobs(status, available_at, created_at);
        CREATE INDEX IF NOT EXISTS idx_agent_dispatch_lease ON agent_dispatch_jobs(status, lease_expires_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_dispatch_active_run
          ON agent_dispatch_jobs(agent_run_id)
          WHERE agent_run_id IS NOT NULL AND status IN ('ready','running');
        CREATE INDEX IF NOT EXISTS idx_agent_retry_status
          ON agent_retry_requests(status,updated_at);
        CREATE INDEX IF NOT EXISTS idx_commit_projections_work
          ON commit_projections(work_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_commit_projection_items_status
          ON commit_projection_items(projection_id,status,kind);
        CREATE TRIGGER IF NOT EXISTS trg_cancel_agent_dispatch_job
        AFTER UPDATE OF status ON agent_runs
        WHEN NEW.status='cancelled' AND OLD.status<>NEW.status
        BEGIN
          UPDATE agent_dispatch_jobs
          SET status='cancelled',
              cancel_requested_at=COALESCE(NEW.finished_at, STRFTIME('%Y-%m-%dT%H:%M:%f+00:00','now')),
              lease_owner=NULL,
              lease_token=NULL,
              lease_expires_at=NULL,
              updated_at=COALESCE(NEW.finished_at, STRFTIME('%Y-%m-%dT%H:%M:%f+00:00','now'))
          WHERE agent_run_id=NEW.id AND status IN ('ready','running');
        END;
        CREATE INDEX IF NOT EXISTS idx_review_findings_scene ON review_findings(scene_id, revision_id, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_conversation_message_order ON conversation_messages(thread_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread ON conversation_messages(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_conversation_attachments_thread ON conversation_attachments(thread_id, created_at);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_document_chunks_attachment_order ON document_chunks(attachment_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_document_chunks_thread ON document_chunks(thread_id, attachment_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_authorization_thread ON authorization_policies(thread_id, status);
        CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback_reports(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_intent_plans_work ON intent_plans(work_id, created_at);
        """
        connection = self.connect()
        try:
            connection.executescript(schema)
            self._migrate_domain_schema(connection)
            connection.commit()
        finally:
            connection.close()

    def _migrate_domain_schema(self, connection):
        """Add durable writing-domain fields without replacing an existing workspace."""
        connection.execute("DROP INDEX IF EXISTS idx_conversation_scope")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_scope_lookup ON conversation_threads(work_id, scope_type, scope_id, updated_at)"
        )
        chapter_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(chapters)")
        }
        if "volume_id" not in chapter_columns:
            connection.execute(
                "ALTER TABLE chapters ADD COLUMN volume_id TEXT REFERENCES volumes(id)"
            )
        proposal_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(proposals)")
        }
        if "kind" not in proposal_columns:
            connection.execute(
                "ALTER TABLE proposals ADD COLUMN kind TEXT NOT NULL DEFAULT 'scene_script'"
            )
        finding_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(review_findings)")
        }
        for name, definition in {
            "scope_type": "TEXT NOT NULL DEFAULT 'scene'",
            "scope_id": "TEXT NOT NULL DEFAULT ''",
            "revision_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "agent_run_id": "TEXT",
        }.items():
            if name not in finding_columns:
                connection.execute(f"ALTER TABLE review_findings ADD COLUMN {name} {definition}")
        connection.execute(
            "UPDATE review_findings SET scope_id=scene_id WHERE scope_id='' OR scope_id IS NULL"
        )
        feedback_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(feedback_reports)")
        }
        for name, definition in {
            "severity": "TEXT NOT NULL DEFAULT 'minor'",
            "error_json": "TEXT NOT NULL DEFAULT '{}'",
            "remote_status": "TEXT NOT NULL DEFAULT 'disabled'",
            "remote_id": "TEXT",
            "remote_error": "TEXT",
            "last_sync_at": "TEXT",
        }.items():
            if name not in feedback_columns:
                connection.execute(f"ALTER TABLE feedback_reports ADD COLUMN {name} {definition}")
        memory_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(memories)")
        }
        for name, definition in {
            "artifact_id": "TEXT",
            "current_revision_id": "TEXT",
            "source_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "lifecycle_status": "TEXT NOT NULL DEFAULT 'active'",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if name not in memory_columns:
                connection.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
        connection.execute(
            "UPDATE memories SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_work_scope ON memories(work_id,lifecycle_status,confidence_status,scope_type,scope_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_chapters_volume ON chapters(volume_id, stable_order_key)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS document_chunks (
              id TEXT PRIMARY KEY,
              attachment_id TEXT NOT NULL REFERENCES conversation_attachments(id),
              work_id TEXT NOT NULL REFERENCES works(id),
              thread_id TEXT NOT NULL REFERENCES conversation_threads(id),
              ordinal INTEGER NOT NULL,
              paragraph_start INTEGER NOT NULL,
              paragraph_end INTEGER NOT NULL,
              content TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              search_terms_json TEXT NOT NULL,
              character_count INTEGER NOT NULL,
              created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_document_chunks_attachment_order ON document_chunks(attachment_id, ordinal)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_chunks_thread ON document_chunks(thread_id, attachment_id, ordinal)"
        )

        timestamp = now()
        for work in connection.execute("SELECT id FROM works").fetchall():
            volume = connection.execute(
                "SELECT id FROM volumes WHERE work_id=? ORDER BY stable_order_key LIMIT 1",
                (work["id"],),
            ).fetchone()
            if not volume:
                volume_id = new_id("volume")
                connection.execute(
                    "INSERT INTO volumes VALUES (?,?,?,?,?,?,?,?)",
                    (
                        volume_id,
                        work["id"],
                        "000001",
                        "第一卷",
                        "active",
                        1,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                volume_id = volume["id"]
            connection.execute(
                "UPDATE chapters SET volume_id=? WHERE work_id=? AND volume_id IS NULL",
                (volume_id, work["id"]),
            )
            thread = connection.execute(
                "SELECT id FROM conversation_threads WHERE work_id=? AND scope_type='work' AND scope_id=?",
                (work["id"], work["id"]),
            ).fetchone()
            if not thread:
                thread_id = new_id("thread")
                connection.execute(
                    "INSERT INTO conversation_threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        thread_id, work["id"], "work", work["id"], "创作主对话",
                        "active", "discuss", "review", 1, "{}", 0, timestamp, timestamp,
                    ),
                )
                connection.execute(
                    "INSERT INTO authorization_policies VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id("policy"), work["id"], thread_id, "work", work["id"],
                        "review", '["read","discuss"]', None, None, None,
                        "active", 1, timestamp, timestamp,
                    ),
                )

    def recover_attempts(self):
        # Durable dispatcher jobs have leases, so healthy work owned by another
        # process survives startup. Commit projections are synchronous legacy
        # work and have no owner lease; an interrupted running item is retryable.
        agent_work = self.recover_expired_agent_work()
        commit_projections = self.recover_commit_projection_items()
        return {
            "agent_work": agent_work,
            "commit_projections": commit_projections,
        }

    @staticmethod
    def _commit_projection_item_row(row):
        if not row:
            return None
        item = dict(row)
        error_json = item.pop("error_json")
        decision_json = item.pop("decision_json")
        item["error"] = json.loads(error_json) if error_json else None
        item["decision"] = json.loads(decision_json) if decision_json else None
        return item

    def _commit_projection_row(self, connection, row):
        if not row:
            return None
        projection = dict(row)
        projection["schema_version"] = "commit-projection/1.0"
        error_json = projection.pop("error_json")
        decision_json = projection.pop("decision_json")
        projection["error"] = json.loads(error_json) if error_json else None
        projection["decision"] = json.loads(decision_json) if decision_json else None
        projection["items"] = [
            self._commit_projection_item_row(item)
            for item in connection.execute(
                """SELECT * FROM commit_projection_items
                   WHERE projection_id=?
                   ORDER BY CASE kind
                     WHEN 'summary' THEN 1 WHEN 'search' THEN 2
                     WHEN 'memory_followup' THEN 3 ELSE 4 END""",
                (projection["id"],),
            ).fetchall()
        ]
        return projection

    def ensure_commit_projection(
        self,
        *,
        work_id: str,
        revision_id: str,
        input_digest: str | None = None,
    ) -> dict:
        """Idempotently register the four derived projections for a revision."""
        timestamp = now()
        with self.transaction() as connection:
            revision = connection.execute(
                """SELECT revision.content_hash
                   FROM revisions AS revision
                   JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                   WHERE revision.id=? AND artifact.work_id=?""",
                (revision_id, work_id),
            ).fetchone()
            if not revision:
                raise ValueError("revision does not belong to work")
            digest = str(input_digest or revision["content_hash"])
            existing = connection.execute(
                "SELECT * FROM commit_projections WHERE revision_id=?",
                (revision_id,),
            ).fetchone()
            if existing:
                if existing["work_id"] != work_id or existing["input_digest"] != digest:
                    raise ValueError("commit projection input does not match immutable revision")
                return self._commit_projection_row(connection, existing)

            projection_id = new_id("commit-projection")
            connection.execute(
                """INSERT INTO commit_projections
                   (id,work_id,revision_id,status,attempt_count,input_digest,
                    output_ref,output_hash,error_json,decision_json,
                    created_at,updated_at,finished_at)
                   VALUES (?,?,?,'pending',0,?,NULL,NULL,NULL,NULL,?,?,NULL)""",
                (projection_id, work_id, revision_id, digest, timestamp, timestamp),
            )
            for kind in COMMIT_PROJECTION_KINDS:
                connection.execute(
                    """INSERT INTO commit_projection_items
                       (id,projection_id,kind,status,attempt_count,input_digest,
                        output_ref,output_hash,error_json,decision_json,
                        created_at,updated_at,started_at,finished_at)
                       VALUES (?,?,?,'pending',0,?,NULL,NULL,NULL,NULL,?,?,NULL,NULL)""",
                    (new_id("projection-item"), projection_id, kind, digest, timestamp, timestamp),
                )
            row = connection.execute(
                "SELECT * FROM commit_projections WHERE id=?", (projection_id,)
            ).fetchone()
            return self._commit_projection_row(connection, row)

    def get_commit_projection(
        self,
        *,
        work_id: str,
        revision_id: str,
    ) -> dict | None:
        """Return a projection and decoded items, or None when not registered."""
        connection = self.connect()
        try:
            row = connection.execute(
                """SELECT * FROM commit_projections
                   WHERE work_id=? AND revision_id=?""",
                (work_id, revision_id),
            ).fetchone()
            return self._commit_projection_row(connection, row)
        finally:
            connection.close()

    def claim_commit_projection_item(
        self,
        *,
        projection_id: str,
        kind: str,
        allowed_statuses: tuple[str, ...] = ("pending",),
    ) -> dict:
        """Atomically start one item and return ``{claimed, item}``.

        Callers use ``('pending',)`` for normal projection and ``('failed',)``
        for an explicit retry. The returned attempt_count is the CAS generation
        that must be supplied when committing a provider result.
        """
        if kind not in COMMIT_PROJECTION_KINDS:
            raise ValueError("unsupported commit projection kind")
        allowed = tuple(dict.fromkeys(allowed_statuses))
        if not allowed or any(status not in {"pending", "failed"} for status in allowed):
            raise ValueError("allowed_statuses may contain only pending or failed")
        placeholders = ",".join("?" for _ in allowed)
        timestamp = now()
        with self.transaction() as connection:
            row = connection.execute(
                f"""SELECT * FROM commit_projection_items
                    WHERE projection_id=? AND kind=? AND status IN ({placeholders})""",
                (projection_id, kind, *allowed),
            ).fetchone()
            if not row:
                current = connection.execute(
                    """SELECT * FROM commit_projection_items
                       WHERE projection_id=? AND kind=?""",
                    (projection_id, kind),
                ).fetchone()
                return {"claimed": False, "item": self._commit_projection_item_row(current)}
            next_attempt = row["attempt_count"] + 1
            changed = connection.execute(
                f"""UPDATE commit_projection_items
                    SET status='running',attempt_count=?,error_json=NULL,decision_json=NULL,
                        started_at=?,finished_at=NULL,updated_at=?
                    WHERE id=? AND status IN ({placeholders})""",
                (next_attempt, timestamp, timestamp, row["id"], *allowed),
            ).rowcount
            if changed != 1:
                return {"claimed": False, "item": None}
            self._refresh_commit_projection(connection, projection_id, timestamp)
            claimed = connection.execute(
                "SELECT * FROM commit_projection_items WHERE id=?", (row["id"],)
            ).fetchone()
            return {"claimed": True, "item": self._commit_projection_item_row(claimed)}

    def complete_commit_projection_item(
        self,
        *,
        item_id: str,
        output_ref: str,
        output_hash: str,
        attempt_count: int | None = None,
    ) -> dict:
        """Commit an output only for the current running attempt."""
        if not output_ref or not output_hash:
            raise ValueError("output_ref and output_hash are required")
        return self._finish_commit_projection_item(
            item_id=item_id,
            status="done",
            output_ref=output_ref,
            output_hash=output_hash,
            error=None,
            decision=None,
            attempt_count=attempt_count,
        )

    def fail_commit_projection_item(
        self,
        *,
        item_id: str,
        error: dict,
        attempt_count: int | None = None,
    ) -> dict:
        """Persist a structured, retryable-or-terminal item failure."""
        if not isinstance(error, dict):
            raise ValueError("error must be a dict")
        return self._finish_commit_projection_item(
            item_id=item_id,
            status="failed",
            output_ref=None,
            output_hash=None,
            error=error,
            decision=None,
            attempt_count=attempt_count,
        )

    def skip_commit_projection_item(
        self,
        *,
        projection_id: str,
        kind: str,
        decision: dict,
    ) -> dict:
        """Audit an explicit skip without executing the provider."""
        if kind not in COMMIT_PROJECTION_KINDS:
            raise ValueError("unsupported commit projection kind")
        if not isinstance(decision, dict) or not decision:
            raise ValueError("decision must be a non-empty dict")
        timestamp = now()
        with self.transaction() as connection:
            changed = connection.execute(
                """UPDATE commit_projection_items
                   SET status='skipped',decision_json=?,error_json=NULL,
                       output_ref=NULL,output_hash=NULL,finished_at=?,updated_at=?
                   WHERE projection_id=? AND kind=? AND status IN ('pending','failed')""",
                (
                    canonical_json(decision),
                    timestamp,
                    timestamp,
                    projection_id,
                    kind,
                ),
            ).rowcount
            self._refresh_commit_projection(connection, projection_id, timestamp)
            row = connection.execute(
                """SELECT * FROM commit_projection_items
                   WHERE projection_id=? AND kind=?""",
                (projection_id, kind),
            ).fetchone()
            return {"applied": changed == 1, "item": self._commit_projection_item_row(row)}

    def _finish_commit_projection_item(
        self,
        *,
        item_id: str,
        status: str,
        output_ref: str | None,
        output_hash: str | None,
        error: dict | None,
        decision: dict | None,
        attempt_count: int | None,
    ) -> dict:
        timestamp = now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT projection_id FROM commit_projection_items WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                return {"applied": False, "item": None}
            attempt_clause = "" if attempt_count is None else " AND attempt_count=?"
            parameters = [
                status,
                output_ref,
                output_hash,
                canonical_json(error) if error else None,
                canonical_json(decision) if decision else None,
                timestamp,
                timestamp,
                item_id,
            ]
            if attempt_count is not None:
                parameters.append(attempt_count)
            changed = connection.execute(
                f"""UPDATE commit_projection_items
                    SET status=?,output_ref=?,output_hash=?,error_json=?,decision_json=?,
                        finished_at=?,updated_at=?
                    WHERE id=? AND status='running'{attempt_clause}""",
                parameters,
            ).rowcount
            self._refresh_commit_projection(connection, row["projection_id"], timestamp)
            current = connection.execute(
                "SELECT * FROM commit_projection_items WHERE id=?", (item_id,)
            ).fetchone()
            return {"applied": changed == 1, "item": self._commit_projection_item_row(current)}

    def _refresh_commit_projection(self, connection, projection_id: str, timestamp: str):
        rows = connection.execute(
            "SELECT kind,status,attempt_count FROM commit_projection_items WHERE projection_id=?",
            (projection_id,),
        ).fetchall()
        if not rows:
            return
        statuses = [row["status"] for row in rows]
        if "running" in statuses:
            status = "running"
        elif all(item in {"done", "skipped"} for item in statuses):
            status = "completed"
        elif "failed" in statuses:
            status = "failed" if all(item == "failed" for item in statuses) else "partial"
        else:
            status = "pending"
        failed_kinds = [row["kind"] for row in rows if row["status"] == "failed"]
        skipped_kinds = [row["kind"] for row in rows if row["status"] == "skipped"]
        terminal = all(item in {"done", "failed", "skipped"} for item in statuses)
        connection.execute(
            """UPDATE commit_projections
               SET status=?,attempt_count=?,error_json=?,decision_json=?,
                   updated_at=?,finished_at=? WHERE id=?""",
            (
                status,
                sum(row["attempt_count"] for row in rows),
                canonical_json({"failed_kinds": failed_kinds}) if failed_kinds else None,
                canonical_json({"skipped_kinds": skipped_kinds}) if skipped_kinds else None,
                timestamp,
                timestamp if terminal else None,
                projection_id,
            ),
        )

    def recover_commit_projection_items(self) -> dict:
        """Fail interrupted item attempts so an explicit retry can replay them."""
        timestamp = now()
        error = canonical_json({
            "code": "process_restarted",
            "message": "服务重启中断了提交后投影；正文修订未受影响，可安全重试该投影项。",
            "retryable": True,
        })
        with self.transaction() as connection:
            projection_ids = [
                row["projection_id"]
                for row in connection.execute(
                    """SELECT DISTINCT projection_id FROM commit_projection_items
                       WHERE status='running'"""
                ).fetchall()
            ]
            changed = connection.execute(
                """UPDATE commit_projection_items
                   SET status='failed',error_json=?,finished_at=?,updated_at=?
                   WHERE status='running'""",
                (error, timestamp, timestamp),
            ).rowcount
            for projection_id in projection_ids:
                self._refresh_commit_projection(connection, projection_id, timestamp)
        return {"recovered_count": changed, "recovered_at": timestamp}

    @staticmethod
    def _agent_work_row(row):
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item["payload_json"] or "{}")
        item["error"] = json.loads(item["error_json"]) if item.get("error_json") else None
        return item

    def enqueue_agent_work(
        self,
        *,
        operation: str,
        payload: dict | None = None,
        agent_run_id: str | None = None,
        work_item_id: str | None = None,
        available_at: str | None = None,
        retry_of: str | None = None,
        dedupe_by_payload: bool = False,
    ) -> dict:
        """Persist one ready job and return ``{created, job}``.

        An active ``agent_run_id`` is an idempotency key. Concurrent enqueues for
        the same run return the existing ready/running job instead of dispatching
        the provider twice.
        """
        operation = str(operation or "").strip()
        if not operation:
            raise ValueError("operation is required")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        timestamp = now()
        job_id = new_id("agent-job")
        payload_json = canonical_json(payload or {})
        with self.transaction() as connection:
            if agent_run_id:
                existing = connection.execute(
                    """SELECT * FROM agent_dispatch_jobs
                       WHERE agent_run_id=? AND status IN ('ready','running')
                       ORDER BY created_at LIMIT 1""",
                    (agent_run_id,),
                ).fetchone()
                if existing:
                    return {"created": False, "job": self._agent_work_row(existing)}
            if dedupe_by_payload:
                existing = connection.execute(
                    """SELECT * FROM agent_dispatch_jobs
                       WHERE operation=? AND payload_json=? AND status IN ('ready','running')
                       ORDER BY created_at LIMIT 1""",
                    (operation, payload_json),
                ).fetchone()
                if existing:
                    return {"created": False, "job": self._agent_work_row(existing)}
            try:
                connection.execute(
                    """INSERT INTO agent_dispatch_jobs
                       (id,agent_run_id,work_item_id,operation,payload_json,status,
                        lease_owner,lease_token,lease_expires_at,available_at,
                        cancel_requested_at,retry_of,error_json,created_at,updated_at)
                       VALUES (?,?,?,?,?,'ready',NULL,NULL,NULL,?,NULL,?,NULL,?,?)""",
                    (
                        job_id,
                        agent_run_id,
                        work_item_id,
                        operation,
                        payload_json,
                        available_at or timestamp,
                        retry_of,
                        timestamp,
                        timestamp,
                    ),
                )
            except sqlite3.IntegrityError:
                if not agent_run_id:
                    raise
                existing = connection.execute(
                    """SELECT * FROM agent_dispatch_jobs
                       WHERE agent_run_id=? AND status IN ('ready','running')
                       ORDER BY created_at LIMIT 1""",
                    (agent_run_id,),
                ).fetchone()
                if not existing:
                    raise
                return {"created": False, "job": self._agent_work_row(existing)}
            row = connection.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return {"created": True, "job": self._agent_work_row(row)}

    def claim_agent_work(self, *, lease_owner: str, lease_seconds: float = 30) -> dict:
        """Atomically claim the oldest available job; return ``{claimed, job}``."""
        lease_owner = str(lease_owner or "").strip()
        if not lease_owner:
            raise ValueError("lease_owner is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        lease_token = uuid.uuid4().hex
        with self.transaction() as connection:
            row = connection.execute(
                """SELECT id FROM agent_dispatch_jobs
                   WHERE status='ready' AND cancel_requested_at IS NULL AND available_at<=?
                   ORDER BY available_at,created_at,id LIMIT 1""",
                (timestamp,),
            ).fetchone()
            if not row:
                return {"claimed": False, "job": None}
            changed = connection.execute(
                """UPDATE agent_dispatch_jobs
                   SET status='running',lease_owner=?,lease_token=?,lease_expires_at=?,updated_at=?
                   WHERE id=? AND status='ready' AND cancel_requested_at IS NULL""",
                (lease_owner, lease_token, expires_at, timestamp, row["id"]),
            ).rowcount
            if changed != 1:
                return {"claimed": False, "job": None}
            claimed = connection.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE id=?", (row["id"],)
            ).fetchone()
            return {"claimed": True, "job": self._agent_work_row(claimed)}

    def heartbeat_agent_work(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_token: str,
        lease_seconds: float = 30,
    ) -> dict:
        """Extend a live lease and return ``{applied, job}``."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = now()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        with self.transaction() as connection:
            changed = connection.execute(
                """UPDATE agent_dispatch_jobs SET lease_expires_at=?,updated_at=?
                   WHERE id=? AND status='running' AND lease_owner=? AND lease_token=?
                     AND lease_expires_at>? AND cancel_requested_at IS NULL""",
                (expires_at, timestamp, job_id, lease_owner, lease_token, timestamp),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return {"applied": changed == 1, "job": self._agent_work_row(row)}

    def bind_agent_work_run(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_token: str,
        agent_run_id: str,
    ) -> dict:
        """Attach the durable AgentRun created while a leased job starts."""
        timestamp = now()
        with self.transaction() as connection:
            changed = connection.execute(
                """UPDATE agent_dispatch_jobs SET agent_run_id=?,updated_at=?
                   WHERE id=? AND status='running' AND lease_owner=? AND lease_token=?
                     AND cancel_requested_at IS NULL
                     AND (agent_run_id IS NULL OR agent_run_id=?)""",
                (
                    agent_run_id,
                    timestamp,
                    job_id,
                    lease_owner,
                    lease_token,
                    agent_run_id,
                ),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return {"applied": changed == 1, "job": self._agent_work_row(row)}

    def complete_agent_work(
        self, *, job_id: str, lease_owner: str, lease_token: str
    ) -> dict:
        """CAS a leased job to succeeded; stale workers get ``applied=False``."""
        return self._finish_agent_work(
            job_id=job_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            status="succeeded",
            error=None,
        )

    def fail_agent_work(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_token: str,
        error: dict,
    ) -> dict:
        """CAS a leased job to failed and persist its structured error."""
        if not isinstance(error, dict):
            raise ValueError("error must be a dict")
        return self._finish_agent_work(
            job_id=job_id,
            lease_owner=lease_owner,
            lease_token=lease_token,
            status="failed",
            error=error,
        )

    def _finish_agent_work(
        self,
        *,
        job_id: str,
        lease_owner: str,
        lease_token: str,
        status: str,
        error: dict | None,
    ) -> dict:
        timestamp = now()
        with self.transaction() as connection:
            changed = connection.execute(
                """UPDATE agent_dispatch_jobs
                   SET status=?,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                       error_json=?,updated_at=?
                   WHERE id=? AND status='running' AND lease_owner=? AND lease_token=?
                     AND lease_expires_at>? AND cancel_requested_at IS NULL""",
                (
                    status,
                    canonical_json(error) if error else None,
                    timestamp,
                    job_id,
                    lease_owner,
                    lease_token,
                    timestamp,
                ),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM agent_dispatch_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return {"applied": changed == 1, "job": self._agent_work_row(row)}

    def cancel_agent_work(
        self, *, job_id: str | None = None, agent_run_id: str | None = None
    ) -> dict:
        """Cancel one job (or the active job for an AgentRun) and revoke its lease."""
        if not job_id and not agent_run_id:
            raise ValueError("job_id or agent_run_id is required")
        timestamp = now()
        field = "id" if job_id else "agent_run_id"
        value = job_id or agent_run_id
        with self.transaction() as connection:
            changed = connection.execute(
                f"""UPDATE agent_dispatch_jobs
                    SET status='cancelled',cancel_requested_at=?,lease_owner=NULL,
                        lease_token=NULL,lease_expires_at=NULL,updated_at=?
                    WHERE {field}=? AND status IN ('ready','running')""",
                (timestamp, timestamp, value),
            ).rowcount
            row = connection.execute(
                f"SELECT * FROM agent_dispatch_jobs WHERE {field}=? ORDER BY created_at DESC LIMIT 1",
                (value,),
            ).fetchone()
            return {"applied": changed > 0, "cancelled_count": changed, "job": self._agent_work_row(row)}

    def recover_expired_agent_work(self) -> dict:
        """Recover unstarted jobs; close interrupted bound runs for explicit retry."""
        timestamp = now()
        retry_error = canonical_json({
            "code": "lease_expired",
            "message": "工作进程租约已过期，任务将从固定输入恢复。",
            "retryable": True,
        })
        interrupted_error = canonical_json({
            "code": "agent_process_interrupted",
            "message": "服务在模型运行期间中断；迟到结果不会写入，请从固定输入明确重试。",
            "retryable": True,
        })
        resumable_bound_operations = {
            "conversation.message",
            "scene.candidate.generate",
            "scene.draft.generate",
            "scene.draft.rewrite",
            "scene.review",
            "continuity.review",
            "release.review",
            "memory.extract",
            "memory.sweep",
            "knowledge.discover",
        }
        with self.transaction() as connection:
            expired = connection.execute(
                """SELECT id,agent_run_id,operation FROM agent_dispatch_jobs
                   WHERE status='running' AND lease_expires_at IS NOT NULL
                     AND lease_expires_at<=? AND cancel_requested_at IS NULL""",
                (timestamp,),
            ).fetchall()
            interrupted = [
                row for row in expired
                if row["agent_run_id"] and row["operation"] in resumable_bound_operations
            ]
            interrupted_ids = [row["id"] for row in interrupted]
            interrupted_run_ids = [row["agent_run_id"] for row in interrupted]
            for job_id, run_id in zip(interrupted_ids, interrupted_run_ids):
                connection.execute(
                    """UPDATE agent_dispatch_jobs
                       SET status='failed',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                           error_json=?,updated_at=? WHERE id=? AND status='running'""",
                    (interrupted_error, timestamp, job_id),
                )
                connection.execute(
                    """UPDATE agent_runs SET status='failed',failure_json=?,finished_at=?
                       WHERE id=? AND status IN ('queued','running')""",
                    (interrupted_error, timestamp, run_id),
                )
                linked_items = connection.execute(
                    "SELECT id,run_id FROM work_items WHERE acceptance_json LIKE ?",
                    (f'%\"agent_run_id\":\"{run_id}\"%',),
                ).fetchall()
                for item in linked_items:
                    connection.execute(
                        """UPDATE job_attempts SET status='failed',error_code='agent_process_interrupted',finished_at=?
                           WHERE work_item_id=? AND status IN ('queued','started','running')""",
                        (timestamp, item["id"]),
                    )
                    connection.execute(
                        """UPDATE work_items SET status='failed',error_json=?,updated_at=?
                           WHERE id=? AND status IN ('ready','queued','running')""",
                        (interrupted_error, timestamp, item["id"]),
                    )
                    connection.execute(
                        "UPDATE production_runs SET status='failed',updated_at=? WHERE id=? AND status='running'",
                        (timestamp, item["run_id"]),
                    )
            requeued = connection.execute(
                """UPDATE agent_dispatch_jobs
                   SET status='ready',lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                       available_at=?,error_json=?,updated_at=?
                   WHERE status='running' AND lease_expires_at IS NOT NULL
                     AND lease_expires_at<=? AND cancel_requested_at IS NULL""",
                (timestamp, retry_error, timestamp, timestamp),
            ).rowcount
        return {
            "recovered_count": requeued + len(interrupted_ids),
            "requeued_count": requeued,
            "interrupted_count": len(interrupted_ids),
            "interrupted_agent_run_ids": interrupted_run_ids,
            "recovered_at": timestamp,
        }

    # Compatibility aliases used while the service layer migrates to the
    # operation/payload queue contract.
    def enqueue_agent_job(self, *, agent_run_id: str, work_item_id: str | None = None, operation: str = "agent.run", payload: dict | None = None):
        return self.enqueue_agent_work(
            operation=operation,
            payload=payload,
            agent_run_id=agent_run_id,
            work_item_id=work_item_id,
        )["job"]

    def claim_agent_job(self, *, worker_id: str, lease_seconds: float = 30):
        return self.claim_agent_work(
            lease_owner=worker_id, lease_seconds=lease_seconds
        )["job"]

    def heartbeat_agent_job(self, *, job_id: str, worker_id: str, lease_token: str, lease_seconds: float = 30):
        return self.heartbeat_agent_work(
            job_id=job_id,
            lease_owner=worker_id,
            lease_token=lease_token,
            lease_seconds=lease_seconds,
        )["applied"]

    def complete_agent_job(self, *, job_id: str, worker_id: str, lease_token: str):
        return self.complete_agent_work(
            job_id=job_id, lease_owner=worker_id, lease_token=lease_token
        )["applied"]

    def fail_agent_job(self, *, job_id: str, worker_id: str, lease_token: str, error: dict):
        return self.fail_agent_work(
            job_id=job_id,
            lease_owner=worker_id,
            lease_token=lease_token,
            error=error,
        )["applied"]

    def cancel_agent_job(self, *, job_id: str | None = None, agent_run_id: str | None = None):
        return self.cancel_agent_work(job_id=job_id, agent_run_id=agent_run_id)["applied"]

    def recover_expired_agent_jobs(self):
        return self.recover_expired_agent_work()["recovered_count"]

    def claim_agent_retry(self, *, original_run_id: str, idempotency_key: str) -> dict:
        """Claim one logical retry or return its existing durable state."""
        original_run_id = str(original_run_id or "").strip()
        idempotency_key = str(idempotency_key or "").strip()
        if not original_run_id or not idempotency_key:
            raise ValueError("original_run_id and idempotency_key are required")
        token = uuid.uuid4().hex
        timestamp = now()
        with self.transaction() as connection:
            row = connection.execute(
                """SELECT * FROM agent_retry_requests
                   WHERE original_agent_run_id=? AND idempotency_key=?""",
                (original_run_id, idempotency_key),
            ).fetchone()
            if row:
                return {"claimed": False, "request": dict(row)}
            connection.execute(
                """INSERT INTO agent_retry_requests
                   (original_agent_run_id,idempotency_key,claim_token,status,
                    new_agent_run_id,result_json,error_json,created_at,updated_at)
                   VALUES (?,?,?,'running',NULL,NULL,NULL,?,?)""",
                (original_run_id, idempotency_key, token, timestamp, timestamp),
            )
            row = connection.execute(
                """SELECT * FROM agent_retry_requests
                   WHERE original_agent_run_id=? AND idempotency_key=?""",
                (original_run_id, idempotency_key),
            ).fetchone()
            return {"claimed": True, "request": dict(row)}

    def get_agent_retry(self, *, original_run_id: str, idempotency_key: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT * FROM agent_retry_requests
                   WHERE original_agent_run_id=? AND idempotency_key=?""",
                (original_run_id, idempotency_key),
            ).fetchone()
        return dict(row) if row else None

    def complete_agent_retry(
        self,
        *,
        original_run_id: str,
        idempotency_key: str,
        claim_token: str,
        new_run_id: str,
        result: dict,
    ) -> bool:
        with self.transaction() as connection:
            changed = connection.execute(
                """UPDATE agent_retry_requests
                   SET status='succeeded',new_agent_run_id=?,result_json=?,updated_at=?
                   WHERE original_agent_run_id=? AND idempotency_key=?
                     AND claim_token=? AND status='running'""",
                (
                    new_run_id,
                    canonical_json(result),
                    now(),
                    original_run_id,
                    idempotency_key,
                    claim_token,
                ),
            ).rowcount
        return changed == 1

    def fail_agent_retry(
        self,
        *,
        original_run_id: str,
        idempotency_key: str,
        claim_token: str,
        error: dict,
    ) -> bool:
        with self.transaction() as connection:
            changed = connection.execute(
                """UPDATE agent_retry_requests
                   SET status='failed',error_json=?,updated_at=?
                   WHERE original_agent_run_id=? AND idempotency_key=?
                     AND claim_token=? AND status='running'""",
                (
                    canonical_json(error),
                    now(),
                    original_run_id,
                    idempotency_key,
                    claim_token,
                ),
            ).rowcount
        return changed == 1

    def atomic_write_bytes(self, relative: str, content: bytes) -> tuple[str, str]:
        target = (self.data_dir / relative).resolve()
        if self.data_dir not in target.parents:
            raise ValueError("path escapes data directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, target)
        return str(target.relative_to(self.data_dir)).replace("\\", "/"), sha256_bytes(content)

    def atomic_write_text(self, relative_uri: str, content: str) -> tuple[str, str]:
        target = (self.data_dir / relative_uri).resolve()
        if self.data_dir not in target.parents:
            raise ValueError("Artifact path escaped data directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return relative_uri.replace("\\", "/"), sha256_text(content)

    def read_text(self, uri: str) -> str:
        path = (self.data_dir / uri).resolve()
        if self.data_dir not in path.parents:
            raise ValueError("Artifact path escaped data directory")
        return path.read_text(encoding="utf-8")

    @staticmethod
    def rows(rows):
        return [dict(row) for row in rows]

    @staticmethod
    def row(row):
        return dict(row) if row else None
