"""Physical attempt evidence is synthetic and written only to temporary SQLite."""

import io
import json
import threading
import urllib.error

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.service import WritingService
from test_adaptation_integrity import prepared, valid_reply


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


def setup_job(tmp_path, monkeypatch):
    service, work, source, plan = prepared(tmp_path)
    provider = LLMWritingProvider(
        {
            "provider": "openai",
            "model": "synthetic",
            "api_key": "SECRET-KEY",
            "input_cost_per_million": 10,
            "output_cost_per_million": 20,
        }
    )
    provider.request_attempts = 2
    service.provider = provider
    monkeypatch.setattr(provider, "_retry_delay", lambda *args: 0)
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: {"started": False})
    queued = service.adaptation_jobs.enqueue(work["id"], plan["id"], source["chapters"][0]["id"])
    body = {
        "choices": [
            {
                "message": {"content": json.dumps(valid_reply(source["chapters"][0]))},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }
    return service, work, source, plan, queued, provider, body


def test_timeout_retry_has_two_durable_attempts_and_one_known_response(tmp_path, monkeypatch):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    attempts = []

    def transport(request, timeout):
        snapshot = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
        assert snapshot["summary"]["physical_request_count"] == len(attempts) + 1
        assert snapshot["items"][-1]["status"] == "dispatched"
        attempts.append(request)
        if len(attempts) == 1:
            raise TimeoutError("synthetic possibly charged timeout")
        return Response(body)

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", transport)
    service.agent_dispatcher.run_once()
    snapshot = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert [r["status"] for r in snapshot["items"]] == ["failed", "succeeded"]
    assert [r["ordinal"] for r in snapshot["items"]] == [1, 2]
    summary = snapshot["summary"]
    assert summary["physical_request_count"] == 2 and summary["logical_request_count"] == 1
    assert summary["unknown_usage_count"] == 1
    assert summary["totals"]["input_tokens"] == 10
    assert summary["totals"]["usage_status"] == "partial"
    assert summary["totals"]["cost_status"] == "partial"
    assert service.agent_usage(work["id"])["input_tokens"] == 10
    assert service.agent_usage(work["id"])["physical_request_count"] == 2
    assert "SECRET-KEY" not in json.dumps(snapshot)
    assert "possibly charged" not in json.dumps(snapshot)
    assert source["chapters"][0]["paragraphs"][0]["text"] not in json.dumps(
        snapshot, ensure_ascii=False
    )


def test_retry_error_body_usage_is_retained_separately(tmp_path, monkeypatch):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    attempts = []

    def transport(request, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                "https://synthetic.invalid?key=SECRET-KEY",
                429,
                "busy",
                {},
                io.BytesIO(
                    json.dumps(
                        {
                            "error": {"message": "secret diagnostic"},
                            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                        }
                    ).encode()
                ),
            )
        return Response(body)

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", transport)
    service.agent_dispatcher.run_once()
    snapshot = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snapshot["summary"]["totals"]["input_tokens"] == 15
    assert snapshot["summary"]["unknown_usage_count"] == 0
    assert service.agent_usage(work["id"])["input_tokens"] == 15
    assert "secret diagnostic" not in json.dumps(snapshot)


def test_truncated_response_has_reported_usage_but_no_candidate(tmp_path, monkeypatch):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    body["choices"][0]["finish_reason"] = "length"
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen", lambda *args, **kw: Response(body)
    )
    service.agent_dispatcher.run_once()
    snapshot = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snapshot["items"][0]["status"] == "rejected"
    assert snapshot["items"][0]["error_code"] == "provider_output_truncated"
    assert snapshot["summary"]["totals"]["input_tokens"] == 10
    assert not service.get_work(work["id"])["proposals"]


def test_pending_attempt_is_not_zero_consumption_and_other_service_keeps_it_pending(
    tmp_path, monkeypatch
):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    started, finish = threading.Event(), threading.Event()

    def transport(*args, **kw):
        started.set()
        assert finish.wait(8)
        return Response(body)

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", transport)
    worker = threading.Thread(target=service.agent_dispatcher.run_once)
    worker.start()
    try:
        assert started.wait(3)
        second = WritingService(service.repo.data_dir)
        snap = second.request_ledger.for_run(work["id"], queued["agent_run_id"])
        assert snap["summary"]["pending_count"] == 1
        assert snap["summary"]["totals"]["usage_status"] == "not_reported"
        second.cancel_agent_run(work["id"], queued["agent_run_id"])
        second.request_ledger.recover_interrupted()
        assert (
            second.request_ledger.for_run(work["id"], queued["agent_run_id"])["items"][0]["status"]
            == "interrupted"
        )
        finish.set()
        worker.join(5)
        snap = second.request_ledger.for_run(work["id"], queued["agent_run_id"])
        assert snap["summary"]["totals"]["input_tokens"] == 10
        assert service.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "cancelled"
        assert not service.get_work(work["id"])["proposals"]
    finally:
        finish.set()
        worker.join(5)
        service.close()


def test_terminal_replay_is_idempotent_conflicts_rejected_and_pages_are_stable(
    tmp_path, monkeypatch
):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    ledger = service.request_ledger
    run_id = queued["agent_run_id"]
    for number in range(3):
        start = {
            "phase": "started",
            "id": f"req-{number}",
            "logical_id": "logical-one",
            "ordinal": number + 1,
            "provider": {"model": "synthetic", "api_key": "SECRET"},
        }
        finish = {
            "phase": "finished",
            "id": start["id"],
            "status": "succeeded",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "usage_status": "reported",
                "input_tokens_semantics": "total_including_cache",
            },
        }
        ledger.observe(run_id, start)
        ledger.observe(run_id, start)
        ledger.observe(run_id, finish)
        ledger.observe(run_id, finish)
    first = ledger.for_run(work["id"], run_id, limit=2)
    assert first["summary"]["physical_request_count"] == 3
    assert first["summary"]["totals"]["input_tokens"] == 3
    assert first["next_cursor"] == first["items"][-1]["id"]
    second = ledger.for_run(work["id"], run_id, limit=2, after_id=first["next_cursor"])
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    assert "SECRET" not in json.dumps(first)
    with pytest.raises(DomainError):
        ledger.observe(run_id, {**finish, "usage": {"input_tokens": 99}})
    assert ledger.for_run(work["id"], run_id)["summary"]["totals"]["input_tokens"] == 3
    other = service.create_work({"title": "Other"})
    with pytest.raises(DomainError):
        ledger.for_run(other["id"], run_id)


