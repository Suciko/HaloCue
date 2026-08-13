from __future__ import annotations

import importlib
from types import SimpleNamespace

import android_capabilities


def test_required_and_optional_runtime_modules_are_reported():
    report = android_capabilities.capability_report()

    assert report["pillow"]["available"] is True
    assert report["pillow"]["required"] is True
    assert report["anthropic"]["required"] is False
    assert report["opencc"]["required"] is False
    assert report["unitypy"]["required"] is False


def test_optional_import_failure_has_a_readable_reason(monkeypatch):
    def fail_import(name: str):
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", fail_import)

    report = android_capabilities.capability_report()

    assert report["opencc"]["available"] is False
    assert "不可用" in report["opencc"]["reason"]
    assert "opencc" in report["opencc"]["reason"].lower()


def test_missing_runtime_api_is_not_reported_as_available(monkeypatch):
    monkeypatch.setattr(importlib, "import_module", lambda _name: SimpleNamespace())

    report = android_capabilities.capability_report()

    assert report["anthropic"]["available"] is False
    assert "AttributeError" in report["anthropic"]["reason"]


def test_capability_reports_are_fresh_values():
    first = android_capabilities.capability_report()
    first["pillow"]["available"] = False

    assert android_capabilities.capability_report()["pillow"]["available"] is True
