"""Bounded local diagnostics for annotation model reasoning."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


class ReasoningTelemetryWriter:
    """Append maintenance-only reasoning records to a bounded JSONL file."""

    def __init__(self, root: Any, run_key: str, *, max_records: int = 50, max_bytes: int = 2_000_000):
        self.path = Path(root) / str(run_key) / "reasoning.jsonl"
        self.max_records = max(1, int(max_records))
        self.max_bytes = max(256, int(max_bytes))

    def write(self, record: Mapping[str, Any]) -> Path:
        payload = dict(record or {})
        text = str(payload.get("reasoning_text") or "")
        payload["reasoning_text"] = text
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > self.max_bytes:
            budget = max(0, self.max_bytes - len(encoded.encode("utf-8")) + len(text.encode("utf-8")) - 80)
            while len(text.encode("utf-8")) > budget and text:
                text = text[:-max(1, len(text) // 10)]
            payload["reasoning_text"] = text
            payload["reasoning_text_truncated"] = True
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if self.path.is_file():
            lines = self.path.read_text(encoding="utf-8").splitlines()
        lines.append(encoded)
        lines = lines[-self.max_records:]
        while len("\n".join(lines).encode("utf-8")) > self.max_bytes and len(lines) > 1:
            lines.pop(0)
        temporary = self.path.with_suffix(".jsonl.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        return self.path
