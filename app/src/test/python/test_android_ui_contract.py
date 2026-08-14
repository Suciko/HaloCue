from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "main" / "python"


def test_android_settings_show_mapping_instead_of_pc_install_controls():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    css = (ROOT / "css" / "layout.css").read_text(encoding="utf-8")
    javascript = (ROOT / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="androidResourceMapping"' in html
    assert "APK 内置标识映射" in html
    assert 'id="androidAAInstallState"' in html
    assert 'id="androidMappingCharacters"' in html
    assert 'id="androidMappingAliases"' in html
    assert "body.android-native #storageSettings .aa-install-controls" in css
    assert "body.android-native #spineSettings" in css
    assert "resource_mapping" in javascript
    assert "isAzureArchiveInstalled" in javascript
    assert "不代表手机已安装原版 AA" in javascript
    assert "android-native" in javascript


def test_model_editor_has_persistent_save_feedback_next_to_actions():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    javascript = (ROOT / "js" / "app.js").read_text(encoding="utf-8")

    assert 'id="modelSaveNotice"' in html
    assert "模型和 API Key 已安全保存" in javascript
    assert 'id="modelDiscover"' in html
    assert "读取超时，请检查网络或 API 地址后重试" in javascript
    assert "已自动选择" in javascript
    assert "请先填写模型名称，或读取可用模型后再保存" in javascript


def test_android_first_screen_uses_compact_mobile_chrome():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    css = (ROOT / "css" / "layout.css").read_text(encoding="utf-8")
    javascript = (ROOT / "js" / "app.js").read_text(encoding="utf-8")

    assert 'class="topbar android-home-header"' in html
    assert 'class="story-context-bar android-story-summary is-empty"' in html
    assert html.count('class="topbar-action-icon"') == 3
    assert html.count('class="topbar-action-label"') == 3
    assert "body.android-native .topbar" in css
    assert "body.android-native .android-home-header" in css
    assert "body.android-native .android-story-summary" in css
    assert "body.android-native .story-asset-strip.is-empty-state" in css
    assert "body.android-native .workflow-progress" in css
    assert ".welcome-panel.is-compact .readiness-grid" in css
    assert "isAndroidLayoutPreview" in javascript
    assert "android-preview" in javascript
    assert "updateAndroidScrollChrome" in javascript


def test_android_first_screen_does_not_duplicate_system_bar_spacing():
    css = (ROOT / "css" / "layout.css").read_text(encoding="utf-8")
    android_rules = css.split("Android runtime chrome", 1)[1]

    assert "padding:8px 12px 8px" in android_rules
    assert "padding:calc(8px + env(safe-area-inset-top))" not in android_rules
    assert "body.android-native .recent-story" in android_rules


def test_android_fullscreen_surfaces_do_not_duplicate_system_bar_spacing():
    css = (ROOT / "css" / "layout.css").read_text(encoding="utf-8")
    android_rules = css.split("Native WebView padding already accounts for Android system bars.", 1)[1]

    assert "body.android-native .settings-drawer { padding-top:18px;padding-bottom:24px; }" in android_rules
    assert "body.android-native .asset-workbench-header { padding-top:12px; }" in android_rules
    assert "body.android-native .asset-import-dialog { padding-top:0;padding-bottom:10px; }" in android_rules
    assert "body.android-native .asset-import-dialog-shell { padding-bottom:18px; }" in android_rules
    assert "env(safe-area-inset" not in android_rules
    assert "body.android-native .recent-story-button { grid-column:1 / -1;justify-self:center" in android_rules


def test_mobile_background_cards_stack_preview_above_metadata():
    css = (ROOT / "css" / "app.css").read_text(encoding="utf-8")

    assert "@media (max-width: 520px)" in css
    assert ".usage-bound-background,.usage-candidate { grid-template-columns: minmax(0, 1fr); }" in css
    assert ".usage-candidate-preview,.usage-candidate-placeholder { width: 100%; }" in css
    assert ".usage-bound-background-body b,.usage-candidate-body b { overflow-wrap: break-word; word-break: normal; }" in css


def test_android_launcher_uses_halocue_brand_icon():
    main_root = ROOT.parent
    manifest = (main_root / "AndroidManifest.xml").read_text(encoding="utf-8")
    resources = main_root / "res"

    assert 'android:icon="@mipmap/ic_launcher"' in manifest
    assert 'android:roundIcon="@mipmap/ic_launcher_round"' in manifest
    assert (resources / "mipmap-xxxhdpi" / "ic_launcher.png").is_file()
    assert (resources / "mipmap-anydpi-v26" / "ic_launcher.xml").is_file()
    assert (resources / "drawable-nodpi" / "ic_launcher_foreground.png").is_file()
    adaptive = (resources / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text(encoding="utf-8")
    generator = (main_root.parents[2] / "scripts" / "generate-launcher-icon.ps1").read_text(encoding="utf-8")
    colors = (resources / "values" / "colors.xml").read_text(encoding="utf-8")
    assert '@drawable/ic_launcher_foreground' in adaptive
    assert "-ContentScale 0.60" in generator
    assert '<color name="launcher_background">#FFFFFF</color>' in colors


def test_android_asset_import_routes_files_and_directories_to_native_picker():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    dialog = (ROOT / "js" / "library_import.js").read_text(encoding="utf-8")
    assets = (ROOT / "js" / "assets.js").read_text(encoding="utf-8")

    assert "'asset_file'" in dialog
    assert "'asset_tree'" in dialog
    assert "'character'" in dialog
    assert "'batch'" in dialog
    assert "pickAsset" in dialog
    assert "nativeSelection" in assets
    assert "file_token" in assets
    assert "选择角色目录" in html
    assert "选择素材文件夹批量导入" in html


def test_face_workspace_displays_imported_avatar_as_reference_not_face_preview():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    css = (ROOT / "css" / "layout.css").read_text(encoding="utf-8")
    javascript = (ROOT / "js" / "library_faces.js").read_text(encoding="utf-8")

    assert 'id="faceWorkspaceReference"' in html
    assert 'id="faceWorkspaceAvatar"' in html
    assert "角色参考头像" in html
    assert "不会用同一张头像冒充表情差分" in html
    assert ".face-workspace-reference[hidden]{display:none}" in css
    assert "this.renderAvatar(payload.avatar_url || ''" in javascript
    assert "if (result.avatar_url) this.renderAvatar" in javascript


def test_face_workspace_bundles_local_webgl_renderer_for_real_spine_previews():
    html = (ROOT / "ui.html").read_text(encoding="utf-8")
    faces = (ROOT / "js" / "library_faces.js").read_text(encoding="utf-8")
    renderer = (ROOT / "js" / "spine_face_webgl.js").read_text(encoding="utf-8")

    assert 'src="/js/spine-webgl-3.8.95.js"' not in html
    assert 'src="/js/spine_face_webgl.js"' in html
    assert 'id="faceWebglCanvas" width="2048" height="2048"' in html
    assert "this.renderMissingPreviews();" in faces
    assert "this.renderer.render" in faces
    assert "face_ids" in renderer
    assert "faceId !== '00'" in renderer
    assert "SPINE_38_RUNTIME = '/js/spine-webgl-3.8.95.js'" in renderer
    assert "SPINE_42_RUNTIME = '/js/spine-webgl-4.2.119.min.js'" in renderer
    assert "gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, pma)" in renderer
    assert "renderer.premultipliedAlpha = pma" in renderer
    assert "/api/assets/faces/rendered" in renderer
