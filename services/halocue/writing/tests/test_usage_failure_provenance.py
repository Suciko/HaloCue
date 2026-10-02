import json
from types import SimpleNamespace
import pytest
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode()


def test_rejected_response_keeps_its_own_reported_usage(monkeypatch):
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    values = iter(
        [
            {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
            {
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 4},
            },
        ]
    )
    monkeypatch.setattr(provider, "_open_with_retry", lambda request: Response(next(values)))
    provider._call_llm("synthetic", "one")
    with pytest.raises(DomainError):
        provider._call_llm("synthetic", "two")
    assert provider.last_usage()["input_tokens"] == 20


def test_transport_failure_never_reuses_previous_call_usage(monkeypatch):
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    monkeypatch.setattr(
        provider,
        "_open_with_retry",
        lambda request: Response(
            {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            }
        ),
    )
    provider._call_llm("synthetic", "one")

    def fail(request):
        raise TimeoutError("synthetic")

    monkeypatch.setattr(provider, "_open_with_retry", fail)
    with pytest.raises(TimeoutError):
        provider._call_llm("synthetic", "two")
    assert provider.last_usage()["usage_status"] == "not_reported"
    assert provider.last_usage()["input_tokens"] == 0


def test_service_usage_keeps_unknown_and_token_semantics():
    provider = SimpleNamespace(
        last_usage=lambda: {
            "schema_version": "provider-usage/1.0",
            "usage_status": "not_reported",
            "cache_status": "unknown",
            "input_tokens_semantics": "total_including_cache",
            "input_tokens": 0,
        }
    )
    usage = WritingService._provider_usage(SimpleNamespace(provider=provider))
    assert usage["usage_status"] == "not_reported"
    assert usage["input_tokens_semantics"] == "total_including_cache"


@pytest.mark.parametrize("value", [-1, True, "NaN", float("nan"), float("inf"), {}, []])
def test_malformed_usage_does_not_replace_primary_output_error_or_price_it(monkeypatch, value):
    provider = LLMWritingProvider(
        {
            "provider": "openai",
            "model": "synthetic",
            "input_cost_per_million": 10,
            "output_cost_per_million": 20,
        }
    )
    response = {
        "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": value, "completion_tokens": 3},
    }
    monkeypatch.setattr(provider, "_open_with_retry", lambda request: Response(response))
    with pytest.raises(DomainError) as error:
        provider._call_llm("synthetic", "one")
    assert error.value.code == "provider_output_truncated"
    usage = provider.last_usage()
    assert usage["usage_status"] == "invalid"
    assert usage["estimated_cost"] is None


def test_empty_usage_object_is_not_known_zero_consumption(monkeypatch):
    provider = LLMWritingProvider(
        {"provider": "openai", "model": "synthetic", "input_cost_per_million": 10}
    )
    response = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}
    monkeypatch.setattr(provider, "_open_with_retry", lambda request: Response(response))
    result = provider._call_llm("synthetic", "one")
    assert result.usage.as_dict()["usage_status"] == "not_reported"
    assert result.usage.estimated_cost is None


def test_missing_one_primary_token_bucket_is_partial_not_fully_reported(monkeypatch):
    provider = LLMWritingProvider(
        {"provider": "openai", "model": "synthetic", "input_cost_per_million": 10}
    )
    response = {
        "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 30},
    }
    monkeypatch.setattr(provider, "_open_with_retry", lambda request: Response(response))
    result = provider._call_llm("synthetic", "one")
    assert result.usage.as_dict()["usage_status"] == "partial"
    assert result.usage.estimated_cost is None


def test_merge_usage_keeps_known_subtotal_but_does_not_claim_complete_cost():
    first = {
        "input_tokens": 10,
        "output_tokens": 2,
        "estimated_cost": 0.01,
        "usage_status": "reported",
        "cache_status": "supported_miss",
        "input_tokens_semantics": "total_including_cache",
    }
    second = {
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost": None,
        "usage_status": "not_reported",
        "cache_status": "unknown",
        "input_tokens_semantics": "total_including_cache",
    }
    result = WritingService._merge_usage(first, second)
    assert result["input_tokens"] == 10
    assert result["estimated_cost"] == 0.01
    assert result["usage_status"] == "partial"
    assert result["cost_status"] == "partial"
    assert result["cache_status"] == "unknown"
    assert result["input_tokens_semantics"] == "total_including_cache"


