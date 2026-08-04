import json
import subprocess
import sys
from pathlib import Path

import aapaths
import launcher
from aa_install_discovery import AADiscoveryResult, UnityIdentity


HERE = Path(__file__).resolve().parents[1]


def _make_aa_data(root: Path) -> Path:
    data = root / "data"
    for name in ("projects", "saves", "overrides", "settings"):
        (data / name).mkdir(parents=True, exist_ok=True)
    return data


def fake_discovery_result(root: Path) -> AADiscoveryResult:
    install_root = root / "AzureArchive"
    executable = install_root / "App" / "AzureArchive.exe"
    data = _make_aa_data(root / "workspace")
    cache = root / "resource-cache"
    cache.mkdir()
    catalog = (
        executable.parent
        / "AzureArchive_Data"
        / "StreamingAssets"
        / "aa"
        / "catalog.json"
    )
    return AADiscoveryResult(
        executable=executable,
        install_root=install_root,
        identity=UnityIdentity("foxxlight", "AzureArchive"),
        local_low_root=None,
        data=data,
        projects=data / "projects",
        saves=data / "saves",
        overrides=data / "overrides",
        settings=data / "settings",
        resource_cache=cache,
        catalog=catalog,
        recent_project_files=(),
        data_candidates=(),
        requires_selection=False,
        source="test",
        issues=(),
    )


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


def test_aapaths_legacy_dict_includes_new_resolved_fields(
    tmp_path,
    monkeypatch,
):
    result = fake_discovery_result(tmp_path)
    monkeypatch.setattr(
        aapaths,
        "discover_aa",
        lambda *args, **kwargs: result,
        raising=False,
    )

    paths = aapaths.detect(aa_install=str(result.executable))

    assert paths["data"] == str(result.data)
    assert paths["cache"] == str(result.resource_cache)
    assert paths["executable"] == str(result.executable)
    assert paths["catalog"] == str(result.catalog)
    assert paths["tried"] == []


def test_aapaths_save_config_merges_valid_json_and_replaces_invalid_json(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(aapaths, "HERE", str(tmp_path))
    config_path = tmp_path / aapaths.CONF_NAME
    config_path.write_text(
        json.dumps({"spine_cli": "spine", "aa_data": "old"}),
        encoding="utf-8",
    )

    aapaths.save_config(executable="new.exe", cache_dir="cache")

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "spine_cli": "spine",
        "aa_data": "old",
        "aa_executable": "new.exe",
        "aa_cache": "cache",
    }

    config_path.write_text("not json", encoding="utf-8")
    aapaths.save_config(data_dir="new-data")

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "aa_data": "new-data",
    }


def test_environment_report_accepts_aa_install(tmp_path, monkeypatch):
    result = fake_discovery_result(tmp_path)
    monkeypatch.setattr(
        launcher,
        "discover_aa",
        lambda *args, **kwargs: result,
        raising=False,
    )

    report = launcher.build_environment_report(
        HERE,
        explicit_aa_install=str(result.executable),
    )

    assert report["aa"]["connected"] is True
    assert report["aa"]["executable"] == str(result.executable)
    assert report["aa"]["resource_status"] == "installed"
    assert report["aa"]["projects"] == str(result.projects)
    assert report["aa"]["saves"] == str(result.saves)


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
