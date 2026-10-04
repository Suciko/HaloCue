"""Recover public discussion envelopes without interpreting embedded tools."""

from __future__ import annotations

import json
import re

PUBLIC_FIELDS = {
    "text",
    "questions",
    "decision_card",
    "reasoning_summary",
    "ready_for_proposal",
    "ready_to_organize",
}
SIGNALS = PUBLIC_FIELDS - {"text"}


def extract_discussion_envelope(text: str) -> tuple[dict, str] | None:
    """Find one complete reply, retaining prose outside its JSON/code fence.

    Ordinary code samples and ambiguous multiple replies remain ordinary text.
    Recovery only projects public fields; embedded tool requests never execute.
    """
    source = str(text or "").strip()
    decoder = json.JSONDecoder()
    candidates = []
    end = 0
    for match in re.finditer(r"\{", source):
        if match.start() < end:
            continue
        try:
            value, length = decoder.raw_decode(source[match.start() :])
        except ValueError:
            continue
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("text"), str)
            or not SIGNALS.intersection(value)
        ):
            continue
        start, end = match.start(), match.start() + length
        left, right = source[:start], source[end:]
        fence = re.search(r"```(?:json)?\s*$", left, re.IGNORECASE)
        if fence and re.match(r"\s*```", right):
            left = left[: fence.start()]
            right = re.sub(r"^\s*```", "", right, count=1)
        outside = "\n\n".join(part.strip() for part in (left, right) if part.strip())
        candidates.append(({key: value[key] for key in PUBLIC_FIELDS if key in value}, outside))
    return candidates[0] if len(candidates) == 1 else None


def recover_discussion_text(text: str) -> dict | None:
    extracted = extract_discussion_envelope(text)
    if not extracted:
        return None
    reply, outside = extracted
    public = reply["text"].strip()
    reply["text"] = (
        outside
        if public and public in outside
        else "\n\n".join(part for part in (outside, public) if part)
    )
    # A quoted or recovered envelope is presentation evidence, not permission
    # to organize or execute a task. Native tool calls retain their own path.
    reply["ready_for_proposal"] = False
    reply["ready_to_organize"] = False
    return reply