def test_failure_exception_carries_only_normalized_usage(monkeypatch):
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    response = {
        "choices": [{"message": {"content": "SECRET RAW CONTENT"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        "private": "credential",
    }
    monkeypatch.setattr(provider, "_open_with_retry", lambda request: Response(response))
    with pytest.raises(DomainError) as error:
        provider._call_llm("synthetic", "one")
    assert error.value.details["usage"]["input_tokens"] == 12
    assert "SECRET" not in str(error.value.details)
    assert "credential" not in str(error.value.details)


def test_failed_conversation_run_persists_reported_response_usage(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Synthetic failed usage"})
    thread = work["conversation_threads"][0]
    provider = LLMWritingProvider(
        {"provider": "openai", "model": "synthetic", "input_cost_per_million": 10}
    )
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *args, **kwargs: "synthetic")
    monkeypatch.setattr(
        provider,
        "_open_with_retry",
        lambda request: Response(
            {
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 3},
            }
        ),
    )
    service.provider = provider
    with pytest.raises(DomainError):
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "Synthetic test"},
        )
    runs = service.get_work(work["id"])["agent_runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["policy"]["usage"]["input_tokens"] == 42
    assert runs[0]["policy"]["usage"]["usage_status"] == "reported"
    service.close()


def test_failed_durable_adaptation_persists_usage_without_creating_proposal(tmp_path, monkeypatch):
    from test_adaptation_integrity import prepared

    service, work, source, plan = prepared(tmp_path)
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    monkeypatch.setattr(
        provider,
        "_open_with_retry",
        lambda request: Response(
            {
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 37, "completion_tokens": 5},
            }
        ),
    )
    service.provider = provider
    monkeypatch.setattr(service.agent_dispatcher, "start", lambda: None)
    queued = service.adaptation_jobs.enqueue(work["id"], plan["id"], source["chapters"][0]["id"])
    service.agent_dispatcher.run_once()
    run = service.get_agent_run(work["id"], queued["agent_run_id"])
    assert run["status"] == "failed"
    assert run["policy"]["usage"]["input_tokens"] == 37
    assert run["policy"]["usage"]["usage_status"] == "reported"
    assert not service.get_work(work["id"])["proposals"]
    assert service.agent_usage(work["id"])["input_tokens"] == 37


def test_cancelled_adaptation_keeps_arriving_usage_but_never_candidate(tmp_path, monkeypatch):
    import threading
    from test_adaptation_integrity import prepared

    service, work, source, plan = prepared(tmp_path)
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    started, finish = threading.Event(), threading.Event()

    class Delayed(Response):
        def read(self):
            started.set()
            assert finish.wait(5)
            return super().read()

    monkeypatch.setattr(
        provider,
        "_open_with_retry",
        lambda request: Delayed(
            {
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 19, "completion_tokens": 2},
            }
        ),
    )
    service.provider = provider
    try:
        queued = service.adaptation_jobs.enqueue(
            work["id"], plan["id"], source["chapters"][0]["id"]
        )
        assert started.wait(2)
        service.cancel_agent_run(work["id"], queued["agent_run_id"])
        finish.set()
        service.close()
        run = service.get_agent_run(work["id"], queued["agent_run_id"])
        assert run["status"] == "cancelled"
        assert run["policy"]["usage"]["input_tokens"] == 19
        assert not service.get_work(work["id"])["proposals"]
    finally:
        finish.set()
        service.close()


