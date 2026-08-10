from __future__ import annotations

import re
from typing import Protocol


_SECRET_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_backend_override: CredentialBackend | None = None


class CredentialBackend(Protocol):
    def put(self, name: str, value: str) -> None: ...

    def get(self, name: str) -> str | None: ...

    def has(self, name: str) -> bool: ...

    def masked(self, name: str) -> str | None: ...

    def delete(self, name: str) -> None: ...


def _validate_name(name: str) -> str:
    value = str(name or "")
    if not _SECRET_NAME.fullmatch(value):
        raise ValueError("Invalid credential name")
    return value


def _backend() -> CredentialBackend:
    if _backend_override is not None:
        return _backend_override
    try:
        from java import jclass
    except ImportError as error:
        raise RuntimeError("Android credential backend is unavailable") from error
    registry = jclass("com.halocue.android.AndroidRuntimeRegistry")
    return registry.credentials()


def set_backend_for_tests(backend: CredentialBackend | None) -> None:
    global _backend_override
    _backend_override = backend


def set_secret(name: str, value: str) -> None:
    _backend().put(_validate_name(name), str(value))


def get_secret(name: str) -> str | None:
    value = _backend().get(_validate_name(name))
    return None if value is None else str(value)


def secret_status(name: str) -> dict[str, object]:
    safe_name = _validate_name(name)
    backend = _backend()
    masked = backend.masked(safe_name)
    configured = masked is not None
    return {"configured": configured, "masked": None if masked is None else str(masked)}


def delete_secret(name: str) -> None:
    _backend().delete(_validate_name(name))
