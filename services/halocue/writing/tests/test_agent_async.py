from __future__ import annotations

import threading
import time
import json
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class BlockingProvider(FakeWritingProvider):
    is_simulation = False
    kind = "blocking-test"
    display_name = "Blocking test provider"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        self.started.set()
        self.release.wait(timeout=5)
        return {
            "text": "这条结果只有未取消时才应写入对话。",
            "questions": [],
            "reasoning_summary": "完成了可公开的任务摘要。",
            "ready_for_proposal": False,
        }


def wait_for_terminal(service: WritingService, work_id: str, run_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = service.get_agent_run(work_id, run_id)
        if run["status"] not in {"queued", "running"}:
            return run
        time.sleep(0.02)
    raise AssertionError("AgentRun did not reach a terminal state")


def http_json(url: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_enqueued_agent_run_returns_after_input_is_durable(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "异步对话"})
    thread = work["conversation_threads"][0]
    provider = BlockingProvider()
    service.provider = provider

    started_at = time.monotonic()
    queued = service.enqueue_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "先分析，不要阻塞页面。"},
    )

    assert time.monotonic() - started_at < 1
    assert provider.started.wait(timeout=1)
    run = service.get_agent_run(work["id"], queued["agent_run_id"])
    assert run["status"] == "running"
    assert run["policy"]["thread_id"] == thread["id"]
    assert service.repo.read_text(run["input_snapshot_uri"])

    provider.release.set()
    completed = wait_for_terminal(service, work["id"], run["id"])
    assert completed["status"] == "completed"
    restored = service.get_work(work["id"])
    assert restored["conversation_threads"][0]["messages"][-1]["agent_run_id"] == run["id"]


def test_cancelled_agent_run_discards_late_provider_result_and_can_retry(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "取消对话"})
    thread = work["conversation_threads"][0]
    provider = BlockingProvider()
    service.provider = provider

    queued = service.enqueue_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "这轮随后取消。"},
    )
    run_id = queued["agent_run_id"]
    assert provider.started.wait(timeout=1)

    cancelled = service.cancel_agent_run(work["id"], run_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["failure"]["code"] == "cancelled_by_user"
    provider.release.set()
    time.sleep(0.1)

    restored = service.get_work(work["id"])
    current_thread = restored["conversation_threads"][0]
    assert [message["role"] for message in current_thread["messages"]].count("assistant") == 0
    assert not restored["proposals"]

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work["id"], run_id,
        {"expected_thread_version": current_thread["version"]},
    )
    assert retried["retried_from_agent_run_id"] == run_id
    assert retried["work"]["conversation_threads"][0]["messages"][-1]["role"] == "assistant"


def test_active_conversation_requires_redirect_and_redirect_is_idempotent(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "运行中转向"})
    thread = work["conversation_threads"][0]
    provider = BlockingProvider()
    service.provider = provider

    queued = service.enqueue_conversation_message(
        work["id"], thread["id"],
        {"expected_thread_version": thread["version"], "text": "先沿用原来的方向。"},
    )
    run_id = queued["agent_run_id"]
    assert provider.started.wait(timeout=1)
    current_thread = service.get_work(work["id"])["conversation_threads"][0]
    with pytest.raises(DomainError) as active:
        service.enqueue_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": current_thread["version"], "text": "不要并发排第二轮。"},
        )
    assert active.value.code == "agent_run_active"

    result_box = {}

    def redirect():
        result_box["result"] = service.redirect_agent_run(
            work["id"], run_id,
            {
                "expected_thread_version": current_thread["version"],
                "text": "转向：不要解释异常来源，先检查人物反应。",
                "idempotency_key": "turn-once",
            },
        )

    redirect_thread = threading.Thread(target=redirect)
    redirect_thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and service.get_agent_run(work["id"], run_id)["status"] != "cancelled":
        time.sleep(0.01)
    assert service.get_agent_run(work["id"], run_id)["status"] == "cancelled"
    provider.release.set()
    redirect_thread.join(timeout=5)
    assert not redirect_thread.is_alive()

    redirected = result_box["result"]
    assert redirected["redirected_from_agent_run_id"] == run_id
    replacement_id = redirected["agent_run_id"]
    replacement = wait_for_terminal(service, work["id"], replacement_id)
    assert replacement["status"] == "completed"
    restored = service.get_work(work["id"])
    messages = restored["conversation_threads"][0]["messages"]
    assert [item["role"] for item in messages].count("assistant") == 1
    redirected_user = next(item for item in messages if item["content"].get("redirect_of") == run_id)
    assert redirected_user["content"]["text"].startswith("转向：")

    duplicate = service.redirect_agent_run(
        work["id"], run_id,
        {
            "expected_thread_version": restored["conversation_threads"][0]["version"],
            "text": "这段文字不应建立第三轮。",
            "idempotency_key": "turn-once",
        },
    )
    assert duplicate["agent_run_id"] == replacement_id


