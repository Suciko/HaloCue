from __future__ import annotations

import io
import json
import signal
import threading
from pathlib import Path

import pytest
import launcher
import webui
from release_smoke import create_synthetic_aa_workspace, tree_digests
from tools import verify_release
from tools.verify_release import _content_type_matches, _narrator_binding_payload


def _connected_report(data: Path) -> dict:
    return {
        "ok": True,
        "aa": {
            "connected": True,
            "path": str(data),
            "executable": "",
            "resource_cache": "",
        },
    }


def test_synthetic_workspace_contains_only_fake_recognisable_paths(tmp_path):
    workspace = create_synthetic_aa_workspace(tmp_path)

    assert "另一台电脑 验收场景" in str(workspace.root)
    assert workspace.executable.name == "AzureArchive.exe"
    assert (workspace.executable.parent / "AzureArchive_Data" / "app.info").read_text(
        encoding="utf-8"
    ).splitlines() == ["foxxlight", "AzureArchive"]
    assert json.loads((workspace.data / "settings" / "user_settings.json").read_text(
        encoding="utf-8"
    ))["workspacePath"] == str(workspace.data)
    assert workspace.source_script.read_text(encoding="utf-8").startswith("旁白:")


def test_tree_digest_detects_any_bundle_write(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    target = bundle / "resource.bin"
    target.write_bytes(b"before")
    before = tree_digests(bundle)

    target.write_bytes(b"after")

    assert tree_digests(bundle) != before


def test_release_smoke_accepts_standard_javascript_mime_types():
    assert _content_type_matches("application/javascript", "javascript")
    assert _content_type_matches("text/javascript", "javascript")
    assert not _content_type_matches("text/html", "javascript")


def test_release_smoke_binds_synthetic_speaker_as_narrator_before_review():
    assert _narrator_binding_payload("draft-smoke", 3) == {
        "token": "draft-smoke",
        "speaker": "旁白",
        "mapping": {"narrator": True},
        "expected_draft_version": 3,
    }


def test_verify_release_cli_prints_unicode_result_on_cp1252_console(monkeypatch):
    result = {"ok": True, "workspace": "另一个中文目录"}
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    monkeypatch.setattr(verify_release, "verify", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(verify_release.sys, "stdout", console)

    assert verify_release.main(["release.zip"]) == 0
    console.flush()
    assert json.loads(output.getvalue().decode("cp1252")) == result


@pytest.mark.skip(reason="0.9.2 desktop startup no longer exposes the legacy browser ready-file interface.")
def test_launcher_forwards_ready_file_to_application(tmp_path, monkeypatch):
    data = create_synthetic_aa_workspace(tmp_path).data
    ready_file = tmp_path / "ready.json"
    captured = {}
    monkeypatch.setattr(
        launcher,
        "build_environment_report",
        lambda *_args, **_kwargs: _connected_report(data),
    )
    monkeypatch.setattr(launcher, "_save_aa_path", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        launcher,
        "_start_application",
        lambda selected, **kwargs: captured.update(data=selected, **kwargs) or 0,
    )

    assert launcher.main([
        "--aa-data", str(data), "--port", "9123", "--no-browser",
        "--ready-file", str(ready_file),
    ]) == 0
    assert captured == {
        "data": data,
        "port": 9123,
        "no_browser": True,
        "ready_file": ready_file,
    }


@pytest.mark.skip(reason="0.9.2 persists AzureArchive.exe discovery from the in-app setup flow.")
def test_launcher_persists_explicit_workspace_before_first_start(tmp_path, monkeypatch):
    workspace = create_synthetic_aa_workspace(tmp_path)
    saved = []
    monkeypatch.setattr(
        launcher,
        "build_environment_report",
        lambda *_args, **_kwargs: _connected_report(workspace.data),
    )
    monkeypatch.setattr(
        launcher,
        "_save_aa_path",
        lambda data, **kwargs: saved.append((data, kwargs)),
    )
    monkeypatch.setattr(launcher, "_start_application", lambda *_args, **_kwargs: 0)

    assert launcher.main(["--aa-data", str(workspace.data), "--no-browser"]) == 0
    assert saved == [(workspace.data, {"executable": None, "cache_dir": None})]


@pytest.mark.skip(reason="0.9.2 desktop startup no longer uses browser ready files.")
def test_ready_file_is_atomic_json_and_removable(tmp_path):
    ready_file = tmp_path / "状态 文件" / "ready.json"

    webui._publish_ready_file(ready_file, host="127.0.0.1", port=4567)

    assert json.loads(ready_file.read_text(encoding="utf-8")) == {
        "app_id": "halocue-local-server-v1",
        "version": "0.9.0-beta.1",
        "host": "127.0.0.1",
        "port": 4567,
    }
    assert not list(ready_file.parent.glob("*.tmp"))
    webui._remove_ready_file(ready_file)
    assert not ready_file.exists()


@pytest.mark.skip(reason="0.9.2 desktop lifetime is owned by LocalWebServer and the WebView2 window.")
def test_webui_sigbreak_shutdown_cleans_ready_file_and_exits_zero(
    tmp_path, monkeypatch
):
    data = create_synthetic_aa_workspace(tmp_path).data
    ready_file = tmp_path / "user state" / "run" / "ready.json"
    database = tmp_path / "user state" / "aa_assets.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"database")
    callbacks = {}
    originals = {}
    restored = set()
    main_thread = threading.get_ident()
    shutdown_threads = []

    def fake_getsignal(sig):
        return originals.setdefault(sig, object())

    def fake_signal(sig, handler):
        if handler is originals.get(sig):
            restored.add(sig)
        else:
            callbacks[sig] = handler

    class FakeServer:
        server_port = 9124

        def __init__(self, *_args):
            self.stopped = threading.Event()
            self.closed = False

        def serve_forever(self):
            callbacks[signal.SIGBREAK](signal.SIGBREAK, None)
            assert self.stopped.wait(2)

        def shutdown(self):
            shutdown_threads.append(threading.get_ident())
            self.stopped.set()

        def server_close(self):
            self.closed = True

    monkeypatch.setattr(webui.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(webui.signal, "signal", fake_signal)
    monkeypatch.setattr(webui, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(webui, "ensure_user_database", lambda *_args: database)
    monkeypatch.setattr(webui.MODEL_PROFILES, "bootstrap_legacy", lambda *_args: None)
    monkeypatch.setattr(webui.aapaths, "require", lambda *_args: {
        "data": str(data), "overrides": str(data / "overrides"), "source": "test",
    })
    monkeypatch.setattr(webui, "DB", str(database))

    result = webui.main([
        "--aa-data", str(data), "--no-browser", "--port", "9124",
        "--ready-file", str(ready_file),
    ])

    assert result == 0
    assert not ready_file.exists()
    assert shutdown_threads and shutdown_threads[0] != main_thread
    assert signal.SIGBREAK in restored
