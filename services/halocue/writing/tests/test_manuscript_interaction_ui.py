"""Pointer/keyboard regression using shipping manuscript handlers and styles."""

from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def manuscript_page():
    pw = pytest.importorskip("playwright.sync_api")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    markup = source[
        source.index("function blockRowMarkup(") : source.index(
            "function manuscriptInsertBarMarkup("
        )
    ]
    speaker_tones = source[
        source.index("function manuscriptSpeakerTones(") : source.index(
            "function activeManuscriptBlocks("
        )
    ]
    editing = source[
        source.index("function manuscriptCaretOffset(") : source.index(
            "document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='sceneManuscriptForm')"
        )
    ]
    with pw.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 740})
        page.set_content(
            '<main class="writing-workbench-stage"><form id="sceneManuscriptForm"></form><button id="outside">其他操作</button></main>'
        )
        page.add_style_tag(content=(WEB / "writing-workbench.css").read_text(encoding="utf-8"))
        page.add_script_tag(
            content="""
        const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
        const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
        const state={manuscriptDirty:false};
        function markManuscriptDirty(){state.manuscriptDirty=true;}
        function claimAppEvent(e){}
        function registerAppClick(fn){document.addEventListener('click',fn);}
        """
            + markup
            + speaker_tones
            + editing
            + """
        document.querySelector('form').innerHTML=blockRowMarkup({id:'block-test',type:'dialogue',speaker:'测试角色',text:'原始正文'},0);
        """
        )
        yield page
        browser.close()


@pytest.mark.parametrize("activation", ["pointer", "keyboard"])
def test_reading_block_can_enter_edit_mode(manuscript_page, activation):
    page = manuscript_page
    button = page.get_by_role("button", name="编辑第 01 段", exact=True)
    if activation == "pointer":
        button.click()
    else:
        button.focus()
        button.press("Enter")
    field = page.get_by_role("textbox", name="正文内容", exact=True)
    expect(field).to_be_visible()
    expect(field).to_be_focused()
    field.fill("未保存的测试正文")
    assert page.evaluate("state.manuscriptDirty")
    page.locator("#outside").click()
    expect(page.locator("[data-manuscript-block]")).not_to_have_class(re.compile("is-editing"))
    expect(button).to_contain_text("未保存的测试正文")
    button.click()
    expect(field).to_have_value("未保存的测试正文")


@pytest.mark.parametrize("theme,width", [("dark", 1440), ("dark", 390), ("light", 390)])
def test_unsaved_dialog_keeps_actions_visible_and_legible(manuscript_page, theme, width):
    page = manuscript_page
    page.set_viewport_size({"width": width, "height": 740})
    html = (WEB / "index.html").read_text(encoding="utf-8")
    start = html.index('  <dialog id="unsavedManuscriptDialog"')
    fragment = html[start : html.index("</dialog>", start) + len("</dialog>")]
    for name in ["tokens.css", "styles.css", "shell.css", "theme.css"]:
        page.add_style_tag(content=(WEB / name).read_text(encoding="utf-8"))
    page.evaluate("html => document.body.insertAdjacentHTML('beforeend', html)", fragment)
    page.evaluate(
        "theme => {document.documentElement.dataset.theme=theme; document.querySelector('#unsavedManuscriptDialog').showModal()}",
        theme,
    )
    for attr in ["cancel", "discard"]:
        button = page.locator(f"[data-unsaved-manuscript-{attr}]")
        expect(button).to_be_in_viewport()
        contrast = button.evaluate(r"""e => {
          const lum = color => {
            const rgb = color.match(/[\d.]+/g).slice(0,3).map(Number).map(c=>c/255)
              .map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4);
            return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
          };
          const style=getComputedStyle(e),a=lum(style.color),b=lum(style.backgroundColor);
          return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        }""")
        assert contrast >= 4.5
    if theme == "dark":
        background = page.locator(".unsaved-manuscript-actions").evaluate(
            "e=>getComputedStyle(e).backgroundColor"
        )
        assert background == "rgb(37, 45, 57)"