def test_async_agent_http_status_and_cancel_contract(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "异步 HTTP"})
    conversation = work["conversation_threads"][0]
    provider = BlockingProvider()
    service.provider = provider
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/v1"
    try:
        status, response = http_json(
            base + f"/works/{work['id']}/threads/{conversation['id']}/messages:enqueue",
            "POST",
            {"expected_thread_version": conversation["version"], "text": "异步运行。"},
        )
        assert status == 202
        run_id = response["data"]["agent_run_id"]
        assert provider.started.wait(timeout=1)

        status, response = http_json(base + f"/works/{work['id']}/agent-runs/{run_id}")
        assert status == 200
        assert response["data"]["status"] == "running"

        status, response = http_json(
            base + f"/works/{work['id']}/agent-runs/{run_id}:cancel", "POST", {}
        )
        assert status == 200
        assert response["data"]["status"] == "cancelled"
    finally:
        provider.release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


def test_async_agent_http_redirect_is_idempotent_and_isolates_cancelled_result(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "异步 HTTP 转向"})
    conversation = work["conversation_threads"][0]
    provider = BlockingProvider()
    service.provider = provider
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = f"http://127.0.0.1:{server.server_port}/api/v1"
    try:
        status, response = http_json(
            base + f"/works/{work['id']}/threads/{conversation['id']}/messages:enqueue",
            "POST",
            {"expected_thread_version": conversation["version"], "text": "先沿用原方向。"},
        )
        assert status == 202
        original_run_id = response["data"]["agent_run_id"]
        current_thread = response["data"]["work"]["conversation_threads"][0]
        assert provider.started.wait(timeout=1)

        redirect_body = {
            "expected_thread_version": current_thread["version"],
            "text": "转向：先检查人物反应，不要解释异常来源。",
            "idempotency_key": "http-redirect-once",
        }
        status, redirected_response = http_json(
            base + f"/works/{work['id']}/agent-runs/{original_run_id}:redirect",
            "POST",
            redirect_body,
        )
        assert status == 200
        redirected = redirected_response["data"]
        replacement_run_id = redirected["agent_run_id"]
        assert replacement_run_id != original_run_id
        assert redirected["redirected_from_agent_run_id"] == original_run_id

        status, duplicate_response = http_json(
            base + f"/works/{work['id']}/agent-runs/{original_run_id}:redirect",
            "POST",
            {
                **redirect_body,
                "text": "重复请求不应建立第三轮。",
                "expected_thread_version": redirected["work"]["conversation_threads"][0]["version"],
            },
        )
        assert status == 200
        assert duplicate_response["data"]["agent_run_id"] == replacement_run_id
        assert duplicate_response["data"]["redirected_from_agent_run_id"] == original_run_id

        provider.release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, replacement_response = http_json(
                base + f"/works/{work['id']}/agent-runs/{replacement_run_id}"
            )
            if replacement_response["data"]["status"] not in {"queued", "running"}:
                break
            time.sleep(0.02)
        assert replacement_response["data"]["status"] == "completed"

        _, original_response = http_json(
            base + f"/works/{work['id']}/agent-runs/{original_run_id}"
        )
        assert original_response["data"]["status"] == "cancelled"
        _, work_response = http_json(base + f"/works/{work['id']}")
        messages = work_response["data"]["conversation_threads"][0]["messages"]
        assistants = [message for message in messages if message["role"] == "assistant"]
        assert len(assistants) == 1
        assert assistants[0]["agent_run_id"] == replacement_run_id
        assert not any(message.get("agent_run_id") == original_run_id for message in assistants)
        redirected_users = [
            message for message in messages
            if message["role"] == "user" and message["content"].get("redirect_of") == original_run_id
        ]
        assert len(redirected_users) == 1
        assert redirected_users[0]["content"]["text"] == redirect_body["text"]
    finally:
        provider.release.set()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
