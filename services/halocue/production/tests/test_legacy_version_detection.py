from pathlib import Path

from halocue_production.legacy_adapter import Legacy093Adapter


def test_legacy_adapter_reports_the_selected_checkout_version(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'halocue'\nversion = '0.95'\n",
        encoding="utf-8",
    )
    assert Legacy093Adapter._detect_legacy_version(tmp_path) == "0.95"


def test_legacy_adapter_uses_unknown_when_checkout_has_no_marker(tmp_path: Path):
    assert Legacy093Adapter._detect_legacy_version(tmp_path) == "unknown"

