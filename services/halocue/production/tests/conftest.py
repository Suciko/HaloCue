from __future__ import annotations

import os
from pathlib import Path

import pytest

from halocue_production.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    repository_root = project_root.parents[2]
    legacy_root = Path(
        os.environ.get("HALOCUE_LEGACY_ROOT")
        or repository_root
    ).resolve()
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