@pytest.mark.parametrize("operation", ["scene", "scene_review", "continuity", "release_review"])
def test_failed_scene_and_review_runs_keep_usage_in_persisted_policy(
    tmp_path, monkeypatch, operation
):
    from test_vertical_slice import build_to_proposal

    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    provider.is_simulation = True
    monkeypatch.setattr(
        provider,
        "_scene_skill_request",
        lambda *args, **kwargs: {"system_prompt": "synthetic", "user_prompt": "supplied"},
    )
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *args, **kwargs: "synthetic")
    provider.prompt_assembler = SimpleNamespace(
        assemble_work_review_request=lambda *args: {
            "status": "ready",
            "system_prompt": "synthetic",
            "user_prompt": "supplied",
        }
    )
    calls = []

    def respond(request):
        calls.append(request)
        return Response(
            {
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 31, "completion_tokens": 2},
            }
        )

    monkeypatch.setattr(provider, "_open_with_retry", respond)
    service.provider = provider
    current = service.get_work(work_id)
    with pytest.raises(DomainError):
        if operation == "scene":
            service.generate_scene_candidate(
                work_id, scene_id, {"expected_version": current["version"]}
            )
        elif operation == "scene_review":
            service.review_scene(work_id, scene_id, {"expected_version": current["version"]})
        elif operation == "continuity":
            service.review_continuity(work_id, {"expected_version": current["version"]})
        else:
            service.review_release(work_id, {"expected_version": current["version"]})
    assert len(calls) == 1
    failed = [r for r in service.get_work(work_id)["agent_runs"] if r["status"] == "failed"]
    assert failed[0]["policy"]["usage"]["input_tokens"] == 31
    assert failed[0]["policy"]["usage"]["usage_status"] == "reported"
    service.close()


def test_agent_totals_identify_partial_cost_and_unknown_usage(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Synthetic totals"})
    timestamp = "2026-09-07T00:00:00+00:00"
    reported = {
        "input_tokens": 10,
        "output_tokens": 2,
        "usage_status": "reported",
        "estimated_cost": 0.01,
        "input_tokens_semantics": "total_including_cache",
        "cache_status": "unknown",
    }
    missing = {
        "usage_status": "not_reported",
        "estimated_cost": None,
        "input_tokens_semantics": "total_including_cache",
    }
    with service.repo.transaction() as c:
        for ident, usage in [("one", reported), ("two", missing)]:
            c.execute(
                "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    work["id"],
                    "work",
                    work["id"],
                    "synthetic",
                    "failed",
                    json.dumps({"usage": usage}),
                    "none",
                    "none",
                    None,
                    "{}",
                    timestamp,
                    timestamp,
                ),
            )
    totals = service.agent_usage(work["id"])
    assert totals["estimated_cost"] == 0.01
    assert totals["cost_status"] == "partial"
    assert totals["usage_status"] == "partial"
    assert totals["unknown_usage_run_count"] == 1
    assert totals["accounting_scope"] == "recorded_logical_calls"
    service.close()


def test_conversation_usage_status_survives_message_reload_and_presentation(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Usage messages"})
    thread = work["conversation_threads"][0]
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic"})
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *a, **kw: "synthetic")
    monkeypatch.setattr(
        provider,
        "_open_with_retry",
        lambda request: Response(
            {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
        ),
    )
    service.provider = provider
    with pytest.raises(DomainError):
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "synthetic"},
        )
    current = service.get_work(work["id"])
    message = current["conversation_threads"][0]["messages"][-1]
    assert message["usage_status"] == "not_reported"
    assert message["cache_status"] == "unknown"
    assert message["content"]["provider_usage"]["usage_status"] == "not_reported"
    service.close()


def test_followup_scope_exit_failure_does_not_double_count_usage(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from test_agent_production import ToolFollowupProvider

    service = WritingService(tmp_path)
    work = service.create_work({"title": "Scope failure"})
    thread = work["conversation_threads"][0]
    service.provider = ToolFollowupProvider()
    original = service._provider_usage_scope
    observations = []

    @contextmanager
    def scope(provider, run_id):
        with original(provider, run_id):
            yield
        observations.append(run_id)
        if len(observations) == 2:
            raise OSError("synthetic audit exit error")

    monkeypatch.setattr(service, "_provider_usage_scope", scope)
    with pytest.raises(DomainError):
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "Read context"},
        )
    run = service.get_work(work["id"])["agent_runs"][0]
    assert len(service.provider.contexts) == 2
    assert run["policy"]["usage"]["input_tokens"] == 130
    assert run["policy"]["usage"]["estimated_cost"] == pytest.approx(0.003)
    service.close()


