from pathlib import Path

from migration import backup_legacy_state, import_legacy_state, migration_report


def test_migration_report_detects_known_legacy_files(tmp_path: Path):
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    legacy.mkdir()
    (legacy / "aa_config.json").write_text("{}", encoding="utf-8")
    report = migration_report(legacy, current)
    assert report["detected"] is True
    assert report["requires_confirmation"] is True
    assert report["files"][0]["name"] == "aa_config.json"


def test_backup_and_import_never_overwrite_current_files(tmp_path: Path):
    legacy = tmp_path / "legacy"
    current = tmp_path / "current"
    backup_parent = tmp_path / "backups"
    legacy.mkdir()
    current.mkdir()
    (legacy / "aa_config.json").write_text("legacy", encoding="utf-8")
    (legacy / "llm.json").write_text("secret-ref", encoding="utf-8")
    (current / "llm.json").write_text("current", encoding="utf-8")
    backup = backup_legacy_state(legacy, backup_parent)
    result = import_legacy_state(legacy, current)
    assert (backup / "aa_config.json").read_text(encoding="utf-8") == "legacy"
    assert (current / "aa_config.json").read_text(encoding="utf-8") == "legacy"
    assert (current / "llm.json").read_text(encoding="utf-8") == "current"
    assert result["skipped"] == ["llm.json"]
