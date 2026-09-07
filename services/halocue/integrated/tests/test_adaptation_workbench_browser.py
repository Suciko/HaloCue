"""Shipping-browser prose import through source/plan/job/adoption to frozen handoff."""

import json
import os
import sys
import threading
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[4]
for context in ("writing", "production", "integrated"):
    sys.path.insert(0, str(REPO / "services/halocue" / context / "src"))
from halocue_integrated.server import IntegratedRuntime  # noqa: E402
from halocue_writing.providers import FakeWritingProvider  # noqa: E402
from halocue_writing.workflow_pack import ENGINE_RULE_SOURCE, MODE_SOURCES, WORKFLOW_RULE_SOURCES  # noqa: E402


def prose_payload(suffix):
    if suffix == "txt":
        return "第一章 起点\n老师在门口停下，门里的灯亮着。".encode()
    import io
    import zipfile

    stream = io.BytesIO()
    document = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第一章 起点</w:t></w:r></w:p><w:p><w:r><w:t>老师在门口停下，门里的灯亮着。</w:t></w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", document)
    return stream.getvalue()


@pytest.mark.parametrize("suffix", ["txt", "docx"])
def test_shipping_prose_import_review_adoption_freeze_handoff(tmp_path, monkeypatch, suffix):
    pw = pytest.importorskip("playwright.sync_api")
    rules = tmp_path / "rules"
    paths = (
        [path for group in WORKFLOW_RULE_SOURCES.values() for path in group]
        + list(MODE_SOURCES.values())
        + [ENGINE_RULE_SOURCE, "knowledge/老师在场规则.md"]
    )
    for relative in paths:
        target = rules / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Synthetic rule only.\n", encoding="utf-8")
    monkeypatch.setenv("HALOCUE_BA_WRITING_SKILL_DIR", str(rules))
    index = tmp_path / "resources.json"
    index.write_text(json.dumps({"bg": {}, "sounds": [], "characters": []}), encoding="utf-8")
    runtime = IntegratedRuntime(
        host="127.0.0.1",
        port=0,
        writing_data_dir=tmp_path / "writing",
        production_data_dir=tmp_path / "production",
        resource_index=index,
    )
    runtime.start_upstreams()
    thread = threading.Thread(target=runtime.gateway.serve_forever, daemon=True)
    thread.start()
    writing = runtime.writing_service
    # Normal prerequisites are explicit fixture author decisions, not fabricated by import.
    work = writing.create_work({"title": "浏览器改编验收"})
    brief = writing.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "忠实改编门前片段",
            "mode": "bond_short",
            "characters": ["老师"],
        },
    )
    writing.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})

    class Provider(FakeWritingProvider):
        calls = 0

        def generate_scene(self, context):
            self.calls += 1
            chapter = context["chapter"]
            paragraph = chapter["paragraphs"][0]
            return json.dumps(
                {
                    "schema_version": "adaptation-chapter/1.0",
                    "text": "老师: 我们进去看看。\n旁白: 门前的灯亮着。\n",
                    "source_refs": [{"paragraph_id": paragraph["id"], "quote": paragraph["text"]}],
                    "deviations": [],
                    "open_threads": [],
                }
            )

    provider = Provider()
    writing.provider = provider
    try:
        with pw.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("localStorage.setItem('halocue:onboarding:interface-v2','done')")
            page.goto(f"http://127.0.0.1:{runtime.gateway.server_port}/?work_id={work['id']}")
            page.wait_for_load_state("networkidle")
            page.evaluate("async id=>{await loadWork(id)}", work["id"])
            import_control = page.locator("[data-open-import-dialog]").first
            import_control.locator("xpath=ancestor::details/summary").click()
            import_control.click()
            page.locator("[data-aap-file]").set_input_files(
                {
                    "name": "chapter." + suffix,
                    "mimeType": "text/plain"
                    if suffix == "txt"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "buffer": prose_payload(suffix),
                }
            )
            panel = page.locator("dialog.adaptation-workbench")
            panel.wait_for(state="visible")
            assert provider.calls == 0
            panel.get_by_role("button", name="预览原文变化", exact=True).click()
            panel.get_by_role("button", name="确认保存原文", exact=True).click()
            panel.get_by_role("button", name="建立改编计划", exact=True).click()
            assert provider.calls == 0
            panel.get_by_role("button", name="确认计划", exact=True).click()
            panel.get_by_role("button", name="生成模拟候选", exact=True).click()
            panel.get_by_role("button", name="采纳到此场景", exact=True).wait_for(timeout=15000)
            assert provider.calls == 1
            assert "新建场景" in panel.inner_text()
            assert "老师: 我们进去看看。" in panel.inner_text()
            screenshots = Path(
                os.environ.get("HALOCUE_UI_EVIDENCE_DIR", str(tmp_path / "screenshots"))
            )
            screenshots.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshots / "adaptation-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 375, "height": 850})
            page.screenshot(path=str(screenshots / "adaptation-mobile.png"), full_page=True)
            assert panel.evaluate("el=>el.scrollWidth<=el.clientWidth+1")
            page.set_viewport_size({"width": 320, "height": 700})
            assert panel.evaluate("el=>el.scrollWidth<=el.clientWidth+1")
            page.set_viewport_size({"width": 1440, "height": 1000})
            panel.get_by_role("button", name="关闭改编工作台", exact=True).click()
            page.reload()
            page.wait_for_load_state("networkidle")
            page.evaluate("async id=>{await loadWork(id)}", work["id"])
            import_control = page.locator("[data-open-import-dialog]").first
            import_control.locator("xpath=ancestor::details/summary").click()
            import_control.click()
            page.get_by_role("button", name="继续原文改编", exact=True).click()
            panel.get_by_role("button", name="采纳到此场景", exact=True).click()
            panel.get_by_role("button", name="查看正式场景", exact=True).wait_for(timeout=10000)
            assert provider.calls == 1
            panel.get_by_role("button", name="查看正式场景", exact=True).click()
            page.locator("#sceneManuscriptForm").wait_for(state="visible")
            assert page.evaluate("state.surface==='writing'&&state.stage==='draft'")
            assert not errors, errors
            browser.close()
        writing.agent_dispatcher.close()
        current = writing.get_work(work["id"])
        scene = current["chapters"][0]["scenes"][0]
        writing.provider = FakeWritingProvider()
        reviewed = writing.review_scene(
            work["id"], scene["id"], {"expected_version": current["version"]}
        )
        memory = writing.skip_scene_memory_maintenance(
            work["id"],
            scene["id"],
            {"expected_version": reviewed["work"]["version"], "note": "Synthetic explicit skip"},
        )
        continuity = writing.review_continuity(
            work["id"], {"expected_version": memory["work"]["version"]}
        )
        reviewed = writing.review_release(
            work["id"], {"expected_version": continuity["work"]["version"]}
        )
        frozen = writing.freeze_release(
            work["id"], {"expected_version": reviewed["work"]["version"]}
        )
        sent = writing.handoff_release(frozen["release_id"])
        run = runtime.production_service.repository.get_run(sent["production_run_id"])
        draft = runtime.production_service.adapter.store.load_draft(run.draft_token)
        assert "我们进去看看" in json.dumps(draft, ensure_ascii=False)
        assert run.source_summary["upstream_release"]["release_id"] == frozen["release_id"]
    finally:
        runtime.close()
        thread.join(3)


