import json

import pytest

from model_profiles import (
    ModelProfileError,
    ModelProfileStore,
    WindowsCredentialStore,
    MODEL_PRESETS,
)


class FakeCredentials:
    available = True

    def __init__(self):
        self.values = {}

    def read(self, target):
        return self.values.get(target)

    def write(self, target, secret):
        self.values[target] = secret

    def delete(self, target):
        self.values.pop(target, None)


class FakeWinCred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self):
        self.values = {}

    def CredWrite(self, record, _flags):
        if not isinstance(record["CredentialBlob"], str):
            raise TypeError("CredentialBlob must be Unicode")
        self.values[record["TargetName"]] = dict(record)

    def CredRead(self, target, credential_type, _flags):
        assert credential_type == self.CRED_TYPE_GENERIC
        if target not in self.values:
            raise KeyError(target)
        return self.values[target]

    def CredDelete(self, target, credential_type, _flags):
        assert credential_type == self.CRED_TYPE_GENERIC
        self.values.pop(target, None)


def test_windows_credentials_round_trip_without_returning_encoded_bytes():
    api = FakeWinCred()
    store = WindowsCredentialStore(win32cred_module=api)

    store.write("AA-AutoWriter/profile-1", "temporary-value")

    assert store.read("AA-AutoWriter/profile-1") == "temporary-value"
    assert isinstance(
        api.values["AA-AutoWriter/profile-1"]["CredentialBlob"], str
    )
    store.delete("AA-AutoWriter/profile-1")
    assert store.read("AA-AutoWriter/profile-1") is None


def test_saved_profile_keeps_secret_only_in_credential_store(tmp_path):
    credentials = FakeCredentials()
    profiles_path = tmp_path / "llm_profiles.json"
    store = ModelProfileStore(profiles_path, credentials=credentials)

    profile = store.save_profile(
        {
            "name": "Local Gemini",
            "provider": "openai",
            "base_url": "http://127.0.0.1:3000/v1",
            "model": "gemini-example",
            "max_tokens": 12000,
            "vision": True,
            "api_key": "temporary-value",
            "save_key": True,
        }
    )

    raw = profiles_path.read_text(encoding="utf-8")
    assert "temporary-value" not in raw
    assert "api_key" not in raw
    assert profile["secret_status"] == "saved"
    assert profile["credential_available"] is True
    assert credentials.values[f"AA-AutoWriter/{profile['id']}"] == "temporary-value"
    assert store.resolve_api_key(profile["id"]) == "temporary-value"

    reloaded = ModelProfileStore(profiles_path, credentials=credentials)
    assert reloaded.active_profile()["id"] == profile["id"]
    assert reloaded.resolve_api_key(profile["id"]) == "temporary-value"


def test_profile_persists_output_limit_provenance_and_legacy_is_not_manual(tmp_path):
    credentials = FakeCredentials()
    path = tmp_path / "profiles.json"
    store = ModelProfileStore(path, credentials=credentials)
    profile = store.save_profile({
        "name": "Verified model", "provider": "openai", "model": "deepseek-v4-flash",
        "max_tokens": 384000, "max_tokens_source": "api",
        "recommended_max_tokens": 384000, "recommended_source": "api",
        "recommended_label": "接口返回 · 384,000",
    })

    assert profile["max_tokens_source"] == "api"
    assert profile["recommended_max_tokens"] == 384000
    assert profile["recommended_source"] == "api"
    assert profile["recommended_label"] == "接口返回 · 384,000"

    default_label = store.save_profile({
        "name": "Unknown model", "provider": "openai", "model": "unknown-model",
    })
    assert default_label["recommended_label"] == "上限未识别"

    path.write_text(json.dumps({
        "version": 1, "active_profile_id": "legacy", "profiles": [{
            "id": "legacy", "name": "Old", "provider": "openai", "model": "old-model",
            "max_tokens": 16000,
        }],
    }), encoding="utf-8")
    legacy_store = ModelProfileStore(path, credentials=credentials)
    legacy = legacy_store.public_state()["profiles"][0]
    assert legacy["max_tokens_source"] == "legacy"
    assert legacy["recommended_max_tokens"] is None
    assert legacy["recommended_source"] == "unknown"
    assert legacy["recommended_label"] == "上限未识别"


