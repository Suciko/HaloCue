"""Keep actionable provider error fields without exposing raw protocol payloads."""

import re


def provider_error(error: dict, *, fallback: str) -> tuple[str, str, dict]:
    message = str(error.get("message") or fallback)
    message = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[redacted]", message)
    message = re.sub(
        r"(?i)([\"\']?(?:access_token|refresh_token|api_key|authorization)[\"\']?\s*[:=]\s*[\"\']?)[^\s\"\',}]+",
        r"\1[redacted]",
        message,
    )
    message = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", message)[:4000]
    info = error.get("codexErrorInfo")
    details = {}
    if isinstance(info, str):
        details["codex_error_info"] = info
    elif isinstance(info, dict):
        for name, value in info.items():
            details["codex_error_info"] = str(name)
            if isinstance(value, dict) and isinstance(value.get("httpStatusCode"), int):
                details["http_status"] = value["httpStatusCode"]
    for target, field, pattern in (
        ("http_status", "httpStatusCode", r"(?:HTTP\s+|status(?: code)?[\s:=]+)([45]\d\d)"),
        (
            "error_type",
            "type",
            r"\b(invalid_request_error|server_error|authentication_error|permission_error)\b",
        ),
        ("error_code", "code", r"\b(invalid_json_schema|rate_limit_exceeded|insufficient_quota)\b"),
    ):
        value = error.get(field)
        if (target == "http_status" and isinstance(value, int)) or (
            target != "http_status" and isinstance(value, str)
        ):
            details[target] = value[:160] if isinstance(value, str) else value
        elif match := re.search(pattern, message, re.I):
            details.setdefault(target, int(match[1]) if target == "http_status" else match[1])
    code = (
        "codex_quota_exhausted"
        if info in ("usageLimitExceeded", "rateLimitExceeded")
        else "codex_turn_failed"
    )
    return code, f"Codex 请求失败：{message}", details
