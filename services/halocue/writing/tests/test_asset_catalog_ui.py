from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_global_asset_library_separates_custom_and_builtin_sources():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    assert 'data-section="assets"' in html
    assert "ASSET_CATALOG_KINDS" in app
    assert "/production/api/v1/resources/" in app
    assert "/production/api/v1/custom-assets" in app
    assert "我的素材" in app
    assert "AA 内置资源" in app
    assert "1.0 写作资源" in (ROOT / "web" / "writing-workbench.js").read_text(encoding="utf-8")
    assert "asset-card-technical" in app
    assert "技术详情" in app
    assert "AI 识别只会生成标签建议" in app
    assert "data-asset-load-more" in app
    assert "data-asset-preview" in app
    assert "data-custom-asset-upload" in app
    assert "data-custom-asset-recognize" in app
    assert "data-custom-asset-register" in app
    assert "data-custom-asset-edit" in app
    assert "expected_metadata_version" in app
    assert "method:'PATCH'" in app
    assert "data-asset-attach" in app
    assert "spine_animation_rendered" not in app
    assert "没有渲染 Spine 动画" in app


def test_asset_catalog_has_desktop_and_mobile_layout_contracts():
    css = (ROOT / "web" / "shell.css").read_text(encoding="utf-8")

    assert ".app-shell.asset-stage" in css
    assert ".asset-catalog-grid" in css
    assert "@media (max-width: 760px)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css


def test_scene_writing_exposes_traceable_asset_reference_picker():
    workbench = (ROOT / "web" / "writing-workbench.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert "data-scene-asset-picker" in workbench
    assert "scene-assets-trigger" in (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "/asset-references" in workbench
    assert "source_snapshot" in workbench
    assert "source_asset_id" in workbench
    assert "function sceneAssetDisplayName(reference)" in workbench
    assert "displayName !== sourceAssetId" in workbench
    assert "sceneAssetDisplayName(reference)" in workbench
    assert "source_version" in workbench
    assert "production_copy" in workbench
    assert "<summary>技术详情</summary>" in workbench
    assert "引用 ID" in workbench
    assert "资源标识" in workbench
    assert "任务副本状态" in workbench
    assert "content_hash_kind" in workbench
    assert "素材库原件不会改变" in workbench
    assert "source_snapshot?.source === 'writing_catalog'" in workbench
    assert "if (picker.scope === 'custom') query.set('kind', config.customKind);" in workbench
    assert "function sceneAssetItemMatchesPicker(item, picker)" in workbench
    assert "items.filter(item => sceneAssetItemMatchesPicker(item, picker))" in workbench
    assert "function sceneAssetSourceOptions(kind)" in workbench
    assert "if (kind === 'background') return [['writing', '1.0 写作资源'], ['custom', '我的素材']];" in workbench
    assert "declaredKind !== kind" in workbench
    assert "自定义素材缺少类型信息" in workbench
    assert "SCENE ASSET REFERENCES" not in workbench
    assert "份写作资料" in workbench
    assert "scene_asset_references" in workbench
    assert "/asset-suggestions" in workbench
    assert "本地规则建议 · 未调用模型" in workbench
    assert "data-scene-asset-suggestion-kind" in workbench
    assert "data-scene-asset-save" in workbench
    assert "asset_catalog_unavailable" in workbench
    assert "素材库服务未连接" in workbench
    assert "data-scene-asset-picker-retry" in workbench
    assert "data-scene-asset-search" in workbench
    assert "data-scene-asset-quick-query" in workbench
    assert "sceneAssetPreviewUrl" in workbench
    assert "/production/api/v1/resources/${kind}/${encodeURIComponent(key)}/preview" in workbench
    assert "data-scene-asset-preview" in workbench
    assert "不会伪造可选素材" in workbench
    assert "#workspace .scene-context-panel" in workbench
    assert ".workspace-inner > .step-band" not in workbench
    assert ".scene-assets-panel" in css
    assert ".scene-assets-suggestions" in css
    assert ".scene-asset-reference-details" in css
    assert ".scene-asset-picker-dialog" in css
    assert ".scene-asset-picker-error" in css
    assert ".scene-asset-search" in css
    assert ".scene-asset-result-preview" in css
    assert ".chapter-inline-manuscript .block-move" in css
    assert ".chapter-inline-manuscript .block-gutter" in css
    assert ".chapter-inline-manuscript .manuscript-block:focus-within .block-move" in css
