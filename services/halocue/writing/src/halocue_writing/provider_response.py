"""Validate transport completion before treating model content as an artifact."""

from __future__ import annotations

from .errors import DomainError


def validate_completion(data: object, protocol: str, *, allow_tools: bool = False) -> None:
    def reject(code: str, message: str) -> None:
        raise DomainError(code, message, status=502, details={"failure_kind": code})

    if not isinstance(data, dict) or data.get("error"):
        reject("provider_output_invalid", "模型没有返回有效的完成响应。")
    if protocol == "anthropic":
        blocks = data.get("content")
        reason = data.get("stop_reason")
        if not isinstance(blocks, list) or not blocks:
            reject("provider_output_invalid", "模型响应缺少正文。")
        if any(isinstance(block, dict) and block.get("type") == "refusal" for block in blocks) or reason == "refusal":
            reject("provider_refused", "模型拒绝了当前请求。")
        tool_call = any(isinstance(block, dict) and block.get("type") == "tool_use" for block in blocks)
        normal = {"end_turn", "stop_sequence"}
        truncated = reason == "max_tokens"
        tool_reason = "tool_use"
    else:
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            reject("provider_output_invalid", "模型响应缺少唯一的候选结果。")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            reject("provider_output_invalid", "模型响应缺少消息对象。")
        reason = choices[0].get("finish_reason")
        if message.get("refusal") or reason == "content_filter":
            reject("provider_refused", "模型拒绝了当前请求。")
        tool_call = bool(message.get("tool_calls"))
        normal = {"stop"}
        truncated = reason == "length"
        tool_reason = "tool_calls"
    if truncated:
        reject("provider_output_truncated", "模型输出达到上限，候选不完整；请缩小范围或提高输出上限。")
    if tool_call:
        if not allow_tools or reason != tool_reason:
            reject("provider_output_invalid", "模型工具调用不符合当前任务的完成协议。")
    elif reason not in normal:
        reject("provider_output_invalid", "模型响应未确认正常结束。")
