"""Exercise the shipping scene composer markup, styles and resize/key handlers."""
from pathlib import Path
import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"

@pytest.mark.parametrize("width,height,theme", [(1280,844,"light"),(1280,844,"dark"),(390,844,"light"),(390,844,"dark"),(820,520,"dark")])
def test_composer_surface_growth_keyboard_and_actions(width,height,theme):
    pw=pytest.importorskip("playwright.sync_api")
    source=(WEB/"app.js").read_text(encoding="utf8")
    start=source.index('<form id="sceneConversationForm" class="scene-conversation-composer"')
    markup=source[start:source.index('</form>',start)+7]
    helper=source[source.index('function syncSceneComposerSize('):source.index('function syncSceneManuscriptNotice(')]
    start=source.index("document.addEventListener('input',event=>{\n  if(event.target.matches?.('#sceneConversationForm textarea'))")
    permission=source[source.index('function renderPermissionMenu('):source.index('function renderMobileAgent(',source.index('function renderPermissionMenu('))]
    handlers=source[start:source.index('const renderInspectorBeforeSceneAgent=',start)]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={"width":width,"height":height})
            page.set_content(f'<html data-theme="{theme}"><div id="app" class="hc-redesign writing-workbench-stage" data-surface="writing"><aside id="inspectorContent" style="width:min(340px,100%);margin-left:auto"></aside></div></html>')
            for name in ['styles.css','tokens.css','shell.css','writing-workbench.css','redesign.css','theme.css','authoring-ui.css']:
                page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
            page.add_style_tag(content='#app#app{display:block!important;width:100%!important;height:auto!important} #inspectorContent{display:block!important;padding:12px!important;box-sizing:border-box}')
            page.on('pageerror',lambda error:pytest.fail(str(error)))
            page.add_script_tag(content=permission+'''
              const state={manuscriptDirty:false},scene={id:'scene-test'},discussionOnly=false,canChat=true,canPropose=true,existing=true,thread={permission_mode:'review'}; const discussionNotice='';
              const composerPlaceholder='说说这一场想怎么写…';
              const sendAction='<button type="submit" class="primary">发送</button>';
              const esc=value=>String(value);
              document.querySelector('aside').innerHTML=`'''+markup+'''`;
              let sends=0;document.querySelector('form').onsubmit=e=>{e.preventDefault();sends++};
            '''+helper+handlers+'syncSceneComposerSize();')
            field=page.get_by_role('textbox')
            form=page.locator('#sceneConversationForm')
            assert field.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
            assert field.evaluate('e=>getComputedStyle(e).resize')=='none'
            assert page.locator('.scene-agent-submit').evaluate('e=>getComputedStyle(e).borderTopWidth')=='0px'
            assert field.bounding_box()['height']==96
            field.fill('需要讨论的后续衔接。\n'*30)
            limit=max(96,min(224,int(height*.24)))
            assert 96<field.bounding_box()['height']<=limit
            assert field.evaluate('e=>e.scrollHeight>e.clientHeight')
            field.fill('短句')
            assert field.bounding_box()['height']==96
            field.press('Shift+Enter')
            assert '\n' in field.input_value()
            assert page.evaluate('sends')==0
            field.evaluate("e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true,cancelable:true}))")
            assert page.evaluate('sends')==0
            field.press('Enter')
            assert page.evaluate('sends')==1
            expect(page.locator('[data-save-for-agent]')).to_be_hidden()
            # The send selector must not accidentally choose the cross-form save button.
            assert page.locator('button[type="submit"]:not([form])').inner_text()=='发送'
            send_box=page.locator('.scene-agent-submit > .primary').bounding_box()
            assert send_box['width']<=120
            assert page.locator('[data-generate-scene-proposal]').count()==0
            assert page.locator('.permission-menu').count()==0
            expect(page.locator('#sceneConversationForm .agent-chips')).to_have_count(0)
            bounds=form.bounding_box()
            for button in page.locator('.agent-chips button,.scene-agent-submit > .primary').all():
                b=button.bounding_box()
                assert b['x']>=bounds['x'] and b['x']+b['width']<=bounds['x']+bounds['width']+1
            assert page.locator('#sceneComposerHint').is_visible()==(width>760)
        finally:
            browser.close()
