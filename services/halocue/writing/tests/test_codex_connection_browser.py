"""Subscription login distinguishes a missing runtime from an unsigned-in account."""

import re

import pytest
from playwright.sync_api import expect

from test_authoring_workspace_browser import browser as browser, local_authoring as local_authoring


@pytest.mark.parametrize("size", [(1280, 720), (1600, 900)])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("installed", [False, True])
def test_codex_runtime_and_login_states_are_actionable(
    local_authoring, browser, tmp_path, size, theme, installed
):
    _, url = local_authoring
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    state = {
        "schema_version": "codex-connection/1.0",
        "installed": installed,
        "logged_in": False,
        "billing": "chatgpt_subscription",
        "models": [],
        "state": "codex_login_required" if installed else "not_installed",
    }
    calls, errors = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: (
            calls.append(request.url)
            if request.method == "POST" and "/settings/codex/login" in request.url
            else None
        ),
    )
    page.route(
        "**/api/v1/settings/codex",
        lambda route: route.fulfill(json={"ok": True, "connection": state}),
    )
    try:
        page.goto(url + "/?section=projects")
        page.locator("#openSettingsButton").click()
        page.get_by_role("tab", name="外观", exact=True).click()
        page.locator(f'[data-theme-choice="{theme}"]').click()
        page.get_by_role("tab", name="模型服务", exact=True).click()
        page.get_by_role("button", name=re.compile("^Codex 订阅")).click()
        panel = page.locator("#codexConnection")
        if installed:
            expect(panel.locator("[data-codex-status]")).to_contain_text(
                "请登录自己的 ChatGPT 账号"
            )
            expect(panel.get_by_role("button", name="登录 ChatGPT")).to_be_enabled()
            expect(panel.locator("[data-codex-install-link]")).to_be_hidden()
        else:
            expect(panel.locator("[data-codex-status]")).to_contain_text("重新完整解压新版 HaloCue")
            expect(panel.get_by_role("button", name="登录 ChatGPT")).to_be_disabled()
            expect(panel.get_by_role("link", name="查看官方安装说明")).to_be_visible()
            assert (
                panel.get_by_role("link", name="查看官方安装说明").get_attribute("href")
                == "https://developers.openai.com/codex/cli/"
            )
        expect(panel.get_by_role("button", name="测试并启用")).to_be_disabled()
        expect(panel.get_by_role("button", name="检查连接")).to_be_enabled()
        panel.locator("[data-codex-status]").scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        box = page.locator("#settingsDialog").bounding_box()
        assert box["y"] >= 16 and box["y"] + box["height"] <= size[1] - 16
        page.screenshot(path=str(tmp_path / f"codex-{installed}-{theme}-{size[0]}x{size[1]}.png"))
        assert not calls and not errors
    finally:
        page.close()
