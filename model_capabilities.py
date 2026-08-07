# -*- coding: utf-8 -*-
"""Resolve model output limits from sanitized remote metadata or a verified catalog."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional


OUTPUT_LIMIT_PATHS = (
    ("max_completion_tokens",),
    ("max_output_tokens",),
    ("output_token_limit",),
    ("top_provider", "max_completion_tokens"),
)


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_remote_model_record(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep only the safe model capability fields needed by the workbench."""
    if not isinstance(item, Mapping):
        return {
            "id": "",
            "context_length": None,
            "max_output_tokens": None,
        }
    model_id = str(item.get("id") or "").strip()
    record: Dict[str, Any] = {
        "id": model_id,
        "context_length": _positive_int(item.get("context_length")),
        "max_output_tokens": None,
    }
    for path in OUTPUT_LIMIT_PATHS:
        value: Any = item
        for key in path:
            value = value.get(key) if isinstance(value, Mapping) else None
        parsed = _positive_int(value)
        if parsed is not None:
            record["max_output_tokens"] = parsed
            record["max_output_field"] = ".".join(path)
            break
    return record


VERIFIED_MODEL_CAPABILITIES = (
    {
        "service_presets": ("openai", "custom"),
        "patterns": (r"gpt-4o", r"gpt-4o-\d{4}-\d{2}-\d{2}"),
        "max_output_tokens": 16384,
        "source_url": "https://developers.openai.com/api/docs/models/gpt-4o",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("anthropic", "custom"),
        "patterns": (r"claude-sonnet-4-5",),
        "max_output_tokens": 64000,
        "source_url": "https://platform.claude.com/docs/en/about-claude/models/overview",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("gemini", "custom"),
        "patterns": (r"gemini-2\.5-flash",),
        "max_output_tokens": 65536,
        "source_url": "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("deepseek", "custom"),
        "patterns": (r"deepseek-v4-flash",),
        "max_output_tokens": 384000,
        "source_url": "https://api-docs.deepseek.com/quick_start/pricing",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("glm", "custom"),
        "patterns": (r"glm-4\.6",),
        "max_output_tokens": 128000,
        "source_url": "https://docs.bigmodel.cn/cn/guide/models/text/glm-4.6",
        "verified_at": "2026-08-07",
    },
    {
        "service_presets": ("openrouter", "custom"),
        "patterns": (r"openai/gpt-4o-mini",),
        "max_output_tokens": 16384,
        "source_url": "https://openrouter.ai/openai/gpt-4o-mini",
        "verified_at": "2026-08-07",
    },
)


VERIFIED_REASONING_CAPABILITIES = (
    {
        "service_presets": ("deepseek", "custom"),
        "patterns": (r"deepseek-v4-flash(?:-\\d+)?",),
        "toggle": True,
        "efforts": ("low", "medium", "high"),
        "default_mode": "medium",
        "wire_protocol": "deepseek_thinking",
        "source": "catalog",
    },
)


def _catalog_match(model_id: str, service_preset: str) -> Optional[Mapping[str, Any]]:
    for entry in VERIFIED_MODEL_CAPABILITIES:
        if service_preset not in entry["service_presets"] and service_preset != "custom":
            continue
        if any(re.fullmatch(pattern, model_id) for pattern in entry["patterns"]):
            return entry
    return None


def resolve_output_capability(
    model_id: str,
    *,
    service_preset: str = "custom",
    remote_record: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a stable capability result without treating context as output."""
    model_id = str(model_id or "").strip()
    remote = normalize_remote_model_record(remote_record or {})
    context_length = remote.get("context_length")
    remote_limit = remote.get("max_output_tokens")
    if remote_limit is not None and (not remote.get("id") or remote.get("id") == model_id):
        return {
            "model_id": model_id,
            "max_output_tokens": remote_limit,
            "source": "api",
            "source_label": "接口返回 · {:,}".format(remote_limit),
            "source_url": "",
            "verified_at": "",
            "context_length": context_length,
        }
    catalog = _catalog_match(model_id, service_preset)
    if catalog:
        limit = int(catalog["max_output_tokens"])
        return {
            "model_id": model_id,
            "max_output_tokens": limit,
            "source": "catalog",
            "source_label": "官方目录 · {:,}".format(limit),
            "source_url": catalog["source_url"],
            "verified_at": catalog["verified_at"],
            "context_length": context_length,
        }
    return {
        "model_id": model_id,
        "max_output_tokens": None,
        "source": "unknown",
        "source_label": "上限未识别",
        "source_url": "",
        "verified_at": "",
        "context_length": context_length,
    }


def resolve_reasoning_capability(
    model_id: str,
    *,
    service_preset: str = "custom",
    remote_record: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve only verified reasoning controls; unknown models stay provider-default."""
    model_id = str(model_id or "").strip()
    remote = remote_record if isinstance(remote_record, Mapping) else {}
    remote_reasoning = remote.get("reasoning") if isinstance(remote, Mapping) else None
    if isinstance(remote_reasoning, Mapping) and remote.get("id") in {None, "", model_id}:
        efforts = [
            str(value).strip().lower()
            for value in (remote_reasoning.get("efforts") or [])
            if str(value).strip().lower() in {"low", "medium", "high", "max"}
        ]
        toggle = bool(remote_reasoning.get("toggle"))
        default_mode = str(remote_reasoning.get("default_mode") or "provider_default")
        if default_mode not in set(efforts) | {"speed", "provider_default"}:
            default_mode = efforts[0] if efforts else ("speed" if toggle else "provider_default")
        return {
            "toggle": toggle,
            "efforts": list(dict.fromkeys(efforts)),
            "default_mode": default_mode,
            "wire_protocol": str(remote_reasoning.get("wire_protocol") or "none"),
            "source": "api",
        }
    for entry in VERIFIED_REASONING_CAPABILITIES:
        if service_preset not in entry["service_presets"] and service_preset != "custom":
            continue
        if any(re.fullmatch(pattern, model_id) for pattern in entry["patterns"]):
            return {
                "toggle": bool(entry["toggle"]),
                "efforts": list(entry["efforts"]),
                "default_mode": str(entry["default_mode"]),
                "wire_protocol": str(entry["wire_protocol"]),
                "source": str(entry["source"]),
            }
    return {
        "toggle": False,
        "efforts": [],
        "default_mode": "provider_default",
        "wire_protocol": "none",
        "source": "unknown",
    }
