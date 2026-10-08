"""Synthetic stdio peer; it cannot call a model or read credentials."""

import json
import sys

scenario = sys.argv[1]
thread_id, turn_id = "thread-fixture", "turn-fixture"
output_schema = None


def emit(value):
    print(json.dumps(value), flush=True)


def completed():
    text = '{"ok":true}'
    if output_schema and "lines" in output_schema.get("properties", {}):
        state_properties = output_schema["properties"]["state_delta"]["properties"]
        line_properties = output_schema["properties"]["lines"]["items"]["properties"]
        row = {name: False if node.get("type") == "boolean" else 0 if node.get("type") == "integer" else "" for name, node in line_properties.items()}
        row.update(source_id="connection-target", text_fingerprint="connection-fingerprint", direction=None)
        text = json.dumps({"lines": [row], "state_delta": {name: None for name in state_properties}, "memory_events": [], "beats": []})
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
                    "text": "not json" if scenario == "malformed" else text,
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
        output_schema = request["params"].get("outputSchema")
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
        if scenario == "schema-error":
            emit({"method": "error", "params": {
                "threadId": thread_id, "turnId": turn_id, "willRetry": True,
                "error": {"message": "HTTP 400 invalid_request_error: invalid_json_schema at text.format.schema; Missing 'beats'.",
                          "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 400}}},
            }})
            emit({"method": "error", "params": {
                "threadId": thread_id, "turnId": turn_id, "willRetry": False,
                "error": {"message": "HTTP 400 invalid_request_error: invalid_json_schema at text.format.schema; Missing 'act'.",
                          "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 400}}},
            }})
            emit({"method": "turn/completed", "params": {"threadId": thread_id,
                  "turn": {"id": turn_id, "status": "failed", "error": None}}})
            continue
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