def test_intent_persistence_failure_stops_before_network(tmp_path, monkeypatch):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    calls = []

    def fail(run_id, event):
        raise OSError("synthetic ledger unavailable")

    monkeypatch.setattr(service.request_ledger, "observe", fail)
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen", lambda *a, **kw: calls.append(1)
    )
    service.agent_dispatcher.run_once()
    assert calls == []
    assert service.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "failed"


def test_multiple_tool_rounds_have_distinct_logical_requests(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Physical tools"})
    thread = work["conversation_threads"][0]
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *a, **kw: "synthetic")
    count = []

    def transport(request, timeout):
        count.append(1)
        if len(count) == 1:
            return Response(
                {
                    "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "read_work_context",
                                            "arguments": "{}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                }
            )
        return Response(
            {
                "usage": {"prompt_tokens": 20, "completion_tokens": 2},
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "text": "read",
                                    "questions": [],
                                    "reasoning_summary": "verified",
                                    "ready_for_proposal": False,
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", transport)
    service.provider = provider
    result = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "Read context"},
    )
    snap = service.request_ledger.for_run(work["id"], result["agent_run_id"])
    assert snap["summary"]["physical_request_count"] == 2
    assert snap["summary"]["logical_request_count"] == 2
    assert snap["summary"]["totals"]["input_tokens"] == 30
    assert service.agent_usage(work["id"])["input_tokens"] == 30


def test_request_ledger_survives_normal_backup_restore(tmp_path, monkeypatch):
    import base64

    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen", lambda *a, **kw: Response(body)
    )
    service.agent_dispatcher.run_once()
    before = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    _, archive, summary = service.export_writing_backup()
    restored = WritingService(tmp_path / "restored")
    restored.restore_writing_backup(
        {
            "content_base64": base64.b64encode(archive).decode(),
            "expected_backup_hash": summary["backup_hash"],
            "replace_all_works": True,
        }
    )
    after = restored.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert after == before
    assert restored.agent_usage(work["id"])["input_tokens"] == 10
    restored.close()


