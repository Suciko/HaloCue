"""Chapter-first navigation retains the heading; later anchors remain precise."""
from pathlib import Path
import pytest
WEB=Path(__file__).resolve().parents[1]/'web'

@pytest.mark.parametrize('width',[1280,390])
def test_first_scene_keeps_chapter_heading_and_later_scene_aligns(width):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'writing-workbench.js').read_text(encoding='utf8')
    code=source[source.index('  function scrollToChapterScene('):source.index('  function focusChapterScene(')]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':width,'height':800})
            page.set_content('''<main class="workspace" id="workspace" style="height:600px;overflow:auto"><div class="chapter-continuous"><header class="chapter-continuous-head" style="height:160px"><h2>第一章 · 开端</h2><button>章节操作</button></header><nav class="writing-mobile-tabs" style="height:44px">正文 / Agent</nav><section id="chapter-scene-a" data-chapter-scene-anchor="a" style="height:1400px">第一场</section><section id="chapter-scene-b" data-chapter-scene-anchor="b" style="height:1400px">第二场</section></div></main>''')
            page.add_script_tag(content="const scrollBehavior=()=> 'instant';"+code)
            page.evaluate("document.querySelector('#workspace').scrollTop=450;scrollToChapterScene('a')")
            assert page.locator('#workspace').evaluate('e=>e.scrollTop')==0
            assert page.locator('.chapter-continuous-head').bounding_box()['y']>=page.locator('#workspace').bounding_box()['y']
            page.evaluate("scrollToChapterScene('b')")
            offset=page.locator('#chapter-scene-b').bounding_box()['y']-page.locator('#workspace').bounding_box()['y']
            assert abs(offset-(56 if width<=760 else 18))<2
        finally:
            browser.close()
@pytest.mark.parametrize('interrupt',['none','reading','chapter','agent','newer'])
def test_scheduled_position_does_not_override_newer_intent(interrupt):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'writing-workbench.js').read_text(encoding='utf8')
    code=source[source.index('  function scheduleChapterPosition('):source.index('  function focusChapterScene(')]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':390,'height':800})
            page.set_content('<p>定位回归</p>')
            page.add_script_tag(content='''
              const state={work:{id:'w'},writingChapterId:'c',sceneId:'s',surface:'writing',stage:'draft',writingMobileView:'manuscript'};
              let chapterPositionTicket=0,chapterScrollIntentAt=0,frames=[],positions=[];
              window.requestAnimationFrame=fn=>frames.push(fn);
              const scrollToChapterScene=id=>positions.push(id);
            '''+code)
            page.evaluate('''interrupt=>{
              scheduleChapterPosition('s');
              if(interrupt==='reading')chapterScrollIntentAt=10;
              if(interrupt==='chapter')state.writingChapterId='new';
              if(interrupt==='agent')state.writingMobileView='agent';
              if(interrupt==='newer'){state.sceneId='next';scheduleChapterPosition('next');}
              frames.forEach(fn=>fn());
            }''',interrupt)
            assert page.evaluate('positions')==(['s'] if interrupt=='none' else ['next'] if interrupt=='newer' else [])
        finally:
            browser.close()


@pytest.mark.parametrize('interrupt',['none','reading','chapter','agent'])
def test_mobile_return_restores_position_without_fighting_reader(interrupt):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'writing-workbench.js').read_text(encoding='utf8')
    start=source.index("    const mobileView = event.target.closest('.writing-mobile-tabs button[data-writing-mobile-view]');")
    handler=source[start:source.index("    const sceneDrawer = event.target.closest('[data-mobile-scene-drawer]');",start)]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':390,'height':800})
            page.set_content('''<div id="app"><nav class="writing-mobile-tabs"><button data-writing-mobile-view="manuscript">正文</button><button data-writing-mobile-view="agent">Agent</button></nav><main id="workspace" style="height:400px;overflow:auto"><div id="flow" data-chapter-scene-anchor="s" class="is-current" style="height:2500px">很长的正文</div></main></div>''')
            page.add_script_tag(content='''
              const state={work:{id:'w'},writingChapterId:'c',sceneId:'s',surface:'writing',stage:'draft',writingMobileView:'manuscript'};
              let mobileViewTicket=0,chapterScrollIntentAt=0,mobileScrollTop=0,mobileScrollSceneId='',timers=[];
              const claimAppEvent=()=>{},scenes=()=>[{id:'s'}],syncSceneChrome=()=>{};
              const moveInspectorToMobilePane=()=>{document.querySelector('#flow').hidden=state.writingMobileView!=='manuscript'};
              window.setTimeout=fn=>timers.push(fn);window.requestAnimationFrame=fn=>timers.push(fn);
              document.addEventListener('click',event=>{'''+handler+'''});
            ''')
            page.evaluate('''()=>{
              document.querySelector('#workspace').scrollTop=630;
              document.querySelector('[data-writing-mobile-view="agent"]').click();
              document.querySelector('[data-writing-mobile-view="manuscript"]').click();
            }''')
            page.evaluate('''interrupt=>{
              if(interrupt==='reading'){chapterScrollIntentAt=10;document.querySelector('#workspace').scrollTop=840;}
              if(interrupt==='chapter'){state.writingChapterId='other';document.querySelector('#workspace').scrollTop=120;}
              if(interrupt==='agent')document.querySelector('[data-writing-mobile-view="agent"]').click();
              const pending=timers.splice(0);pending.forEach(fn=>fn());
            }''',interrupt)
            expected={'none':630,'reading':840,'chapter':120,'agent':0}[interrupt]
            assert page.locator('#workspace').evaluate('e=>e.scrollTop')==expected
            assert page.evaluate('state.sceneId')=='s'
        finally:
            browser.close()