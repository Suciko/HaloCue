"""Runtime-path presentation in real DOM; extracted shipping JS, synthetic IO only."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        if Path(p.chromium.executable_path).exists():
            instance = p.chromium.launch(headless=True)
        elif Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe").exists():
            instance = p.chromium.launch(channel="msedge", headless=True)
        else:
            pytest.skip("Local Chromium or Edge required")
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    page.set_content("""<div id="spineCliStatus"></div><div id="spineCliCapability"></div>
      <input id="spineCliPath"><button id="saveSpineCli"></button><button id="clearSpineCli"></button>
      <div id="aaEnvironmentStatus"></div><input id="aaSelection"><button id="adoptAaEnvironment"></button>
      <div id="aaEnvironmentCard"></div><input id="aaWorkspaceInput"><button id="adoptAaBtn"></button>
      <button id="inspectAaBtn"></button><button id="unrelated">Other control</button>""")
    production = (ROOT / "services/halocue/production/ui/app.js").read_text(encoding="utf-8")
    writing = (ROOT / "services/halocue/writing/web/app.js").read_text(encoding="utf-8")
    # Extract complete settings blocks and the shipping escaping helper, not reimplementations.
    esc_start = production.index("  const esc =")
    spine_start = production.index("  function renderSpineCliSettings(")
    aa_start = production.index("  function renderAaEnvironment(")
    controller_start = writing.index("const SettingsController =")
    page.add_script_tag(
        content="""
      const $ = selector => document.querySelector(selector);
      const state = {}; const calls = []; const toasts = [];
      let reply = {}; let refreshes = 0;
      let api = async (route, options) => { calls.push({route, body: options?.body ? JSON.parse(options.body) : null}); return reply; };
      const fetch = async (route, options) => ({ok: true, json: async () => await api(route, options)});
      const refreshCapabilities = async () => {refreshes++;};
      const toast = (message, tone) => toasts.push({message, tone});
      const handleError = error => toast(error.message, 'error');
    """
        + production[esc_start : production.index("  const text =", esc_start)]
        + production[spine_start : production.index("  function showSettingsPane(", spine_start)]
        + production[aa_start : production.index("  async function saveModel(", aa_start)]
        + writing[controller_start : writing.index("\n};", controller_start) + 3]
    )
    yield page
    page.close()


def spine(*, valid=True, source="settings", path="C:/synthetic/Spine.com", saved=None):
    return {
        "spine_cli": {
            "configured": valid,
            "valid": valid,
            "source": source,
            "path": path,
            "effective_path": path if valid else None,
            "persisted_path": saved
            if saved is not None
            else path
            if source == "settings"
            else None,
            "reason": None if valid else "saved_spine_cli_unavailable",
        },
        "capability": {"state": "available" if valid else "unavailable"},
    }


def aa(*, override=False, valid=True):
    current = 'C:/synthetic/B<&"工作区'
    startup = "C:/synthetic/A<img src=x onerror=alert(1)>" if override else None
    return {
        "configured": True,
        "valid": valid,
        "path": current,
        "source": "settings_session_override" if override else "settings",
        "persisted_path": current,
        "startup_path": startup,
        "restart_path": startup or current,
        "session_override": override,
        "startup_overrides_saved": override,
    }


def environment(workspace, *, adopted=True):
    return {
        "adopted": adopted,
        "aa_workspace": workspace,
        "environment": {
            "workspace": {
                "valid": True,
                "path": workspace["path"],
                "directories": {"projects": True, "saves": True},
            },
            "resource_cache": {},
            "issues": [],
        },
    }


def test_invalid_saved_spine_is_visible_and_cannot_claim_capability(page):
    result = spine(valid=False, path="C:/missing/<img src=x onerror=alert(1)>")
    # Even a stale capability must not override the authoritative invalid selection.
    result["capability"]["state"] = "available"
    page.evaluate("result => renderSpineCliSettings(result)", result)
    status = page.locator("#spineCliStatus")
    assert "配置路径不可用" in status.inner_text()
    assert result["spine_cli"]["path"] in status.inner_text()
    assert "未回退" in status.inner_text()
    assert "settings" in status.inner_text()
    assert "当前生效路径：无" in status.inner_text()
    assert "没有可用" in page.locator("#spineCliCapability").inner_text()
    assert status.locator("img").count() == 0
    assert page.locator("#spineCliPath").input_value() == result["spine_cli"]["path"]
    assert page.locator("#unrelated").is_enabled()


@pytest.mark.parametrize(
    "source", ["settings", "environment", "legacy_config", "data_config", "discovered"]
)
def test_valid_spine_reports_effective_path_source_and_retains_opt_in(page, source):
    result = spine(source=source)
    page.evaluate("result => renderSpineCliSettings(result)", result)
    text = page.locator("#spineCliStatus").inner_text()
    assert "Spine 预览已启用" in text
    assert "可以选择" in text
    assert "当前生效路径：" + result["spine_cli"]["effective_path"] in text
    assert source in text


def test_clear_spine_reports_environment_fallback_instead_of_disabled(page):
    result = spine(source="environment", path="C:/environment/Spine.com")
    page.evaluate(
        "async result => { reply = result; $('#spineCliPath').value = 'C:/old'; await clearSpineCli(); }",
        result,
    )
    assert page.locator("#spineCliPath").input_value() == result["spine_cli"]["path"]
    assert "environment" in page.locator("#spineCliStatus").inner_text()
    toast = page.evaluate("toasts.at(-1).message")
    assert "关闭" not in toast
    assert "environment" in toast
    assert result["spine_cli"]["path"] in toast
    assert page.evaluate("calls") == [{"route": "/settings/spine-cli", "body": {"clear": True}}]
    assert page.locator("#clearSpineCli").is_enabled()


def test_clear_spine_without_fallback_clears_stale_input(page):
    result = spine(valid=False, source="none", path=None)
    result["spine_cli"]["reason"] = "spine_cli_not_configured"
    page.evaluate(
        "async result => { reply = result; $('#spineCliPath').value = 'old'; await clearSpineCli(); }",
        result,
    )
    assert page.locator("#spineCliPath").input_value() == ""
    assert "未启用 Spine 预览" in page.locator("#spineCliStatus").inner_text()


def test_invalid_spine_save_does_not_toast_success(page):
    page.evaluate(
        "async result => { reply = result; $('#spineCliPath').value = 'missing'; await saveSpineCli(); }",
        spine(valid=False),
    )
    toast = page.evaluate("toasts.at(-1).message")
    assert "不可用" in toast
    assert "设置已保存" not in toast
    assert page.evaluate("toasts.at(-1).tone") == "error"
    assert page.locator("#saveSpineCli").is_enabled()


@pytest.mark.parametrize("override", [False, True])
@pytest.mark.parametrize("surface", ["production", "writing"])
def test_aa_adoption_discloses_current_saved_source_restart_and_escapes(page, override, surface):
    workspace = aa(override=override)
    if surface == "production":
        page.evaluate(
            "async result => { reply = result; await inspectAaEnvironment(true); }",
            environment(workspace),
        )
        card = page.locator("#aaEnvironmentStatus")
        button = page.locator("#adoptAaEnvironment")
    else:
        page.evaluate(
            """async workspace => {
          reply = {ok: true, aa_workspace: workspace};
          $('#aaWorkspaceInput').value = workspace.path;
          SettingsController.aaInspectionRevision = 1;
          SettingsController.aaInspection = {selection: workspace.path, path: workspace.path, revision: 1};
          await SettingsController.adoptAa();
        }""",
            workspace,
        )
        card = page.locator("#aaEnvironmentCard")
        button = page.locator("#adoptAaBtn")
    text = card.inner_text()
    assert "当前生效路径：" + workspace["path"] in text
    assert "已保存路径：" + workspace["persisted_path"] in text
    assert workspace["source"] in text
    assert "重启后路径：" + workspace["restart_path"] in text
    assert card.locator("img").count() == 0
    assert "已采用" in button.inner_text()
    assert page.locator("#unrelated").is_enabled()
    assert len(page.evaluate("calls")) == 1
    if override:
        assert "仅本次会话" in text
        assert "启动配置优先" in text
        assert "重启" in page.evaluate("toasts.at(-1).message")
        assert workspace["restart_path"] in page.evaluate("toasts.at(-1).message")
    else:
        assert "仅本次会话" not in text
        assert "采用" in page.evaluate("toasts.at(-1).message")


def test_production_aa_detection_does_not_claim_detected_path_is_active(page):
    workspace = aa(override=True)
    workspace.update(path=workspace["startup_path"], source="startup", session_override=False)
    result = environment(workspace, adopted=False)
    result["environment"]["workspace"]["path"] = "C:/detected/not-adopted"
    page.evaluate("result => renderAaEnvironment(result)", result)
    text = page.locator("#aaEnvironmentStatus").inner_text()
    assert "当前生效路径：" + workspace["path"] in text
    assert "C:/detected/not-adopted" in text
    assert "启动配置优先" in text
    assert "已保存路径：" + workspace["persisted_path"] in text
    assert page.locator("#adoptAaEnvironment").is_enabled()


def test_invalid_aa_adoption_does_not_claim_success(page):
    page.evaluate(
        "async result => { reply = result; await inspectAaEnvironment(true); }",
        environment(aa(valid=False)),
    )
    assert "已采用" not in page.locator("#adoptAaEnvironment").inner_text()
    assert "不可用" in page.locator("#aaEnvironmentStatus").inner_text()
    assert "已采用" not in page.evaluate("toasts.at(-1).message")


def test_invalid_saved_spine_is_recognized_by_source_without_reason(page):
    result = spine(valid=False)
    result["spine_cli"]["reason"] = None
    page.evaluate("result => renderSpineCliSettings(result)", result)
    assert "配置路径不可用" in page.locator("#spineCliStatus").inner_text()
    assert "未回退" in page.locator("#spineCliStatus").inner_text()


def test_successful_spine_save_keeps_existing_success_flow(page):
    result = spine()
    page.evaluate(
        "async result => { reply = result; $('#spineCliPath').value = result.spine_cli.path; await saveSpineCli(); }",
        result,
    )
    assert page.evaluate("toasts.at(-1).message") == "Spine 表情预览设置已保存。"
    assert page.evaluate("calls") == [
        {"route": "/settings/spine-cli", "body": {"path": result["spine_cli"]["path"]}}
    ]
    assert page.locator("#saveSpineCli").is_enabled()
    assert "当前机器可以调用 Spine CLI" in page.locator("#spineCliCapability").inner_text()


def test_spine_load_error_is_escaped_in_dom(page):
    page.evaluate(
        "async () => { api = async () => { throw new Error('<img src=x onerror=alert(1)>'); }; await loadSpineCliSettings(); }"
    )
    assert "读取设置失败" in page.locator("#spineCliStatus").inner_text()
    assert "<img src=x onerror=alert(1)>" in page.locator("#spineCliStatus").inner_text()
    assert page.locator("#spineCliStatus img").count() == 0


@pytest.mark.parametrize("adopted", [False, True])
def test_production_headline_distinguishes_valid_candidate_from_invalid_active(page, adopted):
    workspace = aa(valid=False)
    workspace["restart_path"] = None
    page.evaluate("result => renderAaEnvironment(result)", environment(workspace, adopted=adopted))
    card = page.locator("#aaEnvironmentStatus")
    assert card.locator("strong").first.inner_text() == "当前 AA 制作环境不可用"
    assert "检测路径（可用）：" + workspace["path"] in card.inner_text()
    assert "当前生效路径：无" in card.inner_text()
    assert "重启后路径：无" in card.inner_text()
    assert "needs-work" in card.get_attribute("class")


@pytest.mark.parametrize("override", [False, True])
def test_writing_adopt_then_inspect_retains_runtime_path_disclosure(page, override):
    workspace = aa(override=override)
    page.evaluate(
        """async workspace => {
      reply = {ok: true, aa_workspace: workspace};
      $('#aaWorkspaceInput').value = workspace.path;
      SettingsController.aaInspectionRevision = 1;
      SettingsController.aaInspection = {selection: workspace.path, path: workspace.path, revision: 1};
      await SettingsController.adoptAa();
    }""",
        workspace,
    )
    card = page.locator("#aaEnvironmentCard")
    assert "重启后路径：" + workspace["restart_path"] in card.inner_text()
    result = environment(workspace, adopted=False)
    result["environment"]["workspace"]["path"] = "C:/candidate/not-yet-adopted"
    page.evaluate(
        "async result => { reply = result; await SettingsController.inspectAa(); }", result
    )
    text = card.inner_text()
    assert "当前生效路径：" + workspace["path"] in text
    assert "已保存路径：" + workspace["persisted_path"] in text
    assert "重启后路径：" + workspace["restart_path"] in text
    assert workspace["source"] in text
    assert "C:/candidate/not-yet-adopted" in text
    assert ("仅本次会话" in text) == override
    assert ("启动配置优先" in text) == override
    assert card.locator("img").count() == 0
    assert page.locator("#adoptAaBtn").is_enabled()
    assert page.locator("#inspectAaBtn").is_enabled()
    assert page.locator("#aaWorkspaceInput").is_enabled()
    assert page.evaluate("calls.map(call => call.route)") == [
        "/production/api/v1/settings/aa-workspace",
        "/production/api/v1/settings/aa-environment",
    ]


@pytest.mark.parametrize("candidate_valid", [False, True])
def test_writing_inspection_reports_invalid_saved_workspace_without_restart_path(
    page, candidate_valid
):
    workspace = aa(valid=False)
    workspace["restart_path"] = None
    result = environment(workspace, adopted=False)
    result["environment"]["workspace"]["valid"] = candidate_valid
    page.evaluate(
        "async result => { reply = result; await SettingsController.inspectAa(); }", result
    )
    card = page.locator("#aaEnvironmentCard")
    assert "当前生效路径：无（当前配置不可用）" in card.inner_text()
    assert "已保存路径：" + workspace["persisted_path"] in card.inner_text()
    assert "重启后路径：无" in card.inner_text()
    assert page.locator("#adoptAaBtn").is_enabled() == candidate_valid


def test_writing_invalid_adoption_cannot_show_success_and_restores_controls(page):
    workspace = aa(valid=False)
    workspace["restart_path"] = None
    page.evaluate(
        """async workspace => {
      reply = {ok: true, aa_workspace: workspace};
      $('#aaWorkspaceInput').value = workspace.path;
      SettingsController.aaInspectionRevision = 1;
      SettingsController.aaInspection = {selection: workspace.path, path: workspace.path, revision: 1};
      await SettingsController.adoptAa();
    }""",
        workspace,
    )
    assert "采用未完成" in page.locator("#aaEnvironmentCard").inner_text()
    assert "已采用" not in page.locator("#aaEnvironmentCard").inner_text()
    assert "已采用" not in page.locator("#adoptAaBtn").inner_text()
    assert page.locator("#adoptAaBtn").is_disabled()
    assert page.locator("#inspectAaBtn").is_enabled()
    assert page.locator("#aaWorkspaceInput").is_enabled()
    assert page.locator("#unrelated").is_enabled()
    assert page.evaluate("toasts.at(-1).tone") is True
    assert "采用结果不一致" in page.evaluate("toasts.at(-1).message")
    assert page.evaluate("SettingsController.aaInspection") is None
