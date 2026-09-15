import socket
import urllib.request
import urllib.error
import threading
import pytest

from integrated_desktop import run_integrated
from services.halocue.runtime_layout import integrated_data_root


def test_integrated_desktop_serves_both_workspaces_and_closes(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path))
    import runtime_layout

    monkeypatch.setattr(runtime_layout, "LAYOUT", runtime_layout.resolve_runtime_layout())

    class View:
        def create_window(self, title, url, **options):
            self.url = url
            with urllib.request.urlopen(url) as response:
                assert "integration-shell.js" in response.read().decode()
            for path, identity in (
                ("/api/v1/health", "halocue-writing"),
                ("/production/api/v1/health", "halocue-production"),
            ):
                with urllib.request.urlopen(url + path) as response:
                    assert identity in response.read().decode()

        def start(self, **options):
            assert options["gui"] == "edgechromium"

    view = View()
    assert run_integrated(port=0, webview_module=view) == 0
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", int(view.url.rsplit(":", 1)[1])))
    assert (tmp_path / "integrated" / "writing").is_dir()
    assert (tmp_path / "integrated" / "production").is_dir()


def test_explicit_state_contains_both_domains(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_USER_DATA_DIR", str(tmp_path))
    assert integrated_data_root() == tmp_path / "integrated"


def test_bundled_writing_rules_are_complete_without_developer_environment(monkeypatch):
    from services.halocue.runtime_layout import enable_service_imports

    enable_service_imports()
    from halocue_writing.ba_skill_runtime import BaWritingSkillRegistry

    monkeypatch.delenv("HALOCUE_BA_WRITING_SKILL_DIR", raising=False)
    registry = BaWritingSkillRegistry()
    for mode in ("main_battle", "long_comedy", "bond_short", "text_reading"):
        assert registry.compile(mode, has_sensei=True)["status"] == "ready"
    assert all((registry.root / path).is_file() for path in registry._pack_paths())


def test_launcher_default_and_compatibility_port(monkeypatch):
    import launcher
    import integrated_desktop
    import desktop_app
    import sys

    calls = []
    monkeypatch.setattr(
        integrated_desktop, "run_integrated", lambda **kwargs: calls.append(kwargs) or 0
    )
    launcher._start_application(None, port=12345)
    assert calls == [{"aa_data": None, "port": 12345, "no_browser": False, "ready_file": None}]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        desktop_app, "run_desktop", lambda *args, **kwargs: calls.append(kwargs) or 0
    )
    launcher._start_application(None, port=12346, legacy_ui=True)
    assert calls[-1]["port"] == 12346


def test_conversion_preflight_never_loads_a_provider(tmp_path, monkeypatch):
    import assetdb
    import webui

    database = tmp_path / "assets.db"
    assetdb.connect(database).close()
    monkeypatch.setattr(webui, "DB", str(database))

    def forbidden(*args):
        raise AssertionError("conversion must not load a provider")

    monkeypatch.setattr(webui, "annotation_provider", forbidden)
    script = tmp_path / "story.txt"
    script.write_text("旁白: 发布测试。", encoding="utf-8")
    result = webui.preflight_story_worker(
        {"script": str(script), "scope": str(tmp_path / "project")}
    )
    assert result


def test_headless_shutdown_requires_private_readiness_token(tmp_path):
    from services.halocue.runtime_layout import enable_service_imports

    enable_service_imports()
    from halocue_integrated.gateway import create_gateway

    server = create_gateway(
        "127.0.0.1",
        0,
        writing_address=("127.0.0.1", 1),
        production_address=("127.0.0.1", 1),
        static_dir=tmp_path,
    )
    server.shutdown_token = "synthetic-private-token"
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/integration/runtime/stop"
    try:
        for headers in ({}, {"X-HaloCue-Shutdown": "wrong"}):
            with pytest.raises(urllib.error.HTTPError) as failure:
                urllib.request.urlopen(urllib.request.Request(url, data=b"{}", headers=headers))
            assert failure.value.code == 403
            assert thread.is_alive()
        with urllib.request.urlopen(
            urllib.request.Request(
                url, data=b"{}", headers={"X-HaloCue-Shutdown": server.shutdown_token}
            )
        ) as response:
            assert response.status == 200
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
