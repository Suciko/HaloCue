from __future__ import annotations

import json

import android_credentials


class FakeCredentialBackend:
    def __init__(self):
        self.values: dict[str, str] = {}

    def put(self, name: str, value: str) -> None:
        self.values[name] = value

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def has(self, name: str) -> bool:
        return name in self.values

    def masked(self, name: str) -> str | None:
        value = self.values.get(name)
        if value is None:
            return None
        return "\u2022" * 4 if len(value) <= 4 else "\u2022" * 4 + value[-4:]

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def setup_function():
    android_credentials.set_backend_for_tests(FakeCredentialBackend())


def teardown_function():
    android_credentials.set_backend_for_tests(None)


def test_secret_round_trip_status_and_delete():
    android_credentials.set_secret("anthropic_api_key", "sk-test-1234")

    assert android_credentials.get_secret("anthropic_api_key") == "sk-test-1234"
    assert android_credentials.secret_status("anthropic_api_key") == {
        "configured": True,
        "masked": "\u2022\u2022\u2022\u20221234",
    }
    assert "sk-test" not in json.dumps(
        android_credentials.secret_status("anthropic_api_key")
    )

    android_credentials.delete_secret("anthropic_api_key")
    assert android_credentials.get_secret("anthropic_api_key") is None
    assert android_credentials.secret_status("anthropic_api_key") == {
        "configured": False,
        "masked": None,
    }


def test_invalid_secret_names_are_rejected():
    for name in ("", "../key", "key with spaces", "key/slash"):
        try:
            android_credentials.set_secret(name, "value")
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid secret name accepted: {name!r}")


def test_short_secret_status_never_contains_the_plaintext():
    android_credentials.set_secret("short_key", "abc")

    status = android_credentials.secret_status("short_key")

    assert status == {"configured": True, "masked": "\u2022\u2022\u2022\u2022"}
    assert "abc" not in json.dumps(status)
