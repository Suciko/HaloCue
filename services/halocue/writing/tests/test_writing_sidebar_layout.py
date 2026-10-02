"""Writing directory uses the shipping renderer/styles at narrow rail widths."""
from pathlib import Path
import re

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.mark.parametrize("width", [180, 236, 320])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_sidebar_single_edge_and_readable_hierarchy(width, theme):
    pw = pytest.importorskip("playwright.sync_api")
    html = (WEB / "index.html").read_text(encoding="utf8")
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<link\b[^>]*>", "", html, flags=re.I)
    source = (WEB / "writing-workbench.js").read_text(encoding="utf8")
    renderer = source[source.index("  function renderWritingTree() {"):source.index("  function currentWritingVolume(")]
    styles = "\n".join((WEB / name).read_text(encoding="utf8") for name in [
        "styles.css", "tokens.css", "shell.css", "writing-workbench.css",
        "production-embed.css", "agent-workspace.css", "redesign.css", "theme.css", "authoring-ui.css",
    ])
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.route("**/*", lambda route: route.abort())
            page.set_content(html)
            page.add_style_tag(content=styles)
            page.evaluate("""({width,theme}) => {
                document.documentElement.dataset.theme=theme;
                document.body.classList.remove('app-loading');
                document.getElementById('bootScreen')?.remove();
                const app=document.getElementById('app');
                app.className='app-shell hc-redesign writing-workbench-stage inspector-collapsed has-panel-inspector';
                app.dataset.surface='writing'; app.style.setProperty('--hc-left-width',width+'px');
                document.getElementById('treePanel').hidden=false;
            }""", {"width": width, "theme": theme})
            page.add_script_tag(content="""
                const scene={id:'s',title:'走廊尽头的旧广播室',contract:{location:'广播室'},current_revision_id:null};
                const chapters=Array.from({length:20},(_,i)=>({id:'c'+i,title:i===0?'第1章 · 在旧广播室寻找失踪的声音':'第'+(i+1)+'章 · 雨后的约定',scenes:[{...scene,id:'s'+i}]}));
                const state={stage:'draft',sceneId:'s0',work:{title:'雨后的广播室与尚未寄出的来信',chapters,volumes:[{id:'v',title:'第一卷',chapters}]}};
                const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
                const chapterTreeExpansion=new Map();
                const writingChapter=()=>chapters[0];
                const stageGate=stage=>({allowed:stage!=='release',reason:'还有场景没有已采纳正文'});
                const blueprintIsConfirmed=()=>true;
                const writingReadinessView=()=>({blocked:false});
                const writingTreeVolumes=()=>state.work.volumes;
                const scenes=()=>chapters.flatMap(c=>c.scenes);
                const chapterStatus=()=>({tone:'idle',label:'待起草'});
            """ + renderer + "\nrenderWritingTree();")
            result=page.evaluate("""() => {
                const q=s=>document.querySelector(s), r=s=>q(s).getBoundingClientRect();
                const panel=q('#treePanel'), handle=q('.panel-resizer-left');
                const line=getComputedStyle(handle,'::before');
                return {
                    width:r('#treePanel').width, border:getComputedStyle(panel).borderRightWidth,
                    lineLeft:line.left, lineWidth:line.width, hitWidth:r('.panel-resizer-left').width,
                    edgeGap:r('.panel-resizer-left').left-r('#treePanel').right,
                    toggleCenter:r('.panel-divider-toggle-left').x+r('.panel-divider-toggle-left').width/2,
                    edge:r('#treePanel').right,
                    titleWidth:r('.chapter-copy b').width,
                    metaBelow:r('.chapter-meta').top>=r('.chapter-copy b').bottom,
                    metaFits:q('.chapter-meta').scrollWidth<=q('.chapter-meta').clientWidth,
                    tabsFit:[...document.querySelectorAll('.writing-stage-tabs button span')].every(e=>e.scrollWidth<=e.clientWidth),
                    hintFits:!q('.writing-stage-hint')||q('.writing-stage-hint').scrollWidth<=q('.writing-stage-hint').clientWidth,
                    headHeight:r('.writing-tree-head').height,
                    treeScroll:q('#sceneTree').scrollHeight>q('#sceneTree').clientHeight,
                    panelScroll:panel.scrollHeight>panel.clientHeight+1,
                    overflow:document.documentElement.scrollWidth>innerWidth,
                    hierarchyLine:getComputedStyle(q('.writing-scene-list')).borderLeftWidth,
                    statusInTitleRow:!!q('.writing-chapter-button > em'),
                };
            }""")
            assert abs(result['width']-width)<2, result
            assert result['border']=='0px' and result['lineLeft']=='0px' and result['lineWidth']=='1px', result
            assert result['hitWidth']>=12 and abs(result['edgeGap'])<1, result
            assert abs(result['toggleCenter']-result['edge'])<1, result
            assert result['titleWidth']>=90, result
            assert result['metaBelow'] and result['metaFits'] and not result['statusInTitleRow'], result
            assert result['tabsFit'] and result['hintFits'] and result['headHeight']<80, result
            assert result['treeScroll'] and not result['panelScroll'] and not result['overflow'], result
            assert result['hierarchyLine']=='0px', result
            # Interaction must never restore the detached, full-height accent line.
            handle=page.locator('.panel-resizer-left')
            line_color=handle.evaluate("e=>getComputedStyle(e,'::before').backgroundColor")
            handle.hover(position={"x":6,"y":40})
            assert handle.evaluate("e=>getComputedStyle(e,'::before').backgroundColor")==line_color
            assert handle.evaluate("e=>getComputedStyle(e).backgroundColor")=='rgba(0, 0, 0, 0)'
            assert handle.evaluate("e=>getComputedStyle(e,'::after').height")=='72px'
            assert handle.evaluate("e=>getComputedStyle(e,'::after').opacity")=='1'
            handle.focus()
            assert handle.evaluate("e=>getComputedStyle(e,'::before').backgroundColor")==line_color
            assert handle.evaluate("e=>getComputedStyle(e,'::after').opacity")=='1'
            page.locator('.writing-chapter-button').first.focus()
            page.locator('.writing-project-head').hover()
            assert handle.evaluate("e=>getComputedStyle(e,'::after').opacity")=='0'

            assert page.locator('.writing-stage-tabs').count()==0
            assert page.locator('.chapter-copy b').first.get_attribute('title')=='第1章 · 在旧广播室寻找失踪的声音'
            page.locator('.writing-chapter-button').first.focus()
            assert page.locator('.writing-chapter-button').first.evaluate("e=>getComputedStyle(e).outlineStyle")=='solid'
            # Expanding the directory must not navigate or disturb an unsaved editor.
            toggle_handler=source[source.index("    const chapterToggle=event.target.closest('[data-toggle-writing-chapter]');"):source.index("    const chapter = event.target.closest('[data-writing-chapter]');")]
            page.add_script_tag(content="const claimAppEvent=()=>{};document.addEventListener('click',event=>{"+toggle_handler+"});")
            page.evaluate("state.manuscriptDirty=true")
            toggle=page.locator('#sceneTree [data-toggle-writing-chapter]').first
            toggle.click()
            assert toggle.get_attribute('aria-expanded')=='false'
            assert page.evaluate("state.sceneId==='s0'&&state.stage==='draft'&&state.manuscriptDirty")
            toggle.press('Enter')
            assert toggle.get_attribute('aria-expanded')=='true'
            # Mobile clones this directory into a dialog outside #app.
            page.set_viewport_size({"width":390,"height":844})
            page.evaluate("""() => {
                const dialog=document.createElement('dialog');
                dialog.id='mobileSceneDrawer'; dialog.className='mobile-scene-drawer';
                dialog.innerHTML='<div class="mobile-scene-drawer-shell"><header>场景列表</header><div class="mobile-scene-drawer-tree">'+document.querySelector('#sceneTree').innerHTML+'</div><footer>管理章节与场景</footer></div>';
                document.body.append(dialog); dialog.showModal();
            }""")
            mobile=page.locator('#mobileSceneDrawer').evaluate("""e=>({
                fits:e.scrollWidth<=e.clientWidth,
                columns:getComputedStyle(e.querySelector('.writing-chapter-button')).gridTemplateColumns.split(' ').length,
                meta:getComputedStyle(e.querySelector('.chapter-meta')).display,
                title:e.querySelector('.chapter-copy b').getBoundingClientRect().width,
                row:e.querySelector('.writing-chapter-button').getBoundingClientRect().height
            })""")
            assert mobile['fits'] and mobile['columns']==3 and mobile['meta']=='flex', mobile
            assert mobile['title']>=90 and mobile['row']>=44, mobile
        finally:
            browser.close()
