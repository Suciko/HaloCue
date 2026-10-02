"""Top save/shortcuts submit the shipping manuscript handler, never Agent APIs."""
from pathlib import Path
import re
import pytest
from playwright.sync_api import expect

WEB=Path(__file__).resolve().parents[1]/'web'

@pytest.fixture
def save_page():
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'app.js').read_text(encoding='utf8')
    helper=source[source.index('function syncTopManuscriptSave('):source.index('function manuscriptNavigationControl(')]
    submit=source[source.index("document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='sceneManuscriptForm')"):source.index('\nfunction renderInspector()',source.index("document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='sceneManuscriptForm')"))]
    html=(WEB/'index.html').read_text(encoding='utf8')
    top=html[html.index('    <header class="topbar'):html.index('</header>',html.index('    <header class="topbar'))+9]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        page=browser.new_page(viewport={'width':1280,'height':844})
        page.set_content('<div id="app" class="hc-redesign writing-workbench-stage" data-surface="writing">'+top+'''<main id="workspace"><form id="sceneManuscriptForm" data-scene-id="s" data-base-revision="r1"><textarea aria-label="正文内容" required>未保存正文</textarea><button data-manuscript-edit type="button">编辑正文</button><button type="submit">底部保存</button></form></main><textarea id="agent" aria-label="Agent 指令"></textarea><dialog id="settings"><input aria-label="设置字段"></dialog></div>''')
        page.on('pageerror',lambda error:pytest.fail(str(error)))
        page.add_script_tag(content='''
          const state={surface:'writing',stage:'draft',work:{id:'w',version:3},manuscriptDirty:true,manuscriptSceneId:'s'};
          let hcRenderAgain=false,pendingSave,requests=[],notices=[];
          const scenes=()=>[{id:'s',chapter_id:'c'}];
          const readManuscriptBlocks=()=>[{id:'b',type:'narration',text:document.querySelector('#sceneManuscriptForm textarea').value}];
          const toast=(text)=>notices.push(text);
          const setBusy=text=>document.querySelector('#saveStatus').textContent=text;
          const api=(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return new Promise((resolve,reject)=>{pendingSave={resolve,reject}})};
          const render=()=>{hcRenderAgain=false;document.querySelector('#saveStatus').textContent=state.manuscriptDirty?'正文未保存':'已保存';syncTopManuscriptSave()};
        '''+helper+submit+'''
          syncTopManuscriptSave();
        ''')
        yield page
        browser.close()

@pytest.mark.parametrize('action',['button','Control+s','Meta+s'])
def test_save_uses_existing_revision_endpoint_once(save_page,action):
    page=save_page
    if action=='button':page.locator('#topManuscriptSave').click()
    else:page.get_by_role('textbox',name='正文内容',exact=True).press(action)
    expect(page.locator('#topManuscriptSave')).to_be_disabled()
    expect(page.locator('#topManuscriptSave')).to_have_text('保存中…')
    assert page.locator('#sceneManuscriptForm').evaluate('e=>e.inert')
    page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'s',ctrlKey:true,bubbles:true,cancelable:true}));document.querySelector('form').requestSubmit()")
    assert page.evaluate('requests.length')==1
    assert page.evaluate('requests[0]')=={'url':'/works/w/scenes/s/manuscript','body':{'expected_version':3,'expected_base_revision_id':'r1','blocks':[{'id':'b','type':'narration','text':'未保存正文'}]}}
    page.evaluate("pendingSave.resolve({work:{id:'w',version:4},superseded_proposal_ids:[]})")
    expect(page.locator('#topManuscriptSave')).to_be_hidden()
    expect(page.locator('#saveStatus')).to_have_text('已保存')
    assert not page.locator('#sceneManuscriptForm').evaluate('e=>e.inert')
    assert page.evaluate('state.manuscriptDirty') is False
    if action=='button':expect(page.get_by_role('button',name='编辑正文',exact=True)).to_be_focused()


