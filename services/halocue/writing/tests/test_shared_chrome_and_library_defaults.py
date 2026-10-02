"""Shared navigation and deterministic library defaults, without model requests."""

from pathlib import Path
import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def page():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("pageerror", lambda error: pytest.fail(str(error)))
        yield page
        browser.close()


@pytest.mark.parametrize(
    "surface", ["works", "writing", "references", "assets", "tasks", "production"]
)
def test_navigation_icons_are_shared_and_idempotent(page, surface):
    page.set_content(
        f'<div id="app" class="hc-redesign" data-surface="{surface}"><nav class="primary-nav"><button class="nav-item" data-section="works">构思</button><button class="nav-item" data-section="assets">素材</button><button class="nav-item" data-action="settings">设置</button></nav></div>'
    )
    page.add_script_tag(
        content="let hook;window.HaloCueRouter={registerRenderHook:(key,fn)=>{hook=fn}};"
    )
    page.add_script_tag(content=(WEB / "app-chrome.js").read_text(encoding="utf8"))
    page.evaluate("hook();hook()")
    for css in ["tokens.css", "shell.css", "theme.css", "agent-workspace.css", "authoring-ui.css"]:
        page.add_style_tag(content=(WEB / css).read_text(encoding="utf8"))
    expect(page.locator(".agent-nav-icon")).to_have_count(3)
    assert page.locator(".agent-nav-icon").evaluate_all(
        'es=>es.every(e=>getComputedStyle(e).display!=="none")'
    )
    assert page.locator(".nav-item").evaluate_all(
        'es=>es.every(e=>getComputedStyle(e,"::before").display==="none")'
    )
    expect(page.get_by_role("button", name="素材", exact=True)).to_be_visible()


