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
import json, os, sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    pass


class StructuredOutputError(LLMError):
    """The provider response is not the JSON shape requested by the caller."""


class OutputCapacityError(StructuredOutputError):
    """The provider stopped because the configured output budget was exhausted."""


class UnsupportedResponseFormatError(LLMError):
    """The OpenAI-compatible endpoint rejected the response_format field."""


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

    def __init__(self, cfg):
        self.cfg = cfg
        self.model = cfg.get("model") or ""
        self.stats = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0}

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

    def complete_json_vision(self, system, images, user, schema):
        """images = [(标识, jpeg_bytes), ...]"""
        raise NotImplementedError

    def list_models(self):
        raise LLMError(f"{self.name} 接口不支持读取模型列表")

    def report(self):
        s = self.stats
        out = (f"{self.name}/{self.model}  调用 {s['calls']} 次  "
               f"输入 {s['in']:,}  输出 {s['out']:,}")
        if s["cache_read"] or s["cache_write"]:
            out += f"  缓存读 {s['cache_read']:,}  缓存写 {s['cache_write']:,}"
        return out


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider(Provider):
    name = "anthropic"

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

    def complete_json(self, static_system, volatile_system, user, schema):
        # 静态部分打缓存断点；易变部分放它后面，避免整段前缀失效
        system = [{"type": "text", "text": static_system,
                   "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        if volatile_system:
            system.append({"type": "text", "text": volatile_system})

        output_config = {"format": {"type": "json_schema", "schema": schema}}
        if self.cfg.get("effort"):
            output_config["effort"] = self.cfg["effort"]

        kw = dict(model=self.model, max_tokens=self.cfg.get("max_tokens", 16000),
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
        self.stats["calls"] += 1
        self.stats["in"] += u.input_tokens
        self.stats["out"] += u.output_tokens
        self.stats["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        self.stats["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        text = "".join(b.text for b in msg.content if b.type == "text")
        if not text.strip():
            raise LLMError("Anthropic 返回了空文本")
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

        kw = dict(model=self.model, max_tokens=self.cfg.get("max_tokens", 16000),
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
        self.stats["calls"] += 1
        self.stats["in"] += u.input_tokens
        self.stats["out"] += u.output_tokens
        self.stats["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        self.stats["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        return parse_and_validate_json_response(
            "".join(b.text for b in msg.content if b.type == "text"), schema, "Anthropic 视觉调用"
        )

    def list_models(self):
        try:
            response = self.client.models.list()
        except Exception as exc:
            raise LLMError(f"{self.model} 读取模型列表失败: {exc}") from exc
        data = getattr(response, "data", response)
        return sorted({
            str(getattr(item, "id", "") or "")
            for item in data
            if str(getattr(item, "id", "") or "")
        })


# ---------------------------------------------------------------- OpenAI 兼容
class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.api_key = self._key()
        self.base_url = str(cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = max(1, int(cfg.get("timeout") or 180))
        self.model = cfg.get("model") or "gpt-5"

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

    def _record_usage(self, response):
        usage = response.get("usage") or {}
        details = usage.get("prompt_tokens_details") or {}
        self.stats["calls"] += 1
        self.stats["in"] += int(usage.get("prompt_tokens") or 0)
        self.stats["out"] += int(usage.get("completion_tokens") or 0)
        self.stats["cache_read"] += int(details.get("cached_tokens") or 0)

    def _completion_text(self, messages, response_format, *, vision=False):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.cfg.get("max_tokens", 16000),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        response = self._request_json("/chat/completions", payload)
        self._record_usage(response)
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
        if not text.strip():
            finish_reason = choice.get("finish_reason") or "unknown"
            prefix = "视觉调用" if vision else "调用"
            if finish_reason == "length":
                raise OutputCapacityError(
                    f"{self.model} {prefix}输出被截断（finish_reason=length，max_tokens="
                    f"{self.cfg.get('max_tokens', 16000)}）；请提高最大输出或缩小 Agent 分块"
                )
            raise LLMError(f"{self.model} {prefix}返回了空文本（finish_reason={finish_reason}）")
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
                raise OutputCapacityError(
                    f"{self.model} {prefix}输出被截断（finish_reason=length，max_tokens={self.cfg.get('max_tokens', 16000)}）；"
                    "请提高最大输出或缩小 Agent 分块"
                ) from exc
            raise

    def _complete(self, messages, schema, schema_name, *, vision=False):
        prefix = "视觉调用" if vision else "调用"
        if (
            getattr(self, "_strict_response_format_unavailable", False)
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
                raise OutputCapacityError(
                    f"{self.model} {prefix}输出被截断（finish_reason=length，max_tokens={self.cfg.get('max_tokens', 16000)}）；"
                    "请提高最大输出或缩小 Agent 分块"
                ) from exc
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

    def list_models(self):
        response = self._request_json("/models")
        data = response.get("data") or []
        return sorted({
            str(item.get("id") or "")
            for item in data
            if isinstance(item, dict) and str(item.get("id") or "")
        })


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
