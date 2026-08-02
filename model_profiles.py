# -*- coding: utf-8 -*-
"""Model profiles with session-only or Windows Credential Manager secrets."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path


_TARGET_PREFIX = "AA-AutoWriter/"
_PROVIDERS = {"openai", "anthropic"}


class ModelProfileError(ValueError):
    pass


class CredentialStoreError(RuntimeError):
    pass


class WindowsCredentialStore:
    """Store generic credentials encrypted by the current Windows account."""

    def __init__(self, *, win32cred_module=None):
        if win32cred_module is None:
            try:
                import win32cred as win32cred_module
            except ImportError:
                win32cred_module = None
        self._api = win32cred_module
        self.available = self._api is not None

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

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"version": 1, "active_profile_id": "", "profiles": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelProfileError(f"无法读取模型配置：{exc}") from exc
        profiles = data.get("profiles")
        if not isinstance(profiles, list):
            raise ModelProfileError("模型配置中的 profiles 必须是数组")
        return {
            "version": 1,
            "active_profile_id": str(data.get("active_profile_id") or ""),
            "profiles": profiles,
        }

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
        return {
            "id": profile_id,
            "name": name,
            "provider": provider,
            "base_url": str(payload.get("base_url") or "").strip(),
            "model": model,
            "max_tokens": max_tokens,
            "vision": bool(payload.get("vision", True)),
        }

    def _secret_status(self, profile_id: str) -> str:
        if self._session_secrets.get(profile_id):
            return "session"
        if self.credentials.read(self._target(profile_id)):
            return "saved"
        return "missing"

    def _public(self, record: dict) -> dict:
        result = {
            key: record.get(key)
            for key in (
                "id",
                "name",
                "provider",
                "base_url",
                "model",
                "max_tokens",
                "vision",
            )
        }
        result["secret_status"] = self._secret_status(str(record["id"]))
        result["credential_available"] = bool(
            getattr(self.credentials, "available", False)
        )
        return result

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
                if bool(payload.get("save_key")):
                    self.credentials.write(self._target(profile_id), secret)
                    self._session_secrets.pop(profile_id, None)
                else:
                    self._session_secrets[profile_id] = secret
                    self.credentials.delete(self._target(profile_id))

            if existing is None:
                state["profiles"].append(record)
            else:
                existing.clear()
                existing.update(record)
            state["active_profile_id"] = profile_id
            self._write(state)
            return self._public(record)

    def public_state(self) -> dict:
        with self._lock:
            state = self._load()
            return {
                "active_profile_id": state["active_profile_id"],
                "profiles": [
                    self._public(record)
                    for record in state["profiles"]
                ],
                "credential_available": bool(
                    getattr(self.credentials, "available", False)
                ),
            }

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