def test_nonempty_secret_is_persisted_even_for_legacy_save_key_false(tmp_path):
    credentials = FakeCredentials()
    profiles_path = tmp_path / "llm_profiles.json"
    store = ModelProfileStore(profiles_path, credentials=credentials)
    profile = store.save_profile(
        {
            "name": "Persisted model",
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "vision-model",
            "api_key": "restart-safe",
            "save_key": False,
        }
    )

    assert profile["secret_status"] == "saved"
    assert store.resolve_api_key(profile["id"]) == "restart-safe"
    assert ModelProfileStore(
        profiles_path, credentials=credentials
    ).resolve_api_key(profile["id"]) == "restart-safe"


def test_blank_secret_preserves_saved_value_until_explicitly_cleared(tmp_path):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    profile = store.save_profile(
        {"name": "Endpoint", "provider": "openai", "model": "model-a", "api_key": "saved-value"}
    )

    updated = store.save_profile(
        {"id": profile["id"], "name": "Renamed", "provider": "openai", "model": "model-b", "api_key": ""}
    )
    assert updated["secret_status"] == "saved"
    assert store.resolve_api_key(profile["id"]) == "saved-value"

    cleared = store.save_profile(
        {"id": profile["id"], "name": "Renamed", "provider": "openai", "model": "model-b", "clear_secret": True}
    )
    assert cleared["secret_status"] == "missing"
    assert store.resolve_api_key(profile["id"]) is None


def test_public_profiles_are_redacted_and_can_be_activated_or_deleted(tmp_path):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    first = store.save_profile(
        {
            "name": "First",
            "provider": "openai",
            "model": "model-a",
            "api_key": "first-secret",
            "save_key": True,
        }
    )
    second = store.save_profile(
        {
            "name": "Second",
            "provider": "anthropic",
            "model": "model-b",
            "api_key": "second-secret",
            "save_key": True,
        }
    )

    state = store.public_state()
    assert state["active_profile_id"] == second["id"]
    assert all("api_key" not in row for row in state["profiles"])

    store.set_active(first["id"])
    assert store.active_profile()["id"] == first["id"]
    store.delete_profile(first["id"], delete_credential=True)
    assert f"AA-AutoWriter/{first['id']}" not in credentials.values
    assert store.active_profile()["id"] == second["id"]


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"name": "", "provider": "openai", "model": "x"}, "name"),
        ({"name": "x", "provider": "unknown", "model": "x"}, "provider"),
        ({"name": "x", "provider": "openai", "model": ""}, "model"),
        (
            {
                "name": "x",
                "provider": "openai",
                "model": "x",
                "max_tokens": 0,
            },
            "max_tokens",
        ),
    ],
)
def test_invalid_profiles_are_rejected_without_writing_state(
    tmp_path, payload, message
):
    path = tmp_path / "profiles.json"
    store = ModelProfileStore(path, credentials=FakeCredentials())

    with pytest.raises(ModelProfileError, match=message):
        store.save_profile(payload)

    assert not path.exists()


def test_legacy_llm_config_is_imported_once_without_secret_fields(tmp_path):
    legacy = tmp_path / "llm.json"
    legacy.write_text(
        json.dumps(
            {
                "provider": "openai",
                "openai": {
                    "model": "legacy-model",
                    "base_url": "https://legacy.invalid/v1",
                    "api_key_env": "LEGACY_KEY",
                    "max_tokens": 7000,
                },
            }
        ),
        encoding="utf-8",
    )
    profiles = tmp_path / "profiles.json"
    store = ModelProfileStore(profiles, credentials=FakeCredentials())

    first = store.bootstrap_legacy(legacy)
    second = store.bootstrap_legacy(legacy)

    assert first["id"] == second["id"]
    assert store.public_state()["profiles"] == [first]
    assert first["model"] == "legacy-model"
    assert first["base_url"] == "https://legacy.invalid/v1"
    raw = profiles.read_text(encoding="utf-8")
    assert "api_key_env" not in raw
    assert "LEGACY_KEY" not in raw


