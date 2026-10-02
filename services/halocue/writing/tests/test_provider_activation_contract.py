import io
import json
import urllib.error

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.model_settings import WritingModelSettings
from halocue_writing.model_capabilities import completion_parameters
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class ModelTestResponse:
    status = 200

    def __init__(self, body: dict | None = None):
        self.body = body if body is not None else {
            "choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
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


def test_current_model_defaults_and_switch_do_not_inherit_old_limits(tmp_path, monkeypatch):
    calls = []
    def request(req, timeout):
        calls.append(json.loads(req.data))
        return ModelTestResponse()
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", request)
    settings = WritingModelSettings(tmp_path)
    settings.activate({**model_payload(model="private", api_key="fixture-key"), "context_window": 32768, "max_input_tokens": 16000, "max_output_tokens": 4096})
    result = settings.activate({"model": "gpt-6-sol"})
    config = result["model"]
    assert config["context_window"] == 1050000 and config["max_tokens"] == 128000
    assert config["max_input_tokens"] is None
    assert calls[-1]["max_completion_tokens"] == 4096 and "max_tokens" not in calls[-1]
    restored = WritingModelSettings(tmp_path).get_credentials()
    assert restored["context_window"] == 1050000


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


def test_custom_model_context_and_wire_parameter_reach_test_and_runtime(tmp_path, monkeypatch):
    calls = []
    def successful_test(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8")))
        return ModelTestResponse()
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", successful_test)
    settings = WritingModelSettings(tmp_path)
    activated = settings.activate({
        **model_payload(model="private-writer", api_key="fixture-key"),
        "context_window": 32768, "max_input_tokens": 24000,
        "max_output_tokens": 8192, "max_tokens": 4096,
        "token_limit_parameter": "max_tokens",
    })
    assert calls[0]["max_tokens"] == 512  # connection probes deliberately use a small budget
    assert "max_completion_tokens" not in calls[0]
    saved = activated["model"]
    assert (saved["context_window"], saved["max_input_tokens"], saved["max_output_tokens"]) == (32768, 24000, 8192)
    assert completion_parameters(settings.get_credentials(), "正文") == {"max_tokens": 4096}


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

def test_model_only_switch_preserves_connection_and_secret_but_resets_model_limits(tmp_path, monkeypatch):
    calls = []
    def success(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8")))
        return ModelTestResponse()
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", success)
    settings = WritingModelSettings(tmp_path)
    first = settings.activate(model_payload(model="writer-a", api_key="secret-a"))["model"]
    result = settings.activate({"model": "writer-b", "expected_config_digest": first["config_digest"]})["model"]
    assert result["model"] == "writer-b"
    for key in ("base_url", "provider", "timeout", "reasoning_mode"):
        assert result[key] == first[key]
    assert result["max_tokens"] == 8192
    assert settings.get_credentials()["api_key"] == "secret-a"
    assert calls[-1]["model"] == "writer-b"
    assert "api_key" not in result


def test_stale_model_picker_cannot_switch_a_new_connection(tmp_path, monkeypatch):
    calls = []
    def success(request, timeout):
        calls.append(request.full_url)
        return ModelTestResponse()
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", success)
    settings = WritingModelSettings(tmp_path)
    old = settings.activate(model_payload(model="writer-a", api_key="secret-a"))["model"]
    new = settings.activate(model_payload(model="writer-c", api_key="secret-c"))["model"]
    count = len(calls)
    with pytest.raises(DomainError) as error:
        settings.activate({"model": "writer-b", "expected_config_digest": old["config_digest"]})
    assert error.value.code == "model_settings_changed"
    assert len(calls) == count
    assert settings.public()["model"] == new


def test_anthropic_picker_reads_provider_list_not_static_names(tmp_path, monkeypatch):
    settings = WritingModelSettings(tmp_path)
    observed = []
    def models(request, timeout):
        observed.append(request)
        return ModelTestResponse({"data": [{"id": "model-from-provider"}]})
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", models)
    result = settings.fetch_models({"provider": "anthropic", "base_url": "https://models.example/v1", "api_key": "test-key"})
    assert result == ["model-from-provider"]
    assert observed[0].get_header("X-api-key") == "test-key"
    assert observed[0].get_header("Authorization") is None

def test_registered_models_keep_their_own_endpoint_secret_and_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", lambda *args, **kwargs: ModelTestResponse())
    settings = WritingModelSettings(tmp_path)
    settings.activate(model_payload(model="writer", api_key="secret-a"))
    first_id = settings.public()["registered_models"][0]["id"]
    settings.activate({**model_payload(model="writer", api_key="secret-b"), "base_url": "https://other.example/v1", "max_tokens": 8192})
    listed = settings.public()
    assert len(listed["registered_models"]) == 2
    assert "secret-a" not in json.dumps(listed)
    assert "secret-b" not in json.dumps(listed)
    assert "registered_models" not in listed["model"]
    settings.activate({"registered_model_id": first_id, "expected_config_digest": listed["model"]["config_digest"]})
    actual = settings.get_credentials()
    assert actual["base_url"] == "https://models.example/v1"
    assert actual["api_key"] == "secret-a"
    assert actual["max_tokens"] == 4096
    assert len(settings.public()["registered_models"]) == 2
    assert next(item for item in settings.public()["registered_models"] if item["id"] == first_id)["current"]


def test_legacy_current_config_is_registered_without_write(tmp_path, monkeypatch):
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", lambda *args, **kwargs: ModelTestResponse())
    settings = WritingModelSettings(tmp_path)
    settings.activate(model_payload(model="writer", api_key="secret-a"))
    data = json.loads(settings.path.read_text(encoding="utf-8"))
    data.pop("registered_models")
    settings.path.write_text(json.dumps(data), encoding="utf-8")
    before = settings.path.read_bytes()
    assert settings.public()["registered_models"][0]["model"] == "writer"
    assert settings.path.read_bytes() == before
    with pytest.raises(DomainError, match="尚未"):
        settings.activate({"registered_model_id": "missing"})
    assert settings.path.read_bytes() == before

def test_registered_selection_failure_and_override_do_not_change_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", lambda *args, **kwargs: ModelTestResponse())
    settings = WritingModelSettings(tmp_path)
    settings.activate(model_payload(model="writer-a", api_key="secret-a"))
    first_id = settings.public()["registered_models"][0]["id"]
    settings.activate(model_payload(model="writer-b", api_key="secret-b"))
    before = settings.path.read_bytes()
    with pytest.raises(DomainError, match="不能覆盖"):
        settings.activate({"registered_model_id": first_id, "model": "injected"})
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://models.example/v1", 404, "missing", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr("halocue_writing.model_settings.urllib.request.urlopen", fail)
    with pytest.raises(DomainError):
        settings.activate({"registered_model_id": first_id})
    assert settings.path.read_bytes() == before
    assert settings.get_credentials()["api_key"] == "secret-b"
