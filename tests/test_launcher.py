import json
import subprocess
import sys
from pathlib import Path

import launcher


HERE = Path(__file__).resolve().parents[1]


def _make_aa_data(root: Path) -> Path:
    data = root / "data"
    for name in ("projects", "saves", "overrides", "settings"):
        (data / name).mkdir(parents=True, exist_ok=True)
    return data


def test_normalize_aa_data_accepts_data_directory_and_workspace_parent(
    tmp_path,
):
    data = _make_aa_data(tmp_path / "存储文件")

    assert launcher.normalize_aa_data_path(data) == data.resolve()
    assert (
        launcher.normalize_aa_data_path(data.parent)
        == data.resolve()
    )


def test_normalize_aa_data_rejects_unrelated_directory(tmp_path):
    unrelated = tmp_path / "普通文件夹"
    unrelated.mkdir()

    assert launcher.normalize_aa_data_path(unrelated) is None


def test_environment_report_explains_missing_program_files(tmp_path):
    data = _make_aa_data(tmp_path / "workspace")

    report = launcher.build_environment_report(
        tmp_path / "empty-program",
        explicit_aa_data=str(data),
    )

    assert report["ok"] is False
    assert report["aa"]["connected"] is True
    assert report["database"]["ready"] is False
    assert any(
        "webui.py" in issue for issue in report["blocking_issues"]
    )


def test_check_json_works_from_another_current_directory(tmp_path):
    data = _make_aa_data(tmp_path / "workspace")

    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "launcher.py"),
            "--check",
            "--json",
            "--aa-data",
            str(data),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["aa"]["path"] == str(data.resolve())
    assert payload["entry_file"] == "启动AA自动写剧本.cmd"