def test_mobile_writing_tabs_use_dark_surfaces(manuscript_page):
    page = manuscript_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.add_style_tag(content=(WEB / "theme.css").read_text(encoding="utf-8"))
    page.evaluate("""() => {
      document.documentElement.dataset.theme='dark';
      const root=document.querySelector('main');root.id='app';root.classList.add('hc-redesign');
      root.insertAdjacentHTML('afterbegin','<nav class="writing-mobile-tabs"><button class="active">正文</button><button>Agent</button></nav>');
    }""")
    tabs = page.locator(".writing-mobile-tabs")
    expect(tabs).to_be_visible()
    assert tabs.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgb(34, 42, 53)"
    assert (
        tabs.locator(".active").evaluate("e=>getComputedStyle(e).backgroundColor")
        == "rgb(43, 59, 82)"
    )


def test_dark_proposal_review_preserves_selected_and_diff_semantics(manuscript_page):
    page = manuscript_page
    for name in ["styles.css", "shell.css", "theme.css"]:
        page.add_style_tag(content=(WEB / name).read_text(encoding="utf-8"))
    page.evaluate("""() => {
      document.documentElement.dataset.theme='dark';
      const root=document.querySelector('main');root.id='app';root.classList.add('hc-redesign');
      root.innerHTML='<section class="scene-inline-review"><header class="desk-head"><h3>改动已标在这里</h3></header><div class="scene-diff-choices"><label class="scene-diff-choice"><input type="checkbox" checked><b>选择这项修改</b></label></div><div class="scene-full-context"><div class="scene-context-line is-added">新增正文</div><div class="scene-context-line is-removed">删除正文</div></div><footer class="scene-diff-actions">应用选中修改</footer></section>';
    }""")
    for selector in [
        ".desk-head",
        ".scene-diff-choices",
        ".scene-full-context",
        ".scene-diff-actions",
    ]:
        assert (
            page.locator(selector).evaluate("e=>getComputedStyle(e).backgroundColor")
            == "rgb(29, 35, 45)"
        )
    assert (
        page.locator(".scene-diff-choice").evaluate("e=>getComputedStyle(e).backgroundColor")
        == "rgb(43, 59, 82)"
    )
    assert (
        page.locator(".is-added").evaluate("e=>getComputedStyle(e).backgroundColor")
        == "rgb(37, 58, 49)"
    )
    assert (
        page.locator(".is-removed").evaluate("e=>getComputedStyle(e).backgroundColor")
        == "rgb(66, 45, 50)"
    )


def test_mobile_view_candidate_leaves_agent_before_focusing_diff(manuscript_page):
    page = manuscript_page
    page.set_viewport_size({"width": 390, "height": 844})
    source = (WEB / "writing-workbench.js").read_text(encoding="utf-8")
    start = source.index("  function focusSceneDiff(")
    handler = source[start : source.index("  function focusSceneReview()", start)]
    # Include the shipping motion helper; omitting it throws before focus runs.
    motion = next(line.strip() for line in source.splitlines() if "const scrollBehavior =" in line)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_script_tag(
        content="""
      state.writingMobileView='agent';state.inspector='agent';
      // focusSceneDiff normally closes over these workbench scroll guards.
      let chapterPositionTicket=0,chapterScrollIntentAt=0;
      function toast(){}
      function render(){document.querySelector('[data-scene-diff-root]').hidden=false;}
      document.body.insertAdjacentHTML('beforeend','<button id="viewCandidate">查看候选</button><div data-scene-diff-root hidden><input type="checkbox" aria-label="选择修改"></div>');
    """
        + motion
        + handler
        + "document.querySelector('#viewCandidate').addEventListener('click',focusSceneDiff)"
    )
    page.locator("#viewCandidate").click()
    expect(page.locator("[data-scene-diff-root]")).to_be_visible()
    expect(page.get_by_role("checkbox", name="选择修改")).to_be_focused()
    assert page.evaluate("state.writingMobileView") == "manuscript"
    assert page.evaluate("state.inspector") == "agent"
    assert errors == []


