from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import DomainError


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

    def _load_public(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DomainError("model_settings_corrupted", "写作模型设置损坏", status=500) from exc
        return value if isinstance(value, dict) else {}

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
            )
        }
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
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DomainError("invalid_model_base_url", "模型接口地址必须是有效的 HTTP(S) URL")
        if parsed.username or parsed.password:
            raise DomainError("invalid_model_base_url", "模型接口地址不能包含账号或密码")
        return cleaned

    @classmethod
    def _validated(cls, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "openai").strip().lower()
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
        try:
            max_tokens = int(payload.get("max_tokens") or 8192)
            timeout = int(payload.get("timeout") or 120)
            input_cost_per_million = float(payload.get("input_cost_per_million") or 0)
            output_cost_per_million = float(payload.get("output_cost_per_million") or 0)
        except (TypeError, ValueError) as exc:
            raise DomainError("invalid_model_limits", "模型预算、超时和单价必须是有效数字") from exc
        if not 256 <= max_tokens <= 256000:
            raise DomainError("invalid_model_limits", "max_tokens 必须在 256 到 256000 之间")
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
        # Ollama / local can be configured without key
        is_local = bool(value.get("preset_id") == "ollama" or "127.0.0.1" in str(value.get("base_url", "")))
        configured = bool(value.get("provider") and value.get("model") and (secret_source != "none" or is_local))
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
            "model": {
                **value,
                "configured": configured,
                "secret_source": secret_source,
                "dpapi_available": os.name == "nt",
            },
            "presets": VENDOR_PRESETS,
        }

    def save(
        self,
        payload: dict[str, Any],
        *,
        connection_test: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        public_cfg = self._validated(payload)
        previous = self._load_public()
        api_key = str(payload.get("api_key") or "").strip()
        if payload.get("clear_secret") is True:
            self.secret.clear()
        env_secret = bool(
            public_cfg.get("api_key_env")
            and os.environ.get(str(public_cfg["api_key_env"]))
        )
        is_local = bool(public_cfg.get("preset_id") == "ollama" or "127.0.0.1" in str(public_cfg.get("base_url", "")))
        if not api_key and not self.secret.exists() and not env_secret and not is_local:
            raise DomainError("model_secret_required", "必须提供 API Key 或已设置的密钥环境变量")
        if api_key:
            self.secret.save(api_key)
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(public_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        return self.public()

    def activate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Test the exact candidate first; only a passing candidate is persisted."""
        self._validated(payload)
        tested = self.test_connection(payload)
        saved = self.save(payload, connection_test=tested)
        return {**saved, "test": tested}

    def get_credentials(self) -> dict[str, Any]:
        public_cfg = self._load_public()
        if not public_cfg:
            return {}
        secret = self.secret.load()
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

    def fetch_models(self, payload: dict[str, Any] | None = None) -> list[str]:
        req_data = payload or {}
        provider = str(req_data.get("provider") or "").strip().lower()
        base_url = str(req_data.get("base_url") or "").strip().rstrip("/")
        api_key = str(req_data.get("api_key") or "").strip()

        # fallback to stored
        stored = self.get_credentials()
        provider = provider or stored.get("provider", "openai")
        base_url = base_url or stored.get("base_url", "")
        api_key = api_key or stored.get("api_key", "")

        if provider == "anthropic":
            # Anthropic models are standard, return curated list
            return [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
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
                # Sort prioritizing common chat models
                return sorted(set(model_ids))
        except Exception as exc:
            raise DomainError(
                "fetch_models_failed",
                f"获取模型列表失败: {exc}",
                status=502,
                details={"endpoint": models_endpoint, "error": str(exc)},
            ) from exc

    def test_connection(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        req_data = payload or {}
        provider = str(req_data.get("provider") or "").strip().lower()
        base_url = str(req_data.get("base_url") or "").strip().rstrip("/")
        model = str(req_data.get("model") or "").strip()
        api_key = str(req_data.get("api_key") or "").strip()

        stored = self.get_credentials()
        provider = provider or stored.get("provider", "openai")
        base_url = base_url or stored.get("base_url", "")
        model = model or stored.get("model", "")
        api_key = api_key or stored.get("api_key", "")

        if not model:
            raise DomainError("model_required", "请先选择或填写要测试的模型名称")

        started = time.monotonic()
        diagnostic_steps = []

        try:
            if provider == "anthropic":
                endpoint = f"{base_url or 'https://api.anthropic.com/v1'}/messages"
                req_body = json.dumps({
                    "model": model,
                    "max_tokens": 10,
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
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "Ping"}],
                }).encode("utf-8")
                req = urllib.request.Request(endpoint, data=req_body, method="POST")
                req.add_header("Content-Type", "application/json")
                if api_key:
                    req.add_header("Authorization", f"Bearer {api_key}")

            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
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
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "user-preferences.json"

    def load(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "writing_tone": "bond_short",  # bond_short, main_battle, long_comedy, text_reading
            "char_warning_threshold": 35,
            "aa_pacing_wait_ms": 2500,
            "max_stage_characters": 4,
            "camera_switch_mode": "speaker_first",
            "editor_font_size": "medium",  # small, medium, large
        }
        if not self.path.is_file():
            return defaults
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update(data)
        except Exception:
            pass
        return defaults

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        for key in (
            "writing_tone",
            "char_warning_threshold",
            "aa_pacing_wait_ms",
            "max_stage_characters",
            "camera_switch_mode",
            "editor_font_size",
        ):
            if key in payload:
                current[key] = payload[key]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return current
