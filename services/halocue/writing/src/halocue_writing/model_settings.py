from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import time
import threading
import uuid
import urllib.error
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import DomainError
from services.halocue.codex_agent import (
    CodexError, connection as codex_connection,
    test_connection as test_codex_connection, validate_config as validate_codex_config,
    enable_subscription_only, require_subscription_provider, subscription_only_enabled,
)
from .provider_response import validate_completion
from .model_capabilities import capabilities, model_catalog, normalize_advanced, upstream_capabilities, completion_parameters, ADVANCED_FIELDS


PROVIDERS = {"openai", "anthropic", "codex"}

VENDOR_PRESETS: list[dict[str, Any]] = [
    {
        "id": "deepseek",
        "name": "DeepSeek 官方",
        "provider": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_key_env": "DEEPSEEK_API_KEY",
        "notes": "超高性价比，写作与演出的高智商推荐",
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 (SiliconFlow)",
        "provider": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "models": [
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen2.5-72B-Instruct",
        ],
        "api_key_env": "SILICONFLOW_API_KEY",
        "notes": "国内高速聚合平台，支持多种开源大模型",
    },
    {
        "id": "openai",
        "name": "OpenAI 官方",
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4-turbo"],
        "api_key_env": "OPENAI_API_KEY",
        "notes": "国际标准 API，支持 GPT-4o 及推理模型",
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "provider": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-5-sonnet-20241022",
        "models": [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
        "api_key_env": "ANTHROPIC_API_KEY",
        "notes": "长文本与精细文字叙事顶尖水准",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-plus",
        "models": ["glm-4-plus", "glm-4-flash", "glm-4-air"],
        "api_key_env": "ZHIPU_API_KEY",
        "notes": "智谱清言官方开放平台",
    },
    {
        "id": "moonshot",
        "name": "月之暗面 (Kimi)",
        "provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "api_key_env": "MOONSHOT_API_KEY",
        "notes": "擅长长文本上下文理解",
    },
    {
        "id": "qwen",
        "name": "阿里通义千问",
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-max",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo"],
        "api_key_env": "DASHSCOPE_API_KEY",
        "notes": "阿里云百炼大模型服务",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-3.5-sonnet",
        "models": [
            "anthropic/claude-3.5-sonnet",
            "deepseek/deepseek-chat",
            "openai/gpt-4o",
        ],
        "api_key_env": "OPENROUTER_API_KEY",
        "notes": "全球模型聚合路由网关",
    },
    {
        "id": "nvidia",
        "name": "NVIDIA NIM",
        "provider": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "deepseek-ai/deepseek-v4.1-flash",
        "models": ["deepseek-ai/deepseek-v4.1-flash", "nvidia/nemotron-3-super-120b-a12b", "moonshotai/kimi-k3"],
        "api_key_env": "NVIDIA_API_KEY",
        "access_badge": "免费试用",
        "access_note": "用于开发与原型验证的免费试用；需申请密钥，受调用速率及账户额度限制，具体政策以官网为准。",
        "notes": "NVIDIA 官方模型 API；可用模型与试用额度以账户为准",
    },
    {
        "id": "amd",
        "name": "AMD Radeon Cloud",
        "provider": "openai",
        "base_url": "https://developer.amd.com.cn/radeon/api/v1",
        "default_model": "DeepSeek-V4.1-Flash",
        "models": ["DeepSeek-V4.1-Flash", "Qwen3.8-Flash-Next", "GLM-5.3-Flash"],
        "api_key_env": "RADEON_API_KEY",
        "access_badge": "限额免费",
        "access_note": "仅公共模型 API 免费；需申请密钥，受配额、并发及速率限制。专用实例另计，免费政策与可用模型以官网为准。",
        "notes": "AMD 公共免费模型 API；需申请密钥，受账户配额与速率限制",
    },
    {
        "id": "ollama",
        "name": "本地 Ollama",
        "provider": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "default_model": "qwen2.5:7b",
        "models": ["qwen2.5:7b", "deepseek-r1:8b", "llama3.1:8b"],
        "api_key_env": "",
        "notes": "本地离线大模型运行环境（默认无需 Key）",
    },
    {
        "id": "custom",
        "name": "自定义接口",
        "provider": "openai",
        "base_url": "",
        "default_model": "",
        "models": [],
        "api_key_env": "",
        "notes": "兼容 OpenAI 格式的各类自建反代或中转服务",
    },
]


