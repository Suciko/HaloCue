"""Windows desktop shell for HaloCue's loopback web application."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

from webui import LocalWebServer, free_port, initialize_runtime


class DesktopAppError(RuntimeError):
    """A startup failure that can be shown directly to a desktop user."""


def _wait_until_ready(url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.05)
    raise DesktopAppError(
        "HaloCue 本地服务启动超时，请关闭其他 HaloCue 窗口后重试。"
    ) from last_error


def run_desktop(
    aa_data: str | None,
    *,
    overrides: str | None = None,
    spine_cli: str | None = None,
    port: int = 8770,
    webview_module=None,
) -> int:
    """Run one HaloCue window and own its local server for the window lifetime."""
    initialize_runtime(
        aa_data=aa_data,
        overrides=overrides,
        spine_cli=spine_cli,
    )
    server = LocalWebServer(port=free_port(port) if port else 0)
    try:
        url = server.start()
        _wait_until_ready(url)
        if webview_module is None:
            try:
                import webview as webview_module
            except Exception as exc:
                raise DesktopAppError(
                    "缺少桌面窗口组件，HaloCue 发布包可能不完整。"
                ) from exc
        webview_module.create_window(
            "HaloCue 0.95",
            url,
            width=1360,
            height=860,
            min_size=(960, 640),
            background_color="#f4f7fb",
        )
        try:
            webview_module.start(gui="edgechromium", debug=False)
        except Exception as exc:
            raise DesktopAppError(
                "无法启动 HaloCue 桌面窗口。请确认系统已安装 Microsoft Edge WebView2 Runtime。"
            ) from exc
        return 0
    finally:
        server.stop()
