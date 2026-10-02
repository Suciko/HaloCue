import json
import sys
import time
from pathlib import Path

import pytest

from services.halocue import codex_agent as codex


@pytest.fixture
def peer(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr(codex, "discover_cli", lambda explicit="": Path(sys.executable))
    fixture = Path(__file__).parent / "fixtures" / "codex_app_server.py"

    def start(scenario="completed"):
        monkeypatch.setattr(codex, "command", lambda cli: [str(cli), str(fixture), scenario])
        return codex.connection()

    yield start
    codex.connection().close()


def config(**kwargs):
    return {
        "provider": "codex",
        "model": "fixture-model",
        "timeout": 5,
        "subscription_only_acknowledged": True,
        **kwargs,
    }


def test_child_environment_does_not_inherit_api_keys_or_codex_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://paid.example")
    monkeypatch.setenv("CODEX_HOME", "private-home")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "private-token")
    env = codex.child_environment(tmp_path)
    assert env["CODEX_HOME"] == str(tmp_path)
    assert "OPENAI_API_KEY" not in env and "OPENAI_BASE_URL" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    args = codex.command(Path("codex"))
    assert 'forced_login_method="chatgpt"' in args
    assert "features.shell_tool=false" in args and "model_providers={}" in args


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key", "secret"),
        ("api_key_env", "OPENAI_API_KEY"),
        ("base_url", "https://paid.example"),
    ],
)
def test_codex_configuration_rejects_api_credentials(field, value):
    with pytest.raises(codex.CodexError, match="不接受"):
        codex.validate_config(config(**{field: value}))


def test_codex_configuration_requires_account_side_extra_usage_acknowledgement():
    with pytest.raises(codex.CodexError) as error:
        codex.validate_config(config(subscription_only_acknowledged=False))
    assert error.value.code == "codex_extra_usage_confirmation_required"


def test_status_is_redacted_and_models_are_discovered(peer):
    status = peer().status()
    assert status["account"] == {"type": "chatgpt", "plan_type": "plus"}
    assert status["models"][0]["id"] == "fixture-model"
    assert "private@example" not in json.dumps(status)
    assert "private-credit-balance" not in json.dumps(status)
    assert "accessToken" not in json.dumps(peer().login())


@pytest.mark.parametrize("scenario", ["completed", "api-auth", "logged-out", "quota"])
def test_connection_contract_round_trip(peer, scenario):
    import jsonschema

    schema_path = Path(__file__).parents[1] / "packages/contracts/codex-connection/1.0.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    status = peer(scenario).status()
    round_trip = json.loads(json.dumps(status))
    jsonschema.validate(round_trip, schema)
    assert round_trip == status
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**status, "accessToken": "synthetic-secret"}, schema)


def test_uninstalled_connection_contract(monkeypatch):
    import jsonschema

    monkeypatch.setattr(codex, "discover_cli", lambda explicit="": None)
    schema_path = Path(__file__).parents[1] / "packages/contracts/codex-connection/1.0.schema.json"
    jsonschema.validate(
        json.loads(json.dumps(codex.CodexConnection().status())),
        json.loads(schema_path.read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("api-auth", "codex_subscription_required"),
        ("logged-out", "codex_login_required"),
        ("quota", "codex_quota_exhausted"),
    ],
)
def test_non_subscription_and_exhausted_accounts_cannot_start_inference(peer, scenario, code):
    peer(scenario)
    with pytest.raises(codex.CodexError) as error:
        codex.CodexTurn(config(), "system", "user")
    assert error.value.code == code


def test_success_reports_actual_usage_and_stops_owned_process(peer):
    peer()
    turn = codex.CodexTurn(config(), "system", "user")
    result = turn.step()
    assert json.loads(result["text"]) == {"ok": True}
    assert result["usage"]["input_tokens"] == 100
    assert result["usage"]["cache_read_tokens"] == 60
    assert result["usage"]["estimated_cost"] is None
    assert turn.client.process.poll() is not None


def test_native_tool_is_paused_until_halo_cue_returns_matching_receipt(peer):
    peer("tool")
    turn = codex.CodexTurn(
        config(),
        "system",
        "user",
        tools=[
            {
                "name": "read_scene_text_window",
                "description": "Read scene",
                "input_schema": {"type": "object"},
            }
        ],
    )
    first = turn.step()
    assert first["tool"]["callId"] == "call-fixture"
    assert turn.client.process.poll() is None
    turn.resume_tool(
        [
            {
                "id": "call-fixture",
                "tool": "read_scene_text_window",
                "status": "succeeded",
                "output": {"text": "synthetic"},
            }
        ]
    )
    assert turn.step()["tool"] is None


def test_unregistered_native_tool_fails_closed(peer):
    peer("unauthorized-tool")
    turn = codex.CodexTurn(config(), "system", "user")
    with pytest.raises(codex.CodexError) as error:
        turn.step()
    assert error.value.code == "codex_tool_not_allowed"
    assert turn.client.process.poll() is not None


def test_failed_turn_is_not_a_success_or_paid_fallback(peer):
    peer("failed")
    turn = codex.CodexTurn(config(), "system", "user")
    with pytest.raises(codex.CodexError) as error:
        turn.step()
    assert error.value.code == "codex_quota_exhausted"


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancel_stop_the_owned_process(peer, cancel):
    peer("timeout")
    turn = codex.CodexTurn(config(), "system", "user")
    turn.deadline = time.monotonic() + 0.05
    with pytest.raises(codex.CodexError) as error:
        turn.step(cancelled=lambda: cancel)
    assert error.value.code == ("codex_cancelled" if cancel else "codex_timeout")
    assert turn.client.process.poll() is not None


def test_missing_usage_is_not_reported_as_zero_cost():
    result = codex.usage_receipt(None)
    assert result["usage_status"] == "not_reported"
    assert result["cache_status"] == "unknown" and result["estimated_cost"] is None
