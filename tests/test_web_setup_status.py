import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import assetdb
import spine_face_analysis
import webui
from aa_install_discovery import AADiscoveryResult, UnityIdentity
from runtime_paths import resolve_runtime_layout


class ActiveProfileStore:
    def active_profile(self):
        return {
            "id": "profile-1",
            "name": "日常标注模型",
            "model": "vision-model",
            "secret_status": "saved",
        }


class EmptyProfileStore:
    def public_state(self):
        return {"models": [], "connections": [], "assignments": {}}

    def active_profile(self):
        return None


def test_setup_status_reports_readiness_without_secret_fields(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        webui,
        "RUNTIME_LAYOUT",
        resolve_runtime_layout(
            module_file=tmp_path / "program" / "runtime_paths.py",
            environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
        ),
    )
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    database = tmp_path / "assets.db"
    assetdb.connect(database).close()
    monkeypatch.setitem(webui.CFG, "aa_data", str(data))
    monkeypatch.setattr(webui, "DB", str(database))
    monkeypatch.setattr(
        webui,
        "MODEL_PROFILES",
        ActiveProfileStore(),
    )

    status = webui.setup_status()

    assert status["aa"]["connected"] is True
    assert status["aa"]["path"] == str(data)
    assert status["aa"]["program"] == {"status": "missing", "path": ""}
    assert status["aa"]["projects"] == {
        "status": "ready",
        "path": str(data / "projects"),
    }
    assert status["aa"]["saves"] == {"status": "missing", "path": ""}
    assert status["aa"]["resource"] == {
        "status": "not_installed",
        "path": "",
    }
    assert status["aa"]["preview_index"] == {
        "status": "not_built",
        "backgrounds": 0,
        "avatars": 0,
        "failed": 0,
    }
    assert status["database"]["ready"] is True
    assert status["model"] == {
        "configured": True,
        "name": "日常标注模型",
        "model": "vision-model",
    }
    assert status["app_id"] == "halocue-local-server-v1"
    assert status["version"] == "0.9.0-beta.1"
    assert status["entry_file"] == "启动AA自动写剧本.cmd"
    serialized = json.dumps(status, ensure_ascii=False).lower()
    assert "api_key" not in serialized
    assert "secret_status" not in serialized


