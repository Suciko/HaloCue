"""Synthetic proposals rendered by shipping functions, styles and selection handlers."""
import os
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / 'web'
APP = (WEB / 'app.js').read_text(encoding='utf-8')


def function(name):
    start = APP.index(f'function {name}(')
    return APP[start:APP.index('\nfunction ', start + 10)]


@pytest.fixture
def review_page():
    pw = pytest.importorskip('playwright.sync_api')
    html = (WEB / 'index.html').read_text(encoding='utf-8')
    styles = '\n'.join((WEB / href.split('?')[0].lstrip('/')).read_text(encoding='utf-8')
                       for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"', html))
    with pw.sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        page.set_content('<html data-theme="dark"><body><main id="app" class="hc-redesign"><section id="review-root" style="max-width:900px;margin:32px auto;padding:0 16px"></section></main></body></html>')
        page.add_style_tag(content=styles)
        page.add_style_tag(content='html,body{height:auto!important;overflow:auto!important} #app.hc-redesign{display:block!important;height:auto!important;min-height:100vh!important;overflow:visible!important} #review-root{width:100%} .message-bubble{min-width:0}')
        page.add_script_tag(content=(WEB / 'change-review.js').read_text(encoding='utf-8'))
        page.add_script_tag(content='''
          const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
          const state={sceneDiffSelections:{},work:{id:'synthetic-work',version:7,artifacts:[]}};
          const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
          const selectedScene=()=>({id:'synthetic-scene'});
          const sceneScriptArtifact=()=>({current_revision:{content:{blocks:[]}}});
          const sceneProposalRuntimeMarkup=()=>'',sceneProposalImpactMarkup=()=>'';
          const registerAppClick=handler=>document.addEventListener('click',handler);
          const claimAppEvent=()=>{},toast=()=>{},setBusy=()=>{},render=()=>{};
          let requests=[];
          const api=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {work:state.work};};
        ''' + '\n'.join(function(name) for name in [
            'proposalChangeReviewMarkup', 'workAgentProposalMarkup', 'sceneScriptLineParts',
            'sceneContextLineMarkup', 'sceneFullContextMarkup', 'sceneChangePreviewMarkup', 'sceneProposalReviewMarkup'
        ]) + APP[APP.index('function updateSceneDiffSelection('):APP.index('function captureManuscriptDraft(')])
        yield page
        browser.close()


def screenshot(page, name):
    if folder := os.environ.get('HALOCUE_UI_SHOTS'):
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path / name), full_page=True)


def render_direction(page):
    page.evaluate('''() => {
      document.querySelector('#app').dataset.surface='works';
      document.querySelector('#review-root').className='';
      state.work.artifacts=[
        {kind:'brief',current_revision:{id:'brief-1',content:{idea:'雨后车站里的失落录音',constraints:'结尾必须在午夜发生'}}},
        {kind:'story_blueprint',current_revision:{id:'blueprint-1',content:{title:'雨后的车站',premise:'一人独自寻找失落的录音',direction:['沿着车站广播追查线索']}}}
      ];
      window.proposal={id:'proposal-test',kind:'brief_blueprint',status:'pending',candidate:{
        base_brief_revision_id:'brief-1',base_blueprint_revision_id:'blueprint-1',
        brief:{idea:'雨后车站里的失落录音'},
        story_blueprint:{title:'雨后的车站',premise:'两名伙伴对录音的处置产生分歧',central_conflict:'公开真相，还是保护朋友？',direction:['沿着车站广播追查线索']}
      }};
      document.querySelector('#review-root').innerHTML=workAgentProposalMarkup(proposal);
    }''')


def render_scene(page):
    page.evaluate('''() => {
      document.querySelector('#app').dataset.surface='writing';
      document.querySelector('#review-root').className='writing-workbench-stage';
      const block=(text,speaker='测试角色')=>({type:'dialogue',speaker,text});
      window.proposal={id:'scene-proposal',kind:'scene_script',status:'pending',candidate:'测试角色：别急，先听完这段录音。\\n旁白：远处传来了脚步声。',block_changes:[
        {id:'replace-one',kind:'replace',base_start:0,base_end:1,old_blocks:[block('我们赶紧离开这里。')],new_blocks:[block('别急，先听完这段录音。')]},
        {id:'insert-two',kind:'insert',base_start:1,base_end:1,old_blocks:[],new_blocks:[{type:'narration',text:'远处传来了脚步声。'}]},
        {id:'delete-three',kind:'delete',base_start:2,base_end:3,old_blocks:[block('一段将被删除的重复解释。')],new_blocks:[]}
      ]};
      document.querySelector('#review-root').innerHTML=sceneProposalReviewMarkup(proposal,{inline:true});
    }''')


