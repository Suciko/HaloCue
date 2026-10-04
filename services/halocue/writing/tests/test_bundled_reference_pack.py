from __future__ import annotations

import gzip
import json
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer

import pytest

from halocue_writing.bundled_character_catalog import BundledCharacterCatalog
from halocue_writing.ba_character_card_import import parse_import_payload
from halocue_writing.official_reference_catalog import OfficialReferenceCatalog
from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from halocue_writing.app import make_handler


def test_all_bundled_cards_validate_and_can_be_selected_by_alias():
    catalog = BundledCharacterCatalog()
    paths = list(catalog.root.glob("*.json"))
    assert len(paths) == 102
    for path in paths:
        parsed = parse_import_payload(catalog.import_payload(path.stem))
        assert parsed.report["status"] == "PASS", path.name
    result = catalog.search("白子")
    assert any(item["name"] == "砂狼白子" for item in result["items"])
    assert all(item["source_kind"] == "maintainer_curated_reference" for item in result["items"])
    with pytest.raises(DomainError):
        catalog.import_payload("../../llm")


def test_compressed_corpus_search_and_get_preserve_reference_identity(tmp_path):
    record = {
        "record_uid": "official-1",
        "source_file": "ExcelDB/scenario.json",
        "speakers": ["白子"],
        "text": {"zh_cn": "一起出发吧。"},
        "script_events": [{"line_type": "camera"}],
    }
    with gzip.open(tmp_path / "scenario_0.jsonl.gz", "wt", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    catalog = OfficialReferenceCatalog(tmp_path)
    result = catalog.search("白子")
    assert result[0]["zh_cn"] == "一起出发吧。"
    assert result[0]["record_file"] == "scenario_0.jsonl.gz"
    fresh = OfficialReferenceCatalog(tmp_path)
    assert fresh.get("official-1")["evidence_uri"] == result[0]["evidence_uri"]


def test_manifest_records_the_complete_extraction():
    root = BundledCharacterCatalog().root.parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["character_card_count"] == 102
    assert manifest["corpus_source"]["record_counts"]["total"] == 368032
    assert (
        len([name for name in manifest["files"] if name.startswith("official-staging/records/")])
        == 3
    )
    assert all((root / name).is_file() for name in manifest["files"])


def test_reference_card_browser_import_requires_explicit_confirmation(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "随包资料验收"})
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch()
            page = browser.new_page()
            page.goto(
                f"http://127.0.0.1:{server.server_port}/?section=references&work_id={work['id']}&view=overview"
            )
            playwright.expect(page.locator(".library-reference-access")).to_contain_text("102")
            page.get_by_role("button", name="浏览随包人物参考", exact=True).click()
            playwright.expect(page.locator("[data-reference-character]")).to_have_count(18)
            assert service.get_work(work["id"])["version"] == work["version"]
            page.locator("#officialReferenceSearchForm input").fill("白子")
            page.locator("#officialReferenceSearchForm button").click()
            button = page.locator('[data-reference-character="砂狼白子"]')
            playwright.expect(button).to_be_visible(timeout=30000)
            button.click()
            playwright.expect(page.locator("#characterImportDialog")).to_be_visible()
            playwright.expect(page.locator('#characterImportForm [type="submit"]')).to_be_enabled()
            assert service.get_work(work["id"])["version"] == work["version"]
            page.locator('#characterImportForm [type="submit"]').click()
            playwright.expect(page.locator("#characterImportDialog")).not_to_be_visible()
            loaded = service.get_work(work["id"])
            cards = [item for item in loaded["artifacts"] if item["kind"] == "character_card"]
            assert len(cards) == 1
            assert loaded["version"] > work["version"]
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()
