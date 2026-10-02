"""Direct scene entry actions use shipping handlers, without automatic model calls."""
from pathlib import Path
import pytest
from playwright.sync_api import expect
WEB=Path(__file__).resolve().parents[1]/'web'

@pytest.mark.parametrize('width',[1280,390])
def test_drafting_entry_prefills_preserves_draft_and_never_sends(width):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'writing-workbench.js').read_text(encoding='utf8')
    start=source.index("    const startDraft=event.target.closest('[data-start-scene-drafting]');")
    end=source.index("    const focusDiff =",start)
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':width,'height':844})
            page.set_content('<button data-start-scene-drafting>让 Agent 起草本场</button><button data-writing-mobile-view="agent">Agent</button><form id="sceneConversationForm"><textarea name="text" aria-label="指令"></textarea><button type="submit">发送</button></form>')
            page.add_script_tag(content='''
            const state={};let submissions=0,opened=0;
            function selectedScene(){return {id:'s',title:'旧广播室'};}
            function pendingProposal(){return null;}
            function claimAppEvent(){} function toast(){} function renderSceneAgentInspector(){}
            window.HaloCuePanels={open(){opened++;}};
            document.querySelector('[data-writing-mobile-view]').onclick=()=>{opened++;};
            document.querySelector('form').onsubmit=e=>{e.preventDefault();submissions++;};
            document.addEventListener('click',event=>{
            '''+source[start:end]+''' });''')
            page.get_by_role('button',name='让 Agent 起草本场',exact=True).click()
            field=page.get_by_role('textbox',name='指令')
            expect(field).to_be_focused()
            expect(field).to_have_value(__import__('re').compile('.*旧广播室.*'))
            assert page.evaluate('submissions')==0
            field.fill('我自己写的要求，不要替换')
            page.get_by_role('button',name='让 Agent 起草本场',exact=True).click()
            expect(field).to_have_value('我自己写的要求，不要替换')
            assert page.evaluate('submissions')==0
            assert page.evaluate('opened')==2
        finally:
            browser.close()