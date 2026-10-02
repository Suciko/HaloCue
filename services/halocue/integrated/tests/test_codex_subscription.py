import json
import sys
from pathlib import Path

import pytest

from services.halocue import codex_agent as codex
from halocue_writing.errors import DomainError
from halocue_writing.model_settings import WritingModelSettings
from halocue_writing.providers import make_writing_provider
from halocue_production.direction_models import DirectionModelGateway
from halocue_production.errors import ProductionError
from halocue_production.model_settings import DirectionModelSettings


def payload(**values):
    return {
        "provider": "codex",
        "model": "fixture-model",
        "subscription_only_acknowledged": True,
        **values,
    }


@pytest.fixture
def synthetic_peer(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr(codex, "discover_cli", lambda explicit="": Path(sys.executable))
    fixture = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "codex_app_server.py"

    def scenario(name):
        monkeypatch.setattr(codex, "command", lambda cli: [str(cli), str(fixture), name])

    scenario("completed")
    yield scenario
    codex.connection().close()


@pytest.mark.parametrize("kind", ["writing", "production"])
def test_switching_to_codex_drops_old_api_credentials(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("FIXTURE_API_KEY", "must-not-be-used")
    settings = (
        WritingModelSettings(tmp_path) if kind == "writing" else DirectionModelSettings(tmp_path)
    )
    settings.save(
        {
            "provider": "openai",
            "model": "old-model",
            "base_url": "https://paid.example/v1",
            "api_key_env": "FIXTURE_API_KEY",
        }
    )
    candidate = settings.resolve_candidate(payload())
    assert candidate["api_key"] == "" and candidate["api_key_env"] == ""
    assert candidate["base_url"] == "" and candidate["billing"] == "chatgpt_subscription"
    saved = settings.save(payload())
    assert saved["model"]["configured"] is True
    credentials = (
        settings.get_credentials() if kind == "writing" else settings.provider_settings()[1]
    )
    assert credentials["api_key"] == ""


@pytest.mark.parametrize("kind", ["writing", "production"])
def test_codex_model_settings_reject_explicit_api_key_without_changing_saved_profile(
    tmp_path, kind
):
    settings = (
        WritingModelSettings(tmp_path) if kind == "writing" else DirectionModelSettings(tmp_path)
    )
    error_type = DomainError if kind == "writing" else ProductionError
    with pytest.raises(error_type) as error:
        settings.save(payload(api_key="not-allowed"))
    assert error.value.code == "codex_subscription_required"
    assert not settings.path.exists()


def test_writing_activation_uses_real_subscription_transport_and_versions_profile(
    tmp_path, synthetic_peer
):
    settings = WritingModelSettings(tmp_path)
    result = settings.activate(payload())
    assert result["test"]["billing"] == "chatgpt_subscription"
    provider = make_writing_provider(settings)
    assert provider.is_simulation is False
    assert provider.descriptor()["provider"] == "codex"
    assert provider._call_llm("Return JSON", "synthetic").usage.cache_read_tokens == 60


def test_writing_native_tool_exchange_preserves_call_identity(synthetic_peer):
    synthetic_peer("tool")
    provider = make_writing_provider({**payload(), "configured": True})
    tools = [
        {
            "name": "read_scene_text_window",
            "description": "Read scene",
            "input_schema": {"type": "object"},
        }
    ]
    first = provider._call_llm("Return JSON", "synthetic", tools=tools)
    call = first.tool_calls[0]
    assert call.id == "call-fixture" and call.name == "read_scene_text_window"
    second = provider._call_llm(
        "Return JSON",
        "synthetic",
        tools=tools,
        tool_results=[
            {
                "id": call.id,
                "tool": call.name,
                "status": "succeeded",
                "output": {"text": "synthetic"},
            }
        ],
    )
    assert json.loads(second.text) == {"ok": True} and not second.tool_calls
    assert provider.last_usage()["estimated_cost"] is None


def test_native_tool_continuation_is_one_turn_with_one_cumulative_receipt(synthetic_peer):
    synthetic_peer("tool")
    provider = make_writing_provider({**payload(), "configured": True})
    observed = []
    tools = [
        {
            "name": "read_scene_text_window",
            "description": "Read scene",
            "input_schema": {"type": "object"},
        }
    ]
    with provider.observe_requests(observed.append):
        first = provider._call_llm("Return JSON", "synthetic", tools=tools)
        assert provider.usage_receipt_pending() is True
        assert [event["phase"] for event in observed] == ["started"]
        call = first.tool_calls[0]
        final = provider._call_llm(
            "Return JSON",
            "synthetic",
            tools=tools,
            tool_results=[
                {
                    "id": call.id,
                    "tool": call.name,
                    "status": "succeeded",
                    "output": {"text": "synthetic"},
                }
            ],
        )
    assert provider.usage_receipt_pending() is False
    assert [event["phase"] for event in observed] == ["started", "finished"]
    assert observed[0]["id"] == observed[1]["id"]
    assert final.usage.usage_status == "reported"
    assert final.usage.input_tokens == 100 and final.usage.cache_read_tokens == 60


def test_direction_gateway_keeps_schema_validation_and_usage(tmp_path, synthetic_peer):
    settings = DirectionModelSettings(tmp_path)
    candidate = settings.resolve_candidate(payload())
    gateway = DirectionModelGateway(settings, tmp_path)
    provider = gateway.provider(candidate)
    result = provider.complete_json(
        "Return JSON",
        "",
        "synthetic",
        {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
    )
    assert result == {"ok": True}
    assert provider.request_records[-1]["billing"] == "chatgpt_subscription"
    assert provider.stats["cache_read"] == 60


def test_bad_direction_output_fails_without_a_mock_success(tmp_path, synthetic_peer):
    from llm import StructuredOutputError

    synthetic_peer("malformed")
    provider = DirectionModelGateway(DirectionModelSettings(tmp_path), tmp_path).provider(payload())
    with pytest.raises(StructuredOutputError):
        provider.complete_json("Return JSON", "", "synthetic", {"type": "object"})


def test_failed_turn_preserves_actual_usage(tmp_path, synthetic_peer):
    synthetic_peer("failed")
    provider = DirectionModelGateway(DirectionModelSettings(tmp_path), tmp_path).provider(payload())
    with pytest.raises(ProductionError) as error:
        provider.complete_json("Return JSON", "", "synthetic", {"type": "object"})
    assert error.value.code == "codex_quota_exhausted"
    assert provider.stats["in"] == 100
    assert provider.request_records[-1]["status"] == "failed"
    assert provider.request_records[-1]["cache_read_tokens"] == 60


def test_subscription_activation_blocks_old_api_role_and_pinned_provider(
    tmp_path, monkeypatch, synthetic_peer
):
    monkeypatch.setenv("FIXTURE_API_KEY", "must-not-be-used")
    old_payload = {
        "provider": "openai",
        "model": "old-model",
        "base_url": "https://paid.example/v1",
        "api_key_env": "FIXTURE_API_KEY",
    }
    writing = WritingModelSettings(tmp_path / "writing")
    direction = DirectionModelSettings(tmp_path / "production")
    writing.save(old_payload)
    direction.save(old_payload)
    pinned = make_writing_provider(writing)
    old_direction_config = direction.provider_settings()[1]
    pinned_direction = DirectionModelGateway(direction, tmp_path).provider(old_direction_config)
    old_file = direction.path.read_bytes()
    writing.activate(payload())
    assert writing.public()["subscription_only"] is True
    assert direction.public()["model"]["configured"] is False
    assert direction.path.read_bytes() == old_file
    assert pinned.descriptor()["can_call_model"] is False
    with pytest.raises(DomainError, match="仅订阅"):
        pinned._call_llm("test", "test")
    with pytest.raises(ProductionError, match="仅订阅"):
        DirectionModelGateway(direction, tmp_path).provider(old_direction_config)
    with pytest.raises(ProductionError, match="仅订阅"):
        pinned_direction.complete_json("test", "", "test", {"type": "object"})
    with pytest.raises(DomainError, match="仅订阅"):
        writing.save(old_payload)
    with pytest.raises(ProductionError, match="仅订阅"):
        direction.save(old_payload)


def test_blocked_old_writing_profile_does_not_become_simulated_success(
    tmp_path, monkeypatch, synthetic_peer
):
    monkeypatch.setenv("FIXTURE_API_KEY", "must-not-be-used")
    writing = WritingModelSettings(tmp_path / "writing")
    writing.save(
        {
            "provider": "openai",
            "model": "old-model",
            "base_url": "https://paid.example/v1",
            "api_key_env": "FIXTURE_API_KEY",
        }
    )
    direction = DirectionModelSettings(tmp_path / "production")
    candidate = direction.resolve_candidate(payload())
    tested = DirectionModelGateway(direction, tmp_path).test_connection(candidate)
    direction.save(candidate, connection_test=tested)
    provider = make_writing_provider(writing)
    assert provider.is_simulation is False
    assert provider.descriptor()["can_call_model"] is False
    with pytest.raises(DomainError, match="仅订阅"):
        provider._call_llm("test", "test")


def test_connection_probe_rejects_malformed_json(synthetic_peer):
    synthetic_peer("malformed")
    with pytest.raises(codex.CodexError) as error:
        codex.test_connection(payload())
    assert error.value.code == "codex_output_invalid"


def test_http_status_and_login_do_not_return_tokens(runtime, monkeypatch):
    import urllib.request

    class Connection:
        def status(self):
            return {
                "schema_version": "codex-connection/1.0",
                "installed": True,
                "logged_in": False,
                "models": [],
                "state": "codex_login_required",
            }

        def login(self):
            return {"type": "chatgpt", "auth_url": "https://auth.openai.com/authorize?fixture=1"}

    monkeypatch.setattr("halocue_writing.app.codex_connection", lambda: Connection())
    with urllib.request.urlopen(
        f"http://127.0.0.1:{runtime.port}/api/v1/settings/codex"
    ) as response:
        assert json.load(response)["connection"]["state"] == "codex_login_required"
    request = urllib.request.Request(
        f"http://127.0.0.1:{runtime.port}/api/v1/settings/codex/login",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        assert json.load(response)["connection"]["type"] == "chatgpt"
