from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .errors import NotFound
from .repository import Repository, canonical_json, sha256_text


@dataclass(frozen=True)
class _Action:
    id: str
    label: str
    target_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "enabled": True,
        }
        if self.target_id:
            result["target_id"] = self.target_id
        return result


class WritingHarness:
    """Resolve one author-facing state from the persisted writing domain.

    This is a read-only projection. Artifact/Revision, Proposal, Gate and
    ScriptRelease remain the authoritative records; callers must still cross
    their existing version checks to perform any action.
    """

    _PROGRESS_STEPS = (
        ("direction", "讨论与确定方向"),
        ("structure", "建立章节与场景"),
        ("draft", "逐场写作"),
        ("review", "审查与记忆"),
        ("release", "冻结并交给 AA 制作"),
    )

    def __init__(self, repository: Repository):
        self.repository = repository

    def resolve(
        self,
        work_id: str,
        *,
        scope_type: str = "work",
        scope_id: str | None = None,
        provider: dict | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        scope_type = str(scope_type or "work").strip()
        scope_id = str(scope_id or work_id).strip()
        if scope_type not in {"work", "chapter", "scene"}:
            raise ValueError("scope_type must be work, chapter, or scene")

        with self.repository.connect() as connection:
            work = connection.execute(
                "SELECT * FROM works WHERE id=?", (work_id,)
            ).fetchone()
            if not work:
                raise NotFound("work", work_id)
            self._validate_scope(connection, work_id, scope_type, scope_id)

            if thread_id:
                thread = connection.execute(
                    "SELECT scope_type,scope_id FROM conversation_threads WHERE id=? AND work_id=?",
                    (thread_id, work_id),
                ).fetchone()
                if not thread:
                    raise NotFound("conversation_thread", thread_id)
                if thread["scope_type"] != scope_type or thread["scope_id"] != scope_id:
                    raise ValueError("thread scope must match harness scope")

            state = self._read_state(
                connection, work_id, scope_type, scope_id, thread_id=thread_id
            )

        result = self._resolve_state(state)
        result.update(
            {
                "schema_version": "writing-harness-status/1.0",
                "work_id": work_id,
                "work_version": work["version"],
                "scope": {"type": scope_type, "id": scope_id},
            }
        )
        warnings = list(result.get("warnings") or [])
        if provider and provider.get("is_simulation"):
            warnings.append(
                {
                    "code": "provider_simulation",
                    "message": "当前使用本地模拟 Provider，结果不是由真实模型生成。",
                }
            )
        result["warnings"] = warnings
        return result

    def doctor(self, work_id: str, *, runtime: dict | None = None) -> dict[str, Any]:
        """Run read-only integrity checks without repairing or rewriting data."""
        runtime = runtime if isinstance(runtime, dict) else {}
        checks: list[dict[str, Any]] = []
        with self.repository.connect() as connection:
            work = connection.execute(
                "SELECT * FROM works WHERE id=?", (work_id,)
            ).fetchone()
            if not work:
                raise NotFound("work", work_id)

            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            checks.append(
                self._check(
                    "database.integrity",
                    ok=quick_check == "ok",
                    message="作品数据库结构可读取。" if quick_check == "ok" else "作品数据库完整性检查失败。",
                    impact="作品、运行和审批状态可能无法可靠恢复。",
                    repair="停止写入并从最近一次已验证备份恢复。",
                )
            )

            revision_rows = connection.execute(
                """SELECT revision.id,revision.content_uri,revision.content_hash
                   FROM revisions AS revision
                   JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                   WHERE artifact.work_id=?""",
                (work_id,),
            ).fetchall()
            broken_revisions = self._invalid_text_records(revision_rows)
            checks.append(
                self._check(
                    "revisions.integrity",
                    ok=not broken_revisions,
                    message=(
                        f"{len(revision_rows)} 个 Revision 内容校验通过。"
                        if not broken_revisions
                        else f"{len(broken_revisions)} 个 Revision 内容缺失或哈希不一致。"
                    ),
                    details={"revision_ids": broken_revisions},
                    impact="正文或创作资料不能作为可信事实源。",
                    repair="从备份恢复这些 Revision，恢复前不要冻结 ScriptRelease。",
                )
            )

            pending_proposals = connection.execute(
                """SELECT id,candidate_uri,candidate_hash FROM proposals
                   WHERE work_id=? AND status='pending'""",
                (work_id,),
            ).fetchall()
            broken_proposals = self._invalid_text_records(
                pending_proposals,
                uri_key="candidate_uri",
                hash_key="candidate_hash",
                id_key="id",
            )
            checks.append(
                self._check(
                    "proposals.integrity",
                    ok=not broken_proposals,
                    message=(
                        f"{len(pending_proposals)} 个待决定 Proposal 可安全审阅。"
                        if not broken_proposals
                        else f"{len(broken_proposals)} 个待决定 Proposal 已损坏。"
                    ),
                    details={"proposal_ids": broken_proposals},
                    impact="用户看到的候选可能不是创建时固定的候选。",
                    repair="退回损坏的 Proposal，并基于当前 Revision 重新生成。",
                )
            )

            projection_items = connection.execute(
                """SELECT item.id,item.status,item.output_ref,item.output_hash
                   FROM commit_projection_items AS item
                   JOIN commit_projections AS projection ON projection.id=item.projection_id
                   JOIN revisions AS revision ON revision.id=projection.revision_id
                   JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                   WHERE projection.work_id=? AND artifact.current_revision_id=projection.revision_id""",
                (work_id,),
            ).fetchall()
            completed_projection_items = [
                row for row in projection_items if row["status"] == "done"
            ]
            broken_projection_outputs = self._invalid_text_records(
                completed_projection_items,
                uri_key="output_ref",
                hash_key="output_hash",
                id_key="id",
            )
            checks.append(
                self._check(
                    "commit_projection.integrity",
                    ok=not broken_projection_outputs,
                    message=(
                        f"{len(completed_projection_items)} 个提交投影输出校验通过。"
                        if not broken_projection_outputs
                        else f"{len(broken_projection_outputs)} 个提交投影输出缺失或哈希不一致。"
                    ),
                    details={"projection_item_ids": broken_projection_outputs},
                    impact="摘要或检索等派生数据不能安全使用；正式 Revision 不受影响。",
                    repair="从固定 Revision 只补跑损坏的投影步骤。",
                )
            )
            failed_projection_items = [
                row["id"] for row in projection_items if row["status"] == "failed"
            ]
            pending_projection_items = [
                row["id"] for row in projection_items if row["status"] in {"pending", "running"}
            ]
            checks.append(
                self._check(
                    "commit_projection.progress",
                    ok=not failed_projection_items and not pending_projection_items,
                    severity="warning",
                    message=(
                        "当前 Revision 的派生维护已经完成。"
                        if not failed_projection_items and not pending_projection_items
                        else f"提交投影还有 {len(failed_projection_items)} 个失败项、{len(pending_projection_items)} 个待处理项。"
                    ),
                    details={
                        "failed_item_ids": failed_projection_items,
                        "pending_item_ids": pending_projection_items,
                    },
                    impact="正式内容已经保存，但摘要、检索、记忆或审查待办可能尚未同步。",
                    repair="保留已完成输出，只补跑失败或待处理步骤。",
                )
            )

            failed_runs = connection.execute(
                """SELECT id,input_snapshot_uri,input_digest FROM agent_runs
                   WHERE work_id=? AND status='failed' ORDER BY created_at DESC""",
                (work_id,),
            ).fetchall()
            broken_snapshots = self._invalid_text_records(
                failed_runs,
                uri_key="input_snapshot_uri",
                hash_key="input_digest",
                id_key="id",
            )
            checks.append(
                self._check(
                    "agent_snapshots.integrity",
                    ok=not broken_snapshots,
                    message=(
                        f"{len(failed_runs)} 个失败 AgentRun 的恢复快照可读取。"
                        if not broken_snapshots
                        else f"{len(broken_snapshots)} 个 AgentRun 无法安全重试。"
                    ),
                    details={"agent_run_ids": broken_snapshots},
                    impact="对应运行不能从固定输入恢复。",
                    repair="保留失败记录，并从当前作品状态重新发起任务。",
                )
            )

            failed_jobs = connection.execute(
                """SELECT COUNT(*) FROM agent_dispatch_jobs
                   WHERE status='failed' AND (
                     agent_run_id IN (SELECT id FROM agent_runs WHERE work_id=?)
                     OR work_item_id IN (
                       SELECT item.id FROM work_items AS item
                       JOIN production_runs AS run ON run.id=item.run_id
                       WHERE run.work_id=?
                     )
                   )""",
                (work_id, work_id),
            ).fetchone()[0]
            checks.append(
                self._check(
                    "agent_queue.failures",
                    ok=failed_jobs == 0,
                    severity="warning",
                    message=(
                        "持久 Agent 队列没有失败任务。"
                        if failed_jobs == 0
                        else f"持久 Agent 队列保留了 {failed_jobs} 个失败任务。"
                    ),
                    impact="部分 Agent 工作没有完成，但已完成产物仍然保留。",
                    repair="从作品状态页检查失败原因，只重试仍然有效的固定输入。",
                )
            )

        provider = runtime.get("provider") if isinstance(runtime.get("provider"), dict) else {}
        checks.append(
            self._check(
                "provider.available",
                ok=bool(provider.get("can_call_model")),
                severity="warning",
                message=(
                    f"写作模型 {provider.get('display_name') or provider.get('kind')} 可调用。"
                    if provider.get("can_call_model")
                    else "当前没有可调用的真实写作模型。"
                ),
                impact="只能运行明确标记的模拟生成，不能产生真实模型结果。",
                repair="在设置中配置并测试写作模型。",
            )
        )
        skill = runtime.get("ba_writing_skill") if isinstance(runtime.get("ba_writing_skill"), dict) else {}
        checks.append(
            self._check(
                "ba_writing_pack.ready",
                ok=skill.get("status") == "ready" and not skill.get("missing_files"),
                message=(
                    f"BA WritingPack {skill.get('pack_version')} 已固定。"
                    if skill.get("status") == "ready" and not skill.get("missing_files")
                    else "BA WritingPack 不完整。"
                ),
                details={"missing_files": skill.get("missing_files") or []},
                impact="Agent 无法按已版本化的 BA 写作规则稳定运行。",
                repair="重新物化 ba-writing Skill，并处理缺失的必要资源。",
            )
        )
        dispatcher = runtime.get("dispatcher") if isinstance(runtime.get("dispatcher"), dict) else {}
        checks.append(
            self._check(
                "agent_dispatcher.running",
                ok=bool(dispatcher.get("running")),
                severity="warning",
                message="持久 Agent Dispatcher 正在运行。" if dispatcher.get("running") else "持久 Agent Dispatcher 未运行。",
                impact="已排队任务会保留，但不会继续执行。",
                repair="启动写作服务的 Dispatcher。",
            )
        )

        blockers = [item for item in checks if item["status"] == "error"]
        warnings = [item for item in checks if item["status"] == "warning"]
        return {
            "schema_version": "writing-harness-doctor/1.0",
            "work_id": work_id,
            "ok": not blockers,
            "outcome": "needs_user" if blockers else ("partial" if warnings else "completed"),
            "blocking_count": len(blockers),
            "warning_count": len(warnings),
            "checks": checks,
            "recommended_actions": list(
                dict.fromkeys(
                    item["repair"]
                    for item in checks
                    if item["status"] != "ok" and item.get("repair")
                )
            ),
        }

    @staticmethod
    def _validate_scope(connection, work_id: str, scope_type: str, scope_id: str) -> None:
        if scope_type == "work":
            valid = scope_id == work_id
        elif scope_type == "chapter":
            valid = bool(
                connection.execute(
                    "SELECT 1 FROM chapters WHERE id=? AND work_id=?",
                    (scope_id, work_id),
                ).fetchone()
            )
        else:
            valid = bool(
                connection.execute(
                    "SELECT 1 FROM scenes WHERE id=? AND work_id=?",
                    (scope_id, work_id),
                ).fetchone()
            )
        if not valid:
            raise NotFound(scope_type, scope_id)

    def _read_state(
        self,
        connection,
        work_id: str,
        scope_type: str,
        scope_id: str,
        *,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        artifacts = {
            row["kind"]: dict(row)
            for row in connection.execute(
                "SELECT kind,current_revision_id FROM artifacts WHERE work_id=?",
                (work_id,),
            ).fetchall()
        }
        real_chapters = connection.execute(
            "SELECT * FROM chapters WHERE work_id=? AND status<>'placeholder' ORDER BY stable_order_key",
            (work_id,),
        ).fetchall()
        scenes = connection.execute(
            "SELECT * FROM scenes WHERE work_id=? ORDER BY stable_order_key",
            (work_id,),
        ).fetchall()
        scoped_scene_ids: set[str] | None = None
        if scope_type == "scene":
            scoped_scene_ids = {scope_id}
        elif scope_type == "chapter":
            scoped_scene_ids = {row["id"] for row in scenes if row["chapter_id"] == scope_id}

        proposals = connection.execute(
            "SELECT * FROM proposals WHERE work_id=? AND status='pending' ORDER BY created_at DESC",
            (work_id,),
        ).fetchall()
        if thread_id:
            linked_proposal_ids = {
                row["proposal_id"]
                for row in connection.execute(
                    """SELECT proposal_id FROM conversation_messages
                       WHERE thread_id=? AND proposal_id IS NOT NULL""",
                    (thread_id,),
                ).fetchall()
            }
            for row in connection.execute(
                "SELECT proposal_id,policy_json FROM agent_runs WHERE work_id=? AND proposal_id IS NOT NULL",
                (work_id,),
            ).fetchall():
                try:
                    policy = json.loads(row["policy_json"] or "{}")
                except json.JSONDecodeError:
                    policy = {}
                if policy.get("thread_id") == thread_id:
                    linked_proposal_ids.add(row["proposal_id"])
            proposals = [row for row in proposals if row["id"] in linked_proposal_ids]
        if scoped_scene_ids is not None:
            proposals = [
                row
                for row in proposals
                if row["scope_id"] in scoped_scene_ids or row["scope_id"] == scope_id
            ]

        agent_runs = connection.execute(
            "SELECT * FROM agent_runs WHERE work_id=? ORDER BY created_at DESC",
            (work_id,),
        ).fetchall()
        if thread_id:
            linked_run_ids = {
                row["agent_run_id"]
                for row in connection.execute(
                    """SELECT agent_run_id FROM conversation_messages
                       WHERE thread_id=? AND agent_run_id IS NOT NULL""",
                    (thread_id,),
                ).fetchall()
            }
            filtered_runs = []
            for row in agent_runs:
                try:
                    policy = json.loads(row["policy_json"] or "{}")
                except json.JSONDecodeError:
                    policy = {}
                if row["id"] in linked_run_ids or policy.get("thread_id") == thread_id:
                    filtered_runs.append(row)
            agent_runs = filtered_runs
        if scope_type != "work":
            agent_runs = [
                row
                for row in agent_runs
                if row["scope_type"] == scope_type and row["scope_id"] == scope_id
            ]
        latest_agent_run = agent_runs[0] if agent_runs else None
        failed_runs = [latest_agent_run] if latest_agent_run and latest_agent_run["status"] == "failed" else []
        active_runs = [latest_agent_run] if latest_agent_run and latest_agent_run["status"] in {"queued", "running"} else []

        releases = connection.execute(
            "SELECT * FROM script_releases WHERE work_id=? ORDER BY released_at DESC",
            (work_id,),
        ).fetchall()
        release_gate = connection.execute(
            "SELECT * FROM gates WHERE work_id=? AND kind='release.review' ORDER BY created_at DESC LIMIT 1",
            (work_id,),
        ).fetchone()
        continuity_gate = connection.execute(
            "SELECT * FROM gates WHERE work_id=? AND kind='continuity.review' ORDER BY created_at DESC LIMIT 1",
            (work_id,),
        ).fetchone()
        open_blockers = connection.execute(
            """SELECT id,message FROM review_findings
               WHERE work_id=? AND status='open' AND severity='blocking'
               ORDER BY created_at""",
            (work_id,),
        ).fetchall()

        projection_parameters: list[Any] = [work_id]
        projection_scope = ""
        if scoped_scene_ids is not None:
            if scoped_scene_ids:
                placeholders = ",".join("?" for _ in scoped_scene_ids)
                projection_scope = f" AND artifact.scope_id IN ({placeholders})"
                projection_parameters.extend(sorted(scoped_scene_ids))
            else:
                projection_scope = " AND 1=0"
        commit_projection_issues = connection.execute(
            f"""SELECT projection.id,projection.revision_id,projection.status,
                       artifact.scope_type,artifact.scope_id,
                       SUM(CASE WHEN item.status='failed' THEN 1 ELSE 0 END) AS failed_count
                FROM commit_projections AS projection
                JOIN revisions AS revision ON revision.id=projection.revision_id
                JOIN artifacts AS artifact ON artifact.id=revision.artifact_id
                JOIN commit_projection_items AS item ON item.projection_id=projection.id
                WHERE projection.work_id=?
                  AND artifact.current_revision_id=projection.revision_id
                  AND projection.status IN ('partial','failed')
                  {projection_scope}
                GROUP BY projection.id
                ORDER BY projection.updated_at DESC""",
            projection_parameters,
        ).fetchall()

        return {
            "artifacts": artifacts,
            "real_chapters": real_chapters,
            "scenes": scenes,
            "scoped_scene_ids": scoped_scene_ids,
            "proposals": proposals,
            "failed_runs": failed_runs,
            "active_runs": active_runs,
            "releases": releases,
            "release_gate": release_gate,
            "release_gate_current": self._release_gate_current(
                connection, work_id, release_gate, scenes
            ),
            "continuity_gate_current": self._release_gate_current(
                connection, work_id, continuity_gate, scenes
            ),
            "open_blockers": open_blockers,
            "memory": self._memory_state(connection, work_id, scenes, scoped_scene_ids),
            "commit_projection_issues": commit_projection_issues,
        }

    def _resolve_state(self, state: dict[str, Any]) -> dict[str, Any]:
        if state["active_runs"]:
            run = state["active_runs"][0]
            return self._result(
                outcome="in_progress",
                phase="agent_running",
                headline="Agent 正在处理当前任务，已完成的步骤会持续保留",
                action=_Action("agent.inspect", "查看运行进度", run["id"]),
                logical_step="draft" if run["scope_type"] == "scene" else "direction",
                secondary=[_Action("agent.cancel", "停止这次运行", run["id"])],
            )

        resume = self._latest_resume(state["failed_runs"])
        if resume:
            return self._result(
                outcome="needs_user",
                phase="agent_recovery",
                headline="上一次 Agent 运行停在可恢复位置",
                action=_Action("agent.retry", "从固定输入重试", resume["agent_run_id"]),
                logical_step="direction",
                resume=resume,
            )

        if state["proposals"]:
            proposal = state["proposals"][0]
            if proposal["kind"] == "memory_bundle":
                logical_step = "review"
            elif proposal["kind"] in {"story_structure", "chapter_plan"}:
                logical_step = "structure"
            elif proposal["scope_type"] == "scene":
                logical_step = "draft"
            else:
                logical_step = "direction"
            return self._result(
                outcome="needs_user",
                phase="proposal_review",
                headline="Agent 已形成修改建议，等待你的决定",
                action=_Action("proposal.apply", "审阅并应用修改", proposal["id"]),
                logical_step=logical_step,
                secondary=[_Action("proposal.reject", "退回这项建议", proposal["id"])],
            )

        if state["commit_projection_issues"]:
            projection = state["commit_projection_issues"][0]
            knowledge_source = projection["scope_type"] in {"work", "character"}
            return self._result(
                outcome="needs_user",
                phase="commit_projection",
                headline="正式内容已经保存，但有一项派生维护需要补跑",
                action=_Action("projection.retry", "只重试未完成项", projection["revision_id"]),
                logical_step="direction" if knowledge_source else "review",
                warnings=[
                    {
                        "code": "commit_projection_partial",
                        "message": f"{projection['failed_count']} 个摘要、检索或维护步骤未完成；正式 Revision 没有受到影响。",
                        "projection_id": projection["id"],
                    }
                ],
            )

        if not self._has_revision(state["artifacts"], "brief"):
            return self._result(
                outcome="ready",
                phase="brief",
                headline="先和创作导演说清这次想写什么",
                action=_Action("brief.build", "开始讨论作品方向"),
                logical_step="direction",
            )

        if not self._accepted_blueprint(state["artifacts"]):
            return self._result(
                outcome="ready",
                phase="blueprint",
                headline="写作意图已经保存，下一步形成故事方向",
                action=_Action("blueprint.generate", "形成故事方向"),
                logical_step="direction",
            )

        if not state["real_chapters"]:
            return self._result(
                outcome="ready",
                phase="structure",
                headline="故事方向已确定，现在建立要写的章节",
                action=_Action("chapter.create", "建立第一章"),
                logical_step="structure",
            )

        if not state["scenes"]:
            chapter = state["real_chapters"][0]
            return self._result(
                outcome="ready",
                phase="structure",
                headline="章节已建立，下一步把本章拆成可写场景",
                action=_Action("scene.create", "建立第一个场景", chapter["id"]),
                logical_step="structure",
            )

        target_scenes = state["scenes"]
        if state["scoped_scene_ids"] is not None:
            target_scenes = [row for row in target_scenes if row["id"] in state["scoped_scene_ids"]]
        missing = [row for row in target_scenes if not row["current_revision_id"]]
        if missing:
            scene = missing[0]
            return self._result(
                outcome="ready",
                phase="scene_draft",
                headline=f"{scene['title']} 已有明确位置，先装配可信上下文",
                action=_Action("scene.context.assemble", "准备本场上下文", scene["id"]),
                logical_step="draft",
                secondary=[_Action("scene.draft.generate", "生成本场候选", scene["id"])],
            )

        incomplete_memory = [row for row in state["memory"] if not row["complete"]]
        if incomplete_memory:
            scene_id = incomplete_memory[0]["scene_id"]
            return self._result(
                outcome="in_progress",
                phase="memory",
                headline="正文已保存，等待提取可审阅的长期事实",
                action=_Action("memory.extract", "整理本场记忆", scene_id),
                logical_step="review",
                secondary=[_Action("memory.skip", "记录本场无需沉淀", scene_id)],
            )

        if not state["continuity_gate_current"] and not state["open_blockers"]:
            return self._result(
                outcome="ready",
                phase="release_review",
                headline=(
                    "全篇审查已通过，还需要更新跨场景连续性审查"
                    if state["release_gate_current"]
                    else "正文已齐，先检查跨场景连续性"
                ),
                action=_Action("continuity.review", "运行连续性审查"),
                logical_step="review",
            )

        if state["open_blockers"] or not state["release_gate_current"]:
            blockers = [
                {"id": row["id"], "message": row["message"]}
                for row in state["open_blockers"]
            ]
            return self._result(
                outcome="blocked" if blockers else "ready",
                phase="release_review",
                headline=(
                    "全篇审查发现必须处理的问题"
                    if blockers
                    else "正文已齐，等待全篇审查"
                ),
                action=_Action("release.review", "重新运行全篇审查" if blockers else "开始全篇审查"),
                logical_step="review",
                blockers=blockers,
            )

        if state["releases"]:
            release = state["releases"][0]
            return self._result(
                outcome="completed",
                phase="released",
                headline=f"{release['display_version']} 已冻结，可以进入 AA 制作",
                action=_Action("production.open", "进入 AA 制作", release["id"]),
                logical_step="release",
                secondary=[_Action("release.inspect", "查看冻结版本", release["id"])],
                all_completed=True,
            )

        return self._result(
            outcome="ready",
            phase="release_review",
            headline="全篇审查已通过，可以冻结不可变版本",
            action=_Action("release.freeze", "冻结 ScriptRelease"),
            logical_step="release",
        )

    @staticmethod
    def _has_revision(artifacts: dict, kind: str) -> bool:
        return bool(artifacts.get(kind, {}).get("current_revision_id"))

    def _accepted_blueprint(self, artifacts: dict) -> bool:
        artifact = artifacts.get("story_blueprint") or {}
        revision_id = artifact.get("current_revision_id")
        if not revision_id:
            return False
        with self.repository.connect() as connection:
            revision = connection.execute(
                "SELECT content_uri FROM revisions WHERE id=?", (revision_id,)
            ).fetchone()
        if not revision:
            return False
        try:
            content = json.loads(self.repository.read_text(revision["content_uri"]))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return False
        return content.get("status", "accepted") == "accepted"

    def _latest_resume(self, failed_runs) -> dict[str, Any] | None:
        for run in failed_runs:
            try:
                snapshot = self.repository.read_text(run["input_snapshot_uri"])
            except (OSError, UnicodeError, ValueError):
                continue
            if sha256_text(snapshot) != run["input_digest"]:
                continue
            try:
                decoded = json.loads(snapshot)
            except json.JSONDecodeError:
                continue
            if not isinstance(decoded, dict):
                continue
            return {
                "available": True,
                "agent_run_id": run["id"],
                "input_snapshot_uri": run["input_snapshot_uri"],
                "input_digest": run["input_digest"],
            }
        return None

    @staticmethod
    def _memory_state(connection, work_id: str, scenes, scoped_scene_ids: set[str] | None) -> list[dict[str, Any]]:
        items = connection.execute(
            """SELECT item.* FROM work_items AS item
               JOIN production_runs AS run ON run.id=item.run_id
               WHERE run.work_id=? AND item.type='memory.extract'
               ORDER BY item.created_at DESC""",
            (work_id,),
        ).fetchall()
        by_revision: dict[str, dict[str, Any]] = {}
        for item in items:
            try:
                refs = json.loads(item["input_refs_json"] or "{}")
            except json.JSONDecodeError:
                continue
            revision_id = refs.get("scene_revision_id")
            if revision_id and revision_id not in by_revision:
                by_revision[revision_id] = dict(item)
        result = []
        for scene in scenes:
            if scoped_scene_ids is not None and scene["id"] not in scoped_scene_ids:
                continue
            revision_id = scene["current_revision_id"]
            if not revision_id:
                continue
            item = by_revision.get(revision_id)
            status = item["status"] if item else "missing"
            result.append(
                {
                    "scene_id": scene["id"],
                    "revision_id": revision_id,
                    "status": status,
                    "complete": status in {"succeeded", "skipped"},
                }
            )
        return result

    def _release_gate_current(self, connection, work_id: str, gate, scenes) -> bool:
        if not gate or gate["status"] != "passed" or not scenes:
            return False
        try:
            snapshot = json.loads(gate["result_json"])
        except json.JSONDecodeError:
            return False
        scene_refs = []
        legacy_scene_refs = []
        for scene in scenes:
            revision_id = scene["current_revision_id"]
            if not revision_id:
                return False
            revision = connection.execute(
                "SELECT content_hash FROM revisions WHERE id=?", (revision_id,)
            ).fetchone()
            if not revision:
                return False
            asset_references = self._scene_asset_reference_snapshot(
                connection, work_id, scene["id"]
            )
            scene_refs.append(
                {
                    "scene_id": scene["id"],
                    "revision_id": revision_id,
                    "content_hash": revision["content_hash"],
                    "asset_references": asset_references,
                    "asset_reference_digest": sha256_text(
                        canonical_json(asset_references)
                    ),
                }
            )
            legacy_scene_refs.append(
                {
                    "scene_id": scene["id"],
                    "revision_id": revision_id,
                    "content_hash": revision["content_hash"],
                }
            )

        dependencies = []
        for artifact in connection.execute(
            """SELECT kind,scope_type,scope_id,current_revision_id FROM artifacts
               WHERE work_id=? AND kind IN ('brief','story_blueprint','work_canon','world_bible','character_card')
                 AND current_revision_id IS NOT NULL ORDER BY kind,scope_id""",
            (work_id,),
        ).fetchall():
            revision = connection.execute(
                "SELECT content_hash FROM revisions WHERE id=?",
                (artifact["current_revision_id"],),
            ).fetchone()
            if not revision:
                return False
            dependencies.append(
                {
                    "kind": artifact["kind"],
                    "scope_type": artifact["scope_type"],
                    "scope_id": artifact["scope_id"],
                    "revision_id": artifact["current_revision_id"],
                    "content_hash": revision["content_hash"],
                }
            )

        memory = self._release_memory_snapshot(connection, work_id, scene_refs)
        work = connection.execute(
            "SELECT active_writing_pack_version FROM works WHERE id=?", (work_id,)
        ).fetchone()
        snapshot_scene_refs = snapshot.get("scene_revision_refs")
        scene_refs_current = snapshot_scene_refs == scene_refs
        # Gate snapshots written before asset references were introduced remain
        # readable, but only while the current scenes still have no references.
        legacy_scene_refs_current = (
            snapshot_scene_refs == legacy_scene_refs
            and all(not row["asset_references"] for row in scene_refs)
        )
        return bool(
            snapshot.get("scene_revision_ids") == [row["revision_id"] for row in scene_refs]
            and (scene_refs_current or legacy_scene_refs_current)
            and snapshot.get("dependency_refs") == dependencies
            and snapshot.get("memory_maintenance") == memory
            and snapshot.get("writing_pack_version") == work["active_writing_pack_version"]
        )

    @staticmethod
    def _scene_asset_reference_snapshot(connection, work_id: str, scene_id: str) -> list[dict]:
        rows = connection.execute(
            """SELECT * FROM scene_asset_references
               WHERE work_id=? AND scene_id=?
               ORDER BY CASE asset_kind
                 WHEN 'background' THEN 1 WHEN 'character' THEN 2
                 WHEN 'sound' THEN 3 ELSE 4 END, created_at, id""",
            (work_id, scene_id),
        ).fetchall()
        references = []
        for row in rows:
            references.append(
                {
                    "reference_id": row["id"],
                    "asset_kind": row["asset_kind"],
                    "source_type": row["source_type"],
                    "source_asset_id": row["source_asset_id"],
                    "display_name": row["display_name"],
                    "source_version": row["source_version"],
                    "content_hash": row["content_hash"],
                    "content_hash_kind": row["content_hash_kind"],
                    "source_snapshot": json.loads(row["source_snapshot_json"] or "{}"),
                    "production_copy": (
                        json.loads(row["production_copy_json"])
                        if row["production_copy_json"]
                        else None
                    ),
                }
            )
        return references

    @staticmethod
    def _release_memory_snapshot(connection, work_id: str, scene_refs: list[dict]) -> list[dict]:
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
        for scene in scene_refs:
            task = by_revision.get(scene["revision_id"], {})
            status = task.get("status") or "missing"
            result.append(
                {
                    "scene_id": scene["scene_id"],
                    "revision_id": scene["revision_id"],
                    "work_item_id": task.get("work_item_id"),
                    "status": status,
                    "decision": task.get("decision"),
                    "complete": status in {"succeeded", "skipped"},
                }
            )
        return result

    def _result(
        self,
        *,
        outcome: str,
        phase: str,
        headline: str,
        action: _Action,
        logical_step: str,
        secondary: list[_Action] | None = None,
        blockers: list[dict] | None = None,
        warnings: list[dict] | None = None,
        resume: dict | None = None,
        all_completed: bool = False,
    ) -> dict[str, Any]:
        steps = []
        ids = [step_id for step_id, _ in self._PROGRESS_STEPS]
        current_index = ids.index(logical_step)
        for index, (step_id, label) in enumerate(self._PROGRESS_STEPS):
            if all_completed or index < current_index:
                status = "completed"
            elif index == current_index:
                status = "blocked" if outcome == "blocked" else "current"
            else:
                status = "upcoming"
            steps.append({"id": step_id, "label": label, "status": status})
        decision_basis = {
            "agent_running": "已有运行中的工作项，先查看当前进度；已完成步骤不会重复执行。",
            "agent_recovery": "上一次运行失败，但固定输入仍可读取，先从该尝试恢复。",
            "proposal_review": "存在待审 Proposal，正式资料在你决定前不会改变。",
            "commit_projection": "正式 Revision 已保存，只有派生投影未完成，只补跑未完成项。",
            "brief": "当前作品还没有已确认的创意简报，先保存创作意图。",
            "blueprint": "创意简报已经确认，但 StoryBlueprint 还没有确认。",
            "structure": "作品方向已经确认，但还没有完整的可写章节或场景结构。",
            "scene_draft": "目标场景还没有当前正文修订，先装配可信上下文再生成候选。",
            "memory": "正文已经保存，但本场长期事实还没有完成审阅。",
            "release_review": "发布前的审查 Gate 还没有全部满足，先完成当前审查依赖。",
            "released": "ScriptRelease 已冻结，后续修改必须形成新的版本。",
        }.get(phase, "依据当前作品的正式产物状态和审查依赖。")
        return {
            "outcome": outcome,
            "phase": phase,
            "headline": headline,
            "decision_basis": decision_basis,
            "progress": {
                "completed": sum(item["status"] == "completed" for item in steps),
                "total": len(steps),
                "steps": steps,
            },
            "blockers": blockers or [],
            "warnings": warnings or [],
            "primary_action": action.as_dict(),
            "secondary_actions": [item.as_dict() for item in (secondary or [])],
            "resume": resume,
        }

    def _invalid_text_records(
        self,
        rows,
        *,
        uri_key: str = "content_uri",
        hash_key: str = "content_hash",
        id_key: str = "id",
    ) -> list[str]:
        broken = []
        for row in rows:
            try:
                content = self.repository.read_text(row[uri_key])
            except (OSError, UnicodeError, ValueError):
                broken.append(row[id_key])
                continue
            if sha256_text(content) != row[hash_key]:
                broken.append(row[id_key])
        return broken

    @staticmethod
    def _check(
        check_id: str,
        *,
        ok: bool,
        message: str,
        severity: str = "blocker",
        details: dict | None = None,
        impact: str = "",
        repair: str = "",
    ) -> dict[str, Any]:
        status = "ok" if ok else ("warning" if severity == "warning" else "error")
        return {
            "id": check_id,
            "status": status,
            "severity": "info" if ok else severity,
            "message": message,
            "details": details or {},
            "impact": "" if ok else impact,
            "repair": "" if ok else repair,
        }
