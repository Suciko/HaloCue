import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2] / "main" / "python"


def test_render_upload_percent_encodes_a_chinese_character_key_in_the_url():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const requests = [];
const window = {};
const document = {getElementById: () => ({getContext: () => ({})})};
const fetch = async (url, options) => {
  for (const value of Object.values(options.headers || {})) {
    if ([...String(value)].some(character => character.codePointAt(0) > 255)) {
      throw new TypeError('WebView rejected a non-Latin-1 request header');
    }
  }
  requests.push({url, headers: options.headers});
  return {ok: true, json: async () => ({ok: true})};
};
vm.runInNewContext(source, {window, document, fetch, Boolean, String, Error, encodeURIComponent});
(async () => {
  const renderer = new window.FaceWebGlRenderer();
  await renderer.upload(
    {aa_key: '凯伊约会服', sha256: 'kei-digest'},
    '00',
    {kind: 'png'}
  );
  console.log(JSON.stringify(requests[0]));
})().catch(error => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", script, str(ROOT / "js" / "spine_face_webgl.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    request = json.loads(completed.stdout)
    assert request["url"] == (
        "/api/assets/faces/rendered?"
        "aa_key=%E5%87%AF%E4%BC%8A%E7%BA%A6%E4%BC%9A%E6%9C%8D"
        "&sha256=kei-digest&face_id=00"
    )
    assert request["headers"] == {"Content-Type": "image/png"}


def test_renderer_uses_atlas_pma_and_supports_all_texture_pages():
    source = (ROOT / "js" / "spine_face_webgl.js").read_text(encoding="utf-8")
    assert "premultipliedAlpha: false" in source
    assert "UNPACK_PREMULTIPLY_ALPHA_WEBGL, pma" in source
    assert "bundle.texture_pages" in source
    assert "renderer.premultipliedAlpha = pma" in source
    assert "var pma = is42 ? atlasPma : true" in source


def test_renderer_routes_spine_42_to_matching_runtime():
    source = (ROOT / "js" / "spine_face_webgl.js").read_text(encoding="utf-8")
    assert "spine-webgl-4.2.119.min.js" in source
    assert "startsWith('4.2')" in source


def test_face_workspace_polls_the_server_while_vision_ai_is_queued():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function node() {
  return {
    textContent: '', hidden: false, disabled: false, open: false, dataset: {},
    classList: {contains: () => true, add: () => {}, remove: () => {}},
    addEventListener: () => {}, setAttribute: () => {}, removeAttribute: () => {},
    appendChild: () => {}, querySelector: () => null, querySelectorAll: () => [],
  };
}
const nodes = {};
[
  'faceWorkspace','faceWorkspaceBackdrop','faceWorkspaceCharacter','faceWorkspacePhase',
  'faceWorkspaceProgress','faceWorkspaceResult','faceWorkspaceMore','faceWorkspaceForceButton',
  'faceWorkspaceStart','faceWorkspaceStatus','faceWorkspaceReference','faceWorkspaceAvatar',
  'faceWorkspaceLabels','faceWorkspaceLog'
].forEach(id => nodes[id] = node());
const document = {
  getElementById: id => nodes[id] || null,
  createElement: () => node(),
  addEventListener: () => {},
};
const window = {
  FaceWebGlRenderer: function () {
    this.render = async () => ({
      complete: true, rendered_count: 44, total: 44, vision_status: 'queued'
    });
  },
};
vm.runInNewContext(source, {
  window, document, Boolean, String, Number, Object, Array, Promise, Error,
  setTimeout, clearTimeout, console
});
(async () => {
  const workspace = window.FaceWorkspace;
  workspace.selected = {aa_key: '凯伊约会服', sha256: 'digest'};
  workspace.generation = 1;
  workspace.isOpen = () => true;
  let refreshes = 0, loads = 0;
  workspace.refresh = () => { refreshes += 1; };
  workspace.loadLabels = () => { loads += 1; };
  await workspace.renderMissingPreviews();
  console.log(JSON.stringify({
    phase: nodes.faceWorkspacePhase.textContent,
    status: nodes.faceWorkspaceStatus.textContent,
    refreshes, loads
  }));
})().catch(error => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", script, str(ROOT / "js" / "library_faces.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    result = json.loads(completed.stdout)
    assert result == {
        "phase": "AI 正在看图识别",
        "status": "44 张高清差分已保存，正在等待视觉 AI 返回表情语义。",
        "refreshes": 1,
        "loads": 0,
    }
