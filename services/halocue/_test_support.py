"""Service test defaults must never discover a maintainer's AA/catalog data."""

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHROMIUM_UNSAFE_PORTS = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53,
    69, 77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115,
    117, 119, 123, 135, 137, 139, 143, 161, 179, 389, 427, 465, 512,
    513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587,
    601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045,
    5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6697, 10080,
}
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
def isolated_production_defaults(request, monkeypatch, tmp_path):
    relative = Path(str(request.node.path)).relative_to(Path(__file__).parent)
    if relative.parts[0] not in {"production", "integrated"}:
        return
    isolated_legacy_root = request.getfixturevalue("isolated_legacy_root")
    monkeypatch.setenv("HALOCUE_LEGACY_ROOT", str(isolated_legacy_root))
    monkeypatch.setenv("HALOCUE_RESOURCE_INDEX", str(isolated_legacy_root / "aa_resources.json"))
    monkeypatch.setenv("HALOCUE_NAME_BASELINE", str(tmp_path / "absent-baseline.json"))
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path / "compat-user-data"))
    monkeypatch.delenv("HALOCUE_AA_DATA", raising=False)
