"""Use the existing production schema and job controls over Codex stdio."""

import threading

from llm import Provider, parse_and_validate_json_response
from services.halocue.codex_agent import CodexError, CodexTurn
from .errors import ProductionError


class CodexDirectionProvider(Provider):
    name = "codex"

    def __init__(self, config):
        super().__init__(config)
        self._turn = None
        self._turn_lock = threading.Lock()

    def abort_active_request(self):
        with self._turn_lock:
            if self._turn:
                self._turn.close()

    def complete_json(self, static_system, volatile_system, user, schema):
        return self.complete_json_stream(static_system, volatile_system, user, schema)

    def _record_usage(self, usage, **outcome):
        self.stats["calls"] += 1
        for counter, field in (
            ("in", "input_tokens"),
            ("out", "output_tokens"),
            ("cache_read", "cache_read_tokens"),
            ("cache_write", "cache_write_tokens"),
        ):
            self.stats[counter] += usage[field]
        self.stats["cache_reports"] += int(usage["cache_status"] != "unknown")
        self.stats["cache_miss"] += max(0, usage["input_tokens"] - usage["cache_read_tokens"])
        self._append_request_record(
            {
                **usage,
                "provider": "codex",
                "model": self.model,
                "billing": "chatgpt_subscription",
                **outcome,
            }
        )

    def complete_json_stream(
        self, static_system, volatile_system, user, schema, *, on_activity=None
    ):
        turn = None
        try:
            if self._request_cancelled():
                raise CodexError("codex_cancelled", "已停止 Codex 任务。")
            turn = CodexTurn(
                self.cfg,
                static_system + "\n" + volatile_system,
                user,
                schema=schema,
                cancelled=self._request_cancelled,
            )
            with self._turn_lock:
                self._turn = turn
            if on_activity:
                on_activity({"state": "waiting", "model": self.model})
            result = turn.step(cancelled=self._request_cancelled, on_activity=on_activity)
            self._record_usage(result["usage"], finish_reason="stop")
            output = parse_and_validate_json_response(result["text"], schema)
            if on_activity:
                on_activity({"state": "completed", "model": self.model, "finish_reason": "stop"})
            return output
        except CodexError as error:
            if isinstance(error.details.get("usage"), dict):
                self._record_usage(error.details["usage"], status="failed", error_code=error.code)
            raise ProductionError(
                error.code,
                error.message,
                status=409
                if error.code in {"codex_login_required", "codex_quota_exhausted"}
                else 502,
                details=error.details,
            ) from error
        finally:
            if turn:
                turn.close()
            with self._turn_lock:
                self._turn = None

    def complete_json_vision(self, system, images, user, schema):
        raise ProductionError(
            "codex_vision_not_supported",
            "当前 Codex 接入支持文字写作和演出安排；素材视觉识别尚未接入。",
            status=409,
        )