def test_activity_count_does_not_treat_completed_history_as_running(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function writingActivityItems(") : source.index("function renderChrome(")
    ]
    page.add_script_tag(content="const hcArray=v=>Array.isArray(v)?v:[];" + helper)
    assert (
        page.evaluate(
            "backgroundActivityLabel({runs:[{work_items:[{status:'succeeded'},{status:'cancelled'},{status:'skipped'}]}]})"
        )
        == "暂无后台活动"
    )
    assert (
        page.evaluate(
            "backgroundActivityLabel({runs:[{work_items:[{status:'running'},{status:'ready'},{status:'waiting_user'},{status:'failed'}]}]})"
        )
        == "待执行 1 项 · 后台运行 1 项 · 待处理 1 项 · 失败记录 1 项"
    )
    assert page.evaluate("backgroundActivityLabel(null)") == "暂无后台活动"


@pytest.mark.parametrize(
    "kind,expected",
    [("characters", "character"), ("backgrounds", "background"), ("sounds", "sound"), ("cg", "cg")],
)
def test_upload_defaults_to_current_category_with_relevant_fields(page, kind, expected):
    source = (WEB / "app.js").read_text(encoding="utf8")
    markup = source[
        source.index("function ensureCustomAssetUploadDialog(") : source.index(
            "function customAssetValidationMeta("
        )
    ]
    helpers = source[
        source.index("function syncCustomAssetFields(") : source.index(
            "function ensureCustomAssetEditDialog("
        )
    ]
    config = source[
        source.index("const ASSET_CATALOG_KINDS=") : source.index(
            "function assetCatalogSourceLabel("
        )
    ]
    page.add_script_tag(
        content=f"const state={{assetCatalog:{{kind:'{kind}'}}}},$=s=>document.querySelector(s);const renderCustomAssetReview=()=>{{}};"
        + config
        + markup
        + helpers
        + "openCustomAssetUpload();"
    )
    form = page.locator("[data-custom-asset-upload-form]")
    expect(form.locator("[name=kind]")).to_have_value(expected)
    expect(
        form.locator("[name=identifier]")
    ).to_be_visible() if expected == "character" else expect(
        form.locator("[name=identifier]")
    ).to_be_hidden()
    assert form.locator("[name=identifier]").is_enabled() == (expected == "character")
    expect(form.locator("[name=kind]")).to_be_enabled()
    form.locator("[name=kind]").select_option("background")
    expect(form.locator("[name=identifier]")).to_be_hidden()
    expect(form.locator("[name=place]")).to_be_hidden()
    page.evaluate("state.assetUpload={validation:{ok:true}};syncCustomAssetFields(document.querySelector('[data-custom-asset-upload-form]'))")
    form.locator(".custom-asset-meta-details > summary").click()
    expect(form.locator("[name=place]")).to_be_visible()


def test_new_character_draft_source_is_custom_not_official(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    start = source.index("  if(button.dataset.libraryNewCard!==undefined)")
    handler = source[start : source.index("  if(button.dataset.editCard)", start)]
    page.set_content("<button data-library-new-card>新建自定义人物</button>")
    page.add_script_tag(
        content="const state={},claimAppEvent=()=>{},dismissToast=()=>{},render=()=>{},$=()=>null;document.addEventListener('click',event=>{const button=event.target;"
        + handler
        + "});"
    )
    page.get_by_role("button").click()
    assert page.evaluate("state.characterCardDraft.source_type") == "custom"


@pytest.mark.parametrize(
    "view,section",
    [
        ("characters", "characters"),
        ("relations", "relations"),
        ("rules", "world"),
        ("timeline", "canon"),
        ("memories", "canon"),
        ("official", "files"),
    ],
)
def test_reference_categories_keep_old_routes_and_mobile_access(page, view, section):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function renderReferencesNavigation(") : source.index(
            "window.HaloCueRouter=", source.index("function renderReferencesNavigation(")
        )
    ]
    page.set_content('<nav id="referencesNav"></nav><main id="workspace"><div class="library-workbench"></div></main>')
    page.add_script_tag(
        content=f"const state={{libraryView:'{view}'}};const pendingKnowledgeProposals=()=>[];" + helper + "renderReferencesNavigation();"
    )
    expect(page.locator("#referencesNav details")).to_have_count(0)
    expect(page.locator("#referencesNav [data-library-view]")).to_have_count(7)
    expect(page.locator('[aria-current="page"]')).to_have_attribute("data-library-view", section)
    expect(page.locator("[data-reference-mobile-view]")).to_have_value(section)
    expect(page.locator('[aria-current="page"]')).to_be_visible()
    page.evaluate("renderReferencesNavigation()")
    expect(page.locator("#referencesNav [data-library-view]")).to_have_count(7)
    expect(page.locator("[data-reference-mobile-view]")).to_have_count(1)


def test_empty_library_offers_manual_creation_and_import(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function libraryDecisionGuideMarkup(") : source.index(
            "function worldCardPayload("
        )
    ]
    page.add_script_tag(
        content="const libraryCards=()=>[],worldBible=()=>({}),workCanon=()=>({}),pendingKnowledgeProposals=()=>[],unconfirmedWorldCards=()=>[],graphRecords=()=>[],graphLinks=()=>[],esc=x=>x;"
        + helper
        + "document.body.innerHTML=libraryDecisionGuideMarkup();"
    )
    expect(page.get_by_role("button", name="新建人物", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="导入人物资料", exact=True)).to_be_visible()
    expect(
        page.get_by_text("直接添加人物或导入已有资料，不需要先连接模型。", exact=False)
    ).to_be_visible()


def test_library_decision_guide_keeps_smart_checks_collapsed_and_task_first(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function libraryDecisionGuideMarkup(") : source.index(
            "function worldCardPayload("
        )
    ]
    page.add_script_tag(
        content="const libraryCards=()=>[{id:'c1',name:'凯伊',status:'active',trust_status:'confirmed'}],worldBible=()=>({entities:[],rules:[],timeline:[]}),workCanon=()=>({facts:[]}),pendingKnowledgeProposals=()=>[],unconfirmedWorldCards=()=>[],graphRecords=()=>[{id:'c1'}],graphLinks=()=>[],esc=x=>x;"
        + helper
        + "document.body.innerHTML=libraryDecisionGuideMarkup();"
    )
    expect(page.get_by_role("button", name="调整人物", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="建立世界观", exact=True)).to_be_visible()
    expect(page.locator(".library-health-summary")).to_have_count(1)
    expect(page.locator(".library-health-summary")).not_to_have_attribute("open", "")


@pytest.mark.parametrize(
    "view,expected",
    [("characters", False), ("memories", False), ("overview", False), ("official", True)],
)
def test_missing_official_corpus_warning_is_local_to_search(page, view, expected):
    source = (WEB / "app.js").read_text(encoding="utf8")
    observer = source[
        source.index("const officialCatalogObserver=") : source.index(
            "// Draft scene buttons are handled", source.index("const officialCatalogObserver=")
        )
    ]
    page.set_content(
        '<div id="workspace"><div class="library-workbench"><button data-library-view="official">BA 原作资料</button><div class="library-main"><form id="officialReferenceSearchForm"><input name="query"><button type="submit">检索</button></form></div></div></div>'
    )
    page.add_script_tag(
        content=f"const state={{libraryView:'{view}',capabilities:{{official_references:{{available:false}}}}}},$=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];"
        + observer
        + "document.querySelector('.library-main').append(document.createElement('span'));"
    )
    expect(page.locator(".catalog-availability")).to_have_count(1 if expected else 0)
    if expected:
        expect(page.locator("#officialReferenceSearchForm input:disabled")).to_have_count(0)
        expect(page.locator("#officialReferenceSearchForm button:disabled")).to_have_count(0)
        expect(page.get_by_role("button", name="BA 原作资料", exact=True)).to_be_enabled()


def test_optional_official_corpus_fallback_preserves_bundled_metadata_search(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("async function searchOptionalOfficialReferences") : source.index(
            "async function bundledReferenceSearch"
        )
    ]
    page.add_script_tag(
        content="const officialReferenceSearch=async()=>{const error=new Error('未配置');error.code='official_corpus_unavailable';throw error};"
        + helper
    )
    result = page.evaluate("searchOptionalOfficialReferences('白子')")
    assert result == {"result": {"items": []}, "unavailable": True}


def test_optional_official_corpus_fallback_does_not_swallow_validation_errors(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("async function searchOptionalOfficialReferences") : source.index(
            "async function bundledReferenceSearch"
        )
    ]
    page.add_script_tag(
        content="const officialReferenceSearch=async()=>{const error=new Error('请输入关键词');error.code='validation_error';throw error};"
        + helper
    )
    assert page.evaluate("searchOptionalOfficialReferences('x').then(()=>false).catch(error=>error.code)") == "validation_error"


def test_cross_workspace_entry_resets_foreign_inspector_without_touching_local_switch(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[source.index("function commitRoute(") : source.index("function routeForStage(")]
    page.add_script_tag(
        content="""
      const HC_SECTIONS=new Set(['works','writing','references','tasks','assets','production']),HC_WRITING_STAGES=new Set(['structure','draft','release']),HC_LIBRARY_VIEWS=new Set(['overview','characters']);
      const state={inspector:'decision'};let hcRoute={section:'works',library:'overview'},hcLastWritingRoute,hcLastNonAssetRoute;
    """
        + helper
        + "commitRoute({section:'references'});commitRoute({section:'tasks'});commitRoute({section:'writing',stage:'draft'});"
    )
    assert page.evaluate("state.inspector") == "agent"
    page.evaluate("state.inspector='context';commitRoute({stage:'structure'});")
    assert page.evaluate("state.inspector") == "context"
