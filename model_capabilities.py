# -*- coding: utf-8 -*-
"""Resolve model output limits from sanitized remote metadata or a verified catalog."""

from __future__ import annotations

import json
import math
import re
import threading
import time
from urllib.request import Request, urlopen
from urllib.parse import urlparse
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
_REGISTRY_FETCHED_AT = 0.0
_REGISTRY_LAST_FETCH_OK = False
_REGISTRY_REFRESH_SECONDS = 6 * 60 * 60
_REGISTRY_FAILURE_RETRY_SECONDS = 5 * 60
_REGISTRY_PROVIDER_KEYS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "deepseek": "deepseek",
    "glm": "zhipuai",
    "qwen": "alibaba",
    "moonshot": "moonshotai",
    "openrouter": "openrouter",
    "nvidia": "nvidia",
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
        result = {
            "id": str(item.get("id") or "").strip(),
            "context_length": _positive_int(item.get("context_length")),
            "max_output_tokens": _positive_int(item.get("max_output_tokens")),
            "reasoning": dict(reasoning) if reasoning else None,
        }
        if _positive_int(item.get("max_input_tokens")):
            result["max_input_tokens"] = _positive_int(item.get("max_input_tokens"))
        return result
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
    result = {
        "id": str(item.get("id") or "").strip(),
        "context_length": _positive_int(limits.get("context")),
        "max_output_tokens": _positive_int(limits.get("output")),
        "reasoning": reasoning,
    }
    if _positive_int(limits.get("input")):
        result["max_input_tokens"] = _positive_int(limits.get("input"))
    return result


def _positive_or_zero_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _load_models_dev() -> Mapping[str, Any]:
    global _REGISTRY_CACHE, _REGISTRY_FETCHED_AT, _REGISTRY_LAST_FETCH_OK
    with _REGISTRY_LOCK:
        now = time.monotonic()
        ttl = _REGISTRY_REFRESH_SECONDS if _REGISTRY_LAST_FETCH_OK else _REGISTRY_FAILURE_RETRY_SECONDS
        if _REGISTRY_CACHE is not None and now - _REGISTRY_FETCHED_AT < ttl:
            return _REGISTRY_CACHE
        try:
            request = Request(MODELS_DEV_URL, headers={
                "Accept": "application/json",
                "User-Agent": "AA-AutoWriter/1.0",
            })
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            _REGISTRY_CACHE = payload if isinstance(payload, Mapping) else {}
            _REGISTRY_LAST_FETCH_OK = bool(_REGISTRY_CACHE)
        except Exception:
            _REGISTRY_CACHE = _REGISTRY_CACHE or {}
            _REGISTRY_LAST_FETCH_OK = False
        _REGISTRY_FETCHED_AT = now
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
        # Custom provider IDs can be unknown to HaloCue. Only use an exact,
        # unambiguous catalog ID; a fuzzy match could attach the wrong limit.
        matches = [provider["models"][model_id] for provider in data.values()
                   if isinstance(provider, Mapping)
                   and isinstance(provider.get("models"), Mapping)
                   and isinstance(provider["models"].get(model_id), Mapping)]
        if len(matches) == 1:
            item = matches[0]
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
    current = _PRESETS.get(model_id)
    if current:
        return {**current, "verified_at": CATALOG_VERSION}
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
        registry_context = catalog.get("context_window") or (registry.get("context_length") if isinstance(registry, Mapping) else None)
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


# 1.0 integrated settings and transports share these verified, offline defaults.
class ModelCapabilityError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.details = details if isinstance(details, dict) else {}

