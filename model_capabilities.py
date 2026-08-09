# -*- coding: utf-8 -*-
"""Resolve model output limits from sanitized remote metadata or a verified catalog."""

from __future__ import annotations

import json
import re
import threading
from urllib.request import Request, urlopen
from typing import Any, Dict, Mapping, Optional


OUTPUT_LIMIT_PATHS = (
    ("max_completion_tokens",),
    ("max_output_tokens",),
    ("output_token_limit",),
    ("top_provider", "max_completion_tokens"),
)

MODELS_DEV_URL = "https://models.dev/api.json"
_REGISTRY_LOCK = threading.Lock()
_REGISTRY_CACHE = None
_REGISTRY_PROVIDER_KEYS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "deepseek": "deepseek",
    "glm": "zhipuai",
    "qwen": "alibaba",
    "moonshot": "moonshotai",
    "openrouter": "openrouter",
}


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


def normalize_registry_model_record(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize the small, MIT-licensed models.dev capability contract."""
    if not isinstance(item, Mapping):
        return {"id": "", "context_length": None, "max_output_tokens": None, "reasoning": None}
    if "context_length" in item or "max_output_tokens" in item:
        reasoning = item.get("reasoning") if isinstance(item.get("reasoning"), Mapping) else None
        return {
            "id": str(item.get("id") or "").strip(),
            "context_length": _positive_int(item.get("context_length")),
            "max_output_tokens": _positive_int(item.get("max_output_tokens")),
            "reasoning": dict(reasoning) if reasoning else None,
        }
    limits = item.get("limit") if isinstance(item.get("limit"), Mapping) else {}
    reasoning_options = item.get("reasoning_options")
    if isinstance(reasoning_options, Mapping):
        reasoning_options = [reasoning_options]
    if not isinstance(reasoning_options, list):
        reasoning_options = []
    efforts = []
    toggle = False
    budget_min = budget_max = None
    for option in reasoning_options:
        if not isinstance(option, Mapping):
            continue
        kind = str(option.get("type") or "").strip().lower()
        if kind == "toggle":
            toggle = True
        elif kind == "effort":
            for value in option.get("values") or []:
                value = str(value or "").strip().lower()
                if value in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "auto"} and value not in efforts:
                    efforts.append(value)
        elif kind in {"budget", "budget_tokens"}:
            budget_min = _positive_or_zero_int(option.get("min"))
            budget_max = _positive_int(option.get("max"))
    reasoning = None
    if bool(item.get("reasoning")):
        reasoning = {
            "supported": True,
            "toggle": toggle,
            "efforts": efforts,
            "budget_min": budget_min,
            "budget_max": budget_max,
        }
    return {
        "id": str(item.get("id") or "").strip(),
        "context_length": _positive_int(limits.get("context")),
        "max_output_tokens": _positive_int(limits.get("output")),
        "reasoning": reasoning,
    }


def _positive_or_zero_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _load_models_dev() -> Mapping[str, Any]:
    global _REGISTRY_CACHE
    with _REGISTRY_LOCK:
        if _REGISTRY_CACHE is not None:
            return _REGISTRY_CACHE
        try:
            request = Request(MODELS_DEV_URL, headers={
                "Accept": "application/json",
                "User-Agent": "AA-AutoWriter/1.0",
            })
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            _REGISTRY_CACHE = payload if isinstance(payload, Mapping) else {}
        except Exception:
            _REGISTRY_CACHE = {}
        return _REGISTRY_CACHE


def registry_model_record(model_id: str, *, service_preset: str = "custom") -> Optional[Dict[str, Any]]:
    """Look up one exact model in models.dev; failures remain offline-safe."""
    model_id = str(model_id or "").strip()
    preset = str(service_preset or "custom").strip().lower()
    provider_key = _REGISTRY_PROVIDER_KEYS.get(preset)
    if not model_id:
        return None
    data = _load_models_dev()
    keys = [provider_key] if provider_key else []
    if preset == "custom":
        family = _model_family(model_id)
        inferred = _REGISTRY_PROVIDER_KEYS.get(family)
        if inferred:
            keys.append(inferred)
    item = None
    for key in dict.fromkeys(key for key in keys if key):
        provider = data.get(key)
        models = provider.get("models") if isinstance(provider, Mapping) else None
        if not isinstance(models, Mapping):
            continue
        item = models.get(model_id)
        if not isinstance(item, Mapping) and "/" in model_id:
            item = models.get(model_id.rsplit("/", 1)[-1])
        if isinstance(item, Mapping):
            break
    if not isinstance(item, Mapping):
        return None
    record = dict(item)
    record["id"] = model_id
    return normalize_registry_model_record(record)


def _model_family(model_id: str) -> str:
    value = str(model_id or "").strip().lower()
    value = value.rsplit("/", 1)[-1]
    if value.startswith("deepseek"):
        return "deepseek"
    if value.startswith(("gpt-", "o1", "o3", "o4", "o5")):
        return "openai"
    if value.startswith("gemini"):
        return "gemini"
    if value.startswith("claude"):
        return "anthropic"
    if value.startswith(("qwen", "qwq", "qvq")):
        return "qwen"
    if value.startswith("glm") or value.startswith("chatglm"):
        return "glm"
    if value.startswith(("kimi", "moonshot")):
        return "moonshot"
    return ""


def _wire_protocol(model_id: str, service_preset: str) -> str:
    family = _model_family(model_id) or str(service_preset or "").strip().lower()
    return {
        "deepseek": "deepseek_thinking",
        "openai": "openai_reasoning_effort",
        "gemini": "gemini_reasoning_effort",
        "anthropic": "anthropic_thinking",
        "qwen": "qwen_thinking",
        "glm": "glm_thinking",
        "moonshot": "kimi_thinking",
    }.get(family, "none")


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
        "patterns": (r"(?:[\w.-]+/)?deepseek-v4-flash(?:-\d+)?",),
        "toggle": True,
        "efforts": ("low", "medium", "high"),
        "default_mode": "medium",
        "wire_protocol": "deepseek_thinking",
        "source": "catalog",
    },
    {
        "service_presets": ("deepseek", "custom"),
        "patterns": (r"(?:[\w.-]+/)?deepseek-v4-(?:pro|reasoner|chat)(?:-\d+)?",),
        "toggle": False,
        "efforts": (),
        "default_mode": "provider_default",
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
    registry_record: Optional[Mapping[str, Any]] = None,
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
            "context_window_tokens": context_length,
            "context_window_source": "api" if context_length else "unknown",
        }
    registry = (
        normalize_registry_model_record(registry_record)
        if isinstance(registry_record, Mapping)
        else registry_model_record(model_id, service_preset=service_preset)
    )
    catalog = _catalog_match(model_id, service_preset)
    if catalog:
        limit = int(catalog["max_output_tokens"])
        registry_context = registry.get("context_length") if isinstance(registry, Mapping) else None
        return {
            "model_id": model_id,
            "max_output_tokens": limit,
            "source": "catalog",
            "source_label": "官方目录 · {:,}".format(limit),
            "source_url": catalog["source_url"],
            "verified_at": catalog["verified_at"],
            "context_length": context_length or registry_context,
            "context_window_tokens": context_length or registry_context,
            "context_window_source": "api" if context_length else "models_dev" if registry_context else "unknown",
        }
    if registry and registry.get("id") in {None, "", model_id}:
        registry_context = registry.get("context_length")
        registry_limit = registry.get("max_output_tokens")
        if registry_limit is not None:
            return {
                "model_id": model_id,
                "max_output_tokens": registry_limit,
                "source": "models_dev",
                "source_label": "models.dev · {:,}".format(registry_limit),
                "source_url": MODELS_DEV_URL,
                "verified_at": "",
                "context_length": context_length or registry_context,
                "context_window_tokens": context_length or registry_context,
                "context_window_source": "api" if context_length else "models_dev" if registry_context else "unknown",
            }
    return {
        "model_id": model_id,
        "max_output_tokens": None,
        "source": "unknown",
        "source_label": "上限未识别",
        "source_url": "",
        "verified_at": "",
        "context_length": context_length,
        "context_window_tokens": context_length,
        "context_window_source": "api" if context_length else "unknown",
    }


def resolve_reasoning_capability(
    model_id: str,
    *,
    service_preset: str = "custom",
    remote_record: Optional[Mapping[str, Any]] = None,
    registry_record: Optional[Mapping[str, Any]] = None,
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
            "wire_protocol": str(
                remote_reasoning.get("wire_protocol")
                or _wire_protocol(model_id, service_preset)
            ),
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
    registry = (
        normalize_registry_model_record(registry_record)
        if isinstance(registry_record, Mapping)
        else registry_model_record(model_id, service_preset=service_preset)
    )
    registry_reasoning = registry.get("reasoning") if isinstance(registry, Mapping) else None
    if isinstance(registry_reasoning, Mapping) and registry.get("id") in {None, "", model_id}:
        efforts = list(registry_reasoning.get("efforts") or [])
        toggle = bool(registry_reasoning.get("toggle"))
        selectable = [value for value in efforts if value not in {"none", "auto"}]
        default_mode = "medium" if "medium" in selectable else selectable[0] if selectable else "provider_default"
        return {
            "toggle": toggle or "none" in efforts,
            "efforts": selectable,
            "default_mode": default_mode,
            "wire_protocol": _wire_protocol(model_id, service_preset),
            "budget_min": registry_reasoning.get("budget_min"),
            "budget_max": registry_reasoning.get("budget_max"),
            "source": "models_dev",
        }
    return {
        "toggle": False,
        "efforts": [],
        "default_mode": "provider_default",
        "wire_protocol": "none",
        "source": "unknown",
    }
