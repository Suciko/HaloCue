"""Bounded AA reads and author-reviewed performance proposals; no model calls."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

from .errors import ProductionError
from .legacy_adapter import _write_json_atomic
from .models import new_id

STATE = "mcp-performance.json"
JOURNAL = ".mcp-performance-transaction.json"
FILES = ("edited.txt", "identity.json", "diagnostics.json", "session.json", "resources.json", STATE)
FIELDS = {
    "find_productions": {"query", "offset"},
    "read_production": {"run_id", "start", "limit", "query"},
    "search_production_resources": {"run_id", "kind", "query", "offset", "character"},
    "propose_performance_edit": {"read_id", "edits", "reason"},
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def integer(args, key, default, low=0, high=1000000):
    value = args.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ProductionError("mcp_arguments_invalid", f"{key} 超出允许范围")
    return value


def query(args):
    value = args.get("query", "")
    if not isinstance(value, str) or len(value) > 500:
        raise ProductionError("mcp_arguments_invalid", "搜索内容过长或格式无效")
    return value.casefold()


class ProductionMcpWorkspace:
    def __init__(self, service):
        self.service = service
        self.adapter = service.adapter
        # Recover incomplete acceptances before any draft is exposed by the server.
        for run in service.repository.list_runs():
            if (
                run.draft_token
                and (self.adapter.store.get_draft_path(run.draft_token) / JOURNAL).exists()
            ):
                with self.adapter.store.draft_lock(run.draft_token):
                    self._recover(self.adapter.store.get_draft_path(run.draft_token))

    def runs(self):
        return [{"id": r.run_id, "title": r.project} for r in self.service.repository.list_runs()]

    def _run(self, run_id, allowed):
        if not isinstance(run_id, str) or run_id not in allowed:
            raise ProductionError("mcp_access_denied", "这个 AA 制作任务没有授权", status=403)
        return self.service._run(run_id)

    @staticmethod
    def _state(root):
        path = root / STATE
        return (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"reads": {}, "proposals": {}}
        )

    @staticmethod
    def _view(run_id):
        return "/?section=production&run_id=" + run_id + "&review=agent"

    def call(self, connection_id, allowed, tool, args):
        if set(args) - FIELDS[tool]:
            raise ProductionError("mcp_arguments_invalid", "工具含有未声明参数")
        if tool == "find_productions":
            needle, offset = query(args), integer(args, "offset", 0)
            matches = [
                {"run_id": r["id"], "title": r["title"], "view_path": self._view(r["id"])}
                for r in self.runs()
                if r["id"] in allowed and needle in r["title"].casefold()
            ]
            return {
                "productions": matches[offset : offset + 40],
                "total": len(matches),
                "next_offset": offset + 40 if len(matches) > offset + 40 else None,
            }
        if tool == "propose_performance_edit":
            read_id = args.get("read_id")
            if not isinstance(read_id, str) or not re.fullmatch(r"aa-read-[0-9a-f]{12}", read_id):
                raise ProductionError("mcp_read_required", "请先读取 AA 卡片")
            for run_id in allowed:
                run = self._run(run_id, allowed)
                root = self.adapter.store.get_draft_path(run.draft_token)
                with self.service._state_lock, self.adapter.store.draft_lock(run.draft_token):
                    self._recover(root)
                    state = self._state(root)
                    receipt_hash = digest({"connection": connection_id, "arguments": args})
                    for proposal in state["proposals"].values():
                        if proposal["input_hash"] == receipt_hash:
                            return {
                                **self._public(proposal),
                                "duplicate": True,
                                "view_path": self._view(run.run_id),
                            }
                    if read_id in state["reads"]:
                        return self._propose(run, root, state, connection_id, args)
            raise ProductionError("mcp_read_required", "读取记录不可用，请重新读取")
        run = self._run(args.get("run_id"), allowed)
        with self.adapter.store.draft_lock(run.draft_token):
            root = self.adapter.store.get_draft_path(run.draft_token)
            self._recover(root)
            if tool == "search_production_resources":
                kind = args.get("kind", "characters")
                if not isinstance(kind, str) or kind not in {
                    "characters",
                    "backgrounds",
                    "sounds",
                    "character_details",
                    "performance_choices",
                }:
                    raise ProductionError("mcp_arguments_invalid", "素材类型无效")
                if kind == "performance_choices":
                    from .service import DIRECTIVE_COMMANDS

                    resources = self.adapter._draft_resources(run.draft_token)
                    return {
                        "enums": resources.get("enums", {}),
                        "directive_commands": sorted(DIRECTIVE_COMMANDS - {"raw"}),
                    }
                if kind == "character_details":
                    character = self.service.run_character_resource(
                        run.run_id, args.get("character")
                    )
                    # Return frozen logical choices only; never resource file paths/bytes.
                    value = character["character"]
                    return {"character": {k: value.get(k) for k in ("identifier", "name", "faces")}}
                result = self.service.list_run_resources(
                    run.run_id, kind, query=query(args), offset=integer(args, "offset", 0), limit=40
                )
                return {
                    "items": [
                        {
                            k: v
                            for k, v in item.items()
                            if k
                            in {
                                "key",
                                "name",
                                "description",
                                "tags",
                                "usage_hint",
                                "category",
                                "club",
                            }
                        }
                        for item in result["items"]
                    ],
                    "total": result["total"],
                    "next_offset": result["offset"] + 40
                    if result["total"] > result["offset"] + 40
                    else None,
                }
            detail = self.adapter.draft_detail(run.draft_token)
            start, limit = integer(args, "start", 1, 1), integer(args, "limit", 20, 1, 40)
            needle = query(args)
            cards = [
                {"card": n, "kind": c["kind"], "fields": c["current"]}
                for n, c in enumerate(detail["cards"], 1)
                if n >= start and needle in json.dumps(c["current"], ensure_ascii=False).casefold()
            ]
            page = cards[:limit]
            state = self._state(root)
            read_id = new_id("aa-read")
            state["reads"][read_id] = {
                "connection_id": connection_id,
                "version": detail["draft_version"],
                "cards": {str(c["card"]): detail["cards"][c["card"] - 1] for c in page},
            }
            # Keep the most recent exact windows; old handles must be reread.
            state["reads"] = dict(list(state["reads"].items())[-200:])
            _write_json_atomic(root / STATE, state)
            cast = detail.get("cast", {}).get("cast", {})
            return {
                "read_id": read_id,
                "title": run.project,
                "cards": page,
                "cast": {
                    name: {k: value.get(k) for k in ("kind", "id", "name", "role")}
                    for name, value in cast.items()
                    if isinstance(value, dict)
                },
                "total_cards": len(detail["cards"]),
                "next_start": page[-1]["card"] + 1 if len(cards) > limit else None,
                "pending_proposals": [
                    self._public(p) for p in state["proposals"].values() if p["state"] == "pending"
                ],
                "view_path": self._view(run.run_id),
            }

    def _edits(self, run, detail, read, args):
        edits = args.get("edits")
        if not isinstance(edits, list) or not 1 <= len(edits) <= 40:
            raise ProductionError("mcp_arguments_invalid", "每次提交 1 到 40 项演出修改")
        normalized, seen = [], set()
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"card", "operation", "fields"}:
                raise ProductionError("mcp_arguments_invalid", "演出修改格式无效")
            number, operation, fields = edit["card"], edit["operation"], edit["fields"]
            if type(number) is not int or str(number) not in read["cards"]:
                raise ProductionError("mcp_unread_card", "只能修改刚刚读取的卡片或在其后插入指令")
            if (
                not isinstance(fields, dict)
                or not fields
                or any(
                    not isinstance(v, str) or len(v) > 2000 or any(c in v for c in "\r\n\x00")
                    for v in fields.values()
                )
            ):
                raise ProductionError("mcp_arguments_invalid", "演出字段须为单行文本")
            card = read["cards"][str(number)]
            if operation == "update":
                if number in seen:
                    raise ProductionError("mcp_arguments_invalid", "同一卡片的字段请合并提交")
                seen.add(number)
                allowed = (
                    {"face", "emo", "act", "fx"}
                    if card["kind"] == "line"
                    else {"cmd", "arg"}
                    if card["kind"] in {"dir", "background_request"}
                    else set()
                )
                if set(fields) - allowed:
                    raise ProductionError(
                        "mcp_performance_only", "演出操作不能改写冻结台词、说话者或结构"
                    )
                patch = self._patch(run, card, fields)
                if card["kind"] == "line":
                    self.service._validate_line_performance(run, detail, card, patch)
                before = card["current"]
            elif operation == "insert_after":
                if set(fields) != {"cmd", "arg"}:
                    raise ProductionError("mcp_arguments_invalid", "插入演出指令须提供 cmd 和 arg")
                patch = self._patch(run, {"kind": "dir", "current": {}}, fields)
                before = None
            else:
                raise ProductionError("mcp_arguments_invalid", "只支持 update 或 insert_after")
            if patch.get("cmd") == "raw":
                raise ProductionError("mcp_performance_only", "外部 Agent 不能插入原样 AA 代码")
            normalized.append(
                {
                    "card": number,
                    "card_id": card["card_id"],
                    "operation": operation,
                    "fields": patch,
                    "before": before,
                }
            )
        return normalized

    def _patch(self, run, card, fields):
        current = card.get("current") or {}
        command = fields.get("cmd", current.get("cmd", "")).strip().casefold()
        if card["kind"] == "background_request" and command != "bg":
            raise ProductionError("mcp_performance_only", "背景请求须选择背景或黑屏")
        if card["kind"] in {"dir", "background_request"} and command in {"bg", "se", "sound"}:
            key = fields.get("arg", current.get("arg", "")).strip()
            resources = self.adapter._draft_resources(run.draft_token)
            choices = (
                set(resources.get("bg") or {}) | {"BG_Black"}
                if command == "bg"
                else set(resources.get("sounds") or [])
            )
            if key not in choices:
                raise ProductionError(
                    "mcp_resource_not_frozen",
                    "所选素材不在当前任务冻结清单中，请先在 HC 选择素材",
                    status=409,
                )
            return {"cmd": command, "arg": key}
        return self.service._validated_card_patch(card, fields)

    def _propose(self, run, root, state, connection_id, args):
        read = state["reads"][args["read_id"]]
        if read["connection_id"] != connection_id:
            raise ProductionError("mcp_access_denied", "读取记录属于其他连接", status=403)
        key = digest({"connection": connection_id, "arguments": args})
        for proposal in state["proposals"].values():
            if proposal["input_hash"] == key:
                return {
                    **self._public(proposal),
                    "duplicate": True,
                    "view_path": self._view(run.run_id),
                }
        detail = self.adapter.draft_detail(run.draft_token)
        if read["version"] != detail["draft_version"]:
            raise ProductionError("mcp_read_stale", "演出草稿已变化，请重新读取卡片", status=409)
        reason = args.get("reason", "按作者要求调整演出")
        if not isinstance(reason, str) or not 1 <= len(reason) <= 2000:
            raise ProductionError("mcp_arguments_invalid", "请简述修改原因")
        edits = self._edits(run, detail, read, args)
        proposal = {
            "proposal_id": new_id("prop"),
            "input_hash": key,
            "version": read["version"],
            "state": "pending",
            "reason": reason,
            "edits": edits,
        }
        state["proposals"][proposal["proposal_id"]] = proposal
        _write_json_atomic(root / STATE, state)
        return {**self._public(proposal), "duplicate": False, "view_path": self._view(run.run_id)}

    @staticmethod
    def _public(proposal):
        return {k: proposal[k] for k in ("proposal_id", "state", "reason")} | {
            "changes": [
                {
                    "card": e["card"],
                    "operation": e["operation"],
                    "before": e["before"],
                    "after": e["fields"],
                }
                for e in proposal["edits"]
            ]
        }

    def proposals(self, run, version=None):
        with self.adapter.store.draft_lock(run.draft_token):
            root = self.adapter.store.get_draft_path(run.draft_token)
            self._recover(root)
            if not (root / STATE).exists():
                return []
            if version is None:
                version = self.adapter.draft_detail(run.draft_token)["draft_version"]
            return [
                {
                    **self._public(p),
                    "can_apply_safely": p["state"] == "pending" and p["version"] == version,
                }
                for p in self._state(root)["proposals"].values()
            ]

    def decide(self, run, proposal_id, payload):
        with self.service._state_lock, self.adapter.store.draft_lock(run.draft_token):
            root = self.adapter.store.get_draft_path(run.draft_token)
            self._recover(root)
            state = self._state(root)
            proposal = state["proposals"].get(proposal_id)
            if not proposal:
                return False
            action = payload.get("action")
            if action not in {"approve", "reject"}:
                raise ProductionError("invalid_proposal_action", "请选择采用或拒绝")
            if proposal["state"] != "pending":
                if proposal["state"] == ("approved" if action == "approve" else "rejected"):
                    return True
                raise ProductionError("proposal_already_decided", "建议已经处理", status=409)
            if action == "reject":
                proposal["state"] = "rejected"
                _write_json_atomic(root / STATE, state)
                return True
            detail = self.adapter.draft_detail(run.draft_token)
            if (
                self.service._expected_version(payload) != detail["draft_version"]
                or proposal["version"] != detail["draft_version"]
            ):
                raise ProductionError(
                    "proposal_stale", "演出草稿已变化，请重新提出建议", status=409
                )
            if self.service._active_mutation_job(run):
                raise ProductionError("run_busy", "请等待当前演出生成完成再采用建议", status=409)
            # Revalidate against frozen mappings before any write.
            read = {
                "cards": {str(e["card"]): detail["cards"][e["card"] - 1] for e in proposal["edits"]}
            }
            self._edits(
                run,
                detail,
                read,
                {
                    "edits": [
                        {k: e[k] for k in ("card", "operation", "fields")}
                        for e in proposal["edits"]
                    ]
                },
            )
            _write_json_atomic(
                root / JOURNAL,
                {
                    name: base64.b64encode((root / name).read_bytes()).decode()
                    if (root / name).exists()
                    else None
                    for name in FILES
                },
            )
            try:
                version = detail["draft_version"]
                inserted = {}
                for edit in proposal["edits"]:
                    if edit["operation"] == "update":
                        target = next(c for c in detail["cards"] if c["card_id"] == edit["card_id"])
                        if target["kind"] == "background_request":
                            result = self.adapter.resolve_background(
                                token=run.draft_token,
                                card_id=edit["card_id"],
                                background_key=edit["fields"]["arg"],
                                expected_draft_version=version,
                            )
                        else:
                            result = self.adapter.update_card(
                                token=run.draft_token,
                                card_id=edit["card_id"],
                                patch=edit["fields"],
                                expected_draft_version=version,
                            )
                    else:
                        anchor = inserted.get(edit["card_id"], edit["card_id"])
                        before_ids = {
                            c["card_id"]
                            for c in self.adapter.draft_detail(run.draft_token)["cards"]
                        }
                        result = self.adapter.insert_card(
                            token=run.draft_token,
                            after_card_id=anchor,
                            kind="dir",
                            fields=edit["fields"],
                            expected_draft_version=version,
                        )
                        inserted[edit["card_id"]] = next(
                            c["card_id"] for c in result["cards"] if c["card_id"] not in before_ids
                        )
                    version = result["draft_version"]
                proposal["state"] = "approved"
                _write_json_atomic(root / STATE, state)
                self.service._mark_draft_changed(run)
                (root / JOURNAL).unlink()
            except Exception:
                self._recover(root)
                raise
            return True

    @staticmethod
    def _recover(root: Path):
        journal = root / JOURNAL
        if not journal.exists():
            return
        images = json.loads(journal.read_text(encoding="utf-8"))
        if set(images) != set(FILES):
            raise ProductionError("mcp_recovery_failed", "演出建议恢复记录无效", status=500)
        for name in FILES:
            value = images[name]
            path = root / name
            if value is None:
                path.unlink(missing_ok=True)
            else:
                temporary = path.with_suffix(path.suffix + ".recover.tmp")
                temporary.write_bytes(base64.b64decode(value, validate=True))
                os.replace(temporary, path)
        journal.unlink()
