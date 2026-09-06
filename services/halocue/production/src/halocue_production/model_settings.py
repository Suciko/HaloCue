from __future__ import annotations

import base64
import ctypes
import json
import threading
import os
import hashlib
import uuid
from datetime import datetime, timezone
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ProductionError


PROVIDERS = {"openai", "anthropic"}

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
            raise ProductionError(
                "secure_secret_store_unavailable",
                "当前系统不支持 Windows DPAPI，请改用环境变量保存密钥",
                status=409,
            )
        source, source_buffer = cls._blob(value.encode("utf-8"))
        output = _DataBlob()
        description = "HaloCue 1.0 direction model"
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), description, None, None, None, 0, ctypes.byref(output)
        ):
            raise ProductionError("secret_store_failed", "模型密钥加密失败", status=500)
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output.pbData)
            del source_buffer

    @classmethod
    def _unprotect(cls, value: bytes) -> str:
        if os.name != "nt":
            raise ProductionError(
                "secure_secret_store_unavailable",
                "当前系统不支持读取加密模型密钥",
                status=409,
            )
        source, source_buffer = cls._blob(value)
        output = _DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
        ):
            raise ProductionError("secret_store_failed", "模型密钥解密失败", status=500)
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
            raise ProductionError(
                "model_secret_corrupted", "模型密钥存储损坏", status=500
            ) from exc

    def clear(self) -> None:
        if self.path.is_file():
            self.path.unlink()

    def exists(self) -> bool:
        return self.path.is_file()


