"""Usage provenance helpers: zero counters are not evidence of zero billable use."""

import math

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
USAGE_STATUSES = {"reported", "not_reported", "partial", "invalid", "legacy_unknown"}
CACHE_STATUSES = {"supported_hit", "supported_miss", "unsupported", "unknown"}


def token_count(value):
    if type(value) is int and 0 <= value <= 10**15:
        return value, True
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 16:
        number = int(value)
        return (number, True) if number <= 10**15 else (0, False)
    if (
        type(value) is float
        and math.isfinite(value)
        and 0 <= value <= 10**15
        and value.is_integer()
    ):
        return int(value), True
    return 0, False


def normalize_usage(value):
    if not isinstance(value, dict):
        value = {}
    counts = {}
    invalid = False
    for key in TOKEN_KEYS:
        counts[key], valid = token_count(value.get(key, 0))
        invalid |= not valid
    cost = value.get("estimated_cost")
    if cost is not None:
        if type(cost) not in (int, float) or cost < 0 or cost > 10**15 or not math.isfinite(cost):
            cost = None
            invalid = True
        else:
            cost = float(cost)
    status = value.get("usage_status")
    if status not in USAGE_STATUSES:
        status = "legacy_unknown" if value else "not_reported"
    if invalid:
        status, cost = "invalid", None
    cache = value.get("cache_status", "unknown")
    if cache not in CACHE_STATUSES:
        cache = "unknown"
    complete = status == "reported" and cost is not None and value.get("cost_status") != "partial"
    return {
        "schema_version": "provider-usage/1.0",
        "input_tokens_semantics": "total_including_cache"
        if value.get("input_tokens_semantics") == "total_including_cache"
        else "unknown",
        **counts,
        "estimated_cost": cost,
        "usage_status": status,
        "cache_status": cache,
        "cost_status": "complete_estimate"
        if complete
        else "partial"
        if cost is not None
        else "unknown",
    }


def merge_usage(first, second):
    # An empty accumulator is an identity, not an unknown physical request.
    if not first:
        return normalize_usage(second)
    if not second:
        return normalize_usage(first)
    values = [normalize_usage(first), normalize_usage(second)]
    statuses = [v["usage_status"] for v in values]
    result = {key: sum(v[key] for v in values) for key in TOKEN_KEYS}
    costs = [v["estimated_cost"] for v in values if v["estimated_cost"] is not None]
    status = (
        "reported"
        if all(s == "reported" for s in statuses)
        else (
            statuses[0] if statuses[0] == statuses[1] and statuses[0] != "reported" else "partial"
        )
    )
    result.update(
        {
            "schema_version": "provider-usage/1.0",
            "input_tokens_semantics": "total_including_cache"
            if all(v["input_tokens_semantics"] == "total_including_cache" for v in values)
            else "unknown",
            "estimated_cost": sum(costs) if costs else None,
            "usage_status": status,
            "cost_status": "complete_estimate"
            if all(v["cost_status"] == "complete_estimate" for v in values)
            else "partial"
            if costs
            else "unknown",
            "cache_status": values[0]["cache_status"]
            if values[0]["cache_status"] == values[1]["cache_status"]
            else "unknown",
        }
    )
    return result
