"""Permission text must use the flexible column, in both authoring composers."""
from pathlib import Path
import pytest
from playwright.sync_api import expect
WEB=Path(__file__).resolve().parents[1]/'web'

@pytest.mark.parametrize('surface,viewport,rail', [('writing',1280,340),('writing',1280,240),('writing',390,358),('works',1280,600),('works',390,350)])
@pytest.mark.parametrize('theme',['light','dark'])
def test_permission_choices_readable_and_contained(surface,viewport,rail,theme):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'app.js').read_text(encoding='utf8')
    a=source.index('function renderPermissionMenu(thread){')
    renderer=source[a:source.index('\nfunction ',a+10)]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':viewport,'height':667},reduced_motion='reduce')
            page.set_content(f'<html data-theme="{theme}"><div id="app" class="hc-redesign writing-workbench-stage" data-surface="{surface}"><form id="fixture" class="scene-conversation-composer" style="position:fixed;bottom:20px;right:16px;width:{rail}px;height:160px"><div class="scene-agent-submit" style="margin-top:100px" id="menuHost"></div></form></div>')
            for name in ['styles.css','tokens.css','shell.css','writing-workbench.css','agent-workspace.css','redesign.css','theme.css','authoring-ui.css']:
                page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
            page.add_script_tag(content=renderer+";document.querySelector('#menuHost').innerHTML=renderPermissionMenu({permission_mode:'review'});")
            page.locator('.permission-menu > summary').click()
            menu=page.locator('.permission-popover')
            box=menu.bounding_box()
            assert box['x']>=0 and box['x']+box['width']<=viewport+1,box
            assert box['y']>=0 and box['y']+box['height']<=667,box
            for option in menu.locator('button').all():
                metrics=option.evaluate('''e=>({copy:e.querySelector('span').getBoundingClientRect().width,width:e.getBoundingClientRect().width,titleHeight:e.querySelector('b').getBoundingClientRect().height,copyFits:e.querySelector('span').scrollWidth<=e.querySelector('span').clientWidth})''')
                assert metrics['copy']>metrics['width']*.65,metrics
                assert metrics['titleHeight']<30 and metrics['copyFits'],metrics
            expect(menu.locator('[data-permission-mode="review"]')).to_have_attribute('aria-checked','true')
            expect(menu.locator('[data-permission-mode="managed"]')).to_have_attribute('aria-checked','false')
            expect(menu).to_contain_text('核心设定、大规模删除、冻结发布和 AA 交接始终需要确认。')
            page.set_viewport_size({'width':viewport,'height':520})
            assert menu.bounding_box()['y']>=0
            # Every choice remains reachable by keyboard even when menu scrolls.
            menu.locator('[data-permission-mode="managed"]').focus()
            expect(menu.locator('[data-permission-mode="managed"]')).to_be_in_viewport()
            page.locator('.permission-menu > summary').click()
            expect(menu).not_to_be_visible()
        finally:
            browser.close()