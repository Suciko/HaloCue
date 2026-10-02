"""Durable physical request observations; no prompts, response bodies or secrets."""

from contextlib import closing
import json
import re
import sqlite3

from .errors import DomainError, NotFound
from .provider_usage import normalize_usage, merge_usage
from .repository import canonical_json, now
from .workspace_access import workspace_operation

SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_requests (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id),
 logical_id TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>0),
 provider_json TEXT NOT NULL, status TEXT NOT NULL, usage_json TEXT NOT NULL,
 error_code TEXT, started_at TEXT NOT NULL, finished_at TEXT,
 UNIQUE(run_id,logical_id,ordinal)
);
CREATE INDEX IF NOT EXISTS provider_requests_run ON provider_requests(run_id,started_at,id);
"""


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", value):
        raise DomainError("request_observation_invalid", "请求记录标识无效。", status=500)
    return value


def _provider(value):
    value = value if isinstance(value, dict) else {}
    return {
        key: str(value[key])[:256]
        for key in ("kind", "provider", "model", "config_digest", "config_revision")
        if key in value
    }


class RequestLedger:
    def __init__(self, repository):
        self.repo = repository
        self.data_access = repository.data_access

    @workspace_operation
    def observe(self, run_id, event):
        request_id = _identifier(event.get("id"))
        phase = event.get("phase")
        with self.repo.transaction() as c:
            if not c.execute("SELECT id FROM agent_runs WHERE id=?", (run_id,)).fetchone():
                raise NotFound("agent_run", run_id)
            old = c.execute("SELECT * FROM provider_requests WHERE id=?", (request_id,)).fetchone()
            if phase == "started":
                logical_id = _identifier(event.get("logical_id"))
                ordinal = event.get("ordinal")
                if type(ordinal) is not int or ordinal < 1:
                    raise DomainError("request_observation_invalid", "请求序号无效。", status=500)
                provider = canonical_json(_provider(event.get("provider")))
                if old:
                    if (old["run_id"], old["logical_id"], old["ordinal"], old["provider_json"]) != (
                        run_id,
                        logical_id,
                        ordinal,
                        provider,
                    ):
                        raise DomainError(
                            "request_observation_conflict", "请求记录身份冲突。", status=409
                        )
                    return
                c.execute(
                    "INSERT INTO provider_requests VALUES (?,?,?,?,?,'dispatched',?,NULL,?,NULL)",
                    (
                        request_id,
                        run_id,
                        logical_id,
                        ordinal,
                        provider,
                        canonical_json(normalize_usage({})),
                        now(),
                    ),
                )
            elif phase == "finished":
                if not old or old["run_id"] != run_id:
                    raise DomainError(
                        "request_observation_missing", "请求开始记录不存在。", status=409
                    )
                status = event.get("status")
                if status not in {"succeeded", "failed", "rejected"}:
                    raise DomainError(
                        "request_observation_invalid", "请求结束状态无效。", status=500
                    )
                usage = canonical_json(normalize_usage(event.get("usage")))
                code = event.get("error_code")
                code = (
                    code
                    if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", code)
                    else None
                )
                if old["status"] not in {"dispatched", "interrupted"}:
                    if (old["status"], old["usage_json"], old["error_code"]) != (
                        status,
                        usage,
                        code,
                    ):
                        raise DomainError(
                            "request_observation_conflict", "请求结束记录冲突。", status=409
                        )
                    return
                c.execute(
                    "UPDATE provider_requests SET status=?,usage_json=?,error_code=?,finished_at=? WHERE id=?",
                    (status, usage, code, now(), request_id),
                )
            else:
                raise DomainError("request_observation_invalid", "请求记录阶段无效。", status=500)

    def recover_pending(self):
        with closing(self.repo.connect()) as c:
            runs = c.execute(
                "SELECT id,policy_json FROM agent_runs WHERE policy_json LIKE '%pending_request_records%'"
            ).fetchall()
        for run in runs:
            pending = json.loads(run["policy_json"]).get("pending_request_records") or {}
            for ident, terminal in pending.items():
                try:
                    self.observe(run["id"], terminal)
                except (DomainError, OSError, sqlite3.OperationalError):
                    continue
                with self.repo.transaction() as c:
                    row = c.execute(
                        "SELECT policy_json FROM agent_runs WHERE id=?", (run["id"],)
                    ).fetchone()
                    policy = json.loads(row["policy_json"])
                    if policy.get("pending_request_records", {}).get(ident) == terminal:
                        del policy["pending_request_records"][ident]
                        if not policy["pending_request_records"]:
                            policy.pop("pending_request_records")
                        c.execute(
                            "UPDATE agent_runs SET policy_json=? WHERE id=?",
                            (canonical_json(policy), run["id"]),
                        )

    @workspace_operation
    def recover_interrupted(self):
        self.recover_pending()
        with self.repo.transaction() as c:
            return c.execute(
                """UPDATE provider_requests SET status='interrupted',finished_at=?
                WHERE status='dispatched' AND run_id IN (
                  SELECT id FROM agent_runs WHERE status NOT IN ('queued','running'))""",
                (now(),),
            ).rowcount

    @staticmethod
    def summarize(rows, pending=None):
        pending = pending if isinstance(pending, dict) else {}
        observations = []
        pending_count = 0
        for row in rows:
            receipt = pending.get(row["id"]) or {}
            provisional = (
                row["status"] in {"dispatched", "interrupted"}
                and receipt.get("phase") == "finished"
                and receipt.get("id") == row["id"]
            )
            observations.append(
                normalize_usage(receipt.get("usage"))
                if provisional
                else json.loads(row["usage_json"])
            )
            pending_count += bool(provisional)
        total = {}
        for usage in observations:
            total = merge_usage(total, usage)
        return {
            "physical_request_count": len(rows),
            "logical_request_count": len({r["logical_id"] for r in rows}),
            "unknown_usage_count": sum(
                usage.get("usage_status") != "reported" for usage in observations
            ),
            "pending_count": sum(r["status"] == "dispatched" for r in rows),
            "pending_receipt_count": pending_count,
            "interrupted_count": sum(r["status"] == "interrupted" for r in rows),
            "totals": normalize_usage(total),
            "accounting_scope": "observed_codex_turns" if rows and all(
                "provider_json" in row.keys() and json.loads(row["provider_json"]).get("provider") == "codex" for row in rows
            ) else "observed_writing_http_attempts",
        }

    def summaries(self, connection, work_id):
        rows = connection.execute(
            "SELECT p.*,a.policy_json FROM provider_requests p JOIN agent_runs a ON a.id=p.run_id WHERE a.work_id=? ORDER BY p.started_at,p.ordinal,p.id",
            (work_id,),
        ).fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row["run_id"], []).append(row)
        return {
            run_id: self.summarize(
                items, json.loads(items[0]["policy_json"]).get("pending_request_records")
            )
            for run_id, items in grouped.items()
        }

    @workspace_operation
    def for_run(self, work_id, run_id, *, limit=100, after_id=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DomainError("request_page_invalid", "请求记录分页大小需为1到100。", status=400)
        if after_id is not None and (
            not isinstance(after_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", after_id)
        ):
            raise DomainError("request_page_invalid", "请求记录分页标识无效。", status=400)
        with closing(self.repo.connect()) as c:
            if not c.execute(
                "SELECT id FROM agent_runs WHERE id=? AND work_id=?", (run_id, work_id)
            ).fetchone():
                raise NotFound("agent_run", run_id)
            policy = c.execute(
                "SELECT policy_json FROM agent_runs WHERE id=?", (run_id,)
            ).fetchone()
            pending = json.loads(policy["policy_json"]).get("pending_request_records")
            rows = c.execute(
                "SELECT rowid AS sequence,* FROM provider_requests WHERE run_id=? ORDER BY rowid",
                (run_id,),
            ).fetchall()
            after = 0
            if after_id is not None:
                cursor = c.execute(
                    "SELECT rowid AS sequence FROM provider_requests WHERE id=? AND run_id=?",
                    (_identifier(after_id), run_id),
                ).fetchone()
                if not cursor:
                    raise DomainError(
                        "request_page_invalid", "请求记录分页位置不存在。", status=400
                    )
                after = cursor["sequence"]
        remaining = [row for row in rows if row["sequence"] > after]
        result = []
        for row in remaining[:limit]:
            item = dict(row)
            item.pop("sequence")
            item["provider"] = json.loads(item.pop("provider_json"))
            item["usage"] = json.loads(item.pop("usage_json"))
            result.append(item)
        return {
            "schema_version": "provider-request-ledger/1.0",
            "run_id": run_id,
            "items": result,
            "summary": self.summarize(rows, pending),
            "has_more": len(remaining) > len(result),
            "next_cursor": result[-1]["id"] if len(remaining) > len(result) else None,
        }
