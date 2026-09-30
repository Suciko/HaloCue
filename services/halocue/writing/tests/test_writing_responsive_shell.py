"""The real shell must own one full-width mobile track in every rail state."""
from pathlib import Path
import re
import pytest

WEB=Path(__file__).resolve().parents[1]/'web'

@pytest.mark.parametrize('surface',['writing','references','assets','tasks'])
@pytest.mark.parametrize('collapsed',['','tree-collapsed','inspector-collapsed','tree-collapsed inspector-collapsed'])
def test_mobile_shell_overrides_desktop_collapse_tracks(collapsed,surface):
    pw=pytest.importorskip('playwright.sync_api')
    html=(WEB/'index.html').read_text(encoding='utf8')
    names=[name for name in re.findall(r'<link[^>]+href="/([^"?]+)',html) if name.endswith('.css')]
    names=[name for name in names if name not in ['redesign.css','theme.css','authoring-ui.css']]+['redesign.css','theme.css','authoring-ui.css']
    html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S|re.I)
    html=re.sub(r'<link\b[^>]*>','',html,flags=re.I)
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':1440,'height':900})
            page.route('**/*',lambda route:route.abort())
            page.set_content(html)
            for name in names:
                page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
            page.evaluate('''({collapsed,surface})=>{
              document.body.classList.remove('app-loading');document.querySelector('#bootScreen')?.remove();
              const app=document.querySelector('#app');app.className='app-shell hc-redesign writing-workbench-stage has-panel-inspector '+collapsed;app.dataset.surface=surface;
              app.style.setProperty('--hc-left-width','0px');app.style.setProperty('--hc-right-width','340px');
              const workspace=document.querySelector('#workspace');workspace.hidden=false;
              workspace.innerHTML='<div class="chapter-continuous"><h2>第一章</h2><p>正文应该占满可用的窗口，而不是被桌面侧栏网格挤成窄条。</p></div>';
            }''',{'collapsed':collapsed,'surface':surface})
            # Resize in both directions; collapsed state/width preferences stay intact.
            for width in [760,700,390,375,760]:
                page.set_viewport_size({'width':width,'height':844})
                metrics=page.evaluate('''()=>{
                  const app=document.querySelector('#app'),main=document.querySelector('#workspace'),nav=document.querySelector('.mobile-nav');
                  return {width:innerWidth,main:main.getBoundingClientRect().width,left:main.getBoundingClientRect().left,nav:nav.getBoundingClientRect().width,columns:getComputedStyle(app).gridTemplateColumns,overflow:document.documentElement.scrollWidth>innerWidth};
                }''')
                assert metrics['main']>=width-2,metrics
                assert metrics['left']<2 and metrics['nav']>=width-2,metrics
                assert len(metrics['columns'].split())==1 and not metrics['overflow'],metrics
            page.set_viewport_size({'width':1440,'height':900})
            if surface=='writing':assert len(page.locator('#app').evaluate('e=>getComputedStyle(e).gridTemplateColumns').split())==6
            assert collapsed in page.locator('#app').get_attribute('class')
        finally:
            browser.close()
