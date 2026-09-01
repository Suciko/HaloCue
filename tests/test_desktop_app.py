import socket

from desktop_app import run_desktop


class RecordingWebView:
    def __init__(self):
        self.windows = []
        self.start_options = None

    def create_window(self, title, url, **options):
        self.windows.append((title, url, options))
        return object()

    def start(self, **options):
        self.start_options = options


def test_desktop_app_opens_the_local_ui_and_stops_its_server(tmp_path):
    aa_data = tmp_path / "含 空格的工作区" / "data"
    (aa_data / "projects").mkdir(parents=True)
    (aa_data / "saves").mkdir()
    (aa_data / "overrides").mkdir()
    view = RecordingWebView()

    assert run_desktop(str(aa_data), webview_module=view, port=0) == 0

    assert len(view.windows) == 1
    title, url, options = view.windows[0]
    assert title == "HaloCue 1.0.0"
    assert url.startswith("http://127.0.0.1:")
    assert options["min_size"] == (960, 640)
    assert view.start_options["gui"] == "edgechromium"

    port = int(url.rsplit(":", 1)[1])
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()


def test_desktop_app_can_open_before_aa_is_configured(monkeypatch):
    view = RecordingWebView()
    configured = []
    monkeypatch.setattr(
        "desktop_app.initialize_runtime",
        lambda **values: configured.append(values) or {},
    )

    assert run_desktop(None, webview_module=view, port=0) == 0

    assert configured[0]["aa_data"] is None
    assert len(view.windows) == 1
