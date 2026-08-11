# -*- coding: utf-8 -*-
"""
可插拔的 LLM 接入层。

两个实现：
  anthropic  —— 官方 anthropic SDK，带 prompt caching（资源表只在首次计费）
  openai     —— OpenAI 兼容接口，换 base_url 即可打 GPT / DeepSeek / GLM / Kimi / Qwen

统一入口 Provider.complete_json(static_system, volatile_system, user, schema) -> dict
static_system 是跨请求不变的部分（资源表），会被缓存；volatile_system 放会变的内容。
加新家只要再写一个 Provider 子类并在 make_provider 里登记。
"""
import json, os, sys, time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from model_capabilities import normalize_remote_model_record


class LLMError(RuntimeError):
    pass


class EmptyModelResponseError(LLMError):
    """The provider stopped normally without returning visible content."""

    code = "empty_response"

    def __init__(self, message: str, *, finish_reason: str = "unknown", reasoning_chars: int = 0, content_chars: int = 0):
        super().__init__(message)
        self.finish_reason = finish_reason
        self.reasoning_chars = int(reasoning_chars or 0)
        self.content_chars = int(content_chars or 0)


class StructuredOutputError(LLMError):
    """The provider response is not the JSON shape requested by the caller."""


class OutputCapacityError(StructuredOutputError):
    """The provider stopped because the configured output budget was exhausted."""


class UnsupportedResponseFormatError(LLMError):
    """The OpenAI-compatible endpoint rejected the response_format field."""


class RequestDeadlineError(LLMError):
    """The provider kept streaming past the product-level request wall clock."""


def _emit_activity(callback, state, **fields):
    if callback:
        callback({"state": state, **fields})


def _schema_error(path: str, detail: str) -> StructuredOutputError:
    return StructuredOutputError(f"结构化返回不符合 schema：{path} {detail}")