def test_setup_status_is_available_over_local_http(
    tmp_path,
    monkeypatch,
):
    data = tmp_path / "data"
    (data / "projects").mkdir(parents=True)
    database = tmp_path / "assets.db"
    assetdb.connect(database).close()
    monkeypatch.setitem(webui.CFG, "aa_data", str(data))
    monkeypatch.setattr(webui, "DB", str(database))
    monkeypatch.setattr(
        webui,
        "MODEL_PROFILES",
        ActiveProfileStore(),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/setup/status"
        ) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["aa"]["connected"] is True
        assert payload["model"]["configured"] is True
        assert payload["app_id"] == "halocue-local-server-v1"
        assert payload["version"] == "0.9.0-beta.1"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_state_api_treats_missing_legacy_llm_file_as_unconfigured(
    tmp_path,
    monkeypatch,
):
    data = tmp_path / "data"
    data.mkdir()
    database = tmp_path / "assets.db"
    assetdb.connect(database).close()
    monkeypatch.setitem(webui.CFG, "aa_data", str(data))
    monkeypatch.setattr(webui, "DB", str(database))
    monkeypatch.setattr(webui, "LLMCFG", str(tmp_path / "missing-llm.json"))
    monkeypatch.setattr(webui, "MODEL_PROFILES", EmptyProfileStore())
    server = ThreadingHTTPServer(("127.0.0.1", 0), webui.H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(
            f"http://127.0.0.1:{server.server_port}/api/state"
        ) as response:
            payload = json.loads(response.read())
        assert response.status == 200
        assert payload["provider"] == ""
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_setup_status_refreshes_from_saved_executable_after_restart(
    tmp_path,
    monkeypatch,
):
    program = tmp_path / "program"
    program.mkdir()
    executable = tmp_path / "AzureArchive" / "App" / "AzureArchive.exe"
    data = tmp_path / "storage" / "data"
    projects = data / "projects"
    projects.mkdir(parents=True)
    (program / "aa_config.json").write_text(
        json.dumps({
            "aa_executable": str(executable),
            "aa_data": str(data),
        }),
        encoding="utf-8",
    )
    layout = resolve_runtime_layout(
        module_file=program / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    layout.config_path.parent.mkdir(parents=True)
    layout.config_path.write_text(
        (program / "aa_config.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "RUNTIME_LAYOUT", layout)
    monkeypatch.setitem(webui.CFG, "aa_data", str(data))

    def discover(selection=None, **_kwargs):
        recognized = Path(selection) == executable
        return AADiscoveryResult(
            executable=executable if recognized else None,
            install_root=executable.parents[1] if recognized else None,
            identity=UnityIdentity("foxxlight", "AzureArchive") if recognized else None,
            local_low_root=None,
            data=data,
            projects=projects,
            saves=None,
            overrides=None,
            settings=None,
            resource_cache=None,
            catalog=None,
            recent_project_files=(),
            data_candidates=(),
            requires_selection=False,
            source="test",
            issues=(),
        )

    monkeypatch.setattr(webui, "discover_aa", discover)

    status = webui.setup_status()

    assert status["aa"]["program"] == {
        "status": "recognized",
        "path": str(executable),
    }


def test_settings_config_updates_preserve_the_other_runtime_path(tmp_path, monkeypatch):
    layout = resolve_runtime_layout(
        module_file=tmp_path / "program" / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    monkeypatch.setattr(webui, "RUNTIME_LAYOUT", layout)
    config = layout.config_path
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"aa_data": "old-data", "spine_cli": "old-spine"}), encoding="utf-8")

    webui._write_settings_config(aa_data="new-data")

    assert json.loads(config.read_text(encoding="utf-8")) == {
        "aa_data": "new-data",
        "spine_cli": "old-spine",
    }


def test_explicit_data_choice_clears_install_derived_paths(tmp_path, monkeypatch):
    layout = resolve_runtime_layout(
        module_file=tmp_path / "program" / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    monkeypatch.setattr(webui, "RUNTIME_LAYOUT", layout)
    config = layout.config_path
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps({
            "aa_data": "install-data",
            "aa_executable": "AzureArchive.exe",
            "aa_cache": "install-cache",
            "spine_cli": "saved-spine",
        }),
        encoding="utf-8",
    )

    webui._write_settings_config(
        aa_data="user-selected-data",
        aa_executable="",
        aa_cache="",
    )

    assert json.loads(config.read_text(encoding="utf-8")) == {
        "aa_data": "user-selected-data",
        "spine_cli": "saved-spine",
    }


def test_setup_status_and_spine_cli_discovery_ignore_non_object_config(
    tmp_path, monkeypatch
):
    layout = resolve_runtime_layout(
        module_file=tmp_path / "program" / "runtime_paths.py",
        environ={"HALOCUE_USER_DATA_DIR": str(tmp_path / "state")},
    )
    monkeypatch.setattr(webui, "RUNTIME_LAYOUT", layout)
    layout.config_path.parent.mkdir(parents=True)
    layout.config_path.write_text("[]", encoding="utf-8")
    resolved = spine_face_analysis.resolve_spine_cli(
        explicit=tmp_path / "missing-spine", config_path=layout.config_path
    )
    assert resolved is None or resolved.is_file()
    monkeypatch.setattr(webui.spine_face_analysis, "resolve_spine_cli", lambda *args, **kwargs: None)

    status = webui.setup_status()

    assert status["spine"] == {
        "configured": False,
        "path": "",
        "resolved_path": "",
    }