def test_profile_presets_cover_major_openai_compatible_services():
    assert {"deepseek", "glm", "qwen"} <= set(MODEL_PRESETS)
    assert MODEL_PRESETS["deepseek"]["provider"] == "openai"
    assert MODEL_PRESETS["deepseek"]["model"] == "deepseek-v4-flash"
    assert "/v1" in MODEL_PRESETS["qwen"]["base_url"]


def test_profile_can_be_saved_without_api_key_for_later_setup(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=FakeCredentials())

    profile = store.save_profile({
        "name": "Later",
        "provider": "openai",
        "service_preset": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "",
    })

    assert profile["secret_status"] == "missing"
    assert store.profile_record(profile["id"])["service_preset"] == "deepseek"
    with pytest.raises(ModelProfileError, match="API Key"):
        store.provider_settings(profile["id"])


def test_legacy_profiles_migrate_once_and_keep_saved_secret(tmp_path):
    credentials = FakeCredentials()
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "active_profile_id": "profile-1",
            "profiles": [{
                "id": "profile-1",
                "name": "DeepSeek",
                "provider": "openai",
                "service_preset": "deepseek",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "max_tokens": 16000,
                "vision": False,
            }],
        }),
        encoding="utf-8",
    )
    credentials.write("AA-AutoWriter/profile-1", "saved-secret")
    store = ModelProfileStore(path, credentials=credentials)

    first = store.migrate_legacy_profiles()
    second = store.migrate_legacy_profiles()

    assert first == second
    assert first["schema_version"] == 2
    assert len(first["connections"]) == len(first["models"]) == 1
    assert first["assignments"]["base_model_id"] == first["models"][0]["id"]
    connection_id = first["connections"][0]["id"]
    assert store.resolve_connection_key(connection_id) == "saved-secret"
    assert "saved-secret" not in path.read_text(encoding="utf-8")


def test_v2_store_saves_multiple_models_for_one_connection(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=FakeCredentials())
    connection = store.save_connection({
        "name": "千问",
        "service_preset": "qwen",
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "secret",
    })
    text_model = store.save_model({
        "connection_id": connection["id"],
        "model": "qwen-max",
        "max_tokens": 16000,
        "text_status": "passed",
        "vision_status": "unsupported",
        "reasoning_mode": "speed",
        "annotation_max_tokens": 12000,
    })
    vision_model = store.save_model({
        "connection_id": connection["id"],
        "model": "qwen-vl-plus",
        "max_tokens": 8000,
        "text_status": "untested",
        "vision_status": "passed",
    })

    state = store.public_state()

    assert {row["id"] for row in state["models"]} == {
        text_model["id"], vision_model["id"],
    }
    assert text_model["recommended_label"] == "上限未识别"
    assert text_model["reasoning_mode"] == "speed"
    assert text_model["annotation_max_tokens"] == 12000
    assert all(row["connection_id"] == connection["id"] for row in state["models"])
    serialized = json.dumps(state)
    assert '"api_key": "secret"' not in serialized
    assert all("api_key" not in row for row in state["connections"])


def test_provider_settings_include_reasoning_mode_and_task_budget(tmp_path):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    connection = store.save_connection({
        "name": "DeepSeek", "service_preset": "deepseek", "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1", "api_key": "secret",
    })
    model = store.save_model({
        "connection_id": connection["id"], "model": "deepseek-v4-flash",
        "max_tokens": 384000, "annotation_max_tokens": 16000,
        "reasoning_mode": "balanced", "text_status": "passed", "vision_status": "unsupported",
    })
    provider, settings = store.provider_settings_for_model(model["id"])
    assert provider == "openai"
    assert settings["reasoning_mode"] == "balanced"
    assert settings["annotation_max_tokens"] == 16000
    assert settings["reasoning_wire_protocol"] == "deepseek_thinking"
    assert settings["source_context_strategy"] == "preserve"