def _matches_schema_type(value, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def _validate_schema_value(value, schema, path: str) -> None:
    if not isinstance(schema, dict):
        raise _schema_error(path, "schema 无效")
    expected = schema.get("type")
    if isinstance(expected, list):
        if not expected or not any(_matches_schema_type(value, item) for item in expected):
            raise _schema_error(path, "type is outside the allowed range")
        if value is None:
            return
        expected = next(item for item in expected if _matches_schema_type(value, item))
    if expected == "object":
        if not isinstance(value, dict):
            raise _schema_error(path, "应为 object")
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                raise _schema_error(f"{path}.{name}", "缺少必需字段")
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise _schema_error(f"{path}.{unknown[0]}", "不允许的字段")
        for name, child_schema in properties.items():
            if name in value:
                _validate_schema_value(value[name], child_schema, f"{path}.{name}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise _schema_error(path, "应为 array")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_schema_value(item, item_schema, f"{path}[{index}]")
        return
    if expected == "string" and not isinstance(value, str):
        raise _schema_error(path, "应为 string")
    if expected == "boolean" and not isinstance(value, bool):
        raise _schema_error(path, "应为 boolean")
    if expected == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise _schema_error(path, "应为 number")
    if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise _schema_error(path, "应为 integer")
    if expected == "null" and value is not None:
        raise _schema_error(path, "应为 null")
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise _schema_error(path, "值不在允许范围内")


def validate_json_schema(value, schema):
    """Validate a parsed provider response without requiring jsonschema."""
    _validate_schema_value(value, schema, "$response")
    return value


def parse_and_validate_json_response(text, schema, prefix="调用"):
    try:
        value = parse_json_response(text)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StructuredOutputError(f"{prefix}没有返回合法 JSON") from exc
    return validate_json_schema(value, schema)


def parse_json_response(text):
    """Parse a structured-model response, accepting one complete JSON fence.

    Some OpenAI-compatible services return a Markdown ``json`` fence even
    when asked for a JSON schema.  The schema validation still happens after
    parsing; this helper only removes wrapping syntax, never extracts a JSON
    fragment from arbitrary prose.
    """
    value = (text or "").strip()
    lines = value.splitlines()
    if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
        value = "\n".join(lines[1:-1]).strip()
    return json.loads(value)


class Provider:
    name = "?"
    max_request_records = 50

    def __init__(self, cfg):
        self.cfg = cfg
        self.model = cfg.get("model") or ""
        self.request_records = []
        self.reasoning_records = []
        self._request_metadata = {}
        self.stats = {
            "in": 0,
            "out": 0,
            "cache_read": 0,
            "cache_miss": 0,
            "cache_write": 0,
            "cache_reports": 0,
            "calls": 0,
        }

    def _key(self):
        direct = str(self.cfg.get("api_key") or "").strip()
        if direct:
            return direct
        env = self.cfg.get("api_key_env") or ""
        key = os.environ.get(env, "").strip()
        if not key:
            raise LLMError(
                f"环境变量 {env} 没设。\n"
                f"  PowerShell:  $env:{env} = \"你的key\"\n"
                f"  Git Bash:    export {env}=你的key")
        return key

    def complete_json(self, static_system, volatile_system, user, schema):
        raise NotImplementedError

    @contextmanager
    def temporary_reasoning_mode(self, mode):
        previous = self.cfg.get("reasoning_mode")
        self.cfg["reasoning_mode"] = mode
        try:
            yield
        finally:
            if previous is None:
                self.cfg.pop("reasoning_mode", None)
            else:
                self.cfg["reasoning_mode"] = previous

    @contextmanager
    def temporary_output_budget(self, max_tokens):
        previous = self.cfg.get("_output_budget_override")
        self.cfg["_output_budget_override"] = max(1, int(max_tokens))
        try:
            yield
        finally:
            if previous is None:
                self.cfg.pop("_output_budget_override", None)
            else:
                self.cfg["_output_budget_override"] = previous

    def complete_json_stream(
        self, static_system, volatile_system, user, schema, *, on_activity=None,
    ):
        started_ms = int(time.time() * 1000)
        _emit_activity(
            on_activity,
            "waiting",
            model=self.model,
            request_started_at_ms=started_ms,
            elapsed_ms=0,
            first_delta_ms=None,
            received_chars=0,
            finish_reason="",
        )
        result = self.complete_json(static_system, volatile_system, user, schema)
        _emit_activity(
            on_activity,
            "completed",
            model=self.model,
            request_started_at_ms=started_ms,
            elapsed_ms=max(0, int(time.time() * 1000) - started_ms),
            first_delta_ms=None,
            received_chars=0,
            finish_reason="unknown",
        )
        return result

    def complete_json_vision(self, system, images, user, schema):
        """images = [(标识, jpeg_bytes), ...]"""
        raise NotImplementedError

    def list_model_records(self):
        raise LLMError(f"{self.name} 接口不支持读取模型列表")

    def list_models(self):
        """Compatibility view for callers that only need model IDs."""
        return sorted({
            str(record.get("id") or "")
            for record in self.list_model_records()
            if str(record.get("id") or "")
        })

    def report(self):
        s = self.stats
        out = (f"{self.name}/{self.model}  调用 {s['calls']} 次  "
               f"输入 {s['in']:,}  输出 {s['out']:,}")
        if s["cache_read"] or s["cache_write"]:
            out += f"  缓存读 {s['cache_read']:,}  缓存写 {s['cache_write']:,}"
        return out

    def _append_request_record(self, record):
        safe = dict(record or {})
        safe["request_index"] = int(self.stats.get("calls") or 0)
        self.request_records.append(safe)
        if len(self.request_records) > self.max_request_records:
            del self.request_records[:-self.max_request_records]

    def _append_reasoning_record(self, record):
        safe = dict(record or {})
        self.reasoning_records.append(safe)
        if len(self.reasoning_records) > self.max_request_records:
            del self.reasoning_records[:-self.max_request_records]


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider(Provider):
    name = "anthropic"
    supports_compact_annotation = True

    def __init__(self, cfg):
        super().__init__(cfg)
        try:
            import anthropic
        except ImportError:
            raise LLMError("没装 anthropic SDK，先跑:  pip install anthropic")
        self._sdk = anthropic
        client_options = {"api_key": self._key()}
        if cfg.get("base_url"):
            client_options["base_url"] = cfg["base_url"]
        self.client = anthropic.Anthropic(**client_options)
        self.model = cfg.get("model") or "claude-opus-4-6"

    def _record_anthropic_usage(self, usage):
        self.stats["calls"] += 1
        self.stats["in"] += int(getattr(usage, "input_tokens", 0) or 0)
        self.stats["out"] += int(getattr(usage, "output_tokens", 0) or 0)
        cache_read = getattr(usage, "cache_read_input_tokens", None)
        cache_write = getattr(usage, "cache_creation_input_tokens", None)
        if cache_read is not None or cache_write is not None:
            self.stats["cache_reports"] += 1
            self.stats["cache_read"] += int(cache_read or 0)
            self.stats["cache_write"] += int(cache_write or 0)

    def _record_anthropic_response(self, msg, *, text, finish_reason):
        usage = getattr(msg, "usage", None)
        reasoning_parts = []
        for block in getattr(msg, "content", []) or []:
            block_type = getattr(block, "type", "") if not isinstance(block, dict) else block.get("type", "")
            if block_type in {"thinking", "reasoning"}:
                value = getattr(block, "thinking", None) if not isinstance(block, dict) else block.get("thinking")
                if value is None:
                    value = getattr(block, "text", "") if not isinstance(block, dict) else block.get("text", "")
                if value:
                    reasoning_parts.append(str(value))
        reasoning_text = "".join(reasoning_parts)
        record = {
            "requested_max_tokens": self._output_budget(),
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_write_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "reasoning_chars": len(reasoning_text),
            "content_chars": len(str(text or "")),
            "finish_reason": finish_reason,
        }
        self._append_request_record(record)
        if reasoning_text:
            self._append_reasoning_record({
                "request_index": int(self.stats.get("calls") or 0),
                "model": self.model,
                "reasoning_text": reasoning_text,
                "reasoning_chars": len(reasoning_text),
                "content_chars": len(str(text or "")),
                "finish_reason": finish_reason,
            })
        return reasoning_text

    def _output_budget(self) -> int:
        return max(1, int(
            self.cfg.get("_output_budget_override")
            or self.cfg.get("annotation_max_tokens")
            or self.cfg.get("max_tokens")
            or 16000
        ))

    def _reasoning_effort(self):
        if str(self.cfg.get("reasoning_wire_protocol") or "").strip().lower() != "anthropic_thinking":
            return None
        return {
            "minimal": "low", "low": "low", "balanced": "medium",
            "medium": "medium", "deep": "high", "high": "high",
            "xhigh": "xhigh", "max": "max",
        }.get(str(self.cfg.get("reasoning_mode") or "").strip().lower())

    def complete_json(self, static_system, volatile_system, user, schema):
        # 静态部分打缓存断点；易变部分放它后面，避免整段前缀失效
        system = [{"type": "text", "text": static_system,
                   "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        if volatile_system:
            system.append({"type": "text", "text": volatile_system})

        output_config = {"format": {"type": "json_schema", "schema": schema}}
        effort = self.cfg.get("effort") or self._reasoning_effort()
        if effort:
            output_config["effort"] = effort

        kw = dict(model=self.model, max_tokens=self._output_budget(),
                  system=system, messages=[{"role": "user", "content": user}],
                  output_config=output_config)
        if self.cfg.get("thinking", True):
            kw["thinking"] = {"type": "adaptive"}

        try:
            with self.client.messages.stream(**kw) as stream:
                msg = stream.get_final_message()
        except self._sdk.APIStatusError as e:
            raise LLMError(f"Anthropic 返回 {e.status_code}: {e.message}") from e

        u = msg.usage
        self._record_anthropic_usage(u)

        text = "".join(b.text for b in msg.content if b.type == "text")
        finish_reason = str(getattr(msg, "stop_reason", "") or "unknown")
        reasoning_text = self._record_anthropic_response(msg, text=text, finish_reason=finish_reason)
        if not text.strip():
            raise EmptyModelResponseError(
                f"Anthropic 调用返回了空文本（finish_reason={finish_reason}）",
                finish_reason=finish_reason,
                reasoning_chars=len(reasoning_text),
                content_chars=len(text),
            )
        return parse_and_validate_json_response(text, schema, "Anthropic 调用")

    def complete_json_vision(self, system, images, user, schema):
        import base64
        content = []
        for tag, blob in images:
            content.append({"type": "text", "text": f"[{tag}]"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.standard_b64encode(blob).decode()}})
        content.append({"type": "text", "text": user})

        kw = dict(model=self.model, max_tokens=self._output_budget(),
                  system=[{"type": "text", "text": system,
                           "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                  messages=[{"role": "user", "content": content}],
                  output_config={"format": {"type": "json_schema", "schema": schema}})
        try:
            with self.client.messages.stream(**kw) as stream:
                msg = stream.get_final_message()
        except self._sdk.APIStatusError as e:
            raise LLMError(f"Anthropic 返回 {e.status_code}: {e.message}") from e

        u = msg.usage
        self._record_anthropic_usage(u)
        return parse_and_validate_json_response(
            "".join(b.text for b in msg.content if b.type == "text"), schema, "Anthropic 视觉调用"
        )

    def complete_json_stream(
        self, static_system, volatile_system, user, schema, *, on_activity=None,
    ):
        started_ms = int(time.time() * 1000)
        _emit_activity(
            on_activity,
            "waiting",
            model=self.model,
            request_started_at_ms=started_ms,
            elapsed_ms=0,
            first_delta_ms=None,
            received_chars=0,
            finish_reason="",
        )
        system = [{
            "type": "text",
            "text": static_system,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }]
        if volatile_system:
            system.append({"type": "text", "text": volatile_system})
        kw = dict(
            model=self.model,
            max_tokens=self._output_budget(),
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        effort = self.cfg.get("effort") or self._reasoning_effort()
        if effort:
            kw["output_config"]["effort"] = effort
        if self.cfg.get("thinking", True):
            kw["thinking"] = {"type": "adaptive"}

        chunks = []
        received_chars = 0
        first_delta_ms = None
        try:
            with self.client.messages.stream(**kw) as stream:
                for delta in stream.text_stream:
                    delta = str(delta or "")
                    if not delta:
                        continue
                    chunks.append(delta)
                    received_chars += len(delta)
                    elapsed_ms = max(0, int(time.time() * 1000) - started_ms)
                    if first_delta_ms is None:
                        first_delta_ms = elapsed_ms
                    _emit_activity(
                        on_activity,
                        "receiving",
                        model=self.model,
                        request_started_at_ms=started_ms,
                        elapsed_ms=elapsed_ms,
                        first_delta_ms=first_delta_ms,
                        received_chars=received_chars,
                        finish_reason="",
                    )
                msg = stream.get_final_message()
        except Exception as exc:
            api_error = getattr(self._sdk, "APIStatusError", None)
            if api_error is not None and isinstance(exc, api_error):
                raise LLMError(f"Anthropic 返回 {exc.status_code}: {exc.message}") from exc
            raise

        self._record_anthropic_usage(msg.usage)
        finish_reason = str(getattr(msg, "stop_reason", "") or "unknown")
        text = "".join(chunks)
        reasoning_text = self._record_anthropic_response(msg, text=text, finish_reason=finish_reason)
        if not text.strip():
            raise EmptyModelResponseError(
                f"Anthropic 调用返回了空文本（finish_reason={finish_reason}）",
                finish_reason=finish_reason,
                reasoning_chars=len(reasoning_text),
                content_chars=len(text),
            )
        result = parse_and_validate_json_response(text, schema, "Anthropic 调用")
        _emit_activity(
            on_activity,
            "completed",
            model=self.model,
            request_started_at_ms=started_ms,
            elapsed_ms=max(0, int(time.time() * 1000) - started_ms),
            first_delta_ms=first_delta_ms,
            received_chars=received_chars,
            finish_reason=finish_reason,
        )
        return result

    def list_model_records(self):
        try:
            response = self.client.models.list()
        except Exception as exc:
            raise LLMError(f"{self.model} 读取模型列表失败: {exc}") from exc
        data = getattr(response, "data", response)
        records = []
        for item in data:
            model_id = str(getattr(item, "id", "") or "").strip()
            if model_id:
                records.append({"id": model_id})
        return sorted(records, key=lambda record: record["id"])


# ---------------------------------------------------------------- OpenAI 兼容
class OpenAIProvider(Provider):
    name = "openai"
    supports_compact_annotation = True

    def __init__(self, cfg):
        super().__init__(cfg)
        self.api_key = self._key()
        self.base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = max(1, int(cfg.get("timeout") or 180))
        self.wall_timeout = max(1, int(cfg.get("wall_timeout") or 300))
        self.model = cfg.get("model") or "gpt-5"

    def _apply_reasoning_payload(self, payload):
        mode = str(self.cfg.get("reasoning_mode") or "").strip().lower()
        protocol = str(self.cfg.get("reasoning_wire_protocol") or "").strip().lower()
        if mode in {"", "provider_default"}:
            return
        effort = {
            "speed": "none", "minimal": "minimal", "low": "low",
            "balanced": "medium", "medium": "medium", "deep": "high",
            "high": "high", "xhigh": "xhigh", "max": "max",
        }.get(mode)
        if protocol in {"openai_reasoning_effort", "gemini_reasoning_effort"}:
            if effort:
                payload["reasoning_effort"] = effort
            return
        if protocol in {"deepseek_thinking", "glm_thinking", "kimi_thinking"}:
            if mode == "speed":
                payload["thinking"] = {"type": "disabled"}
                return
            payload["thinking"] = {"type": "enabled"}
            if protocol == "deepseek_thinking" and effort:
                payload["reasoning_effort"] = effort
            return
        if protocol == "qwen_thinking":
            enabled = mode != "speed"
            payload["enable_thinking"] = enabled
            if enabled and mode in {"deep", "high"}:
                budget = self.cfg.get("reasoning_budget_max")
                if budget not in (None, ""):
                    payload["thinking_budget"] = max(1, int(budget))
            return
        if protocol != "deepseek_thinking":
            return
        if mode == "speed":
            payload["thinking"] = {"type": "disabled"}
            return
        payload["thinking"] = {"type": "enabled"}
        if effort:
            payload["reasoning_effort"] = effort

    def _output_budget(self) -> int:
        return max(1, int(
            self.cfg.get("_output_budget_override")
            or self.cfg.get("annotation_max_tokens")
            or self.cfg.get("max_tokens")
            or 16000
        ))

    def _capacity_error_message(self, prefix: str) -> str:
        record = self.request_records[-1] if self.request_records else {}
        requested = int(record.get("requested_max_tokens") or self._output_budget())
        reasoning = record.get("reasoning_tokens")
        content_chars = int(record.get("content_chars") or 0)
        reasoning_detail = (
            f"，reasoning_tokens={int(reasoning)}" if reasoning is not None else ""
        )
        return (
            f"{self.model} {prefix}输出被截断（finish_reason=length，"
            f"requested_max_tokens={requested}{reasoning_detail}，content_chars={content_chars}）；"
            "推理与正文共享该输出预算，请提高 Agent 单请求输出预算或缩小 Agent 分块"
        )

    @staticmethod
    def _error_message(payload, fallback):
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if isinstance(error, str) and error:
                return error
            if payload.get("message"):
                return str(payload["message"])
        return fallback

    def _request_json(self, path, payload=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method="GET" if payload is None else "POST",
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + self.api_key,
                **({"Content-Type": "application/json; charset=utf-8"} if body is not None else {}),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                error_payload = None
            message = self._error_message(error_payload, str(exc.reason or exc))
            formatted = f"{self.model} 接口返回 HTTP {exc.code}: {message}"
            if exc.code == 400 and "response_format" in message.lower():
                raise UnsupportedResponseFormatError(formatted) from exc
            raise LLMError(formatted) from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None) or str(exc)
            raise LLMError(f"{self.model} 无法连接模型接口: {reason}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMError(f"{self.model} 接口没有返回合法 JSON") from exc
        if not isinstance(result, dict):
            raise LLMError(f"{self.model} 接口返回格式不正确")
        return result

    def _record_usage(self, response, *, request_record=None):
        usage = response.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        cached = usage.get("prompt_cache_hit_tokens")
        if cached is None:
            cached = details.get("cached_tokens")
        missed = usage.get("prompt_cache_miss_tokens")
        if missed is None and cached is not None:
            missed = max(0, prompt_tokens - int(cached or 0))
        self.stats["calls"] += 1
        self.stats["in"] += prompt_tokens
        self.stats["out"] += int(usage.get("completion_tokens") or 0)
        if cached is not None or missed is not None:
            self.stats["cache_reports"] += 1
            self.stats["cache_read"] += int(cached or 0)
            self.stats["cache_miss"] += int(missed or 0)
        if request_record is not None:
            record = dict(request_record)
            record.update({
                "input_tokens": prompt_tokens,
                "cache_read_tokens": int(cached) if cached is not None else None,
                "uncached_input_tokens": int(missed) if missed is not None else None,
                "output_tokens": int(usage.get("completion_tokens") or 0),
                "reasoning_tokens": (
                    int(completion_details.get("reasoning_tokens"))
                    if completion_details.get("reasoning_tokens") is not None
                    else None
                ),
            })
            self._append_request_record(record)

    def _completion_text(self, messages, response_format, *, vision=False):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._output_budget(),
        }
        self._apply_reasoning_payload(payload)
        if response_format is not None:
            payload["response_format"] = response_format
        response = self._request_json("/chat/completions", payload)
        choices = response.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        self._last_finish_reason = choice.get("finish_reason") or "unknown"
        message = choice.get("message") or {}
        text = message.get("content") if isinstance(message, dict) else ""
        if isinstance(text, list):
            text = "".join(
                str(block.get("text") or "")
                for block in text
                if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
            )
        text = str(text or "")
        reasoning = message.get("reasoning_content") if isinstance(message, dict) else ""
        self._record_usage(
            response,
            request_record={
                "requested_max_tokens": self._output_budget(),
                "reasoning_chars": len(str(reasoning or "")),
                "content_chars": len(text),
                "finish_reason": self._last_finish_reason,
            },
        )
        if reasoning:
            self._append_reasoning_record({
                "request_index": int(self.stats.get("calls") or 0),
                "model": self.model,
                "reasoning_text": str(reasoning),
                "reasoning_chars": len(str(reasoning)),
                "content_chars": len(text),
                "finish_reason": self._last_finish_reason,
            })
        if not text.strip():
            finish_reason = choice.get("finish_reason") or "unknown"
            prefix = "视觉调用" if vision else "调用"
            if finish_reason == "length":
                raise OutputCapacityError(self._capacity_error_message(prefix))
            raise EmptyModelResponseError(
                f"{self.model} {prefix}返回了空文本（finish_reason={finish_reason}）",
                finish_reason=finish_reason,
                reasoning_chars=len(str(reasoning or "")),
                content_chars=len(text),
            )
        return text

    def _stream_completion_text(self, messages, response_format, *, activity, started_ms):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self._output_budget(),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        self._apply_reasoning_payload(payload)
        if response_format is not None:
            payload["response_format"] = response_format
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Accept": "text/event-stream",
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        chunks = []
        usage = None
        finish_reason = "unknown"
        started_monotonic = time.monotonic()
        reasoning_chars = 0
        reasoning_chunks = []
        first_reasoning_ms = None
        first_content_ms = None
        activity.setdefault("first_reasoning_ms", None)
        activity.setdefault("first_content_ms", None)
        activity.setdefault("reasoning_chars", 0)
        activity.setdefault("content_chars", 0)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except (TypeError, ValueError, json.JSONDecodeError) as exc:
                        raise LLMError(f"{self.model} 流式接口返回了非法 SSE JSON") from exc
                    if isinstance(event.get("usage"), dict):
                        usage = event["usage"]
                    choices = event.get("choices") or []
                    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
                    if choice.get("finish_reason"):
                        finish_reason = str(choice["finish_reason"])
                    delta = choice.get("delta") or {}
                    if time.monotonic() - started_monotonic > self.wall_timeout:
                        raise RequestDeadlineError(
                            f"{self.model} 请求超过 {self.wall_timeout} 秒截止时间"
                        )
                    reasoning = delta.get("reasoning_content") if isinstance(delta, dict) else ""
                    reasoning = str(reasoning or "")
                    elapsed_ms = max(0, int(time.time() * 1000) - started_ms)
                    if reasoning:
                        reasoning_chars += len(reasoning)
                        reasoning_chunks.append(reasoning)
                        if first_reasoning_ms is None:
                            first_reasoning_ms = elapsed_ms
                            activity["first_reasoning_ms"] = first_reasoning_ms
                        activity["reasoning_chars"] = reasoning_chars
                        _emit_activity(
                            activity["callback"], "reasoning", model=self.model,
                            request_started_at_ms=started_ms, elapsed_ms=elapsed_ms,
                            first_delta_ms=activity["first_delta_ms"],
                            first_reasoning_ms=first_reasoning_ms,
                            first_content_ms=first_content_ms,
                            received_chars=activity["received_chars"],
                            reasoning_chars=reasoning_chars,
                            content_chars=activity["received_chars"],
                            finish_reason=finish_reason,
                        )
                    content = delta.get("content") if isinstance(delta, dict) else ""
                    if isinstance(content, list):
                        content = "".join(
                            str(block.get("text") or "")
                            for block in content
                            if isinstance(block, dict)
                        )
                    content = str(content or "")
                    if not content:
                        continue
                    chunks.append(content)
                    activity["received_chars"] += len(content)
                    if first_content_ms is None:
                        first_content_ms = elapsed_ms
                        activity["first_content_ms"] = first_content_ms
                    activity["content_chars"] = activity["received_chars"]
                    if activity["first_delta_ms"] is None:
                        activity["first_delta_ms"] = elapsed_ms
                    _emit_activity(
                        activity["callback"],
                        "receiving",
                        model=self.model,
                        request_started_at_ms=started_ms,
                        elapsed_ms=elapsed_ms,
                        first_delta_ms=activity["first_delta_ms"],
                        first_reasoning_ms=first_reasoning_ms,
                        first_content_ms=first_content_ms,
                        received_chars=activity["received_chars"],
                        reasoning_chars=reasoning_chars,
                        content_chars=activity["received_chars"],
                        finish_reason=finish_reason,
                    )
        except HTTPError as exc:
            try:
                error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                error_payload = None
            message = self._error_message(error_payload, str(exc.reason or exc))
            formatted = f"{self.model} 接口返回 HTTP {exc.code}: {message}"
            if exc.code == 400 and "response_format" in message.lower():
                raise UnsupportedResponseFormatError(formatted) from exc
            raise LLMError(formatted) from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", None) or str(exc)
            raise LLMError(f"{self.model} 无法连接模型接口: {reason}") from exc

        self._last_finish_reason = finish_reason
        text = "".join(chunks)
        self._record_usage(
            {"usage": usage or {}},
            request_record={
                "requested_max_tokens": self._output_budget(),
                "elapsed_ms": max(0, int((time.monotonic() - started_monotonic) * 1000)),
                "first_reasoning_ms": first_reasoning_ms,
                "first_content_ms": first_content_ms,
                "reasoning_chars": reasoning_chars,
                "content_chars": activity["received_chars"],
                "finish_reason": finish_reason,
            },
        )
        if reasoning_chars:
            self._append_reasoning_record({
                "request_index": int(self.stats.get("calls") or 0),
                "model": self.model,
                "reasoning_text": "".join(reasoning_chunks),
                "reasoning_chars": reasoning_chars,
                "content_chars": activity["received_chars"],
                "finish_reason": finish_reason,
            })
        if not text.strip():
            prefix = "调用"
            if finish_reason == "length":
                raise OutputCapacityError(self._capacity_error_message(prefix))
            raise EmptyModelResponseError(
                f"{self.model} {prefix}返回了空文本（finish_reason={finish_reason}）",
                finish_reason=finish_reason,
                reasoning_chars=reasoning_chars,
                content_chars=len(text),
            )
        return text

    @staticmethod
    def _json_object_messages(messages, schema):
        instruction = (
            "\n\n兼容模式：严格只返回一个符合下列 JSON Schema 的 JSON 对象。"
            "不要输出 Markdown、标题、解释文字或代码围栏。\nJSON Schema：\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )
        fallback = []
        inserted = False
        for original in messages:
            item = dict(original)
            if not inserted and item.get("role") == "system" and isinstance(item.get("content"), str):
                item["content"] += instruction
                inserted = True
            fallback.append(item)
        if not inserted:
            fallback.insert(0, {"role": "system", "content": instruction.lstrip()})
        return fallback

    def _complete_compatible(self, messages, schema, prefix, *, vision=False):
        response_format = None if getattr(self, "_response_format_unavailable", False) else {"type": "json_object"}
        compatible_messages = self._json_object_messages(messages, schema)
        try:
            fallback_text = self._completion_text(
                compatible_messages,
                response_format,
                vision=vision,
            )
        except UnsupportedResponseFormatError:
            self._response_format_unavailable = True
            fallback_text = self._completion_text(
                compatible_messages,
                None,
                vision=vision,
            )
        try:
            return parse_and_validate_json_response(
                fallback_text, schema, f"{self.model} {prefix}兼容模式"
            )
        except StructuredOutputError as exc:
            if getattr(self, "_last_finish_reason", "") == "length":
                raise OutputCapacityError(self._capacity_error_message(prefix)) from exc
            raise

    def _complete_stream_compatible(
        self, messages, schema, prefix, *, activity, started_ms,
    ):
        response_format = None if getattr(self, "_response_format_unavailable", False) else {"type": "json_object"}
        compatible_messages = self._json_object_messages(messages, schema)
        try:
            fallback_text = self._stream_completion_text(
                compatible_messages,
                response_format,
                activity=activity,
                started_ms=started_ms,
            )
        except UnsupportedResponseFormatError:
            self._response_format_unavailable = True
            fallback_text = self._stream_completion_text(
                compatible_messages,
                None,
                activity=activity,
                started_ms=started_ms,
            )
        try:
            return parse_and_validate_json_response(
                fallback_text, schema, f"{self.model} {prefix}兼容模式"
            )
        except StructuredOutputError as exc:
            if getattr(self, "_last_finish_reason", "") == "length":
                raise OutputCapacityError(self._capacity_error_message(prefix)) from exc
            raise

    def complete_json_stream(
        self, static_system, volatile_system, user, schema, *, on_activity=None,
    ):
        started_ms = int(time.time() * 1000)
        activity = {
            "callback": on_activity,
            "received_chars": 0,
            "first_delta_ms": None,
        }
        _emit_activity(
            on_activity,
            "waiting",
            model=self.model,
            request_started_at_ms=started_ms,
            elapsed_ms=0,
            first_delta_ms=None,
            received_chars=0,
            finish_reason="",
        )
        system = static_system + (("\n\n" + volatile_system) if volatile_system else "")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prefix = "调用"
        if (
            str(self.cfg.get("reasoning_wire_protocol") or "").strip().lower() == "deepseek_thinking"
            or getattr(self, "_strict_response_format_unavailable", False)
            or getattr(self, "_response_format_unavailable", False)
        ):
            result = self._complete_stream_compatible(
                messages, schema, prefix, activity=activity, started_ms=started_ms,
            )
        else:
            strict_format = {
                "type": "json_schema",
                "json_schema": {"name": "annotations", "schema": schema, "strict": True},
            }
            try:
                text = self._stream_completion_text(
                    messages,
                    strict_format,
                    activity=activity,
                    started_ms=started_ms,
                )
            except UnsupportedResponseFormatError:
                self._strict_response_format_unavailable = True
                result = self._complete_stream_compatible(
                    messages, schema, prefix, activity=activity, started_ms=started_ms,
                )
            else:
                try:
                    result = parse_and_validate_json_response(text, schema, f"{self.model} {prefix}")
                except StructuredOutputError as exc:
                    if getattr(self, "_last_finish_reason", "") == "length":
                        raise OutputCapacityError(self._capacity_error_message(prefix)) from exc
                    raise
        _emit_activity(
            on_activity,
            "completed",
            model=self.model,
            request_started_at_ms=started_ms,
            elapsed_ms=max(0, int(time.time() * 1000) - started_ms),
            first_delta_ms=activity["first_delta_ms"],
            first_reasoning_ms=activity.get("first_reasoning_ms"),
            first_content_ms=activity.get("first_content_ms"),
            received_chars=activity["received_chars"],
            reasoning_chars=activity.get("reasoning_chars", 0),
            content_chars=activity.get("content_chars", 0),
            finish_reason=getattr(self, "_last_finish_reason", "unknown"),
        )
        return result

    def _complete(self, messages, schema, schema_name, *, vision=False):
        prefix = "视觉调用" if vision else "调用"
        if (
            str(self.cfg.get("reasoning_wire_protocol") or "").strip().lower() == "deepseek_thinking"
            or getattr(self, "_strict_response_format_unavailable", False)
            or getattr(self, "_response_format_unavailable", False)
        ):
            return self._complete_compatible(messages, schema, prefix, vision=vision)
        strict_format = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema, "strict": True},
        }
        try:
            text = self._completion_text(messages, strict_format, vision=vision)
        except UnsupportedResponseFormatError:
            self._strict_response_format_unavailable = True
            return self._complete_compatible(messages, schema, prefix, vision=vision)
        try:
            return parse_and_validate_json_response(text, schema, f"{self.model} {prefix}")
        except StructuredOutputError as exc:
            if getattr(self, "_last_finish_reason", "") == "length":
                raise OutputCapacityError(self._capacity_error_message(prefix)) from exc
            raise

    def complete_json(self, static_system, volatile_system, user, schema):
        system = static_system + (("\n\n" + volatile_system) if volatile_system else "")
        return self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            schema,
            "annotations",
        )

    def complete_json_vision(self, system, images, user, schema):
        import base64
        content = []
        for tag, blob in images:
            content.append({"type": "text", "text": f"[{tag}]"})
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," +
                       base64.standard_b64encode(blob).decode()}})
        content.append({"type": "text", "text": user})
        return self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": content}],
            schema,
            "labels",
            vision=True,
        )

    def list_model_records(self):
        response = self._request_json("/models")
        data = response.get("data") or []
        records = []
        for item in data:
            record = normalize_remote_model_record(item)
            if record["id"]:
                records.append(record)
        return sorted(records, key=lambda record: record["id"])


