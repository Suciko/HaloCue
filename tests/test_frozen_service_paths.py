"""Frozen imports must not depend on a source checkout's directory depth."""

import importlib.util
from pathlib import Path
import sys

import pytest

from services.halocue import runtime_layout


def _load_at_frozen_location(service, filename):
    root = Path(__file__).resolve().parents[1]
    source = root / "services" / "halocue" / service / "src" / f"halocue_{service}" / filename
    spec = importlib.util.spec_from_file_location(f"halocue_{service}.{source.stem}", source)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(Path(root.anchor) / "HC" / "_internal" / f"halocue_{service}" / filename)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("service", ["production", "writing"])
def test_shared_model_adapter_import_at_shallow_frozen_path(service, tmp_path, monkeypatch):
    runtime_layout.enable_service_imports()
    bundled = tmp_path / "_internal"
    bundled.mkdir()
    root = Path(__file__).resolve().parents[1]
    (bundled / "model_capabilities.py").write_bytes((root / "model_capabilities.py").read_bytes())
    monkeypatch.setattr(sys, "_MEIPASS", str(bundled), raising=False)
    alias = "_halocue_shared_model_capabilities"
    previous = sys.modules.pop(alias, None)
    try:
        module = _load_at_frozen_location(service, "model_capabilities.py")
        assert Path(module._shared.__file__) == bundled / "model_capabilities.py"
        assert module.capabilities("portable-model", "openai")["model"] == "portable-model"
    finally:
        sys.modules.pop(alias, None)
        if previous is not None:
            sys.modules[alias] = previous


def test_catalog_lookup_at_shallow_frozen_path_uses_bundled_metadata(tmp_path, monkeypatch):
    runtime_layout.enable_service_imports()
    bundled = tmp_path / "_internal"
    database = bundled / "data" / "halocue_labels.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"metadata fixture")
    monkeypatch.setattr(sys, "_MEIPASS", str(bundled), raising=False)
    module = _load_at_frozen_location("writing", "resource_catalog.py")
    assert module._bundled_metadata_database() == database.resolve()


def test_frozen_resource_root_never_evaluates_source_parent_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(
        runtime_layout, "__file__", str(Path(Path.cwd().anchor) / "runtime_layout.py")
    )
    assert runtime_layout.repository_root() == tmp_path.resolve()


def test_source_resource_root_still_resolves_repository(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert runtime_layout.repository_root() == Path(__file__).resolve().parents[1]
