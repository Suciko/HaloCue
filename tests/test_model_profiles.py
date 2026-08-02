import json

import pytest

from model_profiles import (
    ModelProfileError,
    ModelProfileStore,
    WindowsCredentialStore,
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


def test_session_secret_is_not_persisted_and_is_lost_after_restart(tmp_path):
    credentials = FakeCredentials()
    profiles_path = tmp_path / "llm_profiles.json"
    store = ModelProfileStore(profiles_path, credentials=credentials)
    profile = store.save_profile(
        {
            "name": "Session model",
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "vision-model",
            "api_key": "one-session-only",
            "save_key": False,
        }
    )

    assert profile["secret_status"] == "session"
    assert credentials.values == {}
    assert store.resolve_api_key(profile["id"]) == "one-session-only"
    assert (
        ModelProfileStore(
            profiles_path, credentials=credentials
        ).resolve_api_key(profile["id"])
        is None
    )


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
