"""Cost diagnostics are estimates, never fabricated provider receipts."""
import json

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.model_capabilities import completion_parameters
from halocue_writing.service import WritingService
from test_scene_conversation_harness import CapturingProvider, create_ready_scene, create_scene_thread
from test_provider_tool_calling import provider


def test_preflight_is_structured_bounded_and_does_not_send_http(monkeypatch):
    client = provider("openai", "https://fixture.invalid/v1")
    client.credentials.update(context_window=1000, max_tokens=200)
    monkeypatch.setattr(client, "_open_with_retry", lambda *_: pytest.fail("must not send HTTP"))
    secret = "private-marker-do-not-log"
    with pytest.raises(DomainError) as raised:
        client._call_llm("规则" * 1000, secret, tools=[])
    details = raised.value.details
    assert raised.value.code == "model_context_limit"
    assert details["request_status"] == "rejected_before_http"
    assert details["estimated_input_tokens"] > details["input_limit_tokens"] == 1000
    assert details["overage_tokens"] == details["estimated_input_tokens"] - 1000
    assert details["actual_input_tokens"] is None
    assert secret not in json.dumps(details, ensure_ascii=False)
    assert {row["label"] for row in details["components"]} >= {"系统规则", "用户输入与上下文"}
    assert len(details["components"]) <= 8


def test_image_preflight_does_not_count_or_expose_base64():
    def blocked(data):
        with pytest.raises(DomainError) as raised:
            completion_parameters({"context_window": 100}, {
                "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data}}]}],
            })
        return raised.value.details
    assert blocked("a") == blocked("a" * 1000000)


def test_output_space_failure_has_preflight_diagnostics():
    with pytest.raises(DomainError) as raised:
        completion_parameters({"context_window": 200}, "hello")
    assert raised.value.details["request_status"] == "rejected_before_http"
    assert raised.value.details["input_limit_tokens"] == 200


def test_conversation_failure_keeps_token_diagnostics_after_restart(tmp_path):
    class Blocked(CapturingProvider):
        def discuss_work(self, messages, work_context):
            completion_parameters({"context_window": 1000}, "中文" * 1000)
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    _, thread = create_scene_thread(service, work_id, scene_id, work)
    service.provider = Blocked()
    with pytest.raises(DomainError):
        service.post_conversation_message(work_id, thread["id"], {
            "expected_thread_version": thread["version"], "text": "只讨论，不改正文。",
        })
    restored = WritingService(tmp_path).get_work(work_id)
    run = next(run for run in restored["agent_runs"] if run.get("failure", {}).get("code") == "model_context_limit")
    diagnostic = run["failure"]["token_diagnostics"]
    assert diagnostic["estimated_input_tokens"] > diagnostic["input_limit_tokens"]
    assert diagnostic["request_status"] == "rejected_before_http"
    assert not run["request_usage"]
    assert service.get_agent_run(work_id, run["id"])["failure"]["token_diagnostics"] == diagnostic
    assert restored["chapters"][-1]["scenes"][0]["current_revision_id"] is None