def test_first_work_prose_save_links_to_existing_direction_conversation(tmp_path):
    from http.server import ThreadingHTTPServer
    from halocue_writing.app import make_handler
    from halocue_writing.service import WritingService

    pw = pytest.importorskip("playwright.sync_api")
    writing = WritingService(tmp_path / "writing")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(writing, REPO / "services/halocue/writing/web")
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pw.sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True)
            page = browser.new_page()
            page.add_init_script("localStorage.setItem('halocue:onboarding:interface-v2','done')")
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.wait_for_load_state("networkidle")
            page.get_by_role("button", name="导入已有内容", exact=True).click()
            aap = {
                "ProjectName": "Synthetic AA",
                "nodes": {
                    "$values": [
                        {
                            "NodeName": "场景一",
                            "Scripts": {
                                "$values": [
                                    {
                                        "text": "开场旁白",
                                        "isDialogScript": False,
                                        "speakerSlotNum": 0,
                                        "characters": {"$values": [{}]},
                                    }
                                ]
                            },
                        }
                    ]
                },
            }
            page.locator("[data-aap-file]").set_input_files(
                {
                    "name": "sample.aap",
                    "mimeType": "application/json",
                    "buffer": json.dumps(aap).encode(),
                }
            )
            page.get_by_role("button", name="交给 Agent 转换", exact=True).wait_for(state="visible")
            assert page.locator("dialog.adaptation-workbench[open]").count() == 0
            page.locator("[data-aap-close]").first.click()
            page.get_by_role("button", name="导入已有内容", exact=True).click()
            page.locator("[data-aap-file]").set_input_files(
                {"name": "first.txt", "mimeType": "text/plain", "buffer": prose_payload("txt")}
            )
            panel = page.locator("dialog.adaptation-workbench")
            panel.get_by_role("button", name="预览原文变化", exact=True).click()
            panel.get_by_role("button", name="确认保存原文", exact=True).click()
            panel.get_by_role("button", name="建立改编计划", exact=True).wait_for()
            with writing.repo.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0] == 1
                assert c.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
            panel.get_by_role("button", name="完善写作方向与发布条件", exact=True).click()
            page.locator("#workConversationForm textarea").wait_for(state="visible")
            # The underlying textarea is visible as soon as the dialog closes;
            # navigation still awaits its work fetch. Wait for the actual prefill.
            import re
            pw.expect(page.locator("#workConversationForm textarea")).to_have_value(
                re.compile(".*不要续写未提供的内容.*"), timeout=5000
            )
            assert page.evaluate("state.stage==='overview'")
            with writing.repo.connect() as c:
                assert c.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        writing.close()