@pytest.mark.parametrize('theme,width', [('dark',1280),('light',1280),('dark',390),('light',390)])
def test_direction_review_full_content_keyboard_and_responsive_layout(review_page,theme,width):
    page=review_page
    page.set_viewport_size({'width':width,'height':1000})
    page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
    render_direction(page)
    expect(page.get_by_role('region',name='AI 改动清单')).to_be_visible()
    assert page.locator('.change-review').bounding_box()['width'] > min(width * .6, 600)
    expect(page.locator('.change-count.is-add')).to_contain_text('1')
    expect(page.locator('.change-count.is-modify')).to_contain_text('1')
    expect(page.locator('.change-count.is-remove')).to_contain_text('1')
    item=page.locator('.change-review-item.is-modify')
    item.locator('summary').focus()
    page.keyboard.press('Enter')
    expect(item.locator('.is-before')).to_contain_text('一人独自寻找')
    expect(item.locator('.is-after')).to_contain_text('两名伙伴')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    for side in page.locator('.change-review-item[open] .change-review-side').all():
        ratio=side.evaluate(r'''e=>{
          const lum=c=>{const [r,g,b]=c.match(/[\d.]+/g).slice(0,3).map(Number).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*r+.7152*g+.0722*b;};
          const s=getComputedStyle(e),a=lum(s.color),b=lum(s.backgroundColor);return(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        }''')
        assert ratio>=4.5
    assert page.evaluate('requests.length')==0
    screenshot(page,f'direction-{theme}-{width}.png')


@pytest.mark.parametrize('width',[1280,390])
def test_scene_selective_apply_uses_exact_reviewed_change_ids(review_page,width):
    page=review_page
    page.set_viewport_size({'width':width,'height':1000})
    render_scene(page)
    expect(page.locator('.scene-review-change')).to_have_count(3)
    assert page.locator('.scene-review-list').evaluate('e=>e.scrollHeight<=e.clientHeight+1')
    expect(page.locator('.scene-review-detail[open] .is-before').first).to_contain_text('我们赶紧离开这里')
    expect(page.locator('.scene-review-detail[open] .is-after').first).to_contain_text('先听完这段录音')
    page.locator('[data-scene-change][value="insert-two"]').uncheck()
    page.locator('[data-scene-change][value="delete-three"]').uncheck()
    expect(page.locator('[data-scene-diff-count]')).to_have_text('已选择 1 / 3 项')
    expect(page.locator('[data-apply-scene-changes]')).to_have_text('应用 1 项修改')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    screenshot(page,f'scene-dark-{width}.png')
    page.locator('[data-apply-scene-changes]').click()
    assert page.evaluate('requests')==[{'url':'/works/synthetic-work/proposals/scene-proposal/accept',
        'body':{'expected_version':7,'selected_change_ids':['replace-one'],'note':'应用 1 项正文修改'}}]


def test_scene_select_all_empty_selection_and_escape_safe_long_text(review_page):
    page=review_page
    render_scene(page)
    page.locator('[data-select-all-scene-changes]').click()
    expect(page.locator('[data-apply-scene-changes]')).to_be_disabled()
    expect(page.locator('[data-scene-change]:checked')).to_have_count(0)
    page.locator('[data-select-all-scene-changes]').click()
    expect(page.locator('[data-scene-change]:checked')).to_have_count(3)
    render_direction(page)
    page.evaluate('''() => {
      proposal.candidate.story_blueprint.premise='<img src=x onerror=alert(1)>'+ '完整文字'.repeat(100)+'结尾证据';
      document.querySelector('#review-root').innerHTML=workAgentProposalMarkup(proposal);
    }''')
    page.locator('.change-review-item.is-modify > summary').click()
    expect(page.locator('.change-review-item.is-modify .is-after')).to_contain_text('结尾证据')
    expect(page.locator('.change-review img')).to_have_count(0)
    assert page.evaluate('requests.length')==0

def test_expand_all_is_scoped_and_never_changes_scene_selection(review_page):
    page=review_page
    render_scene(page)
    selected=page.locator('[data-scene-change]:checked').count()
    page.get_by_role('button',name='收起全部',exact=True).click()
    expect(page.locator('.scene-review-detail[open]')).to_have_count(0)
    expect(page.locator('[data-scene-change]:checked')).to_have_count(selected)
    expect(page.locator('[data-scene-change-preview]').first).to_be_visible()
    button=page.get_by_role('button',name='展开全部',exact=True)
    button.focus()
    button.press('Enter')
    expect(page.locator('.scene-review-detail[open]')).to_have_count(3)
    expect(page.locator('[data-scene-change]:checked')).to_have_count(selected)
    expect(page.locator('[data-scene-change-preview]').first).not_to_be_visible()
    assert page.evaluate('requests.length')==0


def test_work_review_preview_and_bulk_disclosure_do_not_toggle_other_documents(review_page):
    page=review_page
    render_direction(page)
    page.evaluate("document.querySelector('#review-root').insertAdjacentHTML('beforeend','<details id=unrelated><summary>其他文档</summary>不要展开</details>')")
    expect(page.locator('.change-review-item.is-modify .change-review-preview')).to_contain_text('两名伙伴')
    page.get_by_role('button',name='展开全部',exact=True).click()
    expect(page.locator('.change-review-item[open]')).to_have_count(3)
    assert not page.locator('#unrelated').evaluate('e=>e.open')
    page.get_by_role('button',name='收起全部',exact=True).click()
    expect(page.locator('.change-review-item[open]')).to_have_count(0)
    assert page.evaluate('requests.length')==0


def test_discuss_button_is_separate_from_selection_label(review_page):
    page=review_page
    render_scene(page)
    target=page.get_by_role('button',name='讨论第 2 项改动',exact=True)
    target.click()
    expect(page.locator('[data-scene-change]:checked')).to_have_count(3)
    assert target.evaluate('e=>e.closest("label")===null')
    assert page.evaluate('requests.length')==0
