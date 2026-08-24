from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any

from .errors import ProductionError
from .model_settings import DirectionModelSettings


class DirectionModelGateway:
    """Create a 1.0-owned model connection using the proven transport adapter."""

    def __init__(self, settings: DirectionModelSettings, legacy_root: Path) -> None:
        self.settings = settings
        self.legacy_root = legacy_root

    def provider(self):
        provider_name, provider_settings = self.settings.provider_settings()
        legacy = str(self.legacy_root)
        if legacy not in sys.path:
            sys.path.insert(0, legacy)
        try:
            module = importlib.import_module("llm")
            return module.make_provider_from_settings(provider_name, provider_settings)
        except ProductionError:
            raise
        except Exception as exc:
            raise ProductionError(
                "model_provider_unavailable",
                str(exc),
                status=503,
                details={"type": type(exc).__name__},
            ) from exc

    def test_connection(self) -> dict[str, Any]:
        provider = self.provider()
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        started = time.monotonic()
        try:
            result = provider.complete_json(
                "You are a connection test. Return JSON only.",
                "",
                'Return exactly {"ok":true}.',
                schema,
            )
        except Exception as exc:
            raise ProductionError(
                str(getattr(exc, "code", "model_connection_failed")),
                str(exc),
                status=502,
                details={"model": str(getattr(exc, "model", "") or "")},
            ) from exc
        return {
            "ok": True,
            "connection": {
                "provider": str(getattr(provider, "name", "")),
                "model": str(getattr(provider, "model", "")),
                "latency_ms": round((time.monotonic() - started) * 1000),
                "valid": result.get("ok") is True,
                "usage": dict(getattr(provider, "stats", {}) or {}),
            },
        }
