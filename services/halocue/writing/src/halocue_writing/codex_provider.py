"""Adapt real Codex dynamic tool requests to HaloCue's checked tool executor."""

import json
import uuid
from contextlib import contextmanager

from services.halocue.codex_agent import CodexError, CodexTurn, usage_receipt
from .errors import DomainError
from .providers import LLMCallResult, LLMWritingProvider, ProviderToolCall, ProviderUsageSnapshot


class CodexWritingProvider(LLMWritingProvider):
    def __init__(self, credentials, prompt_assembler=None):
        super().__init__(credentials, prompt_assembler)
        self.display_name = f"{self.model} · Codex 订阅"
        self.cache_support = "supported"

    @contextmanager
    def cancellation_scope(self, callback):
        previous = getattr(self._thread_state, "codex_cancelled", None)
        self._thread_state.codex_cancelled = callback
        try:
            yield
        finally:
            self._thread_state.codex_cancelled = previous

    def usage_receipt_pending(self):
        turn = getattr(self._thread_state, "codex_turn", None)
        return bool(turn and turn.pending)

    def _call_llm_impl(self, system_prompt, user_prompt, tools=None, tool_results=None):
        state = self._thread_state
        frame = getattr(state, "request_frame", None)
        if frame is not None and tool_results is None:
            frame["ordinal"] += 1
            event = {
                "phase": "started",
                "id": "request-" + uuid.uuid4().hex,
                "logical_id": frame["logical_id"],
                "ordinal": frame["ordinal"],
                "provider": self.descriptor(),
            }
            observer = getattr(state, "request_observer", None)
            if observer:
                observer(event)
            frame["active"] = event
            state.codex_request_event = event
        elif frame is not None:
            frame["active"] = getattr(state, "codex_request_event", None)
        previous = getattr(state, "codex_turn", None)
        try:
            if tool_results is None:
                if previous:
                    previous.close()
                state.codex_turn = CodexTurn(
                    self.credentials,
                    system_prompt + self._reasoning_instruction(),
                    user_prompt,
                    tools=tools,
                    cancelled=getattr(state, "codex_cancelled", None),
                )
                state.context_compaction = state.codex_turn.context_compaction
            elif previous:
                previous.resume_tool(tool_results)
            else:
                raise CodexError(
                    "codex_tool_exchange_missing", "Codex 工具上下文已结束，请重试本轮任务。"
                )
            result = state.codex_turn.step()
            usage = ProviderUsageSnapshot(**result.get("total_usage", result["usage"]))
            state.last_usage = usage
            tool = result["tool"]
            calls = (
                (
                    ProviderToolCall(
                        tool["callId"],
                        tool["tool"],
                        json.dumps(tool["arguments"], ensure_ascii=False),
                    ),
                )
                if tool
                else ()
            )
            if not tool:
                state.codex_turn = None
                state.codex_request_event = None
            elif frame is not None:
                # A tool yield continues this same managed turn. Its final
                # cumulative receipt completes the original ledger observation.
                frame["active"] = None
            return LLMCallResult(result["text"], "", calls, usage)
        except CodexError as error:
            if getattr(state, "codex_turn", None):
                state.last_usage = ProviderUsageSnapshot(**usage_receipt(state.codex_turn.usage))
            elif isinstance(error.details.get("usage"), dict):
                state.last_usage = ProviderUsageSnapshot(**error.details["usage"])
            if getattr(state, "codex_turn", None):
                state.codex_turn.close()
                state.codex_turn = None
            raise DomainError(
                error.code,
                error.message,
                status=409
                if error.code in {"codex_login_required", "codex_quota_exhausted"}
                else 502,
                details=error.details,
            ) from error