def test_save_failure_keeps_draft_and_retry_available(save_page):
    page=save_page
    page.locator('#topManuscriptSave').click()
    page.evaluate("pendingSave.reject(new Error('模拟保存失败'))")
    expect(page.locator('#topManuscriptSave')).to_be_enabled()
    expect(page.locator('#topManuscriptSave')).to_be_focused()
    expect(page.get_by_role('textbox',name='正文内容',exact=True)).to_have_value('未保存正文')
    assert page.evaluate('state.manuscriptDirty') is True
    page.locator('#topManuscriptSave').click()
    assert page.evaluate('requests.length')==2
    page.evaluate("pendingSave.resolve({work:{id:'w',version:4}})")
    expect(page.locator('#topManuscriptSave')).to_be_hidden()


def test_shortcut_ignores_composer_settings_repeat_and_clean_scene(save_page):
    page=save_page
    page.get_by_role('textbox',name='Agent 指令',exact=True).press('Control+s')
    assert page.evaluate('requests.length')==0
    page.evaluate("document.querySelector('#settings').showModal()")
    page.get_by_role('textbox',name='设置字段',exact=True).press('Control+s')
    assert page.evaluate('requests.length')==0
    page.evaluate("document.querySelector('#settings').close();document.dispatchEvent(new KeyboardEvent('keydown',{key:'s',ctrlKey:true,repeat:true,bubbles:true,cancelable:true}));state.manuscriptDirty=false;syncTopManuscriptSave()")
    page.get_by_role('textbox',name='正文内容',exact=True).press('Control+s')
    expect(page.locator('#topManuscriptSave')).to_be_hidden()
    assert page.evaluate('requests.length')==0
    page.evaluate("state.manuscriptDirty=true;state.stage='structure';syncTopManuscriptSave()")
    page.get_by_role('textbox',name='正文内容',exact=True).press('Control+s')
    expect(page.locator('#topManuscriptSave')).to_be_hidden()
    assert page.evaluate('requests.length')==0
    page.evaluate("state.stage='draft';document.querySelector('#sceneManuscriptForm').remove();syncTopManuscriptSave()")
    expect(page.locator('#topManuscriptSave')).to_be_hidden()
    page.keyboard.press('Control+s')
    assert page.evaluate('requests.length')==0


@pytest.mark.parametrize('width,theme',[(390,'light'),(390,'dark'),(761,'light'),(820,'dark'),(1280,'light')])
def test_dirty_header_keeps_save_and_work_switch_in_bounds(save_page,width,theme):
    page=save_page
    page.set_viewport_size({'width':width,'height':600})
    html=(WEB/'index.html').read_text(encoding='utf8')
    names=[name for name in re.findall(r'<link[^>]+href="/([^"?]+)',html) if name.endswith('.css')]
    names=[name for name in names if name not in ['redesign.css','theme.css','authoring-ui.css']]+['redesign.css','theme.css','authoring-ui.css']
    for name in names:page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
    page.evaluate('''theme=>{
      document.documentElement.dataset.theme=theme;
      document.querySelector('#currentWorkName').textContent='这是一本非常长的作品名称，用来验证顶部空间';
      document.querySelector('#saveStatus').textContent='正文未保存';
      document.querySelector('.panel-controls').hidden=false;
    }''',theme)
    expect(page.locator('#topManuscriptSave')).to_be_visible()
    expect(page.locator('#saveStatus')).to_be_visible()
    boxes=page.locator('.hc-work-switch,#topManuscriptSave,#saveStatus').evaluate_all('els=>els.map(e=>({x:e.getBoundingClientRect().x,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width}))')
    assert boxes[0]['width']>=90,boxes
    assert all(box['x']>=0 and box['right']<=width+1 for box in boxes),boxes
    assert boxes[0]['right']<=boxes[1]['x'],boxes