def test_provider_settings_use_window_context_for_ollama(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=FakeCredentials())
    connection = store.save_connection({
        "name": "Ollama", "service_preset": "ollama", "protocol": "openai",
        "base_url": "http://localhost:11434/v1", "api_key": "local-test-key",
    })
    model = store.save_model({
        "connection_id": connection["id"], "model": "llama3.2",
        "text_status": "passed", "vision_status": "unsupported",
    })

    _provider, settings = store.provider_settings_for_model(model["id"])

    assert settings["source_context_strategy"] == "window"


def test_v2_assignments_require_compatible_tested_models(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=FakeCredentials())
    connection = store.save_connection({
        "name": "Models", "service_preset": "custom", "protocol": "openai",
        "base_url": "https://example.invalid/v1",
    })
    base = store.save_model({
        "connection_id": connection["id"], "model": "text-only",
        "text_status": "passed", "vision_status": "untested",
    })

    with pytest.raises(ModelProfileError, match="图片测试"):
        store.set_assignments({
            "base_model_id": base["id"], "vision_mode": "base",
        })

    saved = store.set_assignments({
        "base_model_id": base["id"], "vision_mode": "disabled",
    })
    assert saved == {
        "base_model_id": base["id"],
        "vision_mode": "disabled",
        "vision_model_id": "",
    }


def test_v2_referenced_models_and_connections_cannot_be_deleted(tmp_path):
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=FakeCredentials())
    connection = store.save_connection({
        "name": "DeepSeek", "service_preset": "deepseek", "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1",
    })
    model = store.save_model({
        "connection_id": connection["id"], "model": "deepseek-chat",
        "text_status": "passed", "vision_status": "unsupported",
    })
    store.set_assignments({
        "base_model_id": model["id"], "vision_mode": "disabled",
    })

    with pytest.raises(ModelProfileError, match="仍被使用"):
        store.delete_model(model["id"])
    with pytest.raises(ModelProfileError, match="仍有模型"):
        store.delete_connection(connection["id"])


def test_delete_unassigned_model_keeps_nonempty_connection_and_key(tmp_path):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    connection = store.save_connection({
        "name": "Shared", "service_preset": "deepseek", "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1", "api_key": "secret",
    })
    base = store.save_model({
        "connection_id": connection["id"], "model": "deepseek-v4-flash",
        "text_status": "passed", "vision_status": "unsupported",
    })
    spare = store.save_model({
        "connection_id": connection["id"], "model": "deepseek-v4-pro",
        "text_status": "untested", "vision_status": "unsupported",
    })
    store.set_assignments({
        "base_model_id": base["id"], "vision_mode": "disabled",
    })

    result = store.delete_model(spare["id"], delete_empty_connection=True)
    state = store.public_state(include_links=True)

    assert result["deleted_connection"] is False
    assert [row["id"] for row in state["models"]] == [base["id"]]
    assert state["connections"][0]["id"] == connection["id"]
    assert store.resolve_connection_key(connection["id"]) == "secret"


def test_delete_last_unassigned_model_can_remove_connection_and_key(tmp_path):
    credentials = FakeCredentials()
    store = ModelProfileStore(tmp_path / "profiles.json", credentials=credentials)
    base_connection = store.save_connection({
        "name": "Base", "service_preset": "deepseek", "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1", "api_key": "base-secret",
    })
    base = store.save_model({
        "connection_id": base_connection["id"], "model": "deepseek-v4-flash",
        "text_status": "passed", "vision_status": "unsupported",
    })
    spare_connection = store.save_connection({
        "name": "Spare", "service_preset": "qwen", "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "spare-secret",
    })
    spare = store.save_model({
        "connection_id": spare_connection["id"], "model": "qwen-vl-max",
    })
    store.set_assignments({
        "base_model_id": base["id"], "vision_mode": "disabled",
    })

    result = store.delete_model(spare["id"], delete_empty_connection=True)
    state = store.public_state(include_links=True)

    assert result == {
        "ok": True,
        "model_id": spare["id"],
        "deleted_connection": True,
        "connection_id": spare_connection["id"],
    }
    assert {row["id"] for row in state["connections"]} == {base_connection["id"]}
    assert store.resolve_connection_key(spare_connection["id"]) is None
