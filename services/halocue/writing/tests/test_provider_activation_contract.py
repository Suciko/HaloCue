import io
import json
import urllib.error

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.model_settings import WritingModelSettings
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class ModelTestResponse:
    status = 200

    def __init__(self, body: dict | None = None):
        self.body = body or {
            "choices": [{"message": {"content": "pong"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


def model_payload(*, model: str, api_key: str) -> dict:
    return {
        "preset_id": "custom",
        "provider": "openai",
        "base_url": "https://models.example/v1",
        "model": model,
        "api_key": api_key,
        "max_tokens": 4096,
        "timeout": 45,
        "reasoning_mode": "balanced",
    }


def test_model_activation_tests_before_persisting_versioned_configuration(tmp_path, monkeypatch):
    calls = []

    def successful_test(request, timeout):
        calls.append({
            "url": request.full_url,
            "timeout": timeout,
            "body": json.loads(request.data.decode("utf-8")),
        })
        return ModelTestResponse()

    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", successful_test)
    settings = WritingModelSettings(tmp_path)

    activated = settings.activate(model_payload(model="writer-a", api_key="secret-a"))
    model = activated["model"]

    assert len(calls) == 1
    assert calls[0]["url"] == "https://models.example/v1/chat/completions"
    assert calls[0]["body"]["model"] == "writer-a"
    assert model["config_revision"]
    assert model["config_digest"].startswith("sha256:")
    assert model["last_tested_at"]
    assert model["last_test_latency_ms"] >= 0
    persisted = json.loads(settings.path.read_text(encoding="utf-8"))
    assert persisted["config_revision"] == model["config_revision"]
    assert persisted["config_digest"] == model["config_digest"]
    assert persisted["last_tested_at"] == model["last_tested_at"]
    assert persisted["last_test_latency_ms"] == model["last_test_latency_ms"]
    assert "api_key" not in persisted


def test_failed_model_activation_keeps_previous_config_and_secret(tmp_path, monkeypatch):
    attempts = 0

    def test_connection(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return ModelTestResponse()
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":{"message":"bad key"}}'),
        )

    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", test_connection)
    settings = WritingModelSettings(tmp_path)
    first = settings.activate(model_payload(model="writer-a", api_key="secret-a"))["model"]

    with pytest.raises(DomainError) as rejected:
        settings.activate(model_payload(model="writer-b", api_key="secret-b"))

    assert rejected.value.code == "connection_test_failed"
    assert attempts == 2
    current = settings.public()["model"]
    assert current["model"] == "writer-a"
    assert current["config_revision"] == first["config_revision"]
    assert current["config_digest"] == first["config_digest"]
    assert current["last_tested_at"] == first["last_tested_at"]
    assert settings.get_credentials()["api_key"] == "secret-a"


def test_service_activation_exposes_provider_identity_and_config_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "halocue_writing.model_settings.urllib.request.urlopen",
        lambda request, timeout: ModelTestResponse(),
    )
    service = WritingService(tmp_path)

    activated = service.activate_writing_model(
        model_payload(model="writer-a", api_key="secret-a")
    )
    descriptor = service.health()["provider"]

    assert descriptor["kind"] == "llm"
    assert descriptor["provider"] == "openai"
    assert descriptor["model"] == "writer-a"
    assert descriptor["config_digest"] == activated["model"]["config_digest"]


def test_real_conversation_retry_rejects_changed_provider_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "halocue_writing.model_settings.urllib.request.urlopen",
        lambda request, timeout: ModelTestResponse(),
    )
    service = WritingService(tmp_path)
    service.activate_writing_model(model_payload(model="writer-a", api_key="secret-a"))
    work = service.create_work({"title": "固定 Provider 的对话"})
    thread = work["conversation_threads"][0]

    def fail_first_turn(_messages, _context):
        raise DomainError("writing_provider_failed", "模型 A 暂时不可用。", status=502)

    service.provider.discuss_work = fail_first_turn
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {
                "expected_thread_version": thread["version"],
                "text": "先讨论开场的异常。",
            },
        )
    assert failed.value.code == "agent_failed"
    failed_run_id = failed.value.details["agent_run_id"]
    failed_work = service.get_work(work["id"])
    current_thread = failed_work["conversation_threads"][0]

    service.activate_writing_model(model_payload(model="writer-b", api_key="secret-b"))

    def must_not_call_new_provider(_messages, _context):
        pytest.fail("配置漂移必须在调用新 Provider 前被拒绝")

    service.provider.discuss_work = must_not_call_new_provider
    with pytest.raises(DomainError) as rejected:
        service.retry_agent_run(
            work["id"],
            failed_run_id,
            {"expected_thread_version": current_thread["version"]},
        )

    assert rejected.value.code == "provider_config_changed"
    assert rejected.value.status == 409
    assert rejected.value.details["agent_run_id"] == failed_run_id
    assert rejected.value.details["snapshot_config_digest"]
    assert rejected.value.details["current_config_digest"]
    assert rejected.value.details["snapshot_config_digest"] != rejected.value.details["current_config_digest"]


def test_fake_conversation_retry_is_not_blocked_by_provider_config_guard(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "Fake Provider 重试"})
    thread = work["conversation_threads"][0]

    def fail_first_turn(_messages, _context):
        raise DomainError("writing_provider_failed", "模拟一次失败。", status=502)

    service.provider.discuss_work = fail_first_turn
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {
                "expected_thread_version": thread["version"],
                "text": "继续讨论当前想法。",
            },
        )
    failed_run_id = failed.value.details["agent_run_id"]
    failed_work = service.get_work(work["id"])
    current_thread = failed_work["conversation_threads"][0]
    service.provider = FakeWritingProvider()

    retried = service.retry_agent_run(
        work["id"],
        failed_run_id,
        {"expected_thread_version": current_thread["version"]},
    )

    assert retried["retried_from_agent_run_id"] == failed_run_id
    assert retried["agent_run_id"] != failed_run_id
    assert retried["simulation"] is True
