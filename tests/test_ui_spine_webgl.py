from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_spine_settings_present_webgl_without_cli_picker():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")

    section = html.split('<section id="spineSettings">', 1)[1].split("</section>", 1)[0]
    assert "Spine 渲染" in section
    assert "本地 WebGL 渲染器已就绪" in section
    assert "spineCliInput" not in section
    assert "browse-spine-cli" not in section
    assert "save-spine-cli" not in section
    assert '<script src="/js/spine_face_webgl.js"></script>' in html


def test_face_workspace_does_not_ask_for_spine_cli_configuration():
    script = (ROOT / "js" / "library_faces.js").read_text(encoding="utf-8")

    assert "请检查 Spine 配置" not in script
    assert "new exports.FaceWebGlRenderer()" in script
