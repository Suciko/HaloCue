"""Bound characters must remain visible independently of picker pagination/search."""

from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

import test_direction_profile_ui as fixtures
from test_direction_profile_ui import ProductionApiFixture, run_reply
from test_scene_background_preview_ui import PNG

profile_browser = fixtures.profile_browser
ui_url = fixtures.ui_url


@pytest.mark.parametrize("width,height", [(1600, 900), (1280, 720)])
def test_bound_avatars_survive_first_page_limit_and_unrelated_search(
    profile_browser, ui_url, width, height
):
    result = run_reply(completed=True)
    mappings = {
        "Early": {"kind": "portrait", "id": "early", "name": "Early"},
        "Late": {"kind": "portrait", "id": "late", "name": "Late"},
        "Missing": {"kind": "portrait", "id": "missing", "name": "Missing"},
    }
    result["run"]["source_summary"]["speakers"] = list(mappings)
    result["draft"]["cast"]["cast"] = mappings
    api = ProductionApiFixture(result)
    resources = {
        identifier: {
            "identifier": identifier,
            "key": identifier,
            "name": mapping["name"],
            "preview_available": identifier != "missing",
            "face_count": 1,
            "faces": [{"id": "00"}],
            "spine": f"CharacterSpine_{identifier}",
        }
        for identifier, mapping in ((item["id"], item) for item in mappings.values())
    }
    errors = []

    def handle(route):
        parsed = urlsplit(route.request.url)
        if "/resources/characters/" in parsed.path:
            identifier = parsed.path.rsplit("/", 1)[-1]
            if identifier == "preview":
                route.fulfill(content_type="image/png", body=PNG)
            else:
                route.fulfill(json={"frozen": True, "character": resources[identifier]})
        elif parsed.path.endswith("/resources/characters"):
            query = parse_qs(parsed.query).get("q", [""])[0]
            # A real index exceeds the initial page; a picker search returns only its hits.
            rows = [resources["late"]] if query == "Late" else [resources["early"]]
            route.fulfill(json={"items": rows, "total": 300, "has_more": not query})
        else:
            api.handle(route)

    context = profile_browser.new_context(viewport={"width": width, "height": height})
    try:
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/v1/**", handle)
        page.add_init_script("localStorage.setItem('halocue.currentRunId', 'run-synthetic');")
        page.goto(ui_url, wait_until="networkidle")
        page.locator('.stage-list [data-stage="mapping"]').click()
        for speaker in ("Early", "Late"):
            row = page.locator("#mappingList .mapping-row").filter(has_text=speaker)
            expect(row.locator("img")).to_be_visible()
            expect(row).not_to_contain_text("头像暂不可用")
        expect(
            page.locator("#mappingList .mapping-row").filter(has_text="Missing")
        ).to_contain_text("头像暂不可用")
        page.locator('#mappingList [data-speaker="Late"]').click()
        page.locator("#characterSearch").fill("Late")
        expect(page.locator("#characterResults [data-character-id]")).to_have_count(1)
        page.locator('#mappingDialog [data-close-dialog="mappingDialog"]').click()
        page.locator('.stage-list [data-stage="generation"]').click()
        page.locator('.stage-list [data-stage="mapping"]').click()
        expect(page.locator("#mappingList img")).to_have_count(2)
        assert api.posts == []
        assert errors == []
    finally:
        context.close()
