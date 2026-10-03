"""External hosts operate authorized works directly through existing Agent tools."""

from __future__ import annotations

import json
import secrets
from urllib.parse import urlencode

from .agent_tools import ToolExecutionContext
from .errors import DomainError
from .external_agents import ExternalAgentExchange
from .repository import canonical_json, new_id, now, sha256_text


class McpWorkspace:
    def __init__(self, service):
        self.service, self.repo = service, service.repo
        self.production = None

    def status(self):
        with self.repo.transaction() as db:
            row = db.execute(
                "SELECT * FROM mcp_connections WHERE status='active' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        works = [{"id": work["id"], "title": work["title"]} for work in self.service.list_works()]
        return {
            "schema_version": "halocue-mcp-connection/1.1",
            "connected": bool(row),
            "connection_id": row["id"] if row else None,
            "allowed_work_ids": json.loads(row["work_ids_json"]) if row else [],
            "works": works,
            "allowed_run_ids": json.loads(row["run_ids_json"]) if row else [],
            "productions": self.production.runs() if self.production else [],
            "capabilities": ["read_materials", "read_scene", "propose_scene_edit"]
            + (
                ["read_production", "read_production_resources", "propose_performance_edit"]
                if self.production
                else []
            ),
        }

    def connect(self, payload):
        ids = payload.get("work_ids", [])
        runs = payload.get("run_ids", [])
        if (
            set(payload) - {"work_ids", "run_ids"}
            or not isinstance(ids, list)
            or not isinstance(runs, list)
            or not (ids or runs)
            or len(ids) > 200
            or len(runs) > 200
            or any(not isinstance(item, str) for item in ids)
            or any(not isinstance(item, str) for item in runs)
            or len(set(ids)) != len(ids)
            or len(set(runs)) != len(runs)
        ):
            raise DomainError("mcp_scope_invalid", "请选择允许外部 Agent 访问的作品。")
        token, connection_id = secrets.token_urlsafe(32), new_id("mcp-connection")
        with self.repo.transaction() as db:
            if any(
                not db.execute("SELECT 1 FROM works WHERE id=?", (item,)).fetchone() for item in ids
            ):
                raise DomainError("mcp_scope_invalid", "授权作品不存在，请刷新后重新选择。")
            available_runs = (
                {run["id"] for run in self.production.runs()} if self.production else set()
            )
            if set(runs) - available_runs:
                raise DomainError("mcp_scope_invalid", "授权 AA 制作任务不存在，请刷新后重新选择。")
            db.execute("UPDATE mcp_connections SET status='revoked' WHERE status='active'")
            db.execute(
                "INSERT INTO mcp_connections (id,token_hash,work_ids_json,status,created_at,run_ids_json) VALUES (?,?,?,?,?,?)",
                (
                    connection_id,
                    sha256_text(token),
                    canonical_json(ids),
                    "active",
                    now(),
                    canonical_json(runs),
                ),
            )
            path = self._connection_path(connection_id)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(
                    canonical_json({"connection_id": connection_id, "token": token}),
                    encoding="utf-8",
                )
                temporary.chmod(0o600)
                temporary.replace(path)
            except OSError as error:
                raise DomainError(
                    "mcp_connection_unavailable",
                    "无法保存 MCP 连接，请检查用户数据目录。",
                    status=503,
                ) from error
        return self.status()

    @staticmethod
    def _connection_path(connection_id):
        from services.halocue.runtime_layout import integrated_data_root

        return integrated_data_root() / "mcp-connections" / f"{connection_id}.json"

    def disconnect(self):
        with self.repo.transaction() as db:
            db.execute("UPDATE mcp_connections SET status='revoked' WHERE status='active'")
        return self.status()

    def invalidate_after_restore(self):
        # A project backup must never resurrect a previously revoked capability.
        with self.repo.transaction() as db:
            db.execute("UPDATE mcp_connections SET status='revoked'")

    def config(self, endpoint, client=None):
        snapshot = self.status()
        if not snapshot["connected"]:
            raise DomainError("mcp_not_connected", "请先选择作品并启用 MCP 连接。", status=409)
        # Share the optional source runtime/loopback checks with file exchange,
        # without creating an editing task.
        runtime, script = ExternalAgentExchange.mcp_runtime(endpoint)
        path = self._connection_path(snapshot["connection_id"])
        if not path.is_file():
            raise DomainError(
                "mcp_connection_unavailable", "本机连接文件不可用，请重新启用连接。", status=409
            )
        config = {
            "mcpServers": {
                "halocue": {
                    "command": str(runtime),
                    "args": [
                        str(script),
                        "--workspace",
                        "--connection",
                        str(path),
                        "--endpoint",
                        endpoint.rstrip("/"),
                    ],
                    "env": {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                }
            }
        }
        if client is not None:
            from .mcp_client_config import client_profile

            return client_profile(config, client)
        return config

    def _authorize(self, db, connection_id, token):
        row = db.execute("SELECT * FROM mcp_connections WHERE id=?", (connection_id,)).fetchone()
        if (
            not row
            or row["status"] != "active"
            or not secrets.compare_digest(row["token_hash"], sha256_text(token or ""))
        ):
            raise DomainError("mcp_access_denied", "MCP 连接未启用或已断开。", status=403)
        return set(json.loads(row["work_ids_json"]))

    def call(self, connection_id, token, payload):
        if set(payload) != {"tool", "arguments"} or not isinstance(payload["arguments"], dict):
            raise DomainError("mcp_arguments_invalid", "工具调用格式无效。")
        tool, arguments = payload["tool"], payload["arguments"]
        fields = {
            "find_scenes": {"query", "offset"},
            "read_scene": {"scene_id", "start", "limit", "query"},
            "search_materials": {"scene_id", "kind", "query"},
            "propose_scene_edit": {"read_id", "edits", "reason"},
            "find_productions": {"query", "offset"},
            "read_production": {"run_id", "start", "limit", "query"},
            "search_production_resources": {"run_id", "kind", "query", "offset", "character"},
            "propose_performance_edit": {"read_id", "edits", "reason"},
        }
        if not isinstance(tool, str) or tool not in fields:
            raise DomainError("mcp_tool_denied", "该操作未开放给外部 MCP。", status=403)
        if set(arguments) - fields[tool]:
            raise DomainError("mcp_arguments_invalid", "工具含有未声明的参数。")
        with self.repo.transaction() as db:
            allowed = self._authorize(db, connection_id, token)
            if tool in {
                "find_productions",
                "read_production",
                "search_production_resources",
                "propose_performance_edit",
            }:
                if not self.production:
                    raise DomainError(
                        "mcp_production_unavailable",
                        "请在 HaloCue 一体化工作区使用 AA 制作连接。",
                        status=503,
                    )
                runs = json.loads(
                    db.execute(
                        "SELECT run_ids_json FROM mcp_connections WHERE id=?", (connection_id,)
                    ).fetchone()[0]
                )
                try:
                    return self.production.call(connection_id, runs, tool, arguments)
                except Exception as error:
                    from halocue_production.errors import ProductionError

                    if isinstance(error, ProductionError):
                        raise DomainError(
                            error.code, str(error), status=error.status, details=error.details
                        ) from error
                    raise
            if tool == "find_scenes":
                query = self._query(arguments).casefold()
                offset = arguments.get("offset", 0)
                if type(offset) is not int or offset < 0:
                    raise DomainError("mcp_arguments_invalid", "结果起点必须是非负整数。")
                matches = []
                for row in db.execute(
                    "SELECT s.*, w.title AS work_title, c.title AS chapter_title "
                    "FROM scenes s JOIN works w ON w.id=s.work_id "
                    "JOIN chapters c ON c.id=s.chapter_id "
                    "ORDER BY w.updated_at DESC,c.stable_order_key,s.stable_order_key"
                ):
                    if row["work_id"] not in allowed:
                        continue
                    if (
                        query
                        and query
                        not in " ".join(
                            row[key] for key in ("title", "work_title", "chapter_title")
                        ).casefold()
                    ):
                        continue
                    matches.append(
                        {
                            "scene_id": row["id"],
                            "title": row["title"],
                            "work": row["work_title"],
                            "chapter": row["chapter_title"],
                            "has_saved_text": bool(row["current_revision_id"]),
                            "view_path": self._view_path(row),
                        }
                    )
                return {
                    "scenes": matches[offset : offset + 40],
                    "total": len(matches),
                    "next_offset": offset + 40 if len(matches) > offset + 40 else None,
                }
            if tool == "propose_scene_edit":
                return self._propose(db, allowed, connection_id, payload)
            scene = self._scene(db, allowed, arguments.get("scene_id"))
            if tool == "search_materials":
                names = {
                    "character_card": "search_character_cards",
                    "world_bible": "search_world_bible",
                    "work_canon": "search_work_canon",
                }
                kind = arguments.get("kind", "character_card")
                if not isinstance(kind, str) or kind not in names:
                    raise DomainError("mcp_arguments_invalid", "资料类型无效。")
                return {
                    "items": self._execute(
                        self._context(db, scene["work_id"], "work", scene["work_id"]),
                        names[kind],
                        {"query": self._query(arguments)},
                    )
                }
            if not scene["current_revision_id"]:
                raise DomainError(
                    "mcp_scene_unsaved",
                    "该场尚无已保存正文，请在 HaloCue 保存正文后再读。",
                    status=409,
                )
            pending = db.execute(
                "SELECT id FROM proposals WHERE work_id=? AND scope_id=? "
                "AND kind='scene_script' AND status='pending' ORDER BY created_at DESC LIMIT 1",
                (scene["work_id"], scene["id"]),
            ).fetchone()
            args = {
                "base_revision_id": scene["current_revision_id"],
                "start": arguments.get("start", 1),
                "limit": arguments.get("limit", 20),
                "query": self._query(arguments),
            }
            if (
                type(args["start"]) is not int
                or args["start"] < 1
                or type(args["limit"]) is not int
                or not 1 <= args["limit"] <= 40
            ):
                raise DomainError("mcp_arguments_invalid", "起点至少为 1，每次读取 1–40 段。")
            if pending:
                args["replace_proposal_id"] = pending["id"]
            window = self._execute(
                self._context(db, scene["work_id"], "scene", scene["id"]),
                "read_scene_text_window",
                args,
            )
            read_id = new_id("mcp-read")
            db.execute(
                "INSERT INTO mcp_scene_reads VALUES (?,?,?,?,?)",
                (read_id, connection_id, scene["work_id"], scene["id"], canonical_json(window)),
            )
            return {
                "read_id": read_id,
                "scene": scene["title"],
                "source": "pending_candidate" if pending else "saved_manuscript",
                "paragraphs": [
                    {
                        "paragraph": block["paragraph_number"],
                        "type": block["type"],
                        "speaker": block.get("speaker"),
                        "text": block["text"],
                    }
                    for block in window["blocks"]
                ],
                "total_paragraphs": window["total_blocks"],
                "next_start": window["next_start"],
                "view_path": self._view_path(scene),
            }

    def _propose(self, db, allowed, connection_id, payload):
        arguments = payload["arguments"]
        read_id = arguments.get("read_id")
        if not isinstance(read_id, str):
            raise DomainError(
                "mcp_read_required", "请先读取场景，再引用返回的 read_id。", status=409
            )
        snapshot = db.execute(
            "SELECT * FROM mcp_scene_reads WHERE id=? AND connection_id=?", (read_id, connection_id)
        ).fetchone()
        if not snapshot:
            raise DomainError(
                "mcp_read_required", "读取记录不属于当前连接，请重新读取场景。", status=409
            )
        scene = self._scene(db, allowed, snapshot["scene_id"])
        digest = sha256_text(canonical_json(payload))
        receipt = db.execute(
            "SELECT proposal_id FROM mcp_edit_receipts WHERE connection_id=? AND input_hash=?",
            (connection_id, digest),
        ).fetchone()
        if receipt:
            return self._receipt(db, scene, receipt["proposal_id"], duplicate=True)
        window = json.loads(snapshot["window_json"])
        by_number = {block["paragraph_number"]: block for block in window["blocks"]}
        edits = arguments.get("edits")
        if not isinstance(edits, list) or not 1 <= len(edits) <= 40:
            raise DomainError("mcp_arguments_invalid", "每次提交 1–40 段修改。")
        patches = []
        for edit in edits:
            if (
                not isinstance(edit, dict)
                or set(edit) != {"paragraph", "text"}
                or type(edit["paragraph"]) is not int
                or edit["paragraph"] not in by_number
            ):
                raise DomainError(
                    "mcp_read_required", "只能修改这次读取到的段落；其他段落请先读取。", status=409
                )
            block = by_number[edit["paragraph"]]
            patches.append(
                {
                    "block_id": block["id"],
                    "old_text_sha256": block["text_sha256"],
                    "new_text": edit["text"],
                }
            )
        args = {
            "base_revision_id": window["base_revision_id"],
            "edits": patches,
            "reason": arguments.get("reason", "按作者要求修改正文。"),
        }
        if window.get("replace_proposal_id"):
            args["replace_proposal_id"] = window["replace_proposal_id"]
        prepared = self._execute(
            self._context(db, scene["work_id"], "scene", scene["id"]),
            "propose_scene_text_edit",
            args,
        )
        proposal_id = self.service._commit_scene_text_edit(
            db,
            scene["work_id"],
            prepared,
            {
                "provider": "external_agent",
                "transport": "workspace_mcp",
                "model": "external_host",
                "is_simulation": False,
                "usage_status": "not_reported",
            },
        )
        db.execute(
            "INSERT INTO mcp_edit_receipts VALUES (?,?,?)", (connection_id, digest, proposal_id)
        )
        return self._receipt(db, scene, proposal_id, duplicate=False)

    @staticmethod
    def _receipt(db, scene, proposal_id, *, duplicate):
        row = db.execute(
            "SELECT status,diff_json FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        return {
            "proposal_id": proposal_id,
            "status": row["status"],
            "duplicate": duplicate,
            "diff": json.loads(row["diff_json"]),
            "view_path": McpWorkspace._view_path(scene),
        }

    @staticmethod
    def _scene(db, allowed, scene_id):
        if not isinstance(scene_id, str):
            raise DomainError("mcp_arguments_invalid", "请引用找到的 scene_id。")
        row = db.execute("SELECT * FROM scenes WHERE id=?", (scene_id,)).fetchone()
        if not row or row["work_id"] not in allowed:
            raise DomainError(
                "mcp_scope_denied", "场景不存在或其作品未授权给当前连接。", status=403
            )
        return row

    @staticmethod
    def _query(arguments):
        query = arguments.get("query", "")
        if not isinstance(query, str) or len(query) > 500:
            raise DomainError("mcp_arguments_invalid", "检索词必须是最多 500 字的文本。")
        return query.strip()

    @staticmethod
    def _view_path(scene):
        return "/?" + urlencode(
            {
                "section": "writing",
                "stage": "draft",
                "work_id": scene["work_id"],
                "chapter_id": scene["chapter_id"],
                "scene_id": scene["id"],
            }
        )

    def _context(self, db, work_id, scope_type, scope_id):
        return ToolExecutionContext(
            connection=db,
            service=self.service,
            work_id=work_id,
            thread_id="",
            scope_type=scope_type,
            scope_id=scope_id,
            permission_mode="review",
            allowed_actions=frozenset({"read", "discuss"}),
            task_contract_id="scene.draft.rewrite",
        )

    def _execute(self, context, name, args):
        invalid = self.service.agent_tools._validate_arguments(
            self.service.agent_tools.get(name), args
        )
        if invalid:
            raise DomainError("mcp_arguments_invalid", invalid)
        result = self.service.agent_tools.execute(context, name, args)
        if result.status != "succeeded":
            raise DomainError(
                "mcp_tool_rejected",
                (result.error or {}).get("message", "工具操作未完成。"),
                status=409,
            )
        return result.output
