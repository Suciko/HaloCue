import pytest

from services.halocue import codex_proxy


def test_windows_static_proxy_and_bypass_are_child_only(monkeypatch):
    monkeypatch.setattr(
        codex_proxy,
        "windows_system_proxy",
        lambda: codex_proxy.parse_windows_proxy("127.0.0.1:7892", "<local>;*.example.test;10.*"),
    )
    parent = {"PATH": "synthetic-path"}
    child = dict(parent)
    codex_proxy.apply_child_proxy(child, windows=True)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        assert child[name] == child[name.lower()] == "http://127.0.0.1:7892"
    assert child["NO_PROXY"] == child["no_proxy"] == "localhost,127.0.0.1,::1,.example.test,10.*"
    assert parent == {"PATH": "synthetic-path"}


@pytest.mark.parametrize("name", ["HTTP_PROXY", "https_proxy", "ALL_PROXY"])
def test_explicit_proxy_prevents_system_fallback(name, monkeypatch):
    monkeypatch.setattr(
        codex_proxy, "windows_system_proxy", lambda: pytest.fail("Explicit proxy wins")
    )
    env = {name: "http://explicit.test:80", "no_proxy": "private.test"}
    codex_proxy.apply_child_proxy(env, windows=True)
    assert env[name] == "http://explicit.test:80"
    assert env["NO_PROXY"] == "private.test"


def test_explicit_no_proxy_including_empty_is_preserved(monkeypatch):
    monkeypatch.setattr(
        codex_proxy,
        "windows_system_proxy",
        lambda: codex_proxy.parse_windows_proxy("host:8080", "<local>"),
    )
    env = {"NO_PROXY": ""}
    codex_proxy.apply_child_proxy(env, windows=True)
    assert env["NO_PROXY"] == env["no_proxy"] == ""


def test_protocol_specific_proxy_and_non_windows(monkeypatch):
    assert codex_proxy.parse_windows_proxy("http=web:8080;https=secure:8081;socks=sock:1080") == {
        "HTTP_PROXY": "http://web:8080",
        "HTTPS_PROXY": "http://secure:8081",
        "ALL_PROXY": "socks5://sock:1080",
    }
    monkeypatch.setattr(codex_proxy, "windows_system_proxy", lambda: pytest.fail("Not Windows"))
    env = {}
    codex_proxy.apply_child_proxy(env, windows=False)
    assert env == {}
