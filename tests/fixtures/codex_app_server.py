"""Synthetic stdio peer; it cannot call a model or read credentials."""

import json
import sys

scenario = sys.argv[1]
thread_id, turn_id = "thread-fixture", "turn-fixture"


def emit(value):
    print(json.dumps(value), flush=True)


def completed():
    emit(
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": thread_id,
                "turnId": turn_id,
                "tokenUsage": {
                    "total": {
                        "inputTokens": 100,
                        "outputTokens": 12,
                        "cachedInputTokens": 60,
                        "cacheWriteInputTokens": 0,
                    }
                },
            },
        }
    )
    emit(
        {
            "method": "item/completed",
            "params": {
                "threadId": thread_id,
                "item": {
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": "not json" if scenario == "malformed" else '{"ok":true}',
                },
            },
        }
    )
    emit(
        {
            "method": "turn/completed",
            "params": {
                "threadId": thread_id,
                "turn": {
                    "id": turn_id,
                    "status": "failed" if scenario == "failed" else "completed",
                    "error": {"codexErrorInfo": "usageLimitExceeded"}
                    if scenario == "failed"
                    else None,
                },
            },
        }
    )


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method is None and request.get("id") == "tool-request":
        assert request["result"]["success"] is True
        completed()
        continue
    result = {}
    if method == "account/read":
        result = {
            "account": None
            if scenario == "logged-out"
            else {
                "type": "apiKey" if scenario == "api-auth" else "chatgpt",
                "planType": "plus",
                "email": "private@example.test",
            }
        }
    elif method == "account/rateLimits/read":
        result = {
            "rateLimits": {
                "credits": {"balance": "private-credit-balance"},
                "primary": {
                    "usedPercent": 100 if scenario == "quota" else 25,
                    "resetsAt": 1900000000,
                },
                "secondary": None,
            }
        }
    elif method == "model/list":
        result = {
            "data": [{"model": "fixture-model", "displayName": "Fixture model", "isDefault": True}],
            "nextCursor": None,
        }
    elif method == "thread/start":
        assert request["params"]["sandbox"] == "read-only"
        assert request["params"]["ephemeral"] is True
        result = {"thread": {"id": thread_id}}
    elif method == "turn/start":
        result = {"turn": {"id": turn_id, "status": "inProgress"}}
    elif method == "account/login/start":
        assert request["params"]["type"] == "chatgpt"
        result = {
            "type": "chatgpt",
            "authUrl": "https://auth.openai.com/authorize?fixture=1",
            "loginId": "private-login",
            "accessToken": "must-never-return",
        }
    if "id" in request:
        emit({"id": request["id"], "result": result})
    if method == "turn/start":
        if scenario == "timeout":
            continue
        if scenario in {"tool", "unauthorized-tool"}:
            emit(
                {
                    "method": "item/tool/call",
                    "id": "tool-request",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "callId": "call-fixture",
                        "tool": "read_scene_text_window" if scenario == "tool" else "shell",
                        "arguments": {"scene_id": "scene-fixture"},
                    },
                }
            )
        else:
            completed()
