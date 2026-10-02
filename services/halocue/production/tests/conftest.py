from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.halocue._test_support import (  # noqa: E402,F401
    isolated_legacy_root,
    isolated_production_defaults,
)
from halocue_production.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path, isolated_legacy_root: Path) -> Settings:  # noqa: F811
    project_root = Path(__file__).resolve().parents[1]
    legacy_root = isolated_legacy_root
    value = Settings(
        project_root=project_root,
        data_dir=tmp_path / "data",
        legacy_root=legacy_root,
        resource_index=None,
        aa_data=None,
        host="127.0.0.1",
        port=0,
    )
    value.prepare()
    return value