# Official account/documentation destinations; never include credentials or referrals.
# Accelerator endpoints verified against NVIDIA NIM and Radeon Cloud docs on 2026-09-27.
_VENDOR_WEBSITES = {
    "deepseek": ("https://platform.deepseek.com/", "https://platform.deepseek.com/api_keys", "https://api-docs.deepseek.com/"),
    "siliconflow": ("https://siliconflow.cn/", "https://cloud.siliconflow.cn/account/ak", "https://docs.siliconflow.cn/"),
    "openai": ("https://platform.openai.com/", "https://platform.openai.com/api-keys", "https://developers.openai.com/api/docs/"),
    "anthropic": ("https://platform.claude.com/", "https://platform.claude.com/settings/keys", "https://platform.claude.com/docs/"),
    "zhipu": ("https://open.bigmodel.cn/", "https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys", "https://docs.bigmodel.cn/"),
    "moonshot": ("https://platform.moonshot.cn/", "https://platform.moonshot.cn/console/api-keys", "https://platform.moonshot.cn/docs/"),
    "qwen": ("https://bailian.console.aliyun.com/", "https://bailian.console.aliyun.com/", "https://help.aliyun.com/zh/model-studio/"),
    "openrouter": ("https://openrouter.ai/", "https://openrouter.ai/settings/keys", "https://openrouter.ai/docs/"),
    "nvidia": ("https://build.nvidia.com/", "https://build.nvidia.com/explore/discover", "https://docs.api.nvidia.com/nim/reference/llm-apis"),
    "amd": ("https://developer.amd.com.cn/radeon/", "https://developer.amd.com.cn/radeon/tokenfactory", "https://amd-aim.github.io/radeon-cloud-docs/api/overview/"),
    "ollama": ("https://ollama.com/", "", "https://docs.ollama.com/"),
}