class DirectionModelSettings:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "direction-model.json"
        self.secret = ModelSecretStore(data_dir / "secrets" / "direction-model.dpapi")
        self.activation_lock = threading.RLock()

    def _secret_store(self, config: dict) -> ModelSecretStore:
        reference = config.get("credential_revision")
        if not reference:
            return self.secret
        if not isinstance(reference, str) or len(reference) != 32 or any(c not in "0123456789abcdef" for c in reference):
            raise ProductionError("model_settings_corrupted", "模型密钥版本无效。", status=500)
        return ModelSecretStore(self.path.parent / "secrets" / f"direction-{reference}.dpapi")

    def resolve_candidate(self, payload: dict | None = None, *, require_model: bool = True) -> dict:
        requested = dict(payload or {})
        stored = self._load_public()
        candidate = {**stored, **requested}
        provider = str(candidate.get("provider") or "openai").strip().lower()
        default_url = "https://api.anthropic.com/v1" if provider == "anthropic" else "https://api.openai.com/v1"
        candidate["provider"] = provider
        raw_url = requested.get("base_url") if "base_url" in requested else (
            stored.get("base_url") if provider == stored.get("provider", "openai") else default_url
        )
        candidate["base_url"] = self.normalize_url(str(raw_url or default_url))
        parsed = urlparse(candidate["base_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ProductionError("invalid_model_base_url", "模型接口地址无效。")
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
        if not key and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ProductionError("model_secret_required", "请为当前接口提供 API Key；切换接口不会沿用旧密钥。", status=409)
        if require_model:
            return {**self._validated(candidate), "api_key": key}
        if provider not in PROVIDERS:
            raise ProductionError("invalid_model_provider", "模型协议无效。")
        return candidate

    def _load_public(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProductionError(
                "model_settings_corrupted", "演出模型设置损坏", status=500
            ) from exc
        return value if isinstance(value, dict) else {}

    @staticmethod
    def normalize_url(raw_url: str) -> str:
        parsed = urlparse(str(raw_url or "").strip().rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ProductionError("invalid_model_base_url", "模型接口地址无效。")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ProductionError("invalid_model_base_url", "模型接口端口无效。") from exc
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

    @staticmethod
    def _validated(payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "").strip().lower()
        if provider not in PROVIDERS:
            raise ProductionError(
                "invalid_model_provider",
                "模型协议只支持 openai 或 anthropic",
                details={"allowed": sorted(PROVIDERS)},
            )
        model = str(payload.get("model") or "").strip()
        if not model or len(model) > 160:
            raise ProductionError("invalid_model_name", "必须填写有效模型名称")
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ProductionError("invalid_model_base_url", "模型地址必须是 HTTP(S) URL")
            if parsed.username or parsed.password:
                raise ProductionError("invalid_model_base_url", "模型地址不能包含账号或密码")
        api_key_env = str(payload.get("api_key_env") or "").strip()
        if api_key_env and not api_key_env.replace("_", "A").isalnum():
            raise ProductionError("invalid_api_key_env", "密钥环境变量名称无效")
        try:
            max_tokens = int(payload.get("max_tokens") or 16000)
            timeout = int(payload.get("timeout") or 180)
        except (TypeError, ValueError) as exc:
            raise ProductionError("invalid_model_limits", "模型预算和超时必须是整数") from exc
        if not 512 <= max_tokens <= 128000:
            raise ProductionError("invalid_model_limits", "max_tokens 必须在 512 到 128000 之间")
        if not 5 <= timeout <= 600:
            raise ProductionError("invalid_model_limits", "timeout 必须在 5 到 600 秒之间")
        return {
            "preset_id": str(payload.get("preset_id") or "custom"),
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "api_key_env": api_key_env,
            "max_tokens": max_tokens,
            "annotation_max_tokens": max_tokens,
            "timeout": timeout,
            "wall_timeout": min(1800, max(timeout, int(payload.get("wall_timeout") or 300))),
            "reasoning_mode": str(payload.get("reasoning_mode") or "balanced").strip(),
            "reasoning_wire_protocol": str(
                payload.get("reasoning_wire_protocol") or ""
            ).strip(),
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
        is_local = urlparse(str(value.get("base_url") or "")).hostname in {"localhost", "127.0.0.1", "::1"}
        configured = bool(value.get("provider") and value.get("model") and (secret_source != "none" or is_local))
        return {
            "ok": True,
            "model": {
                **value,
                "configured": configured,
                "secret_source": secret_source,
                "dpapi_available": os.name == "nt",
            },
            "presets": VENDOR_PRESETS,
        }

    def save(self, payload: dict[str, Any], *, connection_test: dict | None = None) -> dict[str, Any]:
        with self.activation_lock:
            return self._save_candidate(self.resolve_candidate(payload), connection_test=connection_test)

    def _save_candidate(self, candidate: dict, *, connection_test: dict | None = None) -> dict:
        public = self._validated(candidate)
        api_key = candidate["api_key"]
        public["credential_revision"] = uuid.uuid4().hex
        if api_key and not public["api_key_env"]:
            self._secret_store(public).save(api_key)
        public["config_revision"] = uuid.uuid4().hex
        public["config_digest"] = "sha256:" + hashlib.sha256(json.dumps(public, sort_keys=True).encode("utf-8")).hexdigest()
        public["activation_status"] = "active" if connection_test else "saved_unverified"
        if connection_test:
            public["last_tested_at"] = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        if api_key and not public["api_key_env"]:
            try:
                self.secret.save(api_key)
            except Exception:
                pass
        return self.public()

    def fetch_models(self, payload: dict[str, Any] | None = None) -> list[str]:
        import urllib.request
        req_data = self.resolve_candidate(payload, require_model=False)
        provider = str(req_data.get("provider") or "").strip().lower()
        base_url = str(req_data.get("base_url") or "").strip().rstrip("/")
        api_key = str(req_data.get("api_key") or "").strip()

        if provider == "anthropic":
            return [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ]
        if not base_url:
            base_url = "https://api.openai.com/v1"

        models_endpoint = f"{base_url}/models"
        req = urllib.request.Request(models_endpoint)
        req.add_header("User-Agent", "HaloCue/1.0")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("data") or data.get("models") or []
                model_ids = []
                for item in items:
                    if isinstance(item, dict) and "id" in item:
                        model_ids.append(str(item["id"]))
                    elif isinstance(item, str):
                        model_ids.append(item)
                return sorted(set(model_ids))
        except Exception as exc:
            raise ProductionError(
                "fetch_models_failed",
                f"获取模型列表失败: {exc}",
                status=502,
                details={"endpoint": models_endpoint, "error": str(exc)},
            ) from exc


    def provider_settings(self) -> tuple[str, dict[str, Any]]:
        public = self._load_public()
        state = self.public()["model"]
        if not state["configured"]:
            raise ProductionError(
                "direction_generation_not_configured",
                "AI 安排演出的模型尚未配置",
                status=409,
            )
        secret = self._secret_store(public).load() or os.environ.get(str(public.get("api_key_env") or ""), "")
        if secret:
            public["api_key"] = secret
        public.setdefault("source_context_strategy", "window")
        public.setdefault("transport_retries", 2)
        return str(public["provider"]), public
