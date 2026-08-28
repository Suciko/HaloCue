"""Durable, permission-aware tools for the writing Agent.

Tools are deliberately small and side-effect free. Formal artifacts are never
mutated here; a proposal is the only write boundary exposed to the Agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .repository import canonical_json, sha256_text


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: str = "low"
    allowed_modes: frozenset[str] = frozenset({"review", "managed"})
    allowed_scopes: frozenset[str] = frozenset({"work", "chapter", "scene"})
    mutates_formal_data: bool = False
    requires_user_confirmation: bool = False
    required_action: str = "read"


@dataclass
class ToolExecutionContext:
    connection: Any
    service: Any
    work_id: str
    thread_id: str
    scope_type: str
    scope_id: str
    permission_mode: str
    history: list[dict[str, Any]] = field(default_factory=list)
    allowed_actions: frozenset[str] = frozenset({"read", "discuss"})
    policy_status: str = "active"


@dataclass
class PermissionDecision:
    allowed: bool
    reason: str
    status: str = "allowed"


@dataclass
class ToolExecutionResult:
    tool: str
    status: str
    label: str
    output: Any = None
    error: dict[str, Any] | None = None
    input_digest: str = ""
    requires_user_confirmation: bool = False

    def activity(self) -> dict[str, Any]:
        value = self._summary()
        return {
            "tool": self.tool,
            "label": self.label,
            "status": self.status,
            "output": str(value or "")[:240],
            "requires_user_confirmation": self.requires_user_confirmation,
        }

    def _summary(self) -> str:
        value = self.output
        if isinstance(value, list):
            return f"找到 {len(value)} 项结果"
        if not isinstance(value, dict):
            return str(value or "")[:240]
        if "artifacts" in value and isinstance(value["artifacts"], list):
            return f"已读取 {len(value['artifacts'])} 项正式资料"
        if value.get("status") == "discussion_draft":
            return f"已生成「{value.get('title') or '资料'}」讨论草稿"
        if value.get("next") == "user_confirmation":
            return "等待用户确认后创建 Proposal"
        if "conflicts" in value and isinstance(value["conflicts"], list):
            return "未发现重复资料" if not value["conflicts"] else f"发现 {len(value['conflicts'])} 项重复或冲突"
        if "scope" in value:
            return {"work": "作品全局", "chapter": "当前章节", "scene": "当前场景"}.get(str(value["scope"]), str(value["scope"]))
        if "count" in value:
            return f"已处理 {value['count']} 项"
        return canonical_json(value)[:240]


Handler = Callable[[ToolExecutionContext, dict[str, Any]], Any]


class AgentToolRegistry:
    """Registry and dispatcher shared by Fake and real Providers."""

    def __init__(self, service: Any):
        self.service = service
        self._tools: dict[str, tuple[ToolSpec, Handler]] = {}
        self._register_defaults()

    def register(self, spec: ToolSpec, handler: Handler) -> None:
        self._tools[spec.name] = (spec, handler)

    def specs(self) -> list[ToolSpec]:
        return [pair[0] for pair in self._tools.values()]

    def get(self, name: str) -> ToolSpec | None:
        pair = self._tools.get(name)
        return pair[0] if pair else None

    def permission(self, spec: ToolSpec | None, context: ToolExecutionContext) -> PermissionDecision:
        if spec is None:
            return PermissionDecision(False, "工具未注册。", "denied")
        if context.policy_status != "active":
            return PermissionDecision(False, "Agent 授权已经失效。", "denied")
        if context.permission_mode not in spec.allowed_modes:
            return PermissionDecision(False, "当前 Agent 授权模式不允许此工具。", "denied")
        if spec.required_action not in context.allowed_actions:
            return PermissionDecision(False, "当前 Agent 授权不包含此操作。", "denied")
        if context.scope_type not in spec.allowed_scopes:
            return PermissionDecision(False, "工具不属于当前对话作用域。", "denied")
        if spec.mutates_formal_data:
            return PermissionDecision(False, "正式资料必须通过 Proposal 并由用户确认。", "waiting_user")
        return PermissionDecision(True, "允许执行。")

    def execute(self, context: ToolExecutionContext, name: str, arguments: dict[str, Any] | None = None) -> ToolExecutionResult:
        arguments = arguments if isinstance(arguments, dict) else {}
        spec_handler = self._tools.get(name)
        spec = spec_handler[0] if spec_handler else None
        digest = sha256_text(canonical_json(arguments))
        if not spec_handler:
            return ToolExecutionResult(name, "failed", name, error={"code": "tool_not_found", "message": "工具未注册。"}, input_digest=digest)
        validation_error = self._validate_arguments(spec, arguments)
        if validation_error:
            return ToolExecutionResult(
                name, "failed", spec.description,
                error={"code": "tool_invalid_arguments", "message": validation_error}, input_digest=digest,
            )
        decision = self.permission(spec, context)
        if not decision.allowed:
            return ToolExecutionResult(
                name, decision.status, spec.description, error={"code": "permission_denied", "message": decision.reason},
                input_digest=digest, requires_user_confirmation=decision.status == "waiting_user",
            )
        if spec.requires_user_confirmation:
            return ToolExecutionResult(
                name, "waiting_user", spec.description,
                output={"next": "user_confirmation"}, input_digest=digest,
                requires_user_confirmation=True,
            )
        try:
            output = spec_handler[1](context, arguments)
            return ToolExecutionResult(name, "succeeded", spec.description, output=output, input_digest=digest)
        except Exception as exc:
            return ToolExecutionResult(name, "failed", spec.description, error={"code": "tool_failed", "type": type(exc).__name__, "message": str(exc)[:240]}, input_digest=digest)

    @staticmethod
    def _validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> str | None:
        schema = spec.input_schema if isinstance(spec.input_schema, dict) else {}
        return AgentToolRegistry._validate_value(arguments, schema, "参数")

    @staticmethod
    def _validate_value(value: Any, schema: dict[str, Any], path: str) -> str | None:
        expected_types = {"string": str, "integer": int, "object": dict, "array": list, "boolean": bool}
        expected_name = schema.get("type")
        expected = expected_types.get(expected_name)
        if expected and (not isinstance(value, expected) or expected is int and isinstance(value, bool)):
            return f"{path}类型应为 {expected_name}"
        if "enum" in schema and value not in schema.get("enum", []):
            return f"{path}不在允许值范围内"
        if expected_name == "string":
            if len(value) < int(schema.get("minLength", 0)):
                return f"{path}不能为空"
            if "maxLength" in schema and len(value) > int(schema["maxLength"]):
                return f"{path}过长"
        if expected_name == "array":
            if len(value) < int(schema.get("minItems", 0)):
                return f"{path}项目不足"
            item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else None
            if item_schema:
                for index, item in enumerate(value):
                    error = AgentToolRegistry._validate_value(item, item_schema, f"{path}[{index}]")
                    if error:
                        return error
        if expected_name == "object":
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required = schema.get("required") if isinstance(schema.get("required"), list) else []
            for name in required:
                if name not in value or value[name] is None:
                    return f"缺少必填参数：{name}"
            if schema.get("additionalProperties") is False:
                extra = sorted(set(value).difference(properties))
                if extra:
                    return f"包含未声明参数：{', '.join(extra)}"
            for name, item in value.items():
                rule = properties.get(name)
                if isinstance(rule, dict):
                    error = AgentToolRegistry._validate_value(item, rule, f"参数 {name}")
                    if error:
                        return error
        return None

    def _register_defaults(self) -> None:
        # Compatible models sometimes attach a short rationale to a read-only
        # tool call. It is audit-only metadata and must never affect execution.
        read_schema = {
            "type": "object",
            "properties": {"reason": {"type": "string", "maxLength": 500}},
            "additionalProperties": False,
        }
        short_string_list = {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 240},
        }
        source_ref_list = {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        }
        relationship_schema = {
            "type": "object",
            "properties": {
                "target": {"type": "string", "minLength": 1, "maxLength": 120},
                "kind": {"type": "string", "maxLength": 120},
                "summary": {"type": "string", "maxLength": 1000},
                "status": {
                    "type": "string",
                    "enum": ["confirmed", "inferred", "open", "conflict"],
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        }
        character_draft_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "canonical_name": {"type": "string", "minLength": 1, "maxLength": 80},
                "aliases": short_string_list,
                "summary": {"type": "string", "maxLength": 2000},
                "role": {"type": "string", "maxLength": 2000},
                "voice_anchors": short_string_list,
                "knowledge_boundary": {"type": "string", "maxLength": 3000},
                "ooc_constraints": short_string_list,
                "relationships": {"type": "array", "items": relationship_schema},
                "source_refs": source_ref_list,
                "source_type": {"type": "string", "enum": ["official_reference", "custom"]},
                "trust_status": {
                    "type": "string",
                    "enum": ["confirmed", "inferred", "open", "unverified", "conflict"],
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        }
        world_draft_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "kind": {
                    "type": "string",
                    "enum": ["place", "academy", "organization", "object", "technology", "custom"],
                },
                "summary": {"type": "string", "maxLength": 3000},
                "aliases": short_string_list,
                "source": {"type": "string", "maxLength": 500},
                "source_refs": source_ref_list,
                "source_type": {
                    "type": "string",
                    "enum": ["official_reference", "custom", "mixed", "ba_starter"],
                },
                "confidence_status": {
                    "type": "string",
                    "enum": ["confirmed", "inferred", "open", "conflict", "retired"],
                },
                "scope": {"type": "string", "enum": ["work", "chapter", "scene"]},
                "participants": short_string_list,
                "related_world_ids": short_string_list,
            },
            "required": ["name"],
            "additionalProperties": False,
        }
        world_rule_draft_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 120},
                "text": {"type": "string", "minLength": 1, "maxLength": 3000},
                "scope": {"type": "string", "enum": ["work", "chapter", "scene"]},
                "exceptions": short_string_list,
                "source": {"type": "string", "maxLength": 500},
                "source_refs": source_ref_list,
                "confidence_status": {
                    "type": "string",
                    "enum": ["confirmed", "inferred", "open", "conflict", "retired"],
                },
            },
            "required": ["name", "text"],
            "additionalProperties": False,
        }
        self.register(ToolSpec("load_workflow_template", "加载当前阶段任务契约", read_schema), lambda c, a: {"scope": c.scope_type})
        self.register(ToolSpec("read_work_context", "读取当前作品正式上下文", read_schema), self._read_work_context)
        self.register(ToolSpec("read_conversation_history", "读取当前对话历史", read_schema), lambda c, a: c.history[-12:])
        self.register(ToolSpec("search_character_cards", "检索当前作品人物卡", {"type": "object", "properties": {"query": {"type": "string"}}}), self._search_artifact("character_card"))
        self.register(ToolSpec("search_world_bible", "检索当前作品世界观", {"type": "object", "properties": {"query": {"type": "string"}}}), self._search_artifact("world_bible"))
        self.register(ToolSpec("search_work_canon", "检索当前作品事实", {"type": "object", "properties": {"query": {"type": "string"}}}), self._search_artifact("work_canon"))
        self.register(ToolSpec("draft_character_card", "生成角色卡讨论草稿", character_draft_schema, required_action="discuss"), self._draft_character)
        self.register(ToolSpec("draft_world_card", "生成世界观讨论草稿", world_draft_schema, required_action="discuss"), self._draft_world)
        self.register(ToolSpec("draft_world_rule", "生成世界规则讨论草稿", world_rule_draft_schema, required_action="discuss"), self._draft_world_rule)
        self.register(ToolSpec("draft_canon_fact", "生成作品事实讨论草稿", {
            "type": "object",
            "properties": {
                "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                "source_refs": source_ref_list,
                "fact_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "operation": {"type": "string", "enum": ["create", "update", "retire"]},
                "scope": {"type": "string", "enum": ["work", "chapter", "scene"]},
                "source": {"type": "string", "minLength": 1, "maxLength": 500},
            },
            "required": ["text"],
            "additionalProperties": False,
        }, required_action="discuss"), self._draft_fact)
        self.register(ToolSpec("check_knowledge_conflicts", "检查资料重复与冲突", {"type": "object", "properties": {"kind": {"type": "string", "enum": ["character_card", "world_card", "world_rule", "canon_fact"]}, "content": {"type": "object"}}, "required": ["kind", "content"], "additionalProperties": False}), self._check_conflicts)
        self.register(ToolSpec("create_knowledge_proposal", "整理资料候选 Proposal", {"type": "object", "properties": {"kind": {"type": "string", "enum": ["character_card", "world_card", "world_rule", "canon_fact"]}}, "required": ["kind"], "additionalProperties": False}, risk="medium", requires_user_confirmation=True, required_action="discuss"), lambda c, a: {"next": "user_confirmation"})
        self.register(ToolSpec("store_conversation_attachments", "保存对话附件", {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]}), lambda c, a: {"count": int(a.get("count", 0))})

    def _read_work_context(self, context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        rows = context.connection.execute("SELECT kind,scope_type,scope_id,current_revision_id FROM artifacts WHERE work_id=?", (context.work_id,)).fetchall()
        result = []
        for row in rows:
            item = {"kind": row["kind"], "scope_type": row["scope_type"], "scope_id": row["scope_id"]}
            if row["current_revision_id"]:
                revision = context.connection.execute("SELECT content_uri FROM revisions WHERE id=?", (row["current_revision_id"],)).fetchone()
                if revision:
                    item["content"] = __import__("json").loads(context.service.repo.read_text(revision["content_uri"]))
            result.append(item)
        return {"artifacts": result}

    def _search_artifact(self, kind: str) -> Handler:
        def handler(context: ToolExecutionContext, arguments: dict[str, Any]) -> list[dict[str, Any]]:
            query = str(arguments.get("query", "")).strip().lower()
            projected = context.service.search_commit_projections(
                context.work_id,
                query,
                artifact_kinds=[kind],
                limit=12,
            )
            if projected["results"]:
                return [
                    {
                        "kind": item["source"]["kind"],
                        "scope_type": item["source"]["scope_type"],
                        "scope_id": item["source"]["scope_id"],
                        "revision_id": item["source"]["revision_id"],
                        "content_hash": item["source"]["content_hash"],
                        "content": item["content"],
                        "matched_terms": item["matched_terms"],
                        "source": "commit_projection_search",
                    }
                    for item in projected["results"]
                ]
            # A pending or failed replaceable index must never hide formal data.
            data = self._read_work_context(context, {})["artifacts"]
            return [item for item in data if item["kind"] == kind and (not query or query in canonical_json(item).lower())]
        return handler

    @staticmethod
    def _draft_character(context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name", "")).strip() or "待命名角色"
        content = {
            "name": name,
            "source_type": str(arguments.get("source_type") or "custom"),
            "trust_status": str(arguments.get("trust_status") or "open"),
        }
        for field_name in ("canonical_name", "summary", "role", "knowledge_boundary"):
            if field_name in arguments:
                content[field_name] = str(arguments[field_name]).strip()
        for field_name in ("aliases", "voice_anchors", "ooc_constraints", "source_refs"):
            if field_name in arguments:
                content[field_name] = [str(item).strip() for item in arguments[field_name]]
        if "relationships" in arguments:
            content["relationships"] = [
                {
                    key: str(item[key]).strip()
                    for key in ("target", "kind", "summary", "status")
                    if key in item
                }
                for item in arguments["relationships"]
            ]
        return {"kind": "character_card", "title": name, "status": "discussion_draft", "content": content}

    @staticmethod
    def _draft_world(context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name", "")).strip() or "世界观设定草稿"
        content = {
            "name": name,
            "kind": str(arguments.get("kind") or "custom"),
            "source_type": str(arguments.get("source_type") or "custom"),
            "confidence_status": str(arguments.get("confidence_status") or "open"),
            "scope": str(arguments.get("scope") or "work"),
        }
        for field_name in ("summary", "source"):
            if field_name in arguments:
                content[field_name] = str(arguments[field_name]).strip()
        for field_name in ("aliases", "source_refs", "participants", "related_world_ids"):
            if field_name in arguments:
                content[field_name] = [str(item).strip() for item in arguments[field_name]]
        return {"kind": "world_card", "title": name, "status": "discussion_draft", "content": content}

    @staticmethod
    def _draft_world_rule(context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        name = str(arguments.get("name", "")).strip() or "世界规则草稿"
        content = {
            "name": name,
            "text": str(arguments.get("text", "")).strip(),
            "scope": str(arguments.get("scope") or "work"),
            "confidence_status": str(arguments.get("confidence_status") or "open"),
        }
        for field_name in ("source",):
            if field_name in arguments:
                content[field_name] = str(arguments[field_name]).strip()
        for field_name in ("exceptions", "source_refs"):
            if field_name in arguments:
                content[field_name] = [str(item).strip() for item in arguments[field_name]]
        return {"kind": "world_rule", "title": name, "status": "discussion_draft", "content": content}

    @staticmethod
    def _draft_fact(context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        text = str(arguments.get("text", "")).strip()
        source_refs = [str(item).strip() for item in arguments.get("source_refs", []) if str(item).strip()]
        operation = str(arguments.get("operation") or "create").strip()
        content = {
            "text": text,
            "source_refs": source_refs,
            "operation": operation,
        }
        for field_name in ("fact_id", "scope", "source"):
            if str(arguments.get(field_name) or "").strip():
                content[field_name] = str(arguments[field_name]).strip()
        if operation == "create":
            content.setdefault("source", source_refs[0] if source_refs else "作品主对话（待确认）")
            content.setdefault("scope", "work")
            content["confidence_status"] = "open"
        return {
            "kind": "canon_fact",
            "title": "作品事实",
            "status": "discussion_draft",
            "content": content,
        }

    @staticmethod
    def _check_conflicts(context: ToolExecutionContext, arguments: dict[str, Any]) -> dict[str, Any]:
        kind = str(arguments.get("kind") or "")
        content = arguments.get("content") if isinstance(arguments.get("content"), dict) else {}
        conflicts = context.service._knowledge_conflicts(context.connection, context.work_id, kind, content)
        return {"conflicts": conflicts, "count": len(conflicts)}
