from __future__ import annotations

import base64
import ctypes
import json
import os
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
            if self.secret.exists()
            else "environment"
            if env_name and bool(os.environ.get(env_name))
            else "none"
        )
        is_local = bool(value.get("preset_id") == "ollama" or "127.0.0.1" in str(value.get("base_url", "")))
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

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        public = self._validated(payload)
        api_key = str(payload.get("api_key") or "").strip()
        if payload.get("clear_secret") is True:
            self.secret.clear()
        env_secret = bool(
            public.get("api_key_env")
            and os.environ.get(str(public["api_key_env"]))
        )
        is_local = bool(public.get("preset_id") == "ollama" or "127.0.0.1" in str(public.get("base_url", "")))
        if not api_key and not self.secret.exists() and not env_secret and not is_local:
            raise ProductionError(
                "model_secret_required",
                "必须提供 API Key 或已设置的密钥环境变量",
            )
        if api_key:
            self.secret.save(api_key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        return self.public()

    def fetch_models(self, payload: dict[str, Any] | None = None) -> list[str]:
        import urllib.request
        req_data = payload or {}
        provider = str(req_data.get("provider") or "").strip().lower()
        base_url = str(req_data.get("base_url") or "").strip().rstrip("/")
        api_key = str(req_data.get("api_key") or "").strip()

        if not api_key:
            api_key = self.secret.load() or ""
        public_cfg = self._load_public()
        provider = provider or public_cfg.get("provider", "openai")
        base_url = base_url or public_cfg.get("base_url", "")

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
        secret = self.secret.load()
        if secret:
            public["api_key"] = secret
        return str(public["provider"]), public
