"""The scrollport fills the workspace; only readable content is width limited."""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / 'web'


@pytest.mark.parametrize('width,height,theme', [(1756,1000,'light'),(1280,800,'dark'),(390,844,'light'),(390,560,'dark')])
@pytest.mark.parametrize('started', [True, False])
def test_conversation_scrollport_reaches_workspace_edge(width,height,theme,started):
    pw=pytest.importorskip('playwright.sync_api')
    index=(WEB/'index.html').read_text(encoding='utf-8')
    styles='\n'.join((WEB/href.split('?')[0].lstrip('/')).read_text(encoding='utf-8') for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"',index))
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            sidebar=260 if width>760 else 0
            messages=''.join('<article class="conversation-message assistant"><div class="message-column"><div class="message-bubble"><p>保留清晰的阅读宽度，但滚动条应当属于整个主工作区。</p></div></div></article>' for _ in range(20)) if started else '<div class="hc-idea-empty"><h2>从这一幕，开始你的故事</h2><p>说说你的想法。</p></div>'
            page.set_content(f'''<html data-theme="{theme}"><body><div id="app" class="hc-redesign app-shell work-agent-stage" data-surface="works">
              <main id="workspace" class="workspace"><section class="hc-idea-canvas work-agent-canvas {'has-conversation' if started else 'is-start'}">
              <header class="hc-canvas-header"><h1>创作主对话</h1><button>待处理</button></header>
              <section class="work-agent-thread" data-work-discussion-scroll>{messages}</section>
              <div class="work-agent-bottom"><form class="work-agent-composer"><textarea aria-label="消息" placeholder="描述你想怎样修改剧本"></textarea><div class="composer-actions"><button type="button">审核协作</button><button type="button">发送</button></div></form><p class="hc-composer-hint">采纳前不改动作品</p></div>
              </section></main></div></body></html>''')
            page.add_style_tag(content=styles)
            page.add_style_tag(content=f'#app#app.hc-redesign{{display:block!important}} #app#app.hc-redesign #workspace{{position:fixed!important;grid-area:auto!important;margin:0!important;left:{sidebar}px!important;right:0!important;top:56px!important;bottom:0!important;width:auto!important;height:auto!important;padding:0!important}}')
            metrics=page.evaluate('''() => {
              const w=document.querySelector('#workspace'),s=document.querySelector('.work-agent-thread'),c=document.querySelector('.hc-idea-canvas'),b=document.querySelector('.work-agent-composer');
              const wr=w.getBoundingClientRect(),sr=s.getBoundingClientRect(),br=b.getBoundingClientRect();
              return {edge:Math.abs(wr.right-sr.right),left:Math.abs(wr.left-sr.left),outerOverflow:w.scrollHeight-w.clientHeight,canvasWidth:c.getBoundingClientRect().width,workspaceWidth:wr.width,composerRight:br.right,composerLeft:br.left,composerBottom:br.bottom,composerWidth:br.width,horizontal:document.documentElement.scrollWidth-innerWidth,viewport:innerHeight};
            }''')
            assert metrics['edge']<=2,metrics
            assert metrics['left']<=2,metrics
            assert metrics['horizontal']<=1,metrics
            assert metrics['composerWidth']<=824,metrics
            if metrics['workspaceWidth']>1000:
                assert 810<=metrics['composerWidth']<=824,metrics
            assert metrics['composerBottom']<=height,metrics
            assert metrics['composerLeft']>=sidebar,metrics
            if started:
                assert metrics['outerOverflow']<=2,metrics
                before=page.locator('.hc-canvas-header').bounding_box()
                page.locator('[data-work-discussion-scroll]').evaluate('e=>e.scrollTop=200')
                assert page.locator('.hc-canvas-header').bounding_box()==before
        finally:
            browser.close()
