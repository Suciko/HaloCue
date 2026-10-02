"""Knowledge-card editing exposes core fields and keeps extra detail reachable."""

from pathlib import Path

import pytest
from playwright.sync_api import expect


@pytest.fixture
def page():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        yield page
        browser.close()

WEB = Path(__file__).resolve().parents[1] / "web"


def _flow_source() -> str:
    source = (WEB / "app.js").read_text(encoding="utf8")
    return source[
        source.index("function libraryEditorFlowConfig(") : source.index(
            "function decorateLibrary(){"
        )
    ]


def _bootstrap(page, form_markup: str) -> None:
    page.set_content(form_markup)
    helper = _flow_source()
    page.add_script_tag(
        content=(
            "const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\\\"','&quot;');"
            "const hcArray=x=>Array.isArray(x)?x:[];"
            "const state={editCard:null};"
            + helper
        )
    )


def test_world_editor_shows_core_fields_and_keeps_relationships_optional(page):
    _bootstrap(
        page,
        """
        <form id="worldEntityForm">
          <label>类型<select name="kind"><option value="custom">本作原创</option></select></label>
          <label>来源类型<select name="source_type"><option value="custom">自定义设定</option></select></label>
          <label>名称<input name="name" required></label>
          <label>别名<input name="aliases"></label>
          <label>本作定义<textarea name="summary"></textarea></label>
          <label>来源或证据<input name="source" required></label>
          <label>可信状态<select name="confidence_status"><option value="open">待核对</option></select></label>
          <label>关联角色<input name="participants"></label>
          <fieldset class="world-link-picker"><legend>关联的世界观卡</legend><label><input name="related_world_ids" value="world-1" type="checkbox">世界 A</label></fieldset>
          <fieldset class="world-link-picker"><legend>关联的人物卡</legend><label><input name="world_character_card_ids" value="character-1" type="checkbox">角色 A</label></fieldset>
          <div class="actions"><button type="submit">保存</button></div>
        </form>
        """,
    )
    page.evaluate("decorateLibraryEditorFlow(document.querySelector('#worldEntityForm'),'world')")

    expect(page.locator("#worldEntityForm > label:has([name='name'])")).to_be_visible()
    expect(page.locator("#worldEntityForm > label:has([name='summary'])")).to_be_visible()
    expect(page.locator(".library-editor-more .world-link-picker")).to_have_count(2)
    expect(page.locator(".library-editor-steps")).to_have_count(0)

    page.evaluate("""const form=document.querySelector('#worldEntityForm');
      form.elements.name.value='深夜机房';
      form.elements.source.value='用户确认';
      form.elements.summary.value='只在零点后开启';""")
    page.locator("#worldEntityForm .library-editor-more").first.locator("summary").click()
    expect(page.locator(".library-editor-more .world-link-picker").first).to_be_visible()
    page.locator("#worldEntityForm .library-editor-assist > summary").click()
    expect(page.locator("[data-library-assist='world']")).to_be_visible()


def test_world_link_picker_can_filter_people_without_changing_selection(page):
    _bootstrap(
        page,
        """
        <form id="worldEntityForm">
          <label>类型<select name="kind"><option value="custom">本作原创</option></select></label>
          <label>来源类型<select name="source_type"><option value="custom">自定义设定</option></select></label>
          <label>名称<input name="name" value="临时地点"></label>
          <label>别名<input name="aliases"></label>
          <label>本作定义<textarea name="summary">用于测试关联人物筛选</textarea></label>
          <label>来源或证据<input name="source" value="用户确认"></label>
          <label>可信状态<select name="confidence_status"><option value="open">待核对</option></select></label>
          <label>关联角色<input name="participants"></label>
          <fieldset class="world-link-picker character-link-picker">
            <legend>关联的人物卡</legend>
            <label><input name="world_character_card_ids" value="character-kei" type="checkbox">天童凯伊</label>
            <label><input name="world_character_card_ids" value="character-alice" type="checkbox">天童爱丽丝</label>
            <label><input name="world_character_card_ids" value="character-hoshino" type="checkbox">小鸟游星野</label>
          </fieldset>
          <div class="actions"><button type="submit">保存</button></div>
        </form>
        """,
    )
    page.evaluate("decorateLibraryEditorFlow(document.querySelector('#worldEntityForm'),'world')")
    page.locator("#worldEntityForm .library-editor-more").first.locator("summary").click()

    picker = page.locator(".character-link-picker")
    expect(picker.locator("[data-world-link-query]")).to_have_count(1)
    expect(picker.locator("[data-world-link-count]")).to_have_text("已选 0 / 3")

    search = picker.locator("[data-world-link-query]")
    search.fill("凯伊")
    expect(picker.locator("[data-world-link-count]")).to_have_text("显示 1 / 3 · 已选 0")
    visibility = page.evaluate(
        """[...document.querySelectorAll('.character-link-picker input[type="checkbox"]')].map(input => ({
            value: input.value,
            hidden: input.closest('label').hidden,
        }))"""
    )
    assert visibility == [
        {"value": "character-kei", "hidden": False},
        {"value": "character-alice", "hidden": True},
        {"value": "character-hoshino", "hidden": True},
    ]

    picker.locator('input[value="character-kei"]').check()
    expect(picker.locator("[data-world-link-count]")).to_have_text("显示 1 / 3 · 已选 1")
    search.fill("")
    expect(picker.locator("[data-world-link-count]")).to_have_text("已选 1 / 3")
    expect(picker.locator('input[value="character-kei"]')).to_be_checked()


