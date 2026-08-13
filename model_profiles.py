# -*- coding: utf-8 -*-
"""Model profiles with secrets stored in Windows Credential Manager."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from model_capabilities import resolve_reasoning_capability


_TARGET_PREFIX = "AA-AutoWriter/"
_PROVIDERS = {"openai", "anthropic"}
MODEL_PRESETS = {
    "openai": {"label": "OpenAI", "provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o", "vision": True, "official_url": "https://openai.com/api/", "api_key_url": "https://platform.openai.com/api-keys"},
    "anthropic": {"label": "Anthropic", "provider": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-5", "vision": True, "official_url": "https://www.anthropic.com/api", "api_key_url": "https://console.anthropic.com/settings/keys"},
    "gemini": {"label": "Gemini", "provider": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash", "vision": True, "official_url": "https://ai.google.dev/gemini-api/docs", "api_key_url": "https://aistudio.google.com/apikey"},
    "deepseek": {"label": "DeepSeek", "provider": "openai", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-v4-flash", "vision": False, "official_url": "https://www.deepseek.com/", "api_key_url": "https://platform.deepseek.com/api_keys"},
    "glm": {"label": "GLM / 智谱", "provider": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.6", "vision": True, "official_url": "https://open.bigmodel.cn/", "api_key_url": "https://open.bigmodel.cn/usercenter/apikeys"},
    "qwen": {"label": "千问 / 百炼", "provider": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max", "vision": True, "official_url": "https://bailian.console.aliyun.com/", "api_key_url": "https://bailian.console.aliyun.com/?apiKey=1"},
    "moonshot": {"label": "Kimi / Moonshot", "provider": "openai", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2-0905-preview", "vision": False, "official_url": "https://platform.kimi.com/", "api_key_url": "https://platform.kimi.com/console/api-keys"},
    "siliconflow": {"label": "硅基流动", "provider": "openai", "base_url": "https://api.siliconflow.cn/v1", "model": "deepseek-ai/DeepSeek-V3", "vision": False, "official_url": "https://siliconflow.cn/", "api_key_url": "https://cloud.siliconflow.cn/account/ak"},
    "openrouter": {"label": "OpenRouter", "provider": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini", "vision": True, "official_url": "https://openrouter.ai/", "api_key_url": "https://openrouter.ai/settings/keys"},
    "ollama": {"label": "Ollama", "provider": "openai", "base_url": "http://localhost:11434/v1", "model": "llama3.2", "vision": False, "official_url": "https://ollama.com/", "api_key_url": ""},
    "custom": {"label": "自定义", "provider": "openai", "base_url": "", "model": "", "vision": True, "official_url": "", "api_key_url": ""},
}

_CAPABILITY_STATUSES = {"untested", "passed", "failed", "unsupported"}
_VISION_MODES = {"separate", "base", "disabled"}
_MAX_TOKEN_SOURCES = {"legacy", "api", "catalog", "models_dev", "unknown", "manual"}
_RECOMMENDATION_SOURCES = {"api", "catalog", "models_dev", "unknown"}
_REASONING_MODES = {
    "speed", "minimal", "low", "balanced", "medium", "deep", "high",
    "xhigh", "max", "provider_default",
}
_ANNOTATION_BUDGET_SOURCES = {"auto", "manual"}
def resolve_annotation_budget(record: dict) -> tuple[int, str]:
    """Return the effective Agent output budget and whether it is automatic."""
    maximum = max(1, int(record.get("max_tokens") or 16_000))
    configured = record.get("annotation_max_tokens")
    try:
        configured_value = int(configured) if configured not in (None, "") else None
    except (TypeError, ValueError):
        configured_value = None
    raw_source = str(record.get("annotation_max_tokens_source") or "").strip().lower()
    if raw_source in _ANNOTATION_BUDGET_SOURCES:
        source = raw_source
    else:
        # Previous releases wrote 16000 automatically without recording provenance.
        source = "auto" if configured_value in (None, 16_000) else "manual"
    if source == "manual" and configured_value is not None:
        return min(maximum, max(1, configured_value)), source
    return maximum, "auto"


def source_context_strategy_for_connection(connection: dict) -> str:
    return "window" if str(connection.get("service_preset") or "") == "ollama" else "preserve"


class ModelProfileError(ValueError):
    pass


class CredentialStoreError(RuntimeError):
    pass


class _CtypesWindowsCredentials:
    """Small stdlib binding for generic Windows credentials."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self._ctypes = ctypes
        self._credential = Credential
        self._pointer = ctypes.POINTER(Credential)
        self._advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(self._pointer),
        ]
        self._advapi.CredReadW.restype = wintypes.BOOL
        self._advapi.CredWriteW.argtypes = [self._pointer, wintypes.DWORD]
        self._advapi.CredWriteW.restype = wintypes.BOOL
        self._advapi.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi.CredDeleteW.restype = wintypes.BOOL
        self._advapi.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi.CredFree.restype = None

    def _raise_last_error(self):
        error = self._ctypes.get_last_error()
        if error == self.ERROR_NOT_FOUND:
            raise KeyError(error)
        raise OSError(error, self._ctypes.FormatError(error))

    def CredRead(self, target, credential_type, _flags):
        pointer = self._pointer()
        if not self._advapi.CredReadW(target, credential_type, 0, self._ctypes.byref(pointer)):
            self._raise_last_error()
        try:
            record = pointer.contents
            blob = self._ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
            return {"CredentialBlob": blob}
        finally:
            self._advapi.CredFree(pointer)

    def CredWrite(self, record, _flags):
        blob = str(record["CredentialBlob"]).encode("utf-16-le")
        blob_buffer = (self._ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = self._credential()
        credential.Type = int(record["Type"])
        credential.TargetName = str(record["TargetName"])
        credential.Comment = str(record.get("Comment") or "")
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = self._ctypes.cast(
            blob_buffer, self._ctypes.POINTER(self._ctypes.c_ubyte)
        )
        credential.Persist = int(record["Persist"])
        credential.UserName = str(record.get("UserName") or "")
        if not self._advapi.CredWriteW(self._ctypes.byref(credential), 0):
            self._raise_last_error()

    def CredDelete(self, target, credential_type, _flags):
        if not self._advapi.CredDeleteW(target, credential_type, 0):
            self._raise_last_error()


class WindowsCredentialStore:
    """Store generic credentials encrypted by the current Windows account."""

    def __init__(self, *, win32cred_module=None):
        fallback_api = None
        if os.name == "nt":
            try:
                fallback_api = _CtypesWindowsCredentials()
            except (AttributeError, OSError):
                pass
        if win32cred_module is None:
            try:
                import win32cred as win32cred_module
            except ImportError:
                pass
        self._fallback_api = fallback_api
        self._api = win32cred_module or fallback_api
        self.available = self._api is not None

    def _recover_missing_module(self, exc: Exception) -> bool:
        """Use the stdlib binding when a partially bundled pywin32 fails lazily."""
        if not isinstance(exc, ModuleNotFoundError):
            return False
        if self._fallback_api is None or self._api is self._fallback_api:
            return False
        self._api = self._fallback_api
        self.available = True
        return True

    @staticmethod
    def _missing(exc: Exception) -> bool:
        return isinstance(exc, KeyError) or getattr(exc, "winerror", None) == 1168

    def read(self, target: str) -> str | None:
        if not self.available:
            return None
        try:
            record = self._api.CredRead(
                str(target),
                self._api.CRED_TYPE_GENERIC,
                0,
            )
        except Exception as exc:
            if self._recover_missing_module(exc):
                return self.read(target)
            if self._missing(exc):
                return None
            raise CredentialStoreError(
                f"无法读取 Windows 凭据：{type(exc).__name__}"
            ) from exc
        value = record.get("CredentialBlob", b"")
        if isinstance(value, bytes):
            return value.decode("utf-16-le")
        return str(value)

    def write(self, target: str, secret: str) -> None:
        if not self.available:
            raise CredentialStoreError("当前环境不支持 Windows 凭据管理器")
        try:
            self._api.CredWrite(
                {
                    "Type": self._api.CRED_TYPE_GENERIC,
                    "TargetName": str(target),
                    "CredentialBlob": str(secret),
                    "Persist": self._api.CRED_PERSIST_LOCAL_MACHINE,
                    "UserName": "AA Auto Writer",
                    "Comment": "AA 自动写剧本工具的模型接口密钥",
                },
                0,
            )
        except Exception as exc:
            if self._recover_missing_module(exc):
                self.write(target, secret)
                return
            raise CredentialStoreError(
                f"无法写入 Windows 凭据：{type(exc).__name__}"
            ) from exc

    def delete(self, target: str) -> None:
        if not self.available:
            return
        try:
            self._api.CredDelete(
                str(target),
                self._api.CRED_TYPE_GENERIC,
                0,
            )
        except Exception as exc:
            if self._recover_missing_module(exc):
                self.delete(target)
                return
            if self._missing(exc):
                return
            raise CredentialStoreError(
                f"无法删除 Windows 凭据：{type(exc).__name__}"
            ) from exc


class ModelProfileStore:
    """Persist non-secret model settings and keep secrets out of JSON."""

    def __init__(self, path, *, credentials=None):
        self.path = Path(path)
        self.credentials = credentials or WindowsCredentialStore()
        self._session_secrets: dict[str, str] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _target(profile_id: str) -> str:
        return _TARGET_PREFIX + profile_id

    @staticmethod
    def _connection_target(connection_id: str) -> str:
        return _TARGET_PREFIX + "connection/" + connection_id

    @staticmethod
    def _empty_state() -> dict:
        return {
            "version": 2,
            "active_profile_id": "",
            "profiles": [],
            "connections": [],
            "models": [],
            "assignments": {
                "base_model_id": "",
                "vision_mode": "disabled",
                "vision_model_id": "",
            },
        }

    def _load(self) -> dict:
        if not self.path.is_file():
            return self._empty_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelProfileError(f"无法读取模型配置：{exc}") from exc
        profiles = data.get("profiles", [])
        if not isinstance(profiles, list):
            raise ModelProfileError("模型配置中的 profiles 必须是数组")
        state = self._empty_state()
        state["version"] = int(data.get("version") or 1)
        state["active_profile_id"] = str(data.get("active_profile_id") or "")
        state["profiles"] = profiles
        for key in ("connections", "models"):
            value = data.get(key, [])
            if not isinstance(value, list):
                raise ModelProfileError(f"模型配置中的 {key} 必须是数组")
            state[key] = value
        assignments = data.get("assignments")
        if isinstance(assignments, dict):
            state["assignments"] = {
                "base_model_id": str(assignments.get("base_model_id") or ""),
                "vision_mode": str(assignments.get("vision_mode") or "disabled"),
                "vision_model_id": str(assignments.get("vision_model_id") or ""),
            }
        return state

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _validated(payload: dict, *, profile_id: str) -> dict:
        name = str(payload.get("name") or "").strip()
        provider = str(payload.get("provider") or "").strip().lower()
        model = str(payload.get("model") or "").strip()
        if not name:
            raise ModelProfileError("name 不能为空")
        if provider not in _PROVIDERS:
            raise ModelProfileError(
                "provider 必须是 openai 或 anthropic"
            )
        if not model:
            raise ModelProfileError("model 不能为空")
        raw_max_tokens = payload.get("max_tokens", 16000)
        if raw_max_tokens in (None, ""):
            raw_max_tokens = 16000
        try:
            max_tokens = int(raw_max_tokens)
        except (TypeError, ValueError) as exc:
            raise ModelProfileError("max_tokens 必须是整数") from exc
        if not 1 <= max_tokens <= 1_000_000:
            raise ModelProfileError("max_tokens 必须在 1 到 1000000 之间")
        max_tokens_source = str(payload.get("max_tokens_source") or "legacy").strip().lower()
        if max_tokens_source not in _MAX_TOKEN_SOURCES:
            raise ModelProfileError("invalid max token source")
        raw_recommended = payload.get("recommended_max_tokens")
        if raw_recommended in (None, ""):
            recommended = None
        else:
            try:
                recommended = int(raw_recommended)
            except (TypeError, ValueError) as exc:
                raise ModelProfileError("recommended_max_tokens must be an integer") from exc
            if not 1 <= recommended <= 1_000_000:
                raise ModelProfileError("recommended_max_tokens out of range")
        recommended_source = str(payload.get("recommended_source") or "unknown").strip().lower()
        if recommended_source not in _RECOMMENDATION_SOURCES:
            raise ModelProfileError("invalid recommendation source")
        recommended_label = str(payload.get("recommended_label") or "上限未识别").strip()[:120]
        service_preset = str(payload.get("service_preset") or "custom").strip().lower()
        if service_preset not in MODEL_PRESETS:
            raise ModelProfileError("service_preset 无效")
        context_window = payload.get("context_window_tokens")
        if context_window not in (None, ""):
            try:
                context_window = int(context_window)
            except (TypeError, ValueError) as exc:
                raise ModelProfileError("context_window_tokens 必须是整数") from exc
            if not 1 <= context_window <= 10_000_000:
                raise ModelProfileError("context_window_tokens 超出范围")
        context_source = str(payload.get("context_window_source") or "unknown").strip().lower()
        if context_source not in {"api", "catalog", "models_dev", "manual", "unknown"}:
            raise ModelProfileError("context_window_source 无效")
        return {
            "id": profile_id,
            "name": name,
            "provider": provider,
            "service_preset": service_preset,
            "base_url": str(payload.get("base_url") or "").strip(),
            "model": model,
            "max_tokens": max_tokens,
            "max_tokens_source": max_tokens_source,
            "recommended_max_tokens": recommended,
            "recommended_source": recommended_source,
            "recommended_label": recommended_label or "上限未识别",
            "context_window_tokens": context_window,
            "context_window_source": context_source,
            "vision": bool(payload.get("vision", True)),
        }

    def _secret_status(self, profile_id: str) -> str:
        if self._session_secrets.get(profile_id):
            return "session"
        if self.credentials.read(self._target(profile_id)):
            return "saved"
        return "missing"

    def _public(self, record: dict) -> dict:
        record = self._provenance(record)
        result = {
            key: record.get(key)
            for key in (
                "id",
                "name",
                "provider",
                "base_url",
                "model",
                "max_tokens",
                "max_tokens_source",
                "recommended_max_tokens",
                "recommended_source",
                "recommended_label",
                "context_window_tokens",
                "context_window_source",
                "vision",
                "service_preset",
            )
        }
        result["secret_status"] = self._secret_status(str(record["id"]))
        result["credential_available"] = bool(
            getattr(self.credentials, "available", False)
        )
        return result

    @staticmethod
    def _provenance(record: dict) -> dict:
        """Normalize provenance for old JSON records without rewriting them."""
        result = dict(record)
        source = str(result.get("max_tokens_source") or "legacy").strip().lower()
        result["max_tokens_source"] = source if source in _MAX_TOKEN_SOURCES else "legacy"
        raw_recommended = result.get("recommended_max_tokens")
        try:
            recommended = int(raw_recommended) if raw_recommended not in (None, "") else None
        except (TypeError, ValueError):
            recommended = None
        result["recommended_max_tokens"] = (
            recommended if recommended and 1 <= recommended <= 1_000_000 else None
        )
        recommendation_source = str(result.get("recommended_source") or "unknown").strip().lower()
        result["recommended_source"] = (
            recommendation_source
            if recommendation_source in _RECOMMENDATION_SOURCES
            else "unknown"
        )
        result["recommended_label"] = (
            str(result.get("recommended_label") or "\u4e0a\u9650\u672a\u8bc6\u522b").strip()[:120]
            or "\u4e0a\u9650\u672a\u8bc6\u522b"
        )
        return result

    @staticmethod
    def _validated_connection(payload: dict, *, connection_id: str) -> dict:
        name = str(payload.get("name") or "").strip()
        protocol = str(payload.get("protocol") or payload.get("provider") or "").strip().lower()
        preset = str(payload.get("service_preset") or "custom").strip().lower()
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        if not name:
            raise ModelProfileError("连接名称不能为空")
        if protocol not in _PROVIDERS:
            raise ModelProfileError("接口协议必须是 openai 或 anthropic")
        if preset not in MODEL_PRESETS:
            raise ModelProfileError("service_preset 无效")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ModelProfileError("API 地址必须是有效的 HTTP(S) URL")
        return {
            "id": connection_id,
            "name": name,
            "service_preset": preset,
            "protocol": protocol,
            "base_url": base_url,
        }

    @staticmethod
    def _validated_model(payload: dict, *, model_id: str, connection_ids: set[str]) -> dict:
        connection_id = str(payload.get("connection_id") or "").strip()
        model = str(payload.get("model") or "").strip()
        if connection_id not in connection_ids:
            raise ModelProfileError("找不到模型所属的供应商连接")
        if not model:
            raise ModelProfileError("模型名称不能为空")
        try:
            max_tokens = int(payload.get("max_tokens") or 16000)
        except (TypeError, ValueError) as exc:
            raise ModelProfileError("max_tokens 必须是整数") from exc
        if not 1 <= max_tokens <= 1_000_000:
            raise ModelProfileError("max_tokens 必须在 1 到 1000000 之间")
        max_tokens_source = str(payload.get("max_tokens_source") or "legacy").strip().lower()
        if max_tokens_source not in _MAX_TOKEN_SOURCES:
            raise ModelProfileError("invalid max token source")
        raw_recommended = payload.get("recommended_max_tokens")
        if raw_recommended in (None, ""):
            recommended = None
        else:
            try:
                recommended = int(raw_recommended)
            except (TypeError, ValueError) as exc:
                raise ModelProfileError("recommended_max_tokens must be an integer") from exc
            if not 1 <= recommended <= 1_000_000:
                raise ModelProfileError("recommended_max_tokens out of range")
        recommended_source = str(payload.get("recommended_source") or "unknown").strip().lower()
        if recommended_source not in _RECOMMENDATION_SOURCES:
            raise ModelProfileError("invalid recommendation source")
        recommended_label = str(payload.get("recommended_label") or "上限未识别").strip()[:120]
        text_status = str(payload.get("text_status") or "untested")
        vision_status = str(payload.get("vision_status") or "untested")
        if text_status not in _CAPABILITY_STATUSES or vision_status not in _CAPABILITY_STATUSES:
            raise ModelProfileError("模型能力状态无效")
        reasoning_mode = str(payload.get("reasoning_mode") or "balanced").strip().lower()
        if reasoning_mode not in _REASONING_MODES:
            raise ModelProfileError("reasoning_mode 无效")
        raw_annotation_budget = payload.get("annotation_max_tokens")
        raw_annotation_source = str(
            payload.get("annotation_max_tokens_source") or ""
        ).strip().lower()
        if raw_annotation_source and raw_annotation_source not in _ANNOTATION_BUDGET_SOURCES:
            raise ModelProfileError("annotation_max_tokens_source 无效")
        annotation_source = raw_annotation_source or (
            "manual" if raw_annotation_budget not in (None, "") else "auto"
        )
        if annotation_source == "manual":
            try:
                manual_annotation_budget = int(raw_annotation_budget)
            except (TypeError, ValueError) as exc:
                raise ModelProfileError("annotation_max_tokens 必须是整数") from exc
            if not 1 <= manual_annotation_budget <= max_tokens:
                raise ModelProfileError("annotation_max_tokens 必须在 1 到 max_tokens 之间")
        try:
            annotation_max_tokens, annotation_source = resolve_annotation_budget({
                "max_tokens": max_tokens,
                "reasoning_mode": reasoning_mode,
                "annotation_max_tokens": raw_annotation_budget,
                "annotation_max_tokens_source": annotation_source,
            })
        except (TypeError, ValueError) as exc:
            raise ModelProfileError("annotation_max_tokens 必须是整数") from exc
        if not 1 <= annotation_max_tokens <= max_tokens:
            raise ModelProfileError("annotation_max_tokens 必须在 1 到 max_tokens 之间")
        context_window = payload.get("context_window_tokens")
        if context_window not in (None, ""):
            try:
                context_window = int(context_window)
            except (TypeError, ValueError) as exc:
                raise ModelProfileError("context_window_tokens 必须是整数") from exc
            if not 1 <= context_window <= 10_000_000:
                raise ModelProfileError("context_window_tokens 超出范围")
        context_source = str(payload.get("context_window_source") or "unknown").strip().lower()
        if context_source not in {"api", "catalog", "models_dev", "manual", "unknown"}:
            raise ModelProfileError("context_window_source 无效")
        return {
            "id": model_id,
            "connection_id": connection_id,
            "model": model,
            "max_tokens": max_tokens,
            "max_tokens_source": max_tokens_source,
            "recommended_max_tokens": recommended,
            "recommended_source": recommended_source,
            "recommended_label": recommended_label or "上限未识别",
            "text_status": text_status,
            "vision_status": vision_status,
            "reasoning_mode": reasoning_mode,
            "annotation_max_tokens": annotation_max_tokens,
            "annotation_max_tokens_source": annotation_source,
            "context_window_tokens": context_window,
            "context_window_source": context_source,
        }

    def _public_connection(self, record: dict) -> dict:
        result = dict(record)
        result["secret_status"] = (
            "saved" if self.resolve_connection_key(str(record["id"])) else "missing"
        )
        return result

    def migrate_legacy_profiles(self) -> dict:
        with self._lock:
            state = self._load()
            if state["version"] >= 2:
                return self._public_v2_state(state)

            active_profile_id = str(state.get("active_profile_id") or "")
            model_by_profile: dict[str, str] = {}
            for profile in state["profiles"]:
                profile_id = str(profile.get("id") or uuid.uuid4().hex)
                connection_id = "connection-" + profile_id
                model_id = "model-" + profile_id
                connection = self._validated_connection(
                    {
                        "name": profile.get("name") or profile.get("model") or "模型连接",
                        "service_preset": profile.get("service_preset") or "custom",
                        "protocol": profile.get("provider") or "openai",
                        "base_url": profile.get("base_url") or "",
                    },
                    connection_id=connection_id,
                )
                model = self._validated_model(
                    {
                        "connection_id": connection_id,
                        "model": profile.get("model"),
                        "max_tokens": profile.get("max_tokens", 16000),
                        "text_status": "untested",
                        "vision_status": "unsupported" if profile.get("vision") is False else "untested",
                    },
                    model_id=model_id,
                    connection_ids={connection_id},
                )
                state["connections"].append(connection)
                state["models"].append(model)
                model_by_profile[profile_id] = model_id
                old_secret = self.resolve_api_key(profile_id)
                if old_secret and not self.credentials.read(self._connection_target(connection_id)):
                    self.credentials.write(self._connection_target(connection_id), old_secret)

            state["version"] = 2
            state["assignments"] = {
                "base_model_id": model_by_profile.get(active_profile_id, next(iter(model_by_profile.values()), "")),
                "vision_mode": "disabled",
                "vision_model_id": "",
            }
            self._write(state)
            return self._public_v2_state(state)

    def _public_v2_state(self, state: dict) -> dict:
        return {
            "schema_version": 2,
            "connections": [self._public_connection(row) for row in state["connections"]],
            "models": [self._public_model(row) for row in state["models"]],
            "assignments": dict(state["assignments"]),
        }

    @staticmethod
    def _public_model(record: dict) -> dict:
        result = dict(record)
        result.setdefault("reasoning_mode", "balanced")
        budget, source = resolve_annotation_budget(result)
        result["annotation_max_tokens"] = budget
        result["annotation_max_tokens_source"] = source
        return result

    def save_connection(self, payload: dict) -> dict:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            requested_id = str(payload.get("id") or "").strip()
            existing = next((row for row in state["connections"] if row["id"] == requested_id), None)
            connection_id = requested_id if existing else uuid.uuid4().hex
            record = self._validated_connection(payload, connection_id=connection_id)
            secret = str(payload.get("api_key") or "").strip()
            if payload.get("clear_secret"):
                self.credentials.delete(self._connection_target(connection_id))
            elif secret:
                self.credentials.write(self._connection_target(connection_id), secret)
            if existing:
                existing.clear(); existing.update(record)
            else:
                state["connections"].append(record)
            self._write(state)
            return self._public_connection(record)

    def resolve_connection_key(self, connection_id: str) -> str | None:
        return self.credentials.read(self._connection_target(str(connection_id)))

    def save_model(self, payload: dict) -> dict:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            requested_id = str(payload.get("id") or "").strip()
            existing = next((row for row in state["models"] if row["id"] == requested_id), None)
            model_id = requested_id if existing else uuid.uuid4().hex
            record = self._validated_model(
                payload,
                model_id=model_id,
                connection_ids={str(row["id"]) for row in state["connections"]},
            )
            if existing:
                existing.clear(); existing.update(record)
            else:
                state["models"].append(record)
            self._write(state)
            return self._public_model(record)

    def connection_record(self, connection_id: str) -> dict:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            record = next(
                (row for row in state["connections"] if str(row["id"]) == str(connection_id)),
                None,
            )
            if record is None:
                raise ModelProfileError("找不到指定供应商连接")
            return dict(record)

    def model_record(self, model_id: str) -> dict:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            record = next(
                (row for row in state["models"] if str(row["id"]) == str(model_id)),
                None,
            )
            if record is None:
                raise ModelProfileError("找不到指定模型")
            return dict(record)

    def provider_settings_for_model(self, model_id: str) -> tuple[str, dict]:
        """Build runtime settings from a workbench model without exposing metadata."""
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            model = next(
                (row for row in state["models"] if str(row["id"]) == str(model_id)),
                None,
            )
            if model is None:
                raise ModelProfileError("model not found")
            connection = next(
                (
                    row for row in state["connections"]
                    if str(row["id"]) == str(model.get("connection_id") or "")
                ),
                None,
            )
            if connection is None:
                raise ModelProfileError("model connection not found")
            secret = self.resolve_connection_key(str(connection["id"]))
            if not secret:
                raise ModelProfileError("model connection has no API Key")
            public_model = self._public_model(model)
            reasoning = resolve_reasoning_capability(
                str(model["model"]),
                service_preset=str(connection.get("service_preset") or "custom"),
            )
            return str(connection["protocol"]), {
                "model": str(model["model"]),
                "base_url": str(connection.get("base_url") or ""),
                "max_tokens": int(model.get("max_tokens") or 16000),
                "annotation_max_tokens": int(public_model["annotation_max_tokens"]),
                "context_window_tokens": public_model.get("context_window_tokens"),
                "context_window_source": public_model.get("context_window_source", "unknown"),
                "reasoning_mode": str(model.get("reasoning_mode") or "balanced"),
                "reasoning_wire_protocol": reasoning["wire_protocol"],
                "reasoning_budget_min": reasoning.get("budget_min"),
                "reasoning_budget_max": reasoning.get("budget_max"),
                "source_context_strategy": source_context_strategy_for_connection(connection),
                "vision": model.get("vision_status") in {"passed", "untested"},
                "api_key": secret,
            }

    def set_model_capability(self, model_id: str, mode: str, status: str) -> dict:
        if mode not in {"text", "vision"}:
            raise ModelProfileError("mode 必须是 text 或 vision")
        if status not in _CAPABILITY_STATUSES:
            raise ModelProfileError("模型能力状态无效")
        with self._lock:
            model = self.model_record(model_id)
            model[f"{mode}_status"] = status
            return self.save_model(model)

    def set_assignments(self, payload: dict) -> dict:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            models = {str(row["id"]): row for row in state["models"]}
            base_id = str(payload.get("base_model_id") or "")
            vision_mode = str(payload.get("vision_mode") or "disabled")
            vision_id = str(payload.get("vision_model_id") or "")
            if base_id not in models:
                raise ModelProfileError("请选择基础模型")
            if models[base_id].get("text_status") == "unsupported":
                raise ModelProfileError("基础模型不支持文字请求")
            if vision_mode not in _VISION_MODES:
                raise ModelProfileError("图片识别模式无效")
            if vision_mode == "base" and models[base_id].get("vision_status") != "passed":
                raise ModelProfileError("基础模型必须先通过图片测试")
            if vision_mode == "separate":
                if vision_id not in models:
                    raise ModelProfileError("请选择图片识别模型")
                if models[vision_id].get("vision_status") != "passed":
                    raise ModelProfileError("图片识别模型必须先通过图片测试")
            else:
                vision_id = ""
            state["assignments"] = {
                "base_model_id": base_id,
                "vision_mode": vision_mode,
                "vision_model_id": vision_id,
            }
            self._write(state)
            return dict(state["assignments"])

    def delete_model(
        self,
        model_id: str,
        *,
        delete_empty_connection: bool = False,
    ) -> dict:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            assignments = state["assignments"]
            if model_id in {assignments.get("base_model_id"), assignments.get("vision_model_id")}:
                raise ModelProfileError("模型仍被使用，请先更换任务模型")
            model = next(
                (row for row in state["models"] if str(row["id"]) == str(model_id)),
                None,
            )
            if model is None:
                raise ModelProfileError("找不到指定模型")
            connection_id = str(model["connection_id"])
            kept = [row for row in state["models"] if str(row["id"]) != str(model_id)]
            if len(kept) == len(state["models"]):
                raise ModelProfileError("找不到指定模型")
            state["models"] = kept

            # Remove the compatibility profile that originally produced this model.
            for profile in list(state["profiles"]):
                profile_id = str(profile.get("id") or "")
                if str(model_id) != "model-" + profile_id:
                    continue
                state["profiles"].remove(profile)
                self.credentials.delete(self._target(profile_id))
                if state.get("active_profile_id") == profile_id:
                    state["active_profile_id"] = str(
                        (state["profiles"][0] if state["profiles"] else {}).get("id") or ""
                    )
                break

            deleted_connection = False
            if delete_empty_connection and not any(
                str(row["connection_id"]) == connection_id for row in kept
            ):
                state["connections"] = [
                    row for row in state["connections"]
                    if str(row["id"]) != connection_id
                ]
                self.credentials.delete(self._connection_target(connection_id))
                deleted_connection = True
            self._write(state)
            return {
                "ok": True,
                "model_id": str(model_id),
                "deleted_connection": deleted_connection,
                "connection_id": connection_id if deleted_connection else "",
            }

    def delete_connection(self, connection_id: str) -> None:
        with self._lock:
            self.migrate_legacy_profiles()
            state = self._load()
            if any(str(row["connection_id"]) == str(connection_id) for row in state["models"]):
                raise ModelProfileError("连接下仍有模型，请先删除模型")
            kept = [row for row in state["connections"] if str(row["id"]) != str(connection_id)]
            if len(kept) == len(state["connections"]):
                raise ModelProfileError("找不到指定供应商连接")
            state["connections"] = kept
            self.credentials.delete(self._connection_target(str(connection_id)))
            self._write(state)

    def bootstrap_legacy(self, config_path) -> dict | None:
        """Import one non-secret profile from the legacy ``llm.json``.

        Existing profiles always win.  In particular, the legacy environment
        variable name is deliberately not copied because it is secret plumbing,
        not part of a reusable public profile.
        """
        with self._lock:
            state = self._load()
            if state["profiles"]:
                active_id = str(state.get("active_profile_id") or "")
                record = next(
                    (
                        row
                        for row in state["profiles"]
                        if str(row.get("id") or "") == active_id
                    ),
                    state["profiles"][0],
                )
                return self._public(record)

            legacy_path = Path(config_path)
            if not legacy_path.is_file():
                return None
            try:
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None

            provider = str(legacy.get("provider") or "").strip().lower()
            provider_config = legacy.get(provider)
            if provider not in _PROVIDERS or not isinstance(
                provider_config, dict
            ):
                return None
            model = str(provider_config.get("model") or "").strip()
            if not model:
                return None

            record = self._validated(
                {
                    "name": f"{provider} / {model}",
                    "provider": provider,
                    "base_url": provider_config.get("base_url", ""),
                    "model": model,
                    "max_tokens": provider_config.get(
                        "max_tokens",
                        legacy.get("max_tokens", 16000),
                    ),
                    "vision": True,
                },
                profile_id=f"legacy-{provider}",
            )
            state["profiles"].append(record)
            state["active_profile_id"] = record["id"]
            self._write(state)
            return self._public(record)

    def save_profile(self, payload: dict) -> dict:
        with self._lock:
            state = self._load()
            requested_id = str(payload.get("id") or "").strip()
            existing = next(
                (
                    row
                    for row in state["profiles"]
                    if str(row.get("id") or "") == requested_id
                ),
                None,
            )
            profile_id = (
                requested_id
                if existing is not None
                else uuid.uuid4().hex
            )
            record = self._validated(payload, profile_id=profile_id)

            secret = str(payload.get("api_key") or "").strip()
            if bool(payload.get("clear_secret")):
                self._session_secrets.pop(profile_id, None)
                self.credentials.delete(self._target(profile_id))
            elif secret:
                self.credentials.write(self._target(profile_id), secret)
                self._session_secrets.pop(profile_id, None)

            if existing is None:
                state["profiles"].append(record)
            else:
                existing.clear()
                existing.update(record)
            state["active_profile_id"] = profile_id

            # Keep the compatibility profile API and the v2 workbench in sync.
            if state["version"] >= 2:
                connection_id = "connection-" + profile_id
                model_id = "model-" + profile_id
                existing_connection = next(
                    (row for row in state["connections"] if row["id"] == connection_id),
                    None,
                )
                existing_model = next(
                    (row for row in state["models"] if row["id"] == model_id),
                    None,
                )
                connection = self._validated_connection(
                    {
                        "name": record["name"],
                        "service_preset": record["service_preset"],
                        "protocol": record["provider"],
                        "base_url": record["base_url"],
                    },
                    connection_id=connection_id,
                )
                unchanged_endpoint = bool(
                    existing_connection
                    and existing_connection.get("protocol") == connection["protocol"]
                    and existing_connection.get("base_url") == connection["base_url"]
                )
                unchanged_model = bool(
                    existing_model
                    and existing_model.get("model") == record["model"]
                    and unchanged_endpoint
                )
                model = self._validated_model(
                    {
                        "connection_id": connection_id,
                        "model": record["model"],
                        "max_tokens": record["max_tokens"],
                        "max_tokens_source": record["max_tokens_source"],
                        "recommended_max_tokens": record["recommended_max_tokens"],
                        "recommended_source": record["recommended_source"],
                        "recommended_label": record["recommended_label"],
                        "text_status": (
                            existing_model.get("text_status", "untested")
                            if unchanged_model else "untested"
                        ),
                        "vision_status": (
                            "unsupported" if not record["vision"]
                            else existing_model.get("vision_status", "untested")
                            if unchanged_model else "untested"
                        ),
                    },
                    model_id=model_id,
                    connection_ids={connection_id},
                )
                if existing_connection is None:
                    state["connections"].append(connection)
                else:
                    existing_connection.clear(); existing_connection.update(connection)
                if existing_model is None:
                    state["models"].append(model)
                else:
                    existing_model.clear(); existing_model.update(model)
                connection_secret = secret or self.resolve_api_key(profile_id)
                if bool(payload.get("clear_secret")):
                    self.credentials.delete(self._connection_target(connection_id))
                elif connection_secret:
                    self.credentials.write(
                        self._connection_target(connection_id), connection_secret
                    )
                if not state["assignments"].get("base_model_id"):
                    state["assignments"]["base_model_id"] = model_id
            self._write(state)
            return self._public(record)

    def public_state(self, *, include_links: bool = False) -> dict:
        with self._lock:
            state = self._load()
            result = {
                "active_profile_id": state["active_profile_id"],
                "profiles": [
                    self._public(record)
                    for record in state["profiles"]
                ],
                "credential_available": bool(
                    getattr(self.credentials, "available", False)
                ),
                "presets": {
                    key: {
                        field: field_value
                        for field, field_value in value.items()
                        if include_links or field not in {"official_url", "api_key_url"}
                    }
                    for key, value in MODEL_PRESETS.items()
                },
            }
            if state["version"] >= 2:
                result.update(self._public_v2_state(state))
            return result

    def set_active(self, profile_id: str) -> dict:
        with self._lock:
            state = self._load()
            record = next(
                (
                    row
                    for row in state["profiles"]
                    if str(row.get("id") or "") == str(profile_id)
                ),
                None,
            )
            if record is None:
                raise ModelProfileError("找不到指定模型配置")
            state["active_profile_id"] = str(profile_id)
            self._write(state)
            return self._public(record)

    def active_profile(self) -> dict | None:
        state = self.public_state()
        active = state["active_profile_id"]
        return next(
            (row for row in state["profiles"] if row["id"] == active),
            None,
        )

    def delete_profile(
        self,
        profile_id: str,
        *,
        delete_credential: bool = True,
    ) -> None:
        with self._lock:
            state = self._load()
            kept = [
                row
                for row in state["profiles"]
                if str(row.get("id") or "") != str(profile_id)
            ]
            if len(kept) == len(state["profiles"]):
                raise ModelProfileError("找不到指定模型配置")
            self._session_secrets.pop(str(profile_id), None)
            if delete_credential:
                self.credentials.delete(self._target(str(profile_id)))
            state["profiles"] = kept
            if state["active_profile_id"] == str(profile_id):
                state["active_profile_id"] = (
                    str(kept[0].get("id") or "") if kept else ""
                )
            self._write(state)

    def resolve_api_key(self, profile_id: str) -> str | None:
        with self._lock:
            profile_id = str(profile_id)
            session = self._session_secrets.get(profile_id)
            if session:
                return session
            return self.credentials.read(self._target(profile_id))

    def profile_record(self, profile_id: str) -> dict:
        with self._lock:
            state = self._load()
            record = next(
                (
                    row
                    for row in state["profiles"]
                    if str(row.get("id") or "") == str(profile_id)
                ),
                None,
            )
            if record is None:
                raise ModelProfileError("找不到指定模型配置")
            return dict(record)

    def provider_settings(
        self,
        profile_id: str | None = None,
    ) -> tuple[str, dict]:
        with self._lock:
            state = self._load()
            selected_id = str(
                profile_id or state.get("active_profile_id") or ""
            )
            record = next(
                (
                    row
                    for row in state["profiles"]
                    if str(row.get("id") or "") == selected_id
                ),
                None,
            )
            if record is None:
                raise ModelProfileError("尚未选择模型配置")
            secret = self.resolve_api_key(selected_id)
            if not secret:
                raise ModelProfileError("所选模型配置尚未设置 API Key")
            return str(record["provider"]), {
                "model": str(record["model"]),
                "base_url": str(record.get("base_url") or ""),
                "max_tokens": int(record.get("max_tokens") or 16000),
                "vision": bool(record.get("vision", True)),
                "api_key": secret,
            }
