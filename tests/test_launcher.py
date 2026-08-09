import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import aapaths
import assetdb
import launcher
from aa_install_discovery import AADiscoveryResult, UnityIdentity


HERE = Path(__file__).resolve().parents[1]


class _JsonResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_existing_server_must_support_model_workbench(monkeypatch):
    def legacy_server(request_url, timeout):
        if request_url.endswith("/api/setup/status"):
            return _JsonResponse({"entry_file": launcher.ENTRY_FILE})
        raise urllib.error.HTTPError(request_url, 404, "not found", {}, None)

    monkeypatch.setattr(launcher.urllib.request, "urlopen", legacy_server)

    assert launcher.is_existing_server("http://127.0.0.1:8770") is False


def test_existing_server_must_identify_as_halocue(monkeypatch):
    def old_server(request_url, timeout):
        if request_url.endswith("/api/setup/status"):
            return _JsonResponse({"entry_file": launcher.ENTRY_FILE})
        raise AssertionError(request_url)

    monkeypatch.setattr(launcher.urllib.request, "urlopen", old_server)

    assert launcher.is_existing_server("http://127.0.0.1:8770") is False


def test_existing_server_accepts_current_model_workbench(monkeypatch):
    def current_server(request_url, timeout):
        if request_url.endswith("/api/setup/status"):
            return _JsonResponse({"app_id": "halocue-local-server-v1"})
        if request_url.endswith("/api/llm/workbench"):
            return _JsonResponse({"schema_version": 2})
        raise AssertionError(request_url)

    monkeypatch.setattr(launcher.urllib.request, "urlopen", current_server)

    assert launcher.is_existing_server("http://127.0.0.1:8770") is True


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


def test_environment_report_explains_missing_program_files(tmp_path, monkeypatch):
    from runtime_paths import resolve_runtime_layout

    data = _make_aa_data(tmp_path / "workspace")
    layout = resolve_runtime_layout(
        module_file=tmp_path / "empty-program" / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    monkeypatch.setattr(launcher, "RUNTIME_LAYOUT", layout)

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
):
    config_path = tmp_path / aapaths.CONF_NAME
    config_path.write_text(
        json.dumps({"spine_cli": "spine", "aa_data": "old"}),
        encoding="utf-8",
    )

    aapaths.save_config(
        executable="new.exe", cache_dir="cache", config_path=config_path
    )

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "spine_cli": "spine",
        "aa_data": "old",
        "aa_executable": "new.exe",
        "aa_cache": "cache",
    }

    config_path.write_text("not json", encoding="utf-8")
    aapaths.save_config(data_dir="new-data", config_path=config_path)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "aa_data": "new-data",
    }


def test_launcher_uses_user_config_before_read_only_legacy_config(
    tmp_path, monkeypatch
):
    from runtime_paths import resolve_runtime_layout

    layout = resolve_runtime_layout(
        module_file=tmp_path / "program" / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    captured = {}
    monkeypatch.setattr(launcher, "RUNTIME_LAYOUT", layout)
    monkeypatch.setattr(
        launcher,
        "discover_aa",
        lambda *args, **kwargs: captured.update(kwargs) or fake_discovery_result(tmp_path),
    )

    launcher._discover_aa(None, None)

    assert captured["config_path"] == layout.config_path
    assert captured["fallback_config_paths"] == (layout.legacy_config_path,)


def test_launcher_saves_only_to_user_config(tmp_path, monkeypatch):
    from runtime_paths import resolve_runtime_layout

    resource_root = tmp_path / "program"
    resource_root.mkdir()
    legacy = resource_root / "aa_config.json"
    legacy.write_text(json.dumps({"spine_cli": "legacy"}), encoding="utf-8")
    layout = resolve_runtime_layout(
        module_file=resource_root / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    data = _make_aa_data(tmp_path / "workspace")
    monkeypatch.setattr(launcher, "RUNTIME_LAYOUT", layout)

    launcher._save_aa_path(data)

    assert json.loads(layout.config_path.read_text(encoding="utf-8")) == {
        "spine_cli": "legacy",
        "aa_data": str(data),
    }
    assert json.loads(legacy.read_text(encoding="utf-8")) == {
        "spine_cli": "legacy"
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


def test_launcher_persists_all_paths_discovered_from_executable(
    tmp_path,
    monkeypatch,
):
    result = fake_discovery_result(tmp_path)
    disconnected = {
        "ok": False,
        "aa": {"connected": False, "path": ""},
    }
    connected = {
        "ok": True,
        "aa": {
            "connected": True,
            "path": str(result.data),
            "executable": str(result.executable),
            "resource_cache": str(result.resource_cache),
        },
    }
    reports = iter((disconnected, connected))
    saved = []
    monkeypatch.setattr(
        launcher,
        "build_environment_report",
        lambda *args, **kwargs: next(reports),
    )
    monkeypatch.setattr(
        launcher,
        "_choose_aa_install",
        lambda: result.executable,
    )
    monkeypatch.setattr(
        launcher,
        "_save_aa_path",
        lambda data, **kwargs: saved.append((data, kwargs)),
    )
    monkeypatch.setattr(launcher, "_start_application", lambda data: 0)

    assert launcher.main([]) == 0
    assert saved == [
        (
            result.data,
            {
                "executable": result.executable,
                "cache_dir": result.resource_cache,
            },
        )
    ]


def test_check_json_works_from_another_current_directory(tmp_path):
    data = _make_aa_data(tmp_path / "workspace")
    user_data = tmp_path / "halocue-state"
    assetdb.connect(user_data / "aa_assets.db").close()

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
        env={
            **os.environ,
            "HALOCUE_USER_DATA_DIR": str(user_data),
        },
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
