from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_ROOT = REPO_ROOT / "apps" / "desktop-client" / "scene-preview"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        return


def _serve_preview():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(QuietHandler, directory=str(PREVIEW_ROOT)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_synthetic_descriptor_fixture_has_versioned_five_slot_shape():
    descriptor = json.loads(
        (PREVIEW_ROOT / "example.scene-descriptor.json").read_text(encoding="utf-8")
    )

    assert descriptor["schema_version"] == "scene-descriptor/1.0"
    assert descriptor["background"]["preview_uri"] == "./assets/demo-conference-room.png"
    assert not descriptor["background"]["preview_uri"].startswith("/")
    assert [actor["slot"] for actor in descriptor["actors"]] == [1, 2, 3, 4, 5]
    assert all(
        actor["resource_id"] is None or actor["resource_id"].startswith("synthetic/")
        for actor in descriptor["actors"]
    )


@pytest.mark.browser
def test_preview_renders_five_slots_advances_dialogue_and_switches_font(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    server, thread = _serve_preview()
    try:
        with playwright.sync_playwright() as runtime:
            try:
                browser = runtime.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depends on local browser install
                if "Executable doesn't exist" in str(exc):
                    pytest.skip("Playwright Chromium is not installed")
                raise
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
            page.wait_for_selector(".actor-slot")
            page.wait_for_selector("#preview-stage.has-background-image")

            assert page.locator(".actor-slot").count() == 5
            assert page.locator(".actor-slot.is-visible").count() == 5

            page.select_option("#font-select", "nowar")
            assert page.locator("#preview-stage").get_attribute("data-font") == "nowar"

            for _ in range(3):
                page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator("#speaker-name").inner_text() == "Alice"
            assert "欢迎来到 StoryForge" in page.locator("#dialogue-text").inner_text()
            assert page.locator('.actor-slot.is-active[data-slot="3"]').count() == 1

            for _ in range(2):
                page.locator("#preview-stage").click(position={"x": 640, "y": 160})
            assert page.locator("#speaker-name").inner_text() == "Bob"
            assert page.locator('.actor-slot.is-active[data-slot="4"]').count() == 1

            output_dir = REPO_ROOT / "acceptance-output"
            output_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(output_dir / "synthetic-ba-scene-preview.png"), full_page=True)
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