def test_shared_provider_keeps_observers_and_logical_ids_thread_local(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    first = setup_job(tmp_path / "one", monkeypatch)
    second = setup_job(tmp_path / "two", monkeypatch)
    provider = first[5]
    barrier = threading.Barrier(2)

    def call(pair):
        values, text = pair
        with provider.observe_requests(
            lambda event: values[0].request_ledger.observe(values[4]["agent_run_id"], event)
        ):
            provider._call_llm("synthetic", text)

    # OpenAI request begins with the system message, so inspect last user message.
    def correct_transport(request, timeout):
        data = json.loads(request.data)
        count = 11 if data["messages"][-1]["content"] == "one" else 22
        barrier.wait(4)
        return Response(
            {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": count, "completion_tokens": 1},
            }
        )

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", correct_transport)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(call, [(first, "one"), (second, "two")]))
    assert (
        first[0].request_ledger.for_run(first[1]["id"], first[4]["agent_run_id"])["summary"][
            "totals"
        ]["input_tokens"]
        == 11
    )
    assert (
        second[0].request_ledger.for_run(second[1]["id"], second[4]["agent_run_id"])["summary"][
            "totals"
        ]["input_tokens"]
        == 22
    )


def test_request_api_is_work_scoped_and_preserves_unknown_retry(tmp_path, monkeypatch):
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pathlib import Path
    from halocue_writing.app import make_handler

    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    ledger = service.request_ledger
    ledger.observe(
        queued["agent_run_id"],
        {
            "phase": "started",
            "id": "request-pending",
            "logical_id": "logical-test",
            "ordinal": 1,
            "provider": {},
        },
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(service, Path(__file__).resolve().parents[1] / "web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1/works/{work['id']}/agent-runs/{queued['agent_run_id']}/requests"
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read())["data"]
        assert payload["summary"]["pending_count"] == 1
        assert payload["summary"]["unknown_usage_count"] == 1
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(url.replace(work["id"], "other-work"), timeout=3)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_invalid_request_cursor_is_client_error(tmp_path, monkeypatch):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    with pytest.raises(DomainError) as error:
        service.request_ledger.for_run(
            work["id"], queued["agent_run_id"], after_id="invalid!cursor"
        )
    assert error.value.status == 400


def test_plain_http_error_diagnostic_is_preserved_without_becoming_ledger_data(
    tmp_path, monkeypatch
):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://synthetic.invalid", 400, "bad", {}, io.BytesIO(b"plain diagnostic, not JSON")
        )

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fail)
    with provider.observe_requests(
        lambda event: service.request_ledger.observe(queued["agent_run_id"], event)
    ):
        with pytest.raises(urllib.error.HTTPError) as error:
            provider._call_llm("synthetic", "synthetic")
    assert error.value.read(2048) == b"plain diagnostic, not JSON"
    snap = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snap["summary"]["unknown_usage_count"] == 1
    assert "plain diagnostic" not in json.dumps(snap)


def test_one_shot_terminal_persistence_failure_replays_original_success_not_transport(
    tmp_path, monkeypatch
):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    calls = []
    deliveries = []
    observe = service.request_ledger.observe

    def recording(run_id, event):
        if event["phase"] == "finished":
            deliveries.append(event.copy())
            if len(deliveries) == 1:
                raise OSError("synthetic terminal write failure")
        return observe(run_id, event)

    monkeypatch.setattr(service.request_ledger, "observe", recording)
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda *a, **kw: calls.append(1) or Response(body),
    )
    service.agent_dispatcher.run_once()
    assert calls == [1]
    assert len(deliveries) == 2 and deliveries[0] == deliveries[1]
    snap = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snap["items"][0]["status"] == "succeeded"
    assert snap["summary"]["totals"]["input_tokens"] == 10
    assert service.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "completed"