for _preset in VENDOR_PRESETS:
    for _field, _url in zip(("website_url", "api_key_url", "docs_url"), _VENDOR_WEBSITES.get(_preset["id"], ())):
        _preset[_field] = _url
    _current_models = {
        "openai": ["gpt-6-sol", "gpt-6-astra", "gpt-6-luna"],
        "anthropic": ["claude-sonnet-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5"],
        "deepseek": ["deepseek-flash", "deepseek-v4-pro"],
    }.get(_preset["id"])
    if _current_models:
        _preset["models"] = list(dict.fromkeys([*_current_models, *_preset["models"]]))
        _preset["default_model"] = _current_models[0]
        _preset["notes"] = "官方模型预设；实际可用模型与额度以当前接口为准"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class ModelSecretStore:
    """Encrypt model secrets for the current Windows user with DPAPI."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _blob(value: bytes) -> tuple[_DataBlob, Any]:
        buffer = ctypes.create_string_buffer(value)
        return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer

    @classmethod
    def _protect(cls, value: str) -> bytes:
        if os.name != "nt":
            raise DomainError(
                "secure_secret_store_unavailable",
                "当前系统不支持 Windows DPAPI，请改用环境变量保存密钥",
                status=409,
            )
        source, source_buffer = cls._blob(value.encode("utf-8"))
        output = _DataBlob()
        description = "HaloCue 1.0 writing model"
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), description, None, None, None, 0, ctypes.byref(output)
        ):
            raise DomainError("secret_store_failed", "模型密钥加密失败", status=500)
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del source_buffer

    @classmethod
    def _unprotect(cls, value: bytes) -> str:
        if os.name != "nt":
            raise DomainError(
                "secure_secret_store_unavailable",
                "当前系统不支持读取加密模型密钥",
                status=409,
            )
        source, source_buffer = cls._blob(value)
        output = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        ):
            raise DomainError("secret_store_failed", "模型密钥解密失败", status=500)
        try:
            return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del source_buffer

    def save(self, secret: str) -> None:
        encrypted = self._protect(secret)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(base64.b64encode(encrypted))
        os.replace(temporary, self.path)

    def load(self) -> str | None:
        if not self.path.is_file():
            return None
        try:
            encrypted = base64.b64decode(self.path.read_bytes(), validate=True)
            return self._unprotect(encrypted)
        except (OSError, ValueError) as exc:
            raise DomainError(
                "model_secret_corrupted", "模型密钥存储损坏", status=500
            ) from exc

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()

    def exists(self) -> bool:
        return self.path.is_file()


class WritingModelSettings:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "writing-model.json"
        self.secret = ModelSecretStore(data_dir / "secrets" / "writing-model.dpapi")
        self._activation_lock = threading.RLock()

    def _secret_store(self, config: dict) -> ModelSecretStore:
        reference = config.get("credential_revision")
        if not reference:
            return self.secret
        if not isinstance(reference, str) or len(reference) != 32 or any(c not in "0123456789abcdef" for c in reference):
            raise DomainError("model_settings_corrupted", "模型密钥版本无效。", status=500)
        return ModelSecretStore(self.path.parent / "secrets" / f"writing-{reference}.dpapi")

    def resolve_candidate(self, payload: dict | None = None, *, require_model: bool = True) -> dict:
        requested = dict(payload or {})
        stored = self._load_public()
        expected = requested.pop("expected_config_digest", None)
        if expected is not None and expected != self.runtime_identity()["config_digest"]:
            raise DomainError("model_settings_changed", "模型连接已在别处更改，请刷新模型列表后重试。", status=409)
        registered_id = requested.pop("registered_model_id", None)
        if registered_id is not None:
            matches = [item for item in self._registered_configs(stored) if self._registered_id(item) == registered_id]
            if not matches:
                raise DomainError("registered_model_not_found", "该模型尚未在设置中保存，请刷新列表。", status=404)
            if requested:
                raise DomainError("invalid_model_selection", "快捷切换不能覆盖已保存的模型配置。")
            stored = matches[0]
        candidate = {**stored, **requested}
        if (candidate.get("model"), candidate.get("provider")) != (stored.get("model"), stored.get("provider")):
            for field in (*ADVANCED_FIELDS, "max_tokens"):
                if field not in requested:
                    candidate.pop(field, None)
        provider = str(candidate.get("provider") or "openai").strip().lower()
        try:
            require_subscription_provider(provider)
        except CodexError as error:
            raise DomainError(error.code, error.message, status=409) from error
        if provider == "codex":
            # Switching provider must not inherit old URL/secret/price settings.
            clean = {key: candidate.get(key) for key in ("model", "timeout", "subscription_only_acknowledged")}
            clean.update({key: requested[key] for key in ("api_key", "api_key_env", "base_url") if key in requested})
            return {**self._validated({**clean, "provider": "codex"}), "api_key": ""}
        default_url = "https://api.anthropic.com/v1" if provider == "anthropic" else "https://api.openai.com/v1"
        candidate["provider"] = provider
        raw_url = requested.get("base_url") if "base_url" in requested else (
            stored.get("base_url") if provider == stored.get("provider", "openai") else default_url
        )
        candidate["base_url"] = self.normalize_url(str(raw_url or default_url))
        old_provider = str(stored.get("provider") or "openai")
        old_default = "https://api.anthropic.com/v1" if old_provider == "anthropic" else "https://api.openai.com/v1"
        same_endpoint = provider == old_provider and candidate["base_url"] == self.normalize_url(str(stored.get("base_url") or old_default))
        key = str(requested.get("api_key") or "").strip()
        env_name = str(requested.get("api_key_env") or "").strip()
        if key and env_name and key != os.environ.get(env_name, ""):
            env_name = ""
        if not key and env_name:
            key = os.environ.get(env_name, "")
        if not key and same_endpoint and not env_name and requested.get("clear_secret") is not True:
            key = self._secret_store(stored).load() or ""
            if not key:
                env_name = str(stored.get("api_key_env") or "")
                key = os.environ.get(env_name, "")
        candidate["api_key"] = key
        candidate["api_key_env"] = env_name
        parsed = urlparse(candidate["base_url"])
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not key and not local:
            raise DomainError("model_secret_required", "请为当前接口提供 API Key；切换接口不会沿用旧密钥。", status=409)
        if require_model:
            return {**self._validated(candidate), "api_key": key}
        if provider not in PROVIDERS:
            raise DomainError("invalid_model_provider", "模型协议无效。")
        return candidate

    def _load_public(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DomainError("model_settings_corrupted", "写作模型设置损坏", status=500) from exc
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _registered_id(config: dict) -> str:
        identity = [config.get(key) for key in ("provider", "base_url", "model")]
        return "saved-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]

    def _registered_configs(self, value: dict) -> list[dict]:
        configs = {self._registered_id(item): item for item in value.get("registered_models", []) if isinstance(item, dict) and item.get("model")}
        if value.get("model"):
            current = {key: item for key, item in value.items() if key != "registered_models"}
            configs[self._registered_id(current)] = current
        return list(configs.values())

    @staticmethod
    def _config_digest(value: dict[str, Any]) -> str:
        public_config = {
            key: value.get(key)
            for key in (
                "preset_id",
                "provider",
                "base_url",
                "model",
                "api_key_env",
                "max_tokens",
                "timeout",
                "reasoning_mode",
                "input_cost_per_million",
                "output_cost_per_million",
                "credential_revision",
                "subscription_only_acknowledged",
                "billing",
            )
        }
        public_config.update({key: value.get(key) for key in ADVANCED_FIELDS})
        encoded = json.dumps(
            public_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def runtime_identity(self) -> dict[str, Any]:
        value = self._load_public()
        if not value:
            return {
                "settings_version": 0,
                "config_digest": "simulation",
                "provider": "fake",
                "model": "local-rules",
                "is_simulation": True,
            }
        return {
            "settings_version": max(1, int(value.get("settings_version") or 1)),
            "config_revision": str(
                value.get("config_revision")
                or f"model-config-{max(1, int(value.get('settings_version') or 1))}"
            ),
            "config_digest": str(value.get("config_digest") or self._config_digest(value)),
            "provider": str(value.get("provider") or "openai"),
            "model": str(value.get("model") or ""),
            "is_simulation": False,
        }

    @staticmethod
    def normalize_url(raw_url: str) -> str:
        cleaned = str(raw_url or "").strip().rstrip("/")
        if not cleaned:
            return ""
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DomainError("invalid_model_base_url", "模型接口地址必须是有效的 HTTP(S) URL")
        if parsed.username or parsed.password:
            raise DomainError("invalid_model_base_url", "模型接口地址不能包含账号或密码")
        if parsed.query or parsed.fragment:
            raise DomainError("invalid_model_base_url", "模型接口地址不能包含查询参数或片段")
        try:
            port = parsed.port
        except ValueError as exc:
            raise DomainError("invalid_model_base_url", "模型接口端口无效") from exc
        host = parsed.hostname.lower()
        host = f"[{host}]" if ":" in host else host
        if port and port != (443 if parsed.scheme == "https" else 80):
            host += f":{port}"
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/messages", "/models"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        if not path and host == "api.anthropic.com":
            path = "/v1"
        return f"{parsed.scheme}://{host}{path}"

    @classmethod
    def _validated(cls, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "openai").strip().lower()
        if provider == "codex":
            try:
                return validate_codex_config(payload)
            except CodexError as error:
                raise DomainError(error.code, error.message, details=error.details) from error
        if provider not in PROVIDERS:
            raise DomainError(
                "invalid_model_provider",
                "模型协议只支持 openai 或 anthropic",
                details={"allowed": sorted(PROVIDERS)},
            )
        model = str(payload.get("model") or "").strip()
        if not model or len(model) > 160:
            raise DomainError("invalid_model_name", "必须填写或选择有效模型名称")
        base_url = cls.normalize_url(str(payload.get("base_url") or ""))
        preset_id = str(payload.get("preset_id") or "custom").strip()
        api_key_env = str(payload.get("api_key_env") or "").strip()
        if api_key_env and not api_key_env.replace("_", "A").isalnum():
            raise DomainError("invalid_api_key_env", "密钥环境变量名称无效")
        advanced = normalize_advanced(payload)
        try:
            max_tokens = int(payload.get("max_tokens") or advanced.get("max_output_tokens") or 8192)
            timeout = int(payload.get("timeout") or 120)
            input_cost_per_million = float(payload.get("input_cost_per_million") or 0)
            output_cost_per_million = float(payload.get("output_cost_per_million") or 0)
        except (TypeError, ValueError) as exc:
            raise DomainError("invalid_model_limits", "模型预算、超时和单价必须是有效数字") from exc
        if not 256 <= max_tokens <= 10_000_000:
            raise DomainError("invalid_model_limits", "max_tokens 必须在 256 到 10000000 之间")
        if advanced.get("max_output_tokens") and max_tokens > advanced["max_output_tokens"]:
            raise DomainError("invalid_model_limits", "请求输出额度不能超过配置的模型最大输出。")
        if not 5 <= timeout <= 600:
            raise DomainError("invalid_model_limits", "timeout 必须在 5 到 600 秒之间")
        if not 0 <= input_cost_per_million <= 1000 or not 0 <= output_cost_per_million <= 1000:
            raise DomainError("invalid_model_limits", "每百万 Token 单价必须在 0 到 1000 美元之间")
        return {
            "preset_id": preset_id,
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "api_key_env": api_key_env,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "reasoning_mode": str(payload.get("reasoning_mode") or "balanced").strip(),
            "input_cost_per_million": input_cost_per_million,
            "output_cost_per_million": output_cost_per_million,
            **advanced,
        }

    def public(self) -> dict[str, Any]:
        value = self._load_public()
        env_name = str(value.get("api_key_env") or "")
        secret_source = (
            "dpapi"
            if self._secret_store(value).exists()
            else "environment"
            if env_name and bool(os.environ.get(env_name))
            else "none"
        )
        # Ollama / local can be configured without key
        is_local = urlparse(str(value.get("base_url") or "")).hostname in {"localhost", "127.0.0.1", "::1"}
        configured = bool(value.get("provider") and value.get("model") and (secret_source != "none" or is_local))
        if value.get("provider") == "codex":
            secret_source = "codex_managed_login"
            configured = bool(value.get("model") and value.get("subscription_only_acknowledged"))
        elif subscription_only_enabled():
            configured = False
        if value:
            value = {
                **value,
                "settings_version": max(1, int(value.get("settings_version") or 1)),
                "config_revision": str(
                    value.get("config_revision")
                    or f"model-config-{max(1, int(value.get('settings_version') or 1))}"
                ),
                "config_digest": str(value.get("config_digest") or self._config_digest(value)),
            }
        return {
            "ok": True,
            "subscription_only": subscription_only_enabled(),
            "registered_models": [
                {"id": self._registered_id(item), "model": item["model"], "provider": item.get("provider"), "base_url": item.get("base_url"), "current": self._registered_id(item) == self._registered_id(value)}
                for item in self._registered_configs(value)
            ],
            "model": {
                **{key: item for key, item in value.items() if key != "registered_models"},
                "configured": configured,
                "secret_source": secret_source,
                "dpapi_available": os.name == "nt",
            },
            "presets": VENDOR_PRESETS,
            "capability_catalog": model_catalog(),
        }

    def save(
        self,
        payload: dict[str, Any],
        *,
        connection_test: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._activation_lock:
            return self._save_candidate(self.resolve_candidate(payload), connection_test=connection_test)

    def _save_candidate(self, candidate: dict, *, connection_test: dict | None = None) -> dict:
        public_cfg = self._validated(candidate)
        previous = self._load_public()
        api_key = candidate["api_key"]
        public_cfg["credential_revision"] = uuid.uuid4().hex
        if api_key and not public_cfg["api_key_env"]:
            self._secret_store(public_cfg).save(api_key)
        public_cfg["settings_version"] = max(0, int(previous.get("settings_version") or 0)) + 1
        public_cfg["config_revision"] = f"model-config-{public_cfg['settings_version']}"
        public_cfg["config_digest"] = self._config_digest(public_cfg)
        if connection_test:
            activated_at = datetime.now(timezone.utc).isoformat()
            public_cfg.update({
                "activation_status": "active",
                "activated_at": activated_at,
                "last_tested_at": activated_at,
                "last_test_latency_ms": int(connection_test.get("latency_ms") or 0),
            })
        else:
            public_cfg.update({
                "activation_status": "saved_unverified",
                "activated_at": previous.get("activated_at"),
                "last_tested_at": previous.get("last_tested_at"),
                "last_test_latency_ms": previous.get("last_test_latency_ms"),
            })
        registered = {self._registered_id(item): item for item in self._registered_configs(previous)}
        # Freeze legacy credentials before the legacy inspection path is overwritten.
        for item in registered.values():
            if not item.get("credential_revision") and not item.get("api_key_env"):
                old_key = self.secret.load()
                if old_key:
                    item["credential_revision"] = uuid.uuid4().hex
                    self._secret_store(item).save(old_key)
        registered[self._registered_id(public_cfg)] = dict(public_cfg)
        public_cfg["registered_models"] = list(registered.values())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(public_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        if public_cfg.get("provider") == "codex" and connection_test:
            enable_subscription_only()
        # Keep the legacy inspection path synchronized for older local tooling;
        # runtime resolution remains bound to credential_revision above.
        if api_key and not public_cfg["api_key_env"]:
            try:
                self.secret.save(api_key)
            except Exception:
                pass
        return self.public()

    def activate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Test the exact candidate first; only a passing candidate is persisted."""
        with self._activation_lock:
            candidate = self.resolve_candidate(payload)
            tested = self.test_connection(candidate)
            saved = self._save_candidate(candidate, connection_test=tested)
            return {**saved, "test": tested}

    def get_credentials(self) -> dict[str, Any]:
        public_cfg = self._load_public()
        if not public_cfg:
            return {}
        if public_cfg.get("provider") == "codex":
            return {**public_cfg, "api_key": ""}
        secret = self._secret_store(public_cfg).load()
        if not secret and public_cfg.get("api_key_env"):
            secret = os.environ.get(str(public_cfg["api_key_env"]))
        return {
            **public_cfg,
            "api_key": secret or "",
        }

    def provider_settings(self) -> tuple[str, dict[str, Any]]:
        creds = self.get_credentials()
        provider = str(creds.get("provider") or "openai")
        return provider, creds

    def fetch_models(self, payload: dict[str, Any] | None = None) -> list[str] | dict[str, Any]:
        req_data = self.resolve_candidate(payload, require_model=False)
        if req_data.get("provider") == "codex":
            try:
                return [item["id"] for item in codex_connection().status()["models"]]
            except CodexError as error:
                raise DomainError(error.code, error.message, details=error.details) from error
        provider = str(req_data.get("provider") or "").strip().lower()
        base_url = str(req_data.get("base_url") or "").strip().rstrip("/")
        api_key = str(req_data.get("api_key") or "").strip()

        if not base_url:
            base_url = "https://api.openai.com/v1"

        models_endpoint = f"{base_url}/models"
        req = urllib.request.Request(models_endpoint)
        req.add_header("User-Agent", "HaloCue/1.0")
        if provider == "anthropic":
            req.add_header("anthropic-version", "2023-06-01")
            if api_key:
                req.add_header("x-api-key", api_key)
        elif api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("data") or data.get("models") or []
                model_ids = []
                details = []
                for item in items:
                    if isinstance(item, dict) and (item.get("id") or item.get("name") or item.get("model")):
                        detail = upstream_capabilities(item, provider, base_url)
                        model_ids.append(detail["model"])
                        details.append(detail)
                    elif isinstance(item, str):
                        model_ids.append(item)
                        details.append(capabilities(item, provider, base_url))
                # Sort prioritizing common chat models
                if payload and payload.get("include_metadata"):
                    return {"models": sorted(set(model_ids)), "model_details": details}
                return sorted(set(model_ids))
        except Exception as exc:
            raise DomainError(
                "fetch_models_failed",
                f"获取模型列表失败: {exc}",
                status=502,
                details={"endpoint": models_endpoint, "error": str(exc)},
            ) from exc

    def test_connection(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        req_data = self.resolve_candidate(payload)
        if req_data.get("provider") == "codex":
            try:
                return test_codex_connection(req_data)
            except CodexError as error:
                raise DomainError(error.code, error.message, status=502, details=error.details) from error
        provider = str(req_data.get("provider") or "").strip().lower()
        base_url = str(req_data.get("base_url") or "").strip().rstrip("/")
        model = str(req_data.get("model") or "").strip()
        api_key = str(req_data.get("api_key") or "").strip()

        if not model:
            raise DomainError("model_required", "请先选择或填写要测试的模型名称")

        started = time.monotonic()
        diagnostic_steps = []

        try:
            if provider == "anthropic":
                endpoint = f"{base_url or 'https://api.anthropic.com/v1'}/messages"
                req_body = json.dumps({
                    "model": model,
                    **completion_parameters(req_data, [{"role": "user", "content": "Reply with OK."}], probe=True),
                    "messages": [{"role": "user", "content": "Ping"}],
                }).encode("utf-8")
                req = urllib.request.Request(endpoint, data=req_body, method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("anthropic-version", "2023-06-01")
                req.add_header("x-api-key", api_key)
            else:
                endpoint = f"{base_url or 'https://api.openai.com/v1'}/chat/completions"
                req_body = json.dumps({
                    "model": model,
                    **completion_parameters(req_data, [{"role": "user", "content": "Reply with OK."}], probe=True),
                    "messages": [{"role": "user", "content": "Ping"}],
                }).encode("utf-8")
                req = urllib.request.Request(endpoint, data=req_body, method="POST")
                req.add_header("Content-Type", "application/json")
                if api_key:
                    req.add_header("Authorization", f"Bearer {api_key}")

            # Match model discovery and actual generation: relay gateways may reject
            # urllib's anonymous default User-Agent before checking credentials.
            req.add_header("User-Agent", "HaloCue/1.0")
            with urllib.request.urlopen(req, timeout=int(req_data.get("timeout") or 120)) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                validate_completion(body, provider)
                content = body.get("content") if provider == "anthropic" else body["choices"][0]["message"].get("content")
                if not content:
                    raise DomainError("provider_output_invalid", "连接测试没有返回有效内容。", status=502)
                latency_ms = round((time.monotonic() - started) * 1000)
                diagnostic_steps.append({"step": "network", "status": "passed", "label": "接口网络可达"})
                diagnostic_steps.append({"step": "auth", "status": "passed", "label": "鉴权有效"})
                diagnostic_steps.append({"step": "response", "status": "passed", "label": f"响应正常 ({latency_ms}ms)"})
                return {
                    "ok": True,
                    "latency_ms": latency_ms,
                    "model": model,
                    "provider": provider,
                    "diagnostics": diagnostic_steps,
                    "message": f"连接测试成功！耗时 {latency_ms}ms",
                }
        except urllib.error.HTTPError as exc:
            latency_ms = round((time.monotonic() - started) * 1000)
            err_body = exc.read().decode("utf-8", errors="ignore")
            reason = f"HTTP {exc.code}"
            hint = "请检查接口配置"
            if exc.code == 401:
                hint = "API Key 无效、过期或未正确设置"
            elif exc.code == 403:
                hint = "接口或中转网关拒绝访问，请核对服务商访问权限与网关策略；这不一定是密钥错误"
            elif exc.code == 404:
                hint = "接口路径不存在或模型名称有误，请核对 Base URL (是否缺少 /v1) 及模型 ID"
            elif exc.code == 429:
                hint = "账户余额不足或已超出速率限制 (Rate Limit)"
            elif exc.code >= 500:
                hint = "服务商上游服务暂时故障，请稍后再试"

            diagnostic_steps.append({
                "step": "error",
                "status": "failed",
                "code": exc.code,
                "label": f"连接失败: {reason}",
                "hint": hint,
                "raw": err_body[:300],
            })
            raise DomainError(
                "connection_test_failed",
                f"连接测试失败 ({reason}): {hint}",
                status=502,
                details={"diagnostics": diagnostic_steps, "raw": err_body[:300]},
            ) from exc
        except DomainError:
            raise
        except Exception as exc:
            diagnostic_steps.append({
                "step": "error",
                "status": "failed",
                "label": f"网络请求失败: {exc}",
                "hint": "无法连接到目标服务器，请检查网络、Base URL 拼写或代理设置",
            })
            raise DomainError(
                "connection_test_failed",
                f"网络连接失败: {exc}",
                status=502,
                details={"diagnostics": diagnostic_steps},
            ) from exc


class UserPreferencesStore:
    _DEFAULTS: dict[str, Any] = {
        "writing_tone": "bond_short",
        "char_warning_threshold": 35,
        "aa_pacing_wait_ms": 2500,
        "max_stage_characters": 4,
        "camera_switch_mode": "speaker_first",
        "editor_font_size": "medium",
    }
    _ENUMS = {
        "writing_tone": {"bond_short", "main_battle", "long_comedy", "text_reading"},
        # No other camera mode has a documented consumer yet.
        "camera_switch_mode": {"speaker_first"},
        "editor_font_size": {"small", "medium", "large"},
    }
    _INT_RANGES = {
        "char_warning_threshold": (15, 100),
        "aa_pacing_wait_ms": (1000, 5000),
        "max_stage_characters": (1, 5),
    }

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "user-preferences.json"
        self._lock = threading.RLock()

    @classmethod
    def _validate(cls, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise DomainError("invalid_user_preferences", "偏好设置必须是 JSON 对象。")
        result = {}
        for key, value in data.items():
            if key not in cls._DEFAULTS:
                continue
            if key in cls._ENUMS:
                valid = isinstance(value, str) and value in cls._ENUMS[key]
            else:
                low, high = cls._INT_RANGES[key]
                valid = type(value) is int and low <= value <= high
            if not valid:
                raise DomainError(
                    "invalid_user_preferences",
                    f"偏好设置字段无效：{key}。",
                    details={"field": key},
                )
            result[key] = value
        return result

    def _read_locked(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return dict(self._DEFAULTS)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DomainError(
                "invalid_user_preferences",
                "偏好设置文件不是有效的 UTF-8 JSON，原文件未修改。",
            ) from exc
        except OSError as exc:
            raise DomainError(
                "user_preferences_read_failed", "偏好设置文件读取失败。", status=500
            ) from exc
        return {**self._DEFAULTS, **self._validate(data)}

    def load(self) -> dict[str, Any]:
        with self._lock:
            return self._read_locked()

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            # Validate updates first; never reset a damaged original on save.
            updates = self._validate(payload)
            current = {**self._read_locked(), **updates}
            temp_path = self.path.parent / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_text(
                    json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temp_path, self.path)
            except OSError as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass  # Preserve the original write error if cleanup is also denied.
                raise DomainError(
                    "user_preferences_save_failed",
                    "偏好设置保存失败，原文件未修改。",
                    status=500,
                ) from exc
            return current
