"""Review summaries and the actual install dialog stay legible in both themes."""

import json

import pytest


@pytest.mark.parametrize("size", [(1280, 720), (1600, 900)])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("installed", [False, True])
def test_review_and_install_surfaces_follow_theme(runtime, tmp_path, size, theme, installed):
    pw = pytest.importorskip("playwright.sync_api")
    service = runtime.production_service
    aa_data = tmp_path / "aa-data"
    for name in ("projects", "saves", "overrides", "settings"):
        (aa_data / name).mkdir(parents=True)
    service.configure_aa_workspace({"path": str(aa_data)})
    service.settings.resource_index.write_text(
        json.dumps(
            {"bg": {}, "characters": [], "sounds": [], "enums": {"emoticon": {}, "action": {}}}
        ),
        encoding="utf-8",
    )
    created = service.create_run(
        {
            "project": "Theme fixture",
            "source": {"kind": "inline", "text": "旁白: A synthetic scene."},
        }
    )
    run_id = created["run"]["run_id"]
    mapped = service.update_cast(
        run_id,
        {
            "speaker": "旁白",
            "mapping": {"kind": "narrator"},
            "expected_draft_version": created["draft"]["draft_version"],
        },
    )
    reviewed = service.approve_review(
        run_id, {"card_ids": None, "expected_draft_version": mapped["draft"]["draft_version"]}
    )
    token = reviewed["run"]["draft_token"]
    build_id = service.adapter.create_compile_snapshot(token, reviewed["draft"]["draft_version"])
    service.adapter.execute_compile(token, build_id)
    run = service._run(run_id)
    run.state = "compiled"
    run.last_build_id = build_id
    run.last_build_draft_version = reviewed["draft"]["draft_version"]
    service.repository.save_run(run)
    if installed:
        service.install(run_id, {"build_id": build_id, "story_name": "Renamed acceptance"})

    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": size[0], "height": size[1]})
            checks = []
            page.on(
                "request",
                lambda request: (
                    checks.append(request.url) if request.url.endswith("/install-check") else None
                ),
            )
            page.add_init_script(f"localStorage.setItem('halocue.ui.theme','{theme}')")
            page.goto(
                f"http://127.0.0.1:{runtime.port}/?section=production&run_id={run_id}",
                wait_until="networkidle",
            )
            page.locator('.stage-list [data-stage="review"]').click()
            page.get_by_role(
                "button", name="查看安装结果" if installed else "安装到 AA", exact=True
            ).click()
            pw.expect(page.locator("#installDialog")).to_be_visible()
            if installed:
                pw.expect(page.locator("#installProjectPreview")).to_have_text("Renamed acceptance")
                pw.expect(page.locator("#installAapPath")).to_have_text(
                    "projects/Renamed acceptance.aap"
                )
                pw.expect(page.locator(".install-name-grid")).to_be_hidden()
                pw.expect(page.locator("#installRun")).to_be_hidden()
                assert checks == []
            for selector in (
                ".install-build-summary",
                ".install-target-preview",
                ".proposal-summary",
            ):
                colors = page.locator(selector).first.evaluate("""el => {
                    const s=getComputedStyle(el);
                    return {background:s.backgroundColor, color:s.color};
                }""")
                if theme == "dark":
                    assert colors["background"] == "rgb(37, 45, 57)", (selector, colors)
                    assert colors["color"] in {"rgb(201, 212, 223)", "rgb(225, 231, 238)"}, (
                        selector,
                        colors,
                    )
                else:
                    assert colors["background"] in {"rgb(247, 249, 247)", "rgb(238, 246, 240)"}, (
                        selector,
                        colors,
                    )
            box = page.locator("#installDialog").bounding_box()
            assert box["y"] > 56 and box["y"] + box["height"] <= size[1] - 16, box
        finally:
            browser.close()