def test_partial_503_body_preserves_original_retry_classification(tmp_path, monkeypatch):
    from http.client import IncompleteRead

    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)

    class Broken(io.BytesIO):
        def read(self, *a):
            raise IncompleteRead(b"partial")

        def close(self):
            if not getattr(self, "failed_close", False):
                self.failed_close = True
                raise OSError("synthetic close failure")
            super().close()

    calls = []

    def transport(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.HTTPError("https://synthetic.invalid", 503, "busy", {}, Broken())
        return Response(body)

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", transport)
    service.agent_dispatcher.run_once()
    assert calls == [1, 1]
    snap = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snap["items"][0]["error_code"] == "503"
    assert snap["items"][1]["status"] == "succeeded"


def test_unacknowledged_terminal_receipt_survives_and_replays_without_double_count(
    tmp_path, monkeypatch
):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    observe = service.request_ledger.observe
    calls = []

    def unavailable(run_id, event):
        if event["phase"] == "finished":
            raise OSError("synthetic persistent terminal outage")
        return observe(run_id, event)

    monkeypatch.setattr(service.request_ledger, "observe", unavailable)
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda *a, **kw: calls.append(1) or Response(body),
    )
    service.agent_dispatcher.run_once()
    run = service.get_agent_run(work["id"], queued["agent_run_id"])
    assert run["status"] == "failed"
    assert len(run["policy"]["pending_request_records"]) == 1
    snap = service.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snap["summary"]["pending_receipt_count"] == 1
    assert snap["summary"]["totals"]["input_tokens"] == 10
    assert service.agent_usage(work["id"])["input_tokens"] == 10
    # Starting a new service replays the stored terminal receipt, not the request.
    restored = WritingService(service.repo.data_dir)
    snap = restored.request_ledger.for_run(work["id"], queued["agent_run_id"])
    assert snap["items"][0]["status"] == "succeeded"
    assert snap["summary"]["pending_receipt_count"] == 0
    assert restored.agent_usage(work["id"])["input_tokens"] == 10
    assert calls == [1]
    assert restored.get_agent_run(work["id"], queued["agent_run_id"])["status"] == "failed"


def test_conversation_finalization_preserves_unacknowledged_receipt(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Synthetic receipt conversation"})
    thread = work["conversation_threads"][0]
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *a, **kw: "synthetic")
    service.provider = provider
    observe = service.request_ledger.observe
    calls = []

    def unavailable(run_id, event):
        if event["phase"] == "finished":
            raise OSError("synthetic persistent terminal outage")
        return observe(run_id, event)

    monkeypatch.setattr(service.request_ledger, "observe", unavailable)
    body = {
        "choices": [{"message": {"content": "synthetic"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda *a, **kw: calls.append(1) or Response(body),
    )
    with pytest.raises(DomainError, match="Agent"):
        service.post_conversation_message(
            work["id"], thread["id"],
            {"expected_thread_version": thread["version"], "text": "Synthetic test"},
        )
    run = service.get_work(work["id"])["agent_runs"][0]
    assert run["status"] == "failed"
    assert len(run["policy"].get("pending_request_records", {})) == 1
    assert service.agent_usage(work["id"])["input_tokens"] == 10
    restored = WritingService(tmp_path)
    snap = restored.request_ledger.for_run(work["id"], run["id"])
    assert snap["items"][0]["status"] == "succeeded"
    assert snap["summary"]["pending_receipt_count"] == 0
    assert restored.agent_usage(work["id"])["input_tokens"] == 10
    assert restored.get_agent_run(work["id"], run["id"])["status"] == "failed"
    assert calls == [1]
    service.close()
    restored.close()


def test_activity_snapshot_keeps_request_usage_after_refresh(tmp_path, monkeypatch):
    service, work, source, plan, queued, provider, body = setup_job(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen", lambda *args, **kw: Response(body)
    )
    service.agent_dispatcher.run_once()
    activity = service.get_activity_snapshot(work["id"])
    run = next(row for row in activity["agent_runs"] if row["id"] == queued["agent_run_id"])
    summary = service.request_ledger.for_run(work["id"], run["id"])["summary"]
    assert run["request_usage"] == summary
    assert run["request_usage"]["totals"]["input_tokens"] == 10
    assert run["request_usage"]["totals"]["output_tokens"] == 2
    assert run["request_usage"]["physical_request_count"] == 1
    assert "SECRET-KEY" not in json.dumps(activity)
    assert source["chapters"][0]["paragraphs"][0]["text"] not in json.dumps(activity)