def test_save_keeps_native_validation_and_blocks_leave_while_saving(save_page):
    page=save_page
    field=page.get_by_role('textbox',name='正文内容',exact=True)
    field.fill('')
    page.locator('#topManuscriptSave').click()
    assert page.evaluate('requests.length')==0
    expect(field).to_be_focused()
    field.fill('通过校验的正文')
    source=(WEB/'app.js').read_text(encoding='utf8')
    guard=source[source.index('function requestManuscriptNavigation('):source.index('function routeKeepsCurrentManuscript(')]
    page.add_script_tag(content=guard+';let leftScene=false;')
    page.locator('#topManuscriptSave').click()
    page.evaluate('requestManuscriptNavigation(()=>{leftScene=true})')
    assert page.evaluate('leftScene') is False
    assert page.evaluate('notices.at(-1)')=='正在保存正文，请稍候再切换。'
    page.evaluate("pendingSave.resolve({work:{id:'w',version:4}})")
    expect(page.locator('#topManuscriptSave')).to_be_hidden()

@pytest.mark.parametrize('outcome',['success','failure'])
def test_save_from_assistant_preserves_instruction_and_never_sends(save_page,outcome):
    page=save_page
    source=(WEB/'app.js').read_text(encoding='utf8')
    start=source.index('<div class="scene-manuscript-notice"')
    markup=source[start:source.index('<label class="sr-only" for="sceneAgentMessage">',start)]
    page.add_script_tag(content='''
      const composer=document.createElement('form');composer.id='sceneConversationForm';
      composer.innerHTML=`'''+markup+'''<textarea name="text" aria-label="本场要求">保留我写的对白，只补充后续动作。</textarea><button type="submit">发送</button>`;
      document.querySelector('#app').append(composer);
      let agentSends=0;
      composer.onsubmit=e=>{e.preventDefault();agentSends++};
      syncSceneManuscriptNotice();
    ''')
    notice=page.locator('[data-scene-manuscript-notice]')
    save=page.locator('[data-save-for-agent]')
    expect(notice).to_be_visible()
    save.click()
    expect(save).to_be_disabled()
    expect(save).to_have_text('保存中…')
    assert page.evaluate('requests.length')==1
    assert page.evaluate('agentSends')==0
    assert page.evaluate('requests[0].url')=='/works/w/scenes/s/manuscript'
    expect(page.get_by_role('textbox',name='本场要求')).to_have_value('保留我写的对白，只补充后续动作。')
    if outcome=='success':
        page.evaluate("pendingSave.resolve({work:{id:'w',version:4}})")
        expect(notice).to_be_hidden()
        expect(page.get_by_role('textbox',name='本场要求')).to_be_focused()
    else:
        page.evaluate("pendingSave.reject(new Error('模拟保存失败'))")
        expect(notice).to_be_visible()
        expect(save).to_be_enabled()
        expect(save).to_be_focused()
        expect(page.get_by_role('textbox',name='正文内容',exact=True)).to_have_value('未保存正文')
    assert page.evaluate('agentSends')==0
    expect(page.get_by_role('textbox',name='本场要求')).to_have_value('保留我写的对白，只补充后续动作。')


@pytest.mark.parametrize('width,theme',[(390,'light'),(390,'dark'),(1280,'dark')])
def test_assistant_save_notice_layout_and_scope(save_page,width,theme):
    page=save_page
    page.set_viewport_size({'width':width,'height':844})
    source=(WEB/'app.js').read_text(encoding='utf8')
    start=source.index('<div class="scene-manuscript-notice"')
    markup=source[start:source.index('<label class="sr-only" for="sceneAgentMessage">',start)]
    page.add_script_tag(content='''
      const aside=document.createElement('aside');aside.style.width='min(100%, 300px)';
      aside.innerHTML=`'''+markup+'''`;document.querySelector('#app').append(aside);
      syncSceneManuscriptNotice();
    ''')
    for name in ['tokens.css','authoring-ui.css']:
        page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
    page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
    notice=page.locator('[data-scene-manuscript-notice]')
    expect(notice).to_be_visible()
    box=notice.bounding_box();button=page.locator('[data-save-for-agent]').bounding_box()
    assert button['x']>=box['x'] and button['x']+button['width']<=box['x']+box['width']+1
    assert box['height']<170
    page.evaluate("state.manuscriptSceneId='another-scene';syncSceneManuscriptNotice()")
    expect(notice).to_be_hidden()
    page.evaluate("state.manuscriptSceneId='s';state.manuscriptDirty=false;syncSceneManuscriptNotice()")
    expect(notice).to_be_hidden()