def test_character_editor_assistant_prompt_is_proposal_only(page):
    _bootstrap(
        page,
        """
        <form id="libraryCharacterForm">
          <label>来源类型<select name="source_type"><option value="custom">自定义设定</option></select></label>
          <label>采用状态<select name="trust_status"><option value="open">待核对</option></select></label>
          <label>显示名称<input name="name" value="凯伊"></label>
          <label>标准名称<input name="canonical_name" value="凯伊"></label>
          <label>故事职责<textarea name="role">保护爱丽丝</textarea></label>
          <label>声音锚点<textarea name="voice">短句、讲效率</textarea></label>
          <label>知情边界<textarea name="boundary">只知道已经发生的事</textarea></label>
          <label>OOC 红线<textarea name="ooc">不替别人决定</textarea></label>
          <label>关系<textarea name="relationships"></textarea></label>
          <label>来源或证据<input name="source" value="用户确认"></label>
          <div class="actions"><button type="submit">保存</button></div>
        </form>
        """,
    )
    page.evaluate("decorateLibraryEditorFlow(document.querySelector('#libraryCharacterForm'),'characters')")
    prompt = page.evaluate(
        "libraryEditorAssistantPrompt(document.querySelector('#libraryCharacterForm'),'characters')"
    )
    assert "人物卡" in prompt
    assert "凯伊" in prompt
    assert "只生成可审查的 Proposal" in prompt
    assert "不要自动保存" in prompt
    expect(page.locator("[data-library-assist='characters']")).to_have_count(1)


def test_editor_impact_preview_uses_fixed_scene_context(page):
    _bootstrap(
        page,
        """
        <form id="libraryCharacterForm">
          <input type="hidden" name="card_id" value="character-kei">
          <label>显示名称<input name="name" value="凯伊"></label>
          <label>来源或证据<input name="source" value="用户确认"></label>
          <label>故事职责<textarea name="role"></textarea></label>
          <label>声音锚点<textarea name="voice"></textarea></label>
          <label>知情边界<textarea name="boundary"></textarea></label>
          <label>OOC 红线<textarea name="ooc"></textarea></label>
          <label>关系<textarea name="relationships"></textarea></label>
          <select name="source_type"><option value="custom">自定义设定</option></select>
          <select name="trust_status"><option value="confirmed">已确认，可用于写作</option></select>
          <div class="actions"><button type="submit">保存</button></div>
        </form>
        """,
    )
    page.add_script_tag(
        content="""
        const scenes=()=>[{id:'scene-1',chapterTitle:'第一章',title:'温室调查',contract:{context_selection:{mode:'explicit',character_card_ids:['character-kei'],world_item_ids:[],reference_file_ids:[]}}}];
        const sceneContextSelection=scene=>scene.contract.context_selection;
        """
    )
    page.evaluate("decorateLibraryEditorFlow(document.querySelector('#libraryCharacterForm'),'characters')")
    expect(page.locator("[data-library-impact-summary]")).to_have_text("可能影响 1 个场景")
    expect(page.locator("[data-library-impact-list]")).to_contain_text("第一章 / 温室调查")


def test_scene_recommendations_explain_why_and_remain_opt_in(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function sceneContextRecommendationMarkup(") : source.index(
            "function sceneWorldItems()", source.index("function sceneContextRecommendationMarkup(")
        )
    ]
    page.set_content("<main></main>")
    page.add_script_tag(
        content=(
            "const esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');"
            + helper
            + "document.querySelector('main').innerHTML=sceneContextRecommendationMarkup({title:'温室调查',contract:{goal:'凯伊核对门禁记录',location:'温室'}},{character_card_ids:[],world_item_ids:[],reference_file_ids:[]},[{id:'character-kei',name:'凯伊',role:'核对门禁记录',trust_status:'confirmed'}],[{id:'world-greenhouse',name:'温室',summary:'夜间门禁',confidence_status:'confirmed'}]);"
        )
    )
    expect(page.locator(".scene-context-smart-recommendations")).to_have_count(1)
    page.locator(".scene-context-smart-recommendations > summary").click()
    expect(page.get_by_text("凯伊", exact=True)).to_be_visible()
    expect(page.locator(".scene-context-smart-recommendations li").first).to_contain_text("本场提到了「凯伊」")
    expect(page.get_by_role("button", name="加入", exact=True)).to_have_count(2)
