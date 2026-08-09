import builtins

import pytest

import conftest


def _raise_from_playwright_import(monkeypatch, missing_name):
    real_import = builtins.__import__

    def import_with_missing_dependency(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ModuleNotFoundError(
                f"No module named {missing_name!r}", name=missing_name
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_with_missing_dependency)


def test_browser_fixture_skips_when_playwright_package_is_missing(monkeypatch):
    _raise_from_playwright_import(monkeypatch, "playwright")
    fixture = conftest.browser.__wrapped__()

    with pytest.raises(pytest.skip.Exception, match="pip install playwright"):
        next(fixture)


def test_browser_fixture_reraises_missing_transitive_dependency(monkeypatch):
    _raise_from_playwright_import(monkeypatch, "greenlet")
    fixture = conftest.browser.__wrapped__()

    with pytest.raises(BaseException) as caught:
        next(fixture)

    assert isinstance(caught.value, ModuleNotFoundError)
    assert caught.value.name == "greenlet"