# ---------------------------------------------------------------- 假货（不花钱跑通链路）
class MockProvider(Provider):
    """不联网。按行号轮换标注，只用来验证管线是否通畅。"""
    name = "mock"

    def __init__(self, cfg, preset_response=None):
        super().__init__(cfg)
        self.model = "mock"
        if isinstance(cfg, dict) and "lines" in cfg:
            self.preset_response = cfg
        else:
            self.preset_response = preset_response

    def _key(self):
        return "mock"

    def complete_json(self, static_system, volatile_system, user, schema):
        if self.preset_response:
            self.stats["calls"] += 1
            self.stats["in"] += len(static_system) // 3
            self.stats["out"] += 50
            return self.preset_response
        import re as _re
        target_matches = list(_re.finditer(
            r"\[TARGET ([^\]]+)\].*?fingerprint=([0-9a-f]+)", user
        ))
        if target_matches and "source_id" in json.dumps(schema, ensure_ascii=False):
            rows = []
            for index, match in enumerate(target_matches):
                rows.append({
                    "source_id": match.group(1), "text_fingerprint": match.group(2),
                    "face": "", "emo": "", "act": "", "fx": "", "se": "",
                    "bg": "", "bg_request": "", "place": "", "shake": False,
                    "bgfx": "", "trans": "", "move": 0, "shot": "",
                })
            self.stats["calls"] += 1
            self.stats["in"] += len(static_system) // 3
            self.stats["out"] += len(rows) * 20
            return {"lines": rows, "state_delta": {}, "memory_events": []}
        faces = _re.findall(r"^\s{0,2}(\d\d)=", static_system, _re.M) or ["00", "01", "03"]
        rows = []
        for m in _re.finditer(r"^\[(\d+)\]\s*([^:：]+)[:：]", user, _re.M):
            i = int(m.group(1))
            rows.append({"i": i, "face": faces[i % len(faces)],
                         "emo": "[!]" if i % 7 == 3 else "",
                         "act": "jump" if i % 11 == 5 else "",
                         "fx": "特写" if i % 17 == 8 else "",
                         "se": "", "wait": 1500 if i % 13 == 9 else 0, "bg": "",
                         "place": "", "shake": i % 29 == 12,
                         "move": (i % 5) + 1 if i % 19 == 7 else 0})
        self.stats["calls"] += 1
        self.stats["in"] += len(static_system) // 3
        self.stats["out"] += len(rows) * 20
        return {"lines": rows}

    def complete_json_vision(self, system, images, user, schema):
        self.stats["calls"] += 1
        self.stats["in"] += len(images) * 800
        return {"items": [{"key": tag, "label": f"假标注-{tag}", "place": "室外",
                           "time": "白天", "mood": "日常", "chars": "",
                           "descr": "mock 占位", "tags": "mock"}
                          for tag, _ in images]}


REGISTRY = {"anthropic": AnthropicProvider, "openai": OpenAIProvider,
            "mock": MockProvider}


def make_provider_from_settings(name, settings):
    name = str(name or "").strip()
    if name not in REGISTRY:
        raise LLMError(f"未知 provider「{name}」，可选: {'、'.join(REGISTRY)}")
    return REGISTRY[name](dict(settings or {}))


def make_provider(cfg_path, override=None):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    name = override or cfg.get("provider") or "anthropic"
    sub = dict(cfg.get(name) or {})
    for k in ("max_tokens",):
        if k in cfg and k not in sub:
            sub[k] = cfg[k]
    return make_provider_from_settings(name, sub)