LIMIT_FIELDS = ("context_window", "max_input_tokens", "max_output_tokens")
ADVANCED_FIELDS = (*LIMIT_FIELDS, "token_limit_parameter", "temperature", "top_p", "reasoning_effort", "thinking_budget")
CATALOG_VERSION = "2026-09-26"
_OPENAI_SOURCE = "https://developers.openai.com/api/docs/models/compare"
_CLAUDE_SOURCE = "https://platform.claude.com/docs/en/models/overview"
_DEEPSEEK_SOURCE = "https://api-docs.deepseek.com/api/list-models/"
_PRESETS = {
    **{name: {"context_window": 1_050_000, "max_output_tokens": 128_000,
              "token_limit_parameter": "max_completion_tokens", "reasoning": True,
              "sampling": False, "source_url": _OPENAI_SOURCE}
       for name in ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna")},
    "gpt-4o": {"context_window": 128_000, "max_output_tokens": 16_384,
               "token_limit_parameter": "max_tokens", "reasoning": False, "sampling": True,
               "source_url": "https://developers.openai.com/api/docs/models/gpt-4o"},
    **{name: {"context_window": 1_000_000, "max_output_tokens": 128_000,
              "token_limit_parameter": "max_tokens", "reasoning": True,
              "adaptive_thinking": True, "sampling": False, "source_url": _CLAUDE_SOURCE}
       for name in ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5")},
    **{name: {"context_window": 200_000, "max_output_tokens": 64_000,
              "token_limit_parameter": "max_tokens", "reasoning": True,
              "sampling": True, "source_url": _CLAUDE_SOURCE}
       for name in ("claude-haiku-4-5", "claude-haiku-4-5-20251001")},
    **{name: {"context_window": 1_048_576, "max_output_tokens": 393_216,
              "token_limit_parameter": "max_tokens", "reasoning": True,
              "sampling": True, "source_url": _DEEPSEEK_SOURCE}
       for name in ("deepseek-flash", "deepseek-v4-pro")},
}



# Deployment limits, not family guesses. These official references were checked
# 2026-09-27; an identically named model at a custom gateway need not share them.
_DEPLOYMENT_PRESETS = {
    ("integrate.api.nvidia.com", "/v1", "deepseek-ai/deepseek-v4.1-flash"): {
        "context_window": 1_048_576, "max_output_tokens": 1_048_576,
        "token_limit_parameter": "max_tokens", "reasoning": True,
        "source_url": "https://docs.api.nvidia.com/nim/reference/nvidia-deepseek-v4_1-flash-infer",
    },
    ("developer.amd.com.cn", "/radeon/api/v1", "DeepSeek-V4.1-Flash"): {
        "context_window": 1_048_576, "token_limit_parameter": "max_tokens", "reasoning": True,
        # The public model page publishes the shared window, not a separate output cap.
        "source_url": "https://amd-aim.github.io/radeon-cloud-docs/models/deepseek-v4-1-flash/",
    },
}


def capabilities(model, provider="openai", base_url="", *, include_registry=False):
    model = str(model or "").strip()
    known = dict(_PRESETS.get(model, {}))
    if not known:
        previous = _catalog_match(model, "custom")
        if previous:
            known = {"max_output_tokens": previous["max_output_tokens"],
                     "source_url": previous["source_url"],
                     "catalog_version": previous["verified_at"], "source": "verified_catalog"}
    source = known.get("source", "official_preset") if known else "unknown"
    if include_registry and model:
        registry_preset = "nvidia" if urlparse(base_url or "").hostname == "integrate.api.nvidia.com" else "custom"
        registry = registry_model_record(model, service_preset=registry_preset)
        if registry and any(registry.get(field) for field in ("context_length", "max_input_tokens", "max_output_tokens")):
            known.update({key: value for key, value in {
                "context_window": registry.get("context_length"),
                "max_input_tokens": registry.get("max_input_tokens"),
                "max_output_tokens": registry.get("max_output_tokens"),
            }.items() if value is not None})
            known["source_url"] = MODELS_DEV_URL
            source = "models_dev"
    parsed = urlparse(base_url or "")
    deployment = _DEPLOYMENT_PRESETS.get((parsed.hostname, parsed.path.rstrip("/"), model))
    if deployment:
        known.update(deployment)
        source = "provider_documentation"
    expected = "anthropic" if model.startswith("claude-") else "openai"
    if provider != expected and known:
        # Limits can describe a gateway's model, but wire protocol remains explicit.
        known["token_limit_parameter"] = "max_tokens"
    host = urlparse(base_url or "").hostname or ""
    return {"schema_version": "model-limits/1.0", "model": model,
            "known": bool(known), "catalog_version": CATALOG_VERSION,
            "source": source,
            "gateway_override_available": host not in {"api.openai.com", "api.anthropic.com", "api.deepseek.com"},
            **{name: None for name in LIMIT_FIELDS}, **known}


def model_catalog():
    return [capabilities(model, "anthropic" if model.startswith("claude-") else "openai") for model in _PRESETS]


def upstream_capabilities(item, provider="openai", base_url=""):
    name = str(item.get("id") or item.get("name") or item.get("model") or "")
    result = capabilities(name, provider, base_url)
    top = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
    limits = item.get("limit") if isinstance(item.get("limit"), dict) else {}
    aliases = {
        "context_window": item.get("context_window") or item.get("context_length") or limits.get("context"),
        "max_input_tokens": item.get("max_input_tokens") or limits.get("input"),
        "max_output_tokens": (item.get("max_output_tokens") or item.get("max_completion_tokens")
                              or item.get("output_token_limit") or item.get("max_tokens")
                              or top.get("max_completion_tokens") or limits.get("output")),
    }
    fields = []
    for key, value in aliases.items():
        if isinstance(value, str) and value.isascii() and value.isdigit():
            value = int(value)
        if type(value) is int and 0 < value <= 10_000_000:
            result[key] = value
            fields.append(key)
    supported = item.get("supported_parameters")
    if isinstance(supported, list):
        for parameter in ("max_completion_tokens", "max_tokens"):
            if parameter in supported:
                result["token_limit_parameter"] = parameter
                fields.append("token_limit_parameter")
                break
    # A smaller deployed window must not inherit an impossible catalog output cap.
    window = result.get("context_window")
    for key in ("max_input_tokens", "max_output_tokens"):
        if window and result.get(key) and result[key] > window:
            result[key] = None
            if key in fields:
                fields.remove(key)
    result["provider_fields"] = fields
    if fields:
        result.update(known=True, source="provider_metadata", source_url=base_url.rstrip("/") + "/models")
    return result


def normalize_advanced(payload):
    defaults = capabilities(payload.get("model"), payload.get("provider", "openai"), payload.get("base_url", ""))
    result = {}
    for field in (*LIMIT_FIELDS, "thinking_budget"):
        raw = payload.get(field, defaults.get(field))
        if raw in (None, "", 0, "0"):
            result[field] = None
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ModelCapabilityError("invalid_model_limits", f"{field} 必须是整数。") from exc
        if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()) or not 1 <= value <= 10_000_000:
            raise ModelCapabilityError("invalid_model_limits", f"{field} 必须在 1 到 10000000 之间。")
        result[field] = value
    for field, maximum in (("temperature", 2.0), ("top_p", 1.0)):
        raw = payload.get(field)
        if raw in (None, ""):
            result[field] = None
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ModelCapabilityError("invalid_model_limits", f"{field} 必须是数字。") from exc
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ModelCapabilityError("invalid_model_limits", f"{field} 超出可用范围。")
            result[field] = value
    parameter = str(payload.get("token_limit_parameter") or defaults.get("token_limit_parameter") or "auto")
    if parameter not in {"auto", "max_tokens", "max_completion_tokens"}:
        raise ModelCapabilityError("invalid_model_limits", "输出参数只支持自动、max_tokens 或 max_completion_tokens。")
    result["token_limit_parameter"] = parameter
    effort = str(payload.get("reasoning_effort") or "auto")
    if effort not in {"auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"}:
        raise ModelCapabilityError("invalid_model_limits", "推理强度无效。")
    result["reasoning_effort"] = effort
    window = result.get("context_window")
    if window and any(result.get(field) and result[field] > window for field in ("max_input_tokens", "max_output_tokens")):
        raise ModelCapabilityError("invalid_model_limits", "输入或输出能力不能大于上下文窗口。")
    return result


def context_compaction_threshold(config):
    """Soft input budget, reserving output before the actual model limit."""
    limits = normalize_advanced(config)
    target = int(config.get("context_compaction_tokens") or 256_000)
    if target < 1024:
        raise ModelCapabilityError("invalid_model_limits", "上下文压缩阈值至少为1024 tokens。")
    output = min(int(config.get("max_tokens") or 8192), limits.get("max_output_tokens") or 8192)
    candidates = [target]
    if limits.get("max_input_tokens"):
        candidates.append(int(limits["max_input_tokens"] * 0.85))
    if limits.get("context_window"):
        candidates.append(int(limits["context_window"] * 0.85))
        candidates.append(max(1, limits["context_window"] - output - 1024))
    return max(1, min(candidates))


def _context_token_estimate(value):
    text = json.dumps(value, ensure_ascii=False)
    unicode_chars = sum(ord(char) > 127 for char in text)
    return math.ceil(unicode_chars * 2 + (len(text) - unicode_chars) / 3) + 128


def _compact_context_value(value):
    """Only remove manuscript text if blocks reconstruct it byte for byte."""
    if isinstance(value, list):
        return [_compact_context_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    compact = {key: _compact_context_value(item) for key, item in value.items()}
    blocks = value.get("blocks")
    if isinstance(blocks, list) and blocks and isinstance(value.get("text"), str):
        lines = []
        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                break
            kind = block.get("type")
            if kind == "dialogue" and isinstance(block.get("speaker"), str):
                lines.append(f"{block['speaker']}: {block['text']}")
            elif kind == "narration":
                lines.append(f"旁白: {block['text']}")
            elif kind == "action":
                lines.append(block["text"])
            else:
                break
        else:
            if value["text"] == "\n".join(lines) + "\n":
                compact.pop("text")
    return compact


def _compact_context_text(text):
    # Only machine-produced JSON sections, never free-form manuscript or a
    # sentence containing braces. User instruction string values stay exact.
    decoder = json.JSONDecoder()
    starts = [m.end() for m in re.finditer(r"(?:^|\n)(?:作品上下文|上下文|Context|Brief):\s*", text)]
    if text.lstrip().startswith(("{", "[")):
        starts.append(len(text) - len(text.lstrip()))
    for start in sorted(set(starts), reverse=True):
        try:
            value, end = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, (dict, list)):
            packed = json.dumps(_compact_context_value(value), ensure_ascii=False, separators=(",", ":"))
            text = text[:start] + packed + text[start + end:]
    return text


def compact_request_context(config, payload):
    """Shared writing/AA pressure compactor. No history or authored text loss.

    Semantic conversation summaries are built and versioned in the domain,
    before this transport boundary. This last pass packs structured context;
    protected input that remains too large is handled by normal token preflight.
    The stable system prefix, tools and native tool exchanges stay untouched.
    """
    before = _context_token_estimate(payload)
    threshold = context_compaction_threshold(config)
    report = {"schema_version": "context-compaction/1.0", "threshold_tokens": threshold,
              "estimated_before_tokens": before, "estimated_after_tokens": before,
              "triggered": before >= threshold, "method": "lossless_structured_context",
              "protected_context_exceeds_target": False}
    if before < threshold:
        return payload, report
    result = dict(payload)
    messages = []
    native_exchange = any(message.get("role") == "tool" or message.get("tool_calls") or
                          (isinstance(message.get("content"), list) and any(block.get("type") in {"tool_use", "tool_result"}
                           for block in message["content"] if isinstance(block, dict))) for message in payload.get("messages", []))
    for message in payload.get("messages", []):
        # Do not rewrite an in-flight exchange: its exact prior prefix is also
        # the cache boundary for this logical tool round.
        if not native_exchange and message.get("role") == "user" and isinstance(message.get("content"), str):
            message = {**message, "content": _compact_context_text(message["content"])}
        messages.append(message)
    if "messages" in payload:
        result["messages"] = messages
    after = _context_token_estimate(result)
    report.update(estimated_after_tokens=after, protected_context_exceeds_target=after >= threshold)
    return result, report


def completion_parameters(config, contents, *, tools=False, probe=False):
    """Budget output against estimated input; never silently discard authored text."""
    info = capabilities(config.get("model"), config.get("provider", "openai"), config.get("base_url", ""))
    limits = normalize_advanced(config)
    image_count = 0
    def budget_content(value):
        nonlocal image_count
        if isinstance(value, dict):
            if value.get("type") in {"image", "image_url", "input_image"}:
                image_count += 1
                return "[image]"
            return {key: budget_content(item) for key, item in value.items()}
        if isinstance(value, list):
            return [budget_content(item) for item in value]
        return value
    sanitized = budget_content(contents)
    text = json.dumps(sanitized, ensure_ascii=False)
    non_ascii_chars = sum(1 for char in text if ord(char) > 127)
    ascii_chars = len(text) - non_ascii_chars
    serialized_estimate = math.ceil(non_ascii_chars * 2 + ascii_chars / 3)
    overhead_tokens = 128
    estimated = serialized_estimate + overhead_tokens + image_count * 2000
    input_limit = limits.get("max_input_tokens") or limits.get("context_window")
    diagnostics = {
        "schema_version": "token-preflight/1.0",
        "request_status": "rejected_before_http",
        "estimated_input_tokens": estimated,
        "input_limit_tokens": input_limit,
        "overage_tokens": max(0, estimated - input_limit) if input_limit else 0,
        "serialized_json_characters": len(text),
        "non_ascii_characters": non_ascii_chars,
        "ascii_characters": ascii_chars,
        "estimation_method": "保守字符估算，非模型 tokenizer：非 ASCII×2 + ASCII÷3 + 固定开销128 + 每张图片2000；分项含各自 JSON 包装，不等同服务商账单。",
        "actual_input_tokens": None,
        "actual_output_tokens": None,
        "actual_usage_status": "not_sent",
    }
    if input_limit and estimated >= input_limit:
        # Only counts and fixed labels leave this boundary, never prompt text,
        # credentials, image data, tool arguments or arbitrary metadata keys.
        components = []
        if isinstance(sanitized, dict):
            groups = {}
            if "system" in sanitized:
                groups["系统规则"] = [sanitized["system"]]
            for message in sanitized.get("messages", []):
                role = message.get("role") if isinstance(message, dict) else None
                label = {"system": "系统规则", "user": "用户输入与上下文", "assistant": "历史助手回复", "tool": "工具结果"}.get(role, "其他消息")
                groups.setdefault(label, []).append(message)
            if "tools" in sanitized:
                groups["工具定义"] = [sanitized["tools"]]
            for label, fragments in groups.items():
                subtotal = 0
                for fragment in fragments:
                    fragment_text = json.dumps(fragment, ensure_ascii=False)
                    unicode_chars = sum(1 for char in fragment_text if ord(char) > 127)
                    subtotal += math.ceil(unicode_chars * 2 + (len(fragment_text) - unicode_chars) / 3)
                components.append({"label": label, "estimated_tokens": subtotal})
        components.extend([
            {"label": "固定开销", "estimated_tokens": overhead_tokens},
            {"label": "图片预留", "estimated_tokens": image_count * 2000},
        ])
        diagnostics["components"] = components
        raise ModelCapabilityError(
            "model_context_limit",
            f"输入估算约 {estimated} tokens，超出配置的输入容量 {input_limit}；请减少引用范围或调整真实容量。",
            details=diagnostics,
        )
    output = int(config.get("max_tokens") or limits.get("max_output_tokens") or 8192)
    if limits.get("max_output_tokens"):
        output = min(output, limits["max_output_tokens"])
    if probe:
        probe_budget = max(4096 if info.get("reasoning") else 512, (limits.get("thinking_budget") or 0) + 512)
        output = min(output, probe_budget)
    if limits.get("context_window"):
        output = min(output, limits["context_window"] - estimated - 128)
    if output < 1:
        raise ModelCapabilityError("model_context_limit", "当前输入没有留下可用输出空间，请调整上下文范围。", details=diagnostics)
    parameter = limits["token_limit_parameter"]
    if config.get("provider") == "anthropic":
        parameter = "max_tokens"
    elif parameter == "auto":
        parameter = "max_completion_tokens" if str(config.get("model", "")).lower().startswith(("gemini-3", "gpt-5", "gpt-6", "o1", "o3", "o4")) else "max_tokens"
    result = {parameter: output}
    effort = limits["reasoning_effort"]
    if config.get("provider") == "anthropic":
        if limits.get("thinking_budget"):
            budget = limits["thinking_budget"]
            if budget < 1024 or budget >= output:
                raise ModelCapabilityError("invalid_model_limits", "思考预算至少为 1024，且必须小于本次输出额度。")
            result["thinking"] = {"type": "enabled", "budget_tokens": budget}
        elif effort not in {"auto", "none"} and info.get("adaptive_thinking"):
            result.update(thinking={"type": "adaptive"}, output_config={"effort": effort})
    elif effort != "auto":
        result["reasoning_effort"] = effort
    elif tools and str(config.get("model", "")).startswith("gpt-6"):
        result["reasoning_effort"] = "none"
    if info.get("sampling") is not False and not result.get("thinking"):
        for field in ("temperature", "top_p"):
            if limits[field] is not None:
                result[field] = limits[field]
    return result
