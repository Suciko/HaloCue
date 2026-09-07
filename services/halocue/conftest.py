"""Service test defaults must never discover a maintainer's AA/catalog data."""

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# Compatibility modules remain shared code; data lookup uses a different root.
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


@pytest.fixture
def isolated_legacy_root(tmp_path):
    root = tmp_path / "isolated-legacy"
    root.mkdir(exist_ok=True)
    (root / "VERSION").write_text("1.0.0 synthetic fixture\n", encoding="utf-8")
    (root / "aa_resources.json").write_text(
        json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8"
    )
    return root


@pytest.fixture(autouse=True)
def isolated_production_defaults(request, monkeypatch, tmp_path, isolated_legacy_root):
    relative = Path(str(request.node.path)).relative_to(Path(__file__).parent)
    if relative.parts[0] not in {"production", "integrated"}:
        return
    monkeypatch.setenv("HALOCUE_LEGACY_ROOT", str(isolated_legacy_root))
    monkeypatch.setenv("HALOCUE_RESOURCE_INDEX", str(isolated_legacy_root / "aa_resources.json"))
    monkeypatch.setenv("HALOCUE_NAME_BASELINE", str(tmp_path / "absent-baseline.json"))
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path / "compat-user-data"))
    monkeypatch.delenv("HALOCUE_AA_DATA", raising=False)
