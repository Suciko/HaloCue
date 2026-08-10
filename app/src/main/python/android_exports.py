"""Publish private Android build output without exposing paths or content URIs."""

from __future__ import annotations

from typing import Protocol


class PlatformServicesBackend(Protocol):
    def publishAap(self, source: str, project: str): ...


_backend_override: PlatformServicesBackend | None = None


def _backend() -> PlatformServicesBackend:
    if _backend_override is not None:
        return _backend_override
    try:
        from java import jclass
    except ImportError as error:
        raise RuntimeError("Android export backend is unavailable") from error
    registry = jclass("com.halocue.android.AndroidRuntimeRegistry")
    return registry.platformServices()


def set_backend_for_tests(backend: PlatformServicesBackend | None) -> None:
    global _backend_override
    _backend_override = backend


def _read_field(value, name: str):
    if isinstance(value, dict):
        return value.get(name)
    getter = getattr(value, "get" + name[:1].upper() + name[1:])
    return getter()


def publish_aap(source: str, project: str) -> dict[str, object]:
    published = _backend().publishAap(str(source), str(project))
    return {
        "shareId": str(_read_field(published, "shareId")),
        "displayName": str(_read_field(published, "displayName")),
        "relativePath": str(_read_field(published, "relativePath")),
        "size": int(_read_field(published, "size")),
    }
