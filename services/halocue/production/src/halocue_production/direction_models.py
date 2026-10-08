from __future__ import annotations

import time
import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import ProductionError
from .legacy_modules import load_module
from .model_settings import DirectionModelSettings
from services.halocue.codex_agent import CodexError, require_subscription_provider


class DirectionModelGateway:
    """Create a 1.0-owned model connection using the proven transport adapter."""

    def __init__(self, settings: DirectionModelSettings, legacy_root: Path) -> None:
        self.settings = settings
        self.legacy_root = legacy_root

    def provider(self, candidate: dict | None = None):
        provider_name, provider_settings = (
            (candidate["provider"], candidate) if candidate is not None
            else self.settings.provider_settings()
        )
        provider_settings = dict(provider_settings)
        try:
            require_subscription_provider(provider_name)
        except CodexError as error:
            raise ProductionError(error.code, error.message, status=409) from error
        if provider_name == "codex":
            from .codex_provider import CodexDirectionProvider

            return CodexDirectionProvider(provider_settings)
        if provider_name == "anthropic":
            effort = provider_settings.get("reasoning_effort", "auto")
            if effort == "none":
                provider_settings["thinking"] = False
            elif effort != "auto":
                provider_settings["effort"] = effort
        # The legacy OpenAI transport requires a nonempty Authorization value.
        # Only a verified loopback OpenAI-compatible endpoint may be keyless;
        # use an inert transport placeholder, never persist it as a real secret.
        local = urlparse(str(provider_settings.get("base_url") or "")).hostname in {"localhost", "127.0.0.1", "::1"}
        if provider_name == "openai" and local and not provider_settings.get("api_key") and not provider_settings.get("api_key_env"):
            provider_settings["api_key"] = "halocue-local-keyless"
        try:
            module = load_module("llm", self.legacy_root)
            provider = module.make_provider_from_settings(provider_name, provider_settings)
            binder = getattr(provider, "bind_request_guard", None)
            if callable(binder):
                def guard():
                    try:
                        require_subscription_provider(provider_name)
                    except CodexError as error:
                        raise ProductionError(error.code, error.message, status=409) from error
                binder(guard)
            return provider
        except ProductionError:
            raise
        except Exception as exc:
            raise ProductionError(
                "model_provider_unavailable",
                str(exc),
                status=503,
                details={"type": type(exc).__name__},
            ) from exc

    def test_connection(self, candidate: dict | None = None) -> dict[str, Any]:
        provider = self.provider(candidate) if candidate is not None else self.provider()
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        expected = {"ok": True}
        test_kind = "connection"
        if getattr(provider, "name", "") == "codex":
            # Compile the real nested production schema at the model service,
            # rather than proving only a trivial ok:boolean response works.
            from annotation_protocol import build_chunk_schema, ANNOTATION_FIELDS
            from services.halocue.codex_schema import CodexOutputContract

            schema = build_chunk_schema(["connection-target"])
            line = {name: False if name == "shake" else 0 if name == "move" else "" for name in ANNOTATION_FIELDS}
            line.update(source_id="connection-target", text_fingerprint="connection-fingerprint", direction=None)
            wire_state = {key: None for key in schema["properties"]["state_delta"]["properties"]}
            expected = {"lines": [line], "state_delta": wire_state, "memory_events": [], "beats": []}
            # Confirm the exact test sample itself obeys both contracts.
            expected = json.loads(CodexOutputContract(schema).restore_text(json.dumps(expected)))
            test_kind = "direction_schema"
        started = time.monotonic()
        try:
            budget = min(int((candidate or {}).get("max_tokens") or 4096),
                         max(4096, int((candidate or {}).get("thinking_budget") or 0) + 512))
            scoped = provider.temporary_output_budget(budget) if hasattr(provider, "temporary_output_budget") else nullcontext()
            with scoped:
                result = provider.complete_json(
                    "You are a connection test. Return JSON only.",
                    "",
                    'Return this connection-test JSON with no story edits. Follow outputSchema; optional omitted fields must be null, and dictionaries use key/value arrays: ' + json.dumps(expected, ensure_ascii=False),
                    schema,
                )
        except Exception as exc:
            raise ProductionError(
                str(getattr(exc, "code", "model_connection_failed")),
                str(exc),
                status=502,
                details={**getattr(exc, "details", {}), "model": str(getattr(provider, "model", "") or ""), "test_kind": test_kind},
            ) from exc
        if not isinstance(result, dict) or result != expected:
            raise ProductionError("model_connection_failed", "模型未返回有效的连接测试结果。", status=502)
        return {
            "ok": True,
            "connection": {
                "provider": str(getattr(provider, "name", "")),
                "model": str(getattr(provider, "model", "")),
                "latency_ms": round((time.monotonic() - started) * 1000),
                "valid": True,
                "test_kind": test_kind,
                "usage": dict(getattr(provider, "stats", {}) or {}),
            },
        }
