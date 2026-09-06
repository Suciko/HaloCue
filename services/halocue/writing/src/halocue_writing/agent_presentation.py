"""Read-only Agent Harness presentation projection.

This module deliberately has no write methods and no presentation tables. It
turns durable conversation/run records into a bounded, cursor-paginable view
for the workbench. The existing service remains the only command boundary.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

from .errors import DomainError, NotFound
from .repository import Repository, canonical_json, sha256_text


SCHEMA_VERSION = "agent-presentation/1.0"

PUBLIC_TOOL_LABELS = {
    "load_workflow_template": "读取当前任务边界",
    "read_work_context": "读取作品正式资料",
    "read_conversation_history": "读取当前对话",
    "search_character_cards": "检索人物卡",
    "search_world_bible": "检索世界规则",
    "search_work_canon": "检索作品事实",
    "draft_character_card": "整理人物卡草稿",
    "draft_world_card": "整理世界观草稿",
    "draft_world_rule": "整理世界规则草稿",
    "draft_canon_fact": "整理作品事实草稿",
    "check_knowledge_conflicts": "检查资料冲突",
    "create_knowledge_proposal": "整理资料候选",
    "store_conversation_attachments": "保存对话附件",
}


class AgentPresentationQuery:
    def __init__(self, repo: Repository):
        self.repo = repo

    @staticmethod
    def _decode_cursor(value: str | None) -> dict | None:
        if not value:
            return None
        try:
            raw = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
            cursor = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, base64.binascii.Error) as exc:
            raise DomainError("invalid_agent_presentation_cursor", "Agent 时间线游标无效，请重新加载。", status=400) from exc
        if not isinstance(cursor, dict) or cursor.get("v") != 1:
            raise DomainError("invalid_agent_presentation_cursor", "Agent 时间线游标版本不受支持，请重新加载。", status=400)
        return cursor

    @staticmethod
    def _encode_cursor(value: dict) -> str:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _json(value, fallback):
        if not value:
            return fallback
        try:
            result = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback
        return result

    @classmethod
    def _contains_exact_ref(cls, value, needles: set[str]) -> bool:
        """Match persisted JSON references by value, never by substring."""
        if not needles:
            return False
        if isinstance(value, str):
            if value in needles:
                return True
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return False
        else:
            parsed = value
        if isinstance(parsed, str):
            return parsed in needles
        if isinstance(parsed, dict):
            return any(cls._contains_exact_ref(item, needles) for item in parsed.values())
        if isinstance(parsed, (list, tuple)):
            return any(cls._contains_exact_ref(item, needles) for item in parsed)
        return False

    @staticmethod
    def _safe_content(content: dict) -> dict:
        """Only expose user-facing content fields; never provider internals."""
        allowed = {"text", "reasoning_summary", "citations", "attachments", "summary", "label"}
        return {key: content[key] for key in allowed if key in content}

    @staticmethod
    def _source_items(*collections) -> list[dict]:
        result: list[dict] = []
        seen: set[str] = set()
        for collection in collections:
            for item in collection or []:
                if isinstance(item, dict):
                    label = str(item.get("display_label") or item.get("filename") or item.get("label") or "").strip()
                    ref = str(item.get("chunk_id") or item.get("id") or label).strip()
                    source_type = "direct_evidence" if item.get("chunk_id") or item.get("paragraph_ids") else "agent_inference"
                else:
                    label = str(item).strip()
                    ref = label
                    source_type = "direct_evidence" if label else "agent_inference"
                if label.startswith("message-"):
                    label = "本次对话消息"
                elif label.startswith("thread-") or "作品主对话 thread-" in label:
                    label = "作品主对话"
                if not label or ref in seen:
                    continue
                seen.add(ref)
                result.append({"type": source_type, "label": label[:240], "ref": ref[:240]})
        return result[:12]

    @classmethod
    def _draft_card(cls, preview: dict) -> dict | None:
        if not isinstance(preview, dict):
            return None
        kind = str(preview.get("kind") or "")
        components = {
            "character_card": "CharacterProposalCard",
            "world_card": "WorldEntityProposalCard",
            "world_rule": "WorldRuleProposalCard",
            "canon_fact": "CanonProposalCard",
        }
        component = components.get(kind)
        if not component:
            return None
        content = preview.get("content") if isinstance(preview.get("content"), dict) else {}
        return {
            "schema_version": "agent-card/1.0",
            "component": component,
            "title": str(preview.get("title") or content.get("name") or "资料讨论草稿")[:160],
            "status": str(preview.get("status") or "discussion_draft"),
            "operation": str(preview.get("operation") or "create"),
            "summary": str(preview.get("summary") or content.get("summary") or content.get("text") or "")[:1000],
            "sources": cls._source_items(preview.get("sources"), content.get("source_refs")),
        }

    @classmethod
    def _proposal_card(cls, proposal: dict, candidate: dict, work_version: int) -> dict | None:
        kind = str(proposal.get("kind") or "")
        if kind == "brief_blueprint":
            blueprint = candidate.get("story_blueprint") if isinstance(candidate.get("story_blueprint"), dict) else {}
            brief = candidate.get("brief") if isinstance(candidate.get("brief"), dict) else {}
            return {
                "schema_version": "agent-card/1.0",
                "component": "DirectionProposalCard",
                "title": str(blueprint.get("title") or brief.get("idea") or "故事方向候选")[:160],
                "status": proposal["status"],
                "operation": "create",
                "summary": str(blueprint.get("premise") or "")[:1000],
                "direction": {
                    "central_conflict": str(blueprint.get("central_conflict") or "")[:1000],
                    "theme": str(blueprint.get("theme") or "")[:500],
                    "options": [str(item)[:500] for item in (blueprint.get("direction") or []) if str(item).strip()][:8],
                },
                "sources": cls._source_items(candidate.get("source_message_ids")),
                "decision": {
                    "proposal_id": proposal["id"],
                    "can_apply": proposal["status"] == "pending",
                    "partial_accept_supported": False,
                    "expected_work_version": work_version,
                    "candidate_hash": proposal["candidate_hash"],
                },
            }
        components = {
            "character_card": "CharacterProposalCard",
            "world_entity": "WorldEntityProposalCard",
            "world_rule": "WorldRuleProposalCard",
            "canon_fact": "CanonProposalCard",
        }
        component = components.get(kind)
        if not component:
            return None
        content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
        impact = candidate.get("impact_preview") if isinstance(candidate.get("impact_preview"), dict) else {}
        conflict = impact.get("conflict_summary") if isinstance(impact.get("conflict_summary"), dict) else {}
        visible_change_keys = {
            "character_card": {"name", "canonical_name", "role", "voice_anchors", "knowledge_boundary", "ooc_constraints", "relationships"},
            "world_entity": {"name", "kind", "summary", "aliases", "participants", "related_world_ids"},
            "world_rule": {"name", "text", "exceptions"},
            "canon_fact": {"text", "scope"},
        }.get(kind, set())
        changes = []
        for item in candidate.get("field_changes") or []:
            if not isinstance(item, dict) or str(item.get("key") or "").strip() not in visible_change_keys:
                continue
            changes.append({
                "key": str(item["key"])[:100],
                "label": str(item.get("field") or item["key"])[:120],
                "before": item.get("before"),
                "after": item.get("after"),
                "selected": True,
            })
        return {
            "schema_version": "agent-card/1.0",
            "component": component,
            "title": str(content.get("name") or content.get("text") or "资料更新建议")[:160],
            "status": proposal["status"],
            "operation": str(candidate.get("operation") or "create"),
            "summary": str(content.get("summary") or content.get("text") or "")[:1000],
            "changes": changes[:24],
            "sources": cls._source_items(candidate.get("document_citations"), content.get("source_refs"), candidate.get("source_message_ids")),
            "conflict_summary": {
                "status": str(conflict.get("status") or "clear"),
                "count": int(conflict.get("count") or 0),
                "blocking_count": int(conflict.get("blocking_count") or 0),
            },
            "impact": [
                {"id": str(item.get("id") or "")[:100], "label": str(item.get("label") or "")[:160]}
                for item in (impact.get("affected_consumers") or []) if isinstance(item, dict) and item.get("label")
            ][:12],
            "impact_refs": [
                {
                    "kind": str(item.get("kind") or "")[:80],
                    "id": str(item.get("id") or "")[:120],
                    "label": str(item.get("label") or "")[:200],
                    "effect": str(item.get("effect") or "")[:100],
                    "status": str(item.get("status") or "current")[:40],
                }
                for item in (impact.get("affected_refs") or [])
                if isinstance(item, dict) and item.get("id") and item.get("label")
            ][:24],
            "decision": {
                "proposal_id": proposal["id"],
                "can_apply": proposal["status"] == "pending" and int(conflict.get("blocking_count") or 0) == 0,
                "partial_accept_supported": bool((impact.get("decision") or {}).get("partial_accept_supported")),
                "expected_work_version": work_version,
                "candidate_hash": proposal["candidate_hash"],
                "impact_digest": str(impact.get("digest") or ""),
            },
        }

    @staticmethod
    def _event(event_id: str, event_type: str, occurred_at: str, state: str,
               source_status: str, scope: dict, refs: dict | None = None,
               summary: str | None = None, details: dict | None = None) -> dict:
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "state": state,
            "source_status": source_status,
            "scope": scope,
            "refs": refs or {},
        }
        if summary:
            event["summary"] = summary
        if details:
            event["details"] = details
        return event

    @staticmethod
    def _state(status: str, kind: str) -> str:
        mappings = {
            "agent_run": {"completed": "succeeded"},
            "proposal": {"pending": "waiting_user", "accepted": "succeeded", "rejected": "cancelled", "superseded": "cancelled"},
            "work_item": {"ready": "queued"},
            "tool": {"denied": "blocked"},
        }
        return mappings.get(kind, {}).get(status, status)

    @staticmethod
    def _scope(thread: dict) -> dict:
        return {"type": thread["scope_type"], "id": thread["scope_id"]}

    def get_thread_timeline(self, work_id: str, thread_id: str, *, limit: int = 100, cursor: str | None = None):
        limit = max(1, min(int(limit or 100), 200))
        requested = self._decode_cursor(cursor)
        issues: list[dict] = []
        with self.repo.connect() as connection:
            work = connection.execute("SELECT id,title,version,active_writing_pack_version FROM works WHERE id=?", (work_id,)).fetchone()
            if not work:
                raise NotFound("work", work_id)
            thread = connection.execute(
                "SELECT * FROM conversation_threads WHERE id=? AND work_id=?", (thread_id, work_id)
            ).fetchone()
            if not thread:
                raise NotFound("conversation_thread", thread_id)
            thread = dict(thread)
            scope = self._scope(thread)
            messages = self.repo.rows(connection.execute(
                "SELECT * FROM conversation_messages WHERE thread_id=? ORDER BY ordinal", (thread_id,)
            ))
            message_run_ids = {str(row["agent_run_id"]) for row in messages if row.get("agent_run_id")}
            runs = self.repo.rows(connection.execute(
                "SELECT * FROM agent_runs WHERE work_id=? ORDER BY created_at,id", (work_id,)
            ))
            included_runs = []
            for run in runs:
                policy = self._json(run.get("policy_json"), {})
                if not isinstance(policy, dict):
                    policy = {}
                if run["id"] in message_run_ids or policy.get("thread_id") == thread_id:
                    included_runs.append(run)
            run_ids = {run["id"] for run in included_runs}
            tools = self.repo.rows(connection.execute(
                "SELECT * FROM agent_tool_calls WHERE agent_run_id IN ({}) ORDER BY created_at, ordinal".format(
                    ",".join("?" for _ in run_ids) or "NULL"
                ), tuple(run_ids)
            )) if run_ids else []
            proposal_ids = {str(row["proposal_id"]) for row in messages if row.get("proposal_id")}
            proposal_ids.update(str(run["proposal_id"]) for run in included_runs if run.get("proposal_id"))
            proposals = self.repo.rows(connection.execute(
                "SELECT * FROM proposals WHERE work_id=? AND id IN ({})".format(
                    ",".join("?" for _ in proposal_ids) or "NULL"
                ), (work_id, *proposal_ids)
            )) if proposal_ids else []
            work_items = self.repo.rows(connection.execute(
                """SELECT item.*,run.work_id,run.id AS production_run_id
                   FROM work_items AS item
                   JOIN production_runs AS run ON run.id=item.run_id
                   WHERE run.work_id=? ORDER BY item.created_at,item.id""",
                (work_id,),
            ))
            linked_items = []
            link_needles = {thread_id, *run_ids, *proposal_ids}
            for item in work_items:
                if any(
                    self._contains_exact_ref(item.get(key), link_needles)
                    for key in ("input_refs_json", "output_refs_json", "acceptance_json")
                ):
                    linked_items.append(item)
            item_ids = {item["id"] for item in linked_items}
            attempts = self.repo.rows(connection.execute(
                "SELECT * FROM job_attempts WHERE work_item_id IN ({}) ORDER BY started_at,id".format(
                    ",".join("?" for _ in item_ids) or "NULL"
                ), tuple(item_ids),
            )) if item_ids else []

            events: list[dict] = []
            for message in messages:
                content = self._json(message.get("content_json"), {})
                role = str(message.get("role") or "assistant")
                event_type = "message.user" if role == "user" else "message.assistant"
                text = str(content.get("text") or content.get("summary") or "").strip()
                details = {"role": role, "kind": message.get("kind"), "content": self._safe_content(content)}
                usage = {key: message.get(key) for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "estimated_cost") if message.get(key) is not None}
                if usage:
                    details["usage"] = usage
                if message.get("archived_at"):
                    details["context_archived"] = True
                refs = {"thread_id": thread_id, "message_id": message["id"]}
                if message.get("agent_run_id"):
                    refs["agent_run_id"] = message["agent_run_id"]
                if message.get("proposal_id"):
                    refs["proposal_id"] = message["proposal_id"]
                events.append(self._event(
                    f"message:{message['id']}", event_type, message["created_at"], message.get("status") or "created",
                    message.get("status") or "created", scope, refs, text[:240] or None, details,
                ))
                reasoning_summary = str(content.get("reasoning_summary") or "").strip()
                if role == "assistant" and reasoning_summary:
                    events.append(self._event(
                        f"message:{message['id']}:reasoning-summary", "run.reasoning_summary", message["created_at"],
                        "succeeded", message.get("status") or "complete", scope, refs,
                        reasoning_summary[:240], {"visibility": "user_summary"},
                    ))
                draft_card = self._draft_card(content.get("artifact_preview"))
                if role == "assistant" and draft_card:
                    events.append(self._event(
                        f"message:{message['id']}:artifact", "artifact.presented", message["created_at"],
                        "waiting_user" if draft_card["status"] == "discussion_draft" else "succeeded",
                        draft_card["status"], scope, refs, draft_card["title"], {"card": draft_card},
                    ))
            successful_retry_of = set()
            for candidate in included_runs:
                candidate_policy = self._json(candidate.get("policy_json"), {})
                retry_of = candidate_policy.get("retry_of") or candidate_policy.get("retry_of_agent_run_id")
                if retry_of and candidate["status"] not in {"failed", "cancelled"}:
                    successful_retry_of.add(str(retry_of))
            for run in included_runs:
                policy = self._json(run.get("policy_json"), {})
                if not isinstance(policy, dict):
                    policy = {}
                refs = {"thread_id": thread_id, "agent_run_id": run["id"]}
                if run.get("proposal_id"):
                    refs["proposal_id"] = run["proposal_id"]
                provider = policy.get("provider_runtime") if isinstance(policy.get("provider_runtime"), dict) else None
                try:
                    snapshot_text = self.repo.read_text(run["input_snapshot_uri"])
                except (OSError, UnicodeError, TypeError, ValueError):
                    snapshot_text = None
                actual_input_digest = sha256_text(snapshot_text) if snapshot_text is not None else None
                input_valid = actual_input_digest == run["input_digest"]
                details = {
                    "instruction": str(run.get("instruction") or "")[:300],
                    "scope": {"type": run["scope_type"], "id": run["scope_id"]},
                    "input_integrity": {"valid": input_valid, "expected_digest": run["input_digest"]},
                }
                if not input_valid:
                    issues.append({"code": "agent_input_integrity_failed", "source": "agent_run", "id": run["id"], "message": "Agent 固定输入缺失或摘要不匹配。"})
                if provider:
                    details["provider_runtime"] = {key: provider.get(key) for key in ("provider", "model", "is_simulation", "can_call_model") if key in provider}
                events.append(self._event(
                    f"agent-run:{run['id']}:started", "run.started", run["created_at"], self._state(run["status"], "agent_run"), run["status"], scope, refs, "开始处理", details,
                ))
                if run.get("finished_at"):
                    failure = self._json(run.get("failure_json"), {})
                    finish_details = {
                        "failure": {
                            key: failure.get(key)
                            for key in ("code", "message", "status", "retryable", "failure_kind")
                            if failure.get(key) is not None
                        }
                    } if failure else {}
                    finish_type = "run.failed" if run["status"] == "failed" else "run.cancelled" if run["status"] == "cancelled" else "run.completed"
                    events.append(self._event(
                        f"agent-run:{run['id']}:finished", finish_type, run["finished_at"], self._state(run["status"], "agent_run"), run["status"], scope, refs, "处理完成" if run["status"] == "completed" else "处理已结束", finish_details,
                    ))
                    if run["status"] == "failed" and input_valid and run["id"] not in successful_retry_of:
                        events.append(self._event(
                            f"agent-run:{run['id']}:recovery", "recovery.available", run["finished_at"], "waiting_user", run["status"], scope, refs,
                            "可以从已保存输入重试", {"action": "agent.retry", "target_id": run["id"]},
                        ))
            for call in tools:
                refs = {"thread_id": thread_id, "agent_run_id": call["agent_run_id"], "tool_call_id": call["id"]}
                error = self._json(call.get("error_json"), {})
                details = {"tool_name": call["tool_name"], "ordinal": call["ordinal"], "has_error": bool(error)}
                output_summary = str(call.get("output_ref") or "").strip()
                if output_summary:
                    details["output_summary"] = output_summary
                if error:
                    details["error"] = {key: error.get(key) for key in ("code", "message", "retryable") if error.get(key)}
                tool_event_type = "tool.failed" if call["status"] == "failed" else "tool.started" if call["status"] in {"queued", "running"} else "tool.summary"
                tool_summary = PUBLIC_TOOL_LABELS.get(call["tool_name"], "执行 Agent 工具")
                if output_summary and tool_event_type == "tool.summary":
                    tool_summary = f"{tool_summary} · {output_summary}"
                events.append(self._event(
                    f"tool:{call['id']}:state", tool_event_type, call["created_at"], self._state(call["status"], "tool"), call["status"], scope, refs, tool_summary, details,
                ))
            for proposal in proposals:
                refs = {"thread_id": thread_id, "proposal_id": proposal["id"]}
                if proposal.get("base_revision_id"):
                    refs["base_revision_id"] = proposal["base_revision_id"]
                try:
                    candidate_text = self.repo.read_text(proposal["candidate_uri"])
                except (OSError, UnicodeError, TypeError, ValueError):
                    candidate_text = None
                actual_candidate_hash = sha256_text(candidate_text) if candidate_text is not None else None
                candidate_valid = actual_candidate_hash == proposal["candidate_hash"]
                details = {
                    "kind": proposal["kind"], "risk": proposal["risk"], "candidate_hash": proposal["candidate_hash"],
                    "candidate_integrity": {"valid": candidate_valid},
                }
                if not candidate_valid:
                    issues.append({"code": "proposal_candidate_integrity_failed", "source": "proposal", "id": proposal["id"], "message": "Proposal 候选缺失或摘要不匹配。"})
                else:
                    candidate = self._json(candidate_text, {})
                    card = self._proposal_card(proposal, candidate, int(work["version"])) if isinstance(candidate, dict) else None
                    if card:
                        details["card"] = card
                events.append(self._event(
                    f"proposal:{proposal['id']}:created", "proposal.presented", proposal["created_at"], self._state(proposal["status"], "proposal"), proposal["status"], scope, refs, "生成待审修改", details,
                ))
                if proposal.get("decided_at"):
                    events.append(self._event(
                        f"proposal:{proposal['id']}:decided", "proposal.decided", proposal["decided_at"], self._state(proposal["status"], "proposal"), proposal["status"], scope, refs, "修改已处理", details,
                    ))
            for item in linked_items:
                refs = {"thread_id": thread_id, "production_run_id": item["production_run_id"], "work_item_id": item["id"]}
                details = {
                    "type": item["type"],
                    "attempt_count": item["attempt_count"],
                    "has_error": bool(item.get("error_json")),
                }
                events.append(self._event(
                    f"work-item:{item['id']}:created", "work_item.created", item["created_at"], self._state(item["status"], "work_item"), item["status"], scope, refs, item["type"], details,
                ))
                if item.get("updated_at") and item["updated_at"] != item["created_at"]:
                    events.append(self._event(
                        f"work-item:{item['id']}:updated", "work_item.updated", item["updated_at"], self._state(item["status"], "work_item"), item["status"], scope, refs, item["type"], details,
                    ))
            for attempt in attempts:
                item = next((candidate for candidate in linked_items if candidate["id"] == attempt["work_item_id"]), None)
                refs = {"thread_id": thread_id, "work_item_id": attempt["work_item_id"], "attempt_id": attempt["id"]}
                if item:
                    refs["production_run_id"] = item["production_run_id"]
                details = {"ordinal": attempt["ordinal"], "provider": attempt["provider"], "error_code": attempt.get("error_code")}
                events.append(self._event(
                    f"attempt:{attempt['id']}:started", "attempt.started", attempt["started_at"], self._state(attempt["status"], "attempt"), attempt["status"], scope, refs, "开始执行", details,
                ))
                if attempt.get("finished_at"):
                    events.append(self._event(
                        f"attempt:{attempt['id']}:finished", "attempt.finished", attempt["finished_at"], self._state(attempt["status"], "attempt"), attempt["status"], scope, refs, "执行已结束", details,
                    ))

            for item in events:
                if item["scope"]["id"] != thread["scope_id"] and item["event_type"].startswith("message"):
                    issues.append({"code": "scope_mismatch", "source": item["event_type"], "id": item["event_id"], "message": "事件作用域与当前对话不一致。"})
            events.sort(key=lambda item: (item["occurred_at"], item["event_type"], item["event_id"]))
            watermark = max([item["occurred_at"] for item in events] + [datetime.now(timezone.utc).isoformat()])
            digest_payload = [{key: item[key] for key in ("event_id", "event_type", "occurred_at", "state", "source_status", "scope", "refs", "summary", "details") if key in item} for item in events]
            presentation_digest = hashlib.sha256(canonical_json(digest_payload).encode("utf-8")).hexdigest()
            if requested:
                if requested.get("work_id") != work_id or requested.get("thread_id") != thread_id or requested.get("presentation_digest") != presentation_digest:
                    raise DomainError("agent_presentation_cursor_stale", "Agent 时间线已更新，请重新加载。", status=409)
                start = int(requested.get("offset", 0))
            else:
                start = 0
            page = events[start:start + limit]
            next_cursor = None
            if start + limit < len(events):
                next_cursor = self._encode_cursor({"v": 1, "work_id": work_id, "thread_id": thread_id, "presentation_digest": presentation_digest, "offset": start + limit})
            snapshot = {"work_version": work["version"], "thread_version": thread["version"], "writing_pack_version": work["active_writing_pack_version"]}
            if included_runs:
                latest_policy = self._json(included_runs[-1].get("policy_json"), {})
                provider = latest_policy.get("provider_runtime") if isinstance(latest_policy, dict) else None
                if isinstance(provider, dict):
                    snapshot["provider_runtime"] = {key: provider.get(key) for key in ("provider", "model", "settings_version", "config_revision", "config_digest", "is_simulation", "can_call_model") if key in provider}
            return {
                "schema_version": SCHEMA_VERSION,
                "work": {"id": work["id"], "title": work["title"], "version": work["version"]},
                "thread": {key: thread[key] for key in ("id", "work_id", "scope_type", "scope_id", "title", "status", "phase", "permission_mode", "version", "archived_message_count", "created_at", "updated_at")},
                "integrity": {"complete": not issues, "issues": issues, "presentation_digest": presentation_digest},
                "snapshot": snapshot,
                "events": page,
                "cursor": {"next": next_cursor, "has_more": bool(next_cursor), "watermark": watermark},
            }