def test_return_to_specific_change_keeps_mobile_agent_dom_and_draft(manuscript_page):
    page = manuscript_page
    page.set_viewport_size({"width": 390, "height": 844})
    source = (WEB / "writing-workbench.js").read_text(encoding="utf-8")
    start = source.index("  function focusSceneDiff(")
    handler = source[start:source.index("  function focusSceneReview()", start)]
    motion = next(line.strip() for line in source.splitlines() if "const scrollBehavior =" in line)
    page.add_script_tag(content="""
      state.writingMobileView='agent';state.inspector='agent';
      // focusSceneDiff normally closes over these workbench scroll guards.
      let chapterPositionTicket=0,chapterScrollIntentAt=0;
      function toast(){}
      let renders=0;
      function render(){renders++;document.querySelector('#agentDraft').remove();}
      document.body.insertAdjacentHTML('beforeend',`<button data-writing-mobile-view="manuscript">正文</button>
        <button id="returnChange">返回这项</button><textarea id="agentDraft">保留这份草稿</textarea>
        <section data-scene-diff-root hidden>
          <article data-review-change="one"><input type="checkbox" aria-label="第一项" checked></article>
          <article data-review-change="two"><input type="checkbox" aria-label="第二项"><details class="scene-review-detail"><summary>改前改后</summary>完整内容</details></article>
        </section>`);
      document.querySelector('[data-writing-mobile-view]').addEventListener('click',()=>{
        state.writingMobileView='manuscript';
        document.querySelector('[data-scene-diff-root]').hidden=false;
      });
    """ + motion + handler + "document.querySelector('#returnChange').onclick=()=>focusSceneDiff('two');")
    for _ in range(2):
        page.evaluate("state.writingMobileView='agent'")
        page.locator('#returnChange').click()
        expect(page.get_by_role('checkbox', name='第二项')).to_be_focused()
        expect(page.locator('#agentDraft')).to_have_value('保留这份草稿')
        expect(page.get_by_role('checkbox', name='第一项')).to_be_checked()
        expect(page.get_by_role('checkbox', name='第二项')).not_to_be_checked()
        assert page.evaluate('renders') == 0
        assert page.evaluate('state.inspector') == 'agent'
        assert page.locator('.scene-review-detail').evaluate('e=>e.open')


def test_async_projection_render_keeps_current_manuscript_editor_and_caret(manuscript_page):
    page = manuscript_page
    source = (WEB / "app.js").read_text(encoding="utf-8")
    helpers = source[source.index("function captureTransientView()"):source.index("document.addEventListener('compositionstart'")]
    page.add_script_tag(content="""
      let hcLastViewKey='work-a/scene-a';const hcTransientViews=new Map();
      document.querySelector('main').id='workspace';
      document.querySelector('form').dataset.sceneId='scene-a';
    """ + helpers)
    page.get_by_role("button", name="编辑第 01 段", exact=True).click()
    field = page.get_by_role("textbox", name="正文内容", exact=True)
    field.fill("尚未保存的一段文字")
    field.press("ArrowLeft")
    caret = field.evaluate("el=>el.selectionStart")
    page.evaluate("""()=>{
      captureTransientView();
      document.querySelector('form').innerHTML=blockRowMarkup({id:'block-test',type:'dialogue',speaker:'测试角色',text:'尚未保存的一段文字'},0);
      restoreTransientView(hcLastViewKey);
    }""")
    expect(field).to_be_visible()
    expect(field).to_be_focused()
    assert field.evaluate("el=>el.selectionStart") == caret
    expect(field).to_have_value("尚未保存的一段文字")
    # A different scene must never inherit this block's editing state or focus.
    page.locator("#outside").click()
    page.evaluate("""()=>{
      document.querySelector('form').dataset.sceneId='scene-b';
      document.querySelector('form').innerHTML=blockRowMarkup({id:'block-test',type:'narration',text:'另一场'},0);
      restoreTransientView(hcLastViewKey);
    }""")
    expect(page.locator('[data-manuscript-block] textarea[name="text"]')).not_to_be_focused()
    expect(page.locator('[data-manuscript-block]')).not_to_have_class(re.compile('is-editing'))
