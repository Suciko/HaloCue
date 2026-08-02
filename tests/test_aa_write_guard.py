# -*- coding: utf-8 -*-
from PIL import Image
import pytest

from aa_project_assets import assert_aa_closed, resolve_project_target
from aa_registry import AssetRegistrationError, register_background
from asset_validation import validate_background


def test_assert_aa_closed_reports_machine_readable_running_code():
    with pytest.raises(AssetRegistrationError, match="aa_running"):
        assert_aa_closed(running_probe=lambda: True)


def test_running_guard_creates_no_target_directory_or_manifest(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "black").save(source)
    target = resolve_project_target(tmp_path / "data" / "projects" / "Demo")

    with pytest.raises(AssetRegistrationError, match="aa_running"):
        register_background(validate_background(source), target, running_probe=lambda: True)

    assert not target.project_dir.exists()
    assert not target.save_dir.exists()