def test_cancel_before_followup_does_not_record_nonexistent_unknown_call(tmp_path, monkeypatch):
    from test_agent_production import ToolFollowupProvider

    class Provider(ToolFollowupProvider):
        def reset_usage(self):
            self._usage = {}

        def last_usage(self):
            return {
                **self._usage,
                "usage_status": "reported" if self._usage else "not_reported",
                "input_tokens_semantics": "total_including_cache",
            }

    service = WritingService(tmp_path)
    work = service.create_work({"title": "Cancel before followup"})
    thread = work["conversation_threads"][0]
    service.provider = Provider()
    original = service._agent_run_is_running
    cancelled = []

    def check(run_id):
        if service.provider.contexts and not cancelled:
            cancelled.append(run_id)
            service.cancel_agent_run(work["id"], run_id)
        return original(run_id)

    # There is also a liveness check after the first response. Permit that one,
    # then cancel at the next check inside the follow-up lock.
    checks = []

    def on_check(run_id):
        checks.append(run_id)
        if len(checks) == 3:
            return check(run_id)
        return original(run_id)

    monkeypatch.setattr(service, "_agent_run_is_running", on_check)
    service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "Read context"},
    )
    run = service.get_work(work["id"])["agent_runs"][0]
    assert run["status"] == "cancelled"
    assert len(service.provider.contexts) == 1
    assert run["policy"]["usage"]["usage_status"] == "reported"
    assert run["policy"]["usage"]["cost_status"] == "complete_estimate"
    service.close()


def test_cancelled_before_any_invocation_has_no_usage_observation(tmp_path, monkeypatch):
    from test_agent_production import ToolFollowupProvider

    service = WritingService(tmp_path)
    work = service.create_work({"title": "No call"})
    thread = work["conversation_threads"][0]
    provider = ToolFollowupProvider()
    service.provider = provider

    def started(run_id):
        service.cancel_agent_run(work["id"], run_id)

    result = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "synthetic",
            "_run_started_callback": started,
        },
    )
    run = service.get_agent_run(work["id"], result["agent_run_id"])
    assert provider.contexts == []
    assert run["policy"].get("usage") == {}
    service.close()


def test_tool_followup_failure_keeps_both_call_usage_once(tmp_path, monkeypatch):
    from test_agent_production import ToolFollowupProvider

    class FailedFollowup(ToolFollowupProvider):
        def discuss_work(self, messages, context):
            value = super().discuss_work(messages, context)
            if context.get("tool_followup"):
                raise DomainError("provider_output_truncated", "synthetic", status=502)
            return value

    service = WritingService(tmp_path)
    work = service.create_work({"title": "Two observations"})
    thread = work["conversation_threads"][0]
    service.provider = FailedFollowup()
    with pytest.raises(DomainError):
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "Read context"},
        )
    run = service.get_work(work["id"])["agent_runs"][0]
    assert len(service.provider.contexts) == 2
    assert run["policy"]["usage"]["input_tokens"] == 130
    assert service.agent_usage(work["id"])["input_tokens"] == 130
    service.close()


@pytest.mark.parametrize("prices", [
    {"input_cost_per_million": 10},
    {"output_cost_per_million": 20},
    {"input_cost_per_million": 10, "output_cost_per_million": 0},
])
def test_missing_price_for_consumed_bucket_is_unknown_not_free(prices):
    provider = LLMWritingProvider({"provider": "openai", "model": "synthetic", **prices})
    usage = provider._capture_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    assert usage.usage_status == "reported"
    assert usage.estimated_cost is None


def test_complete_prices_keep_known_arithmetic_and_cache_included_once():
    provider = LLMWritingProvider({
        "provider": "openai", "model": "synthetic",
        "input_cost_per_million": 10, "output_cost_per_million": 20,
    })
    usage = provider._capture_usage({"usage": {
        "prompt_tokens": 100, "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 80},
    }})
    assert usage.input_tokens == 100
    assert usage.estimated_cost == pytest.approx(0.00068)
