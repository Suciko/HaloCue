"""Real DOM/event wiring with bundled HTML/controller; all IO is synthetic.

This does not start the full application or contact any model or AA install.
"""

import re
from pathlib import Path

import pytest


def test_settings_credentials_and_workspace_controls_in_real_browser():
    playwright = pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)
    source = (web / "app.js").read_text(encoding="utf-8")
    start = source.index("const SettingsController =")
    controller = source[start : source.index("\n};", start) + 3]
    stubs = """
      window.testCalls = []; window.testToasts = [];
      window.api = async (route, options) => {
        testCalls.push({route, body: options?.body ? JSON.parse(options.body) : null});
        return {models: ['synthetic-model']};
      };
      window.fetch = async (route, options) => {
        const body = JSON.parse(options.body);
        testCalls.push({route, body});
        const result = route.endsWith('aa-environment')
          ? {ok: true, environment: {workspace: body.selection.includes('missing')
              ? {valid: false, path: null} : {valid: true, path: '/synthetic/aa/data'}}}
          : {ok: true, aa_workspace: {valid: true, path: body.path}};
        return {ok: true, json: async () => result};
      };
      window.esc = value => {const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML;};
      window.toast = (message, error) => testToasts.push({message, error: !!error});
      window.state = {};
    """
    with playwright.sync_playwright() as p:
        executable = Path(p.chromium.executable_path)
        if executable.exists():
            browser = p.chromium.launch(headless=True)
        elif Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe").exists():
            browser = p.chromium.launch(channel="msedge", headless=True)
        else:
            pytest.skip("A local Chromium or Edge installation is required")
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(html)
            page.add_style_tag(
                content="dialog {width: 95vw; height: 95vh;} .settings-pane {display:none} .settings-pane.active {display:block}"
            )
            page.add_script_tag(
                content=stubs + controller + "\nwindow.testSettings = SettingsController;"
            )
            page.evaluate("""() => {
              const c = testSettings;
              c.init();
              c.renderModelSettings({model: {configured: false, provider: 'openai', base_url: 'https://a.invalid/v1', model: 'model-a', preset_id: 'a'}, presets: [
                {id: 'a', name: 'Synthetic A', provider: 'openai', base_url: 'https://a.invalid/v1', default_model: 'model-a', models: []},
                {id: 'b', name: 'Synthetic B', provider: 'openai', base_url: 'https://b.invalid/v1', default_model: 'model-b', models: []}
              ]});
              c.dialog.showModal();
              c.dialog.querySelectorAll('details').forEach(node => {node.open = true;});
            }""")
            assert page.locator("#modelEndpointDetails").is_hidden()
            assert page.locator('input[name="apply_scope"][value="writing"]').is_checked()
            page.locator("#settingsApiKey").fill("SYNTHETIC-KEY-A")
            page.locator('[data-preset-id="b"]').click()
            assert page.locator("#settingsApiKey").input_value() == ""
            page.locator("#settingsApiKey").fill("SYNTHETIC-KEY-B")
            assert page.locator("#modelEndpointDetails").is_hidden()
            page.locator('[data-preset-id="custom"]').click()
            assert page.locator("#modelEndpointDetails").is_visible()
            assert page.locator("#settingsApiKey").input_value() == ""
            page.locator("#settingsApiKey").fill("SYNTHETIC-CUSTOM-KEY")
            page.locator("#settingsBaseUrl").fill("https://custom.invalid/v1")
            assert page.locator("#settingsApiKey").input_value() == ""
            page.locator("#fetchModelsBtn").click()
            page.wait_for_function("testCalls.some(call => call.route.endsWith('fetch-models'))")
            sent = page.evaluate("testCalls.find(call => call.route.endsWith('fetch-models')).body")
            assert sent["api_key"] == "" and sent["api_key_env"] == ""

            page.locator('.settings-nav-btn[data-tab="aa"]').click()
            page.locator("#aaWorkspaceInput").fill("/synthetic/missing")
            page.locator("#inspectAaBtn").click()
            page.wait_for_function("document.getElementById('inspectAaBtn').disabled === false")
            assert page.locator("#adoptAaBtn").is_disabled()
            page.locator("#aaWorkspaceInput").fill("/synthetic/AzureArchive.exe")
            page.locator("#inspectAaBtn").click()
            page.wait_for_function("document.getElementById('adoptAaBtn').disabled === false")
            page.locator("#adoptAaBtn").click()
            page.wait_for_function("document.getElementById('adoptAaBtn').textContent === '已采用'")
            sent = page.evaluate("testCalls.find(call => call.route.endsWith('aa-workspace')).body")
            assert sent == {"path": "/synthetic/aa/data"}
            assert page.locator("#adoptAaBtn").is_disabled()
        finally:
            browser.close()
