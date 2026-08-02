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


class LLMError(RuntimeError):
    pass


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
        return parse_json_response(text)

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
        return parse_json_response("".join(b.text for b in msg.content if b.type == "text"))

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
        try:
            from openai import OpenAI
        except ImportError:
            raise LLMError("没装 openai SDK，先跑:  pip install openai")
        self.client = OpenAI(api_key=self._key(),
                             base_url=cfg.get("base_url") or None)
        self.model = cfg.get("model") or "gpt-5"

    def complete_json(self, static_system, volatile_system, user, schema):
        # 兼容接口没有显式缓存控制，多数服务商按前缀自动命中，所以静态部分放最前
        system = static_system + (("\n\n" + volatile_system) if volatile_system else "")
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "annotations", "schema": schema, "strict": True}},
                max_completion_tokens=self.cfg.get("max_tokens", 16000),
            )
        except Exception as e:
            raise LLMError(f"{self.model} 调用失败: {e}") from e

        u = getattr(r, "usage", None)
        self.stats["calls"] += 1
        if u:
            self.stats["in"] += getattr(u, "prompt_tokens", 0) or 0
            self.stats["out"] += getattr(u, "completion_tokens", 0) or 0
            det = getattr(u, "prompt_tokens_details", None)
            self.stats["cache_read"] += getattr(det, "cached_tokens", 0) or 0

        text = r.choices[0].message.content or ""
        if not text.strip():
            raise LLMError(f"{self.model} 返回了空文本")
        return parse_json_response(text)

    def complete_json_vision(self, system, images, user, schema):
        import base64
        content = []
        for tag, blob in images:
            content.append({"type": "text", "text": f"[{tag}]"})
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," +
                       base64.standard_b64encode(blob).decode()}})
        content.append({"type": "text", "text": user})
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "labels", "schema": schema, "strict": True}},
                max_completion_tokens=self.cfg.get("max_tokens", 16000),
            )
        except Exception as e:
            raise LLMError(f"{self.model} 视觉调用失败: {e}") from e
        u = getattr(r, "usage", None)
        self.stats["calls"] += 1
        if u:
            self.stats["in"] += getattr(u, "prompt_tokens", 0) or 0
            self.stats["out"] += getattr(u, "completion_tokens", 0) or 0
        choice = r.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            finish_reason = getattr(choice, "finish_reason", None) or "unknown"
            raise LLMError(
                f"{self.model} 视觉调用返回了空文本"
                f"（finish_reason={finish_reason}）"
            )
        try:
            return parse_json_response(text)
        except (TypeError, ValueError) as exc:
            raise LLMError(
                f"{self.model} 视觉调用没有返回合法 JSON"
            ) from exc

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
