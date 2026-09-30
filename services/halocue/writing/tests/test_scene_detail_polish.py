"""State-specific author actions and compact assistant render with shipping CSS."""
from pathlib import Path
import re
import pytest
from playwright.sync_api import expect
WEB=Path(__file__).resolve().parents[1]/'web'
NOTICE='新的讨论已经建立。我会读取当前作品的正式上下文，但不会把其他对话当作已经确认的事实。'

@pytest.mark.parametrize('mode',['empty','ready','existing','pending','preparing'])
@pytest.mark.parametrize('width,theme',[(1280,'light'),(1280,'dark'),(820,'dark'),(390,'light')])
def test_scene_detail_states(mode,width,theme):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'app.js').read_text(encoding='utf8')
    helpers=source[source.index('function sceneConversationMessageMarkup('):source.index('function latestFailedSceneAgentRun(')]
    action=source[source.index('function sceneDraftActionMarkup('):source.index('function renderDraft(el){\n',source.index('function sceneDraftActionMarkup('))]
    renderer=source[source.index('function renderSceneAgentInspector('):source.index('const renderSceneAgentInspectorWithSelection=')]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':width,'height':844})
            page.set_content(f'<html data-theme="{theme}"><div id="app" class="hc-redesign writing-workbench-stage" data-surface="writing"><main id="primary"></main><aside id="inspectorContent"></aside></div>')
            for name in ['styles.css','tokens.css','shell.css','writing-workbench.css','redesign.css','theme.css','authoring-ui.css','chapter-authoring-ui.css']:
                page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
            page.add_style_tag(content='#app#app{display:block!important}#inspectorContent{width:min(340px,100%);height:700px}')
            page.evaluate('(mode)=>window.testMode=mode',mode)
            page.add_script_tag(content='''
              const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
              const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
              const state={context:testMode==='preparing'?null:{},work:{review_findings:[]},sceneDiffSelections:{}};
              const scene={id:'s',title:'广播室',chapterTitle:'第一章',current_revision_id:testMode==='existing'?'r':null};
              const proposal=testMode==='pending'?{id:'p',block_changes:[{}]}:null;
              const thread={id:'t',messages:[{id:'notice',role:'assistant',kind:'notice',content:{text:'新的讨论已经建立。我会读取当前作品的正式上下文，但不会把其他对话当作已经确认的事实。'}}]};
              const selectedScene=()=>scene,pendingProposal=()=>proposal;
              const sceneReadinessView=()=>({canRun:!['empty','preparing'].includes(testMode),needsCharacterCard:testMode==='empty',missingCharacters:['安'],label:'还缺少人物卡',detail:'缺少人物卡：安。这些人物目前没有已确认并加入本场上下文的卡片。'});
              const sceneConversationThread=()=>thread,workAgentActiveRun=()=>null,sceneAgentRecoveryMarkup=()=>'',renderPermissionMenu=()=>'',libraryCards=()=>[];
              const messageText=m=>m.content.text,agentProseMarkup=text=>'<p>'+esc(text)+'</p>',sceneUserMessageMarkup=agentProseMarkup;
              const sceneAgentComposerDrafts=new Map();
            '''+helpers+action+renderer+'''
              document.querySelector('#primary').innerHTML=sceneDraftActionMarkup(scene,proposal);
              renderSceneAgentInspector();
            ''')
            labels={'empty':'与助手讨论','ready':'与助手讨论','existing':'修改本场正文','pending':'查看待审修改','preparing':'与助手讨论'}
            expect(page.locator('#primary button')).to_have_text(labels[mode])
            if mode=='pending':assert page.locator('#primary button').get_attribute('data-focus-scene-diff') is not None
            else:assert page.locator('#primary button').get_attribute('data-show-scene-agent') is not None
            expect(page.locator('#sceneConversationForm .agent-chips')).to_have_count(0)
            assert len(page.locator('#sceneAgentMessage').get_attribute('placeholder'))<25
            expect(page.locator('.scene-start-note')).to_be_visible()
            assert page.locator('.scene-start-note').get_attribute('open') is None
            page.locator('.scene-start-note summary').click()
            expect(page.locator('.scene-start-note p')).to_have_text(NOTICE)
            if mode=='empty':
                expect(page.locator('.scene-agent-state')).to_be_hidden()
                # Character-card completion is now a scene-local Agent action; the
                # old library navigation duplicated the conversation workflow.
                expect(page.locator('[data-agent-complete-cards]')).to_be_visible()
                expect(page.locator('.scene-discussion-mode')).to_contain_text('缺少人物卡：安')
                expect(page.locator('.scene-discussion-mode')).to_contain_text('手写也是可选路径，不是必经步骤')
                expect(page.locator('.scene-discussion-mode')).not_to_contain_text('可以先在左侧手写')
                expect(page.locator('[data-start-scene-manual]')).to_have_text('直接手写正文')
                # Candidate generation is an Agent conversation/tool action, not a
                # second disabled button in the scene panel.
                expect(page.locator('[data-generate-scene-proposal]')).to_have_count(0)
                assert page.locator('#sceneConversationForm').get_attribute('data-discussion-only')=='true'
                expect(page.locator('.scene-discussion-mode')).to_contain_text('正文候选暂不可生成')
                expect(page.locator('.scene-discussion-mode')).to_contain_text('消耗模型用量')
                expect(page.locator('#sceneAgentMessage')).to_have_attribute('placeholder',re.compile('不写正文'))
                if theme=='dark':
                    background=page.locator('.scene-discussion-mode').evaluate('(node)=>getComputedStyle(node).backgroundColor')
                    assert background=='rgb(37, 45, 57)'
            elif mode=='preparing':
                expect(page.locator('.scene-discussion-mode')).to_contain_text('正在检查起草条件')
                expect(page.locator('.scene-discussion-mode')).to_contain_text('系统正在读取本场已确认资料')
                expect(page.locator('[data-action="assemble-context"]')).to_have_count(0)
                expect(page.locator('[data-start-scene-manual]')).to_be_visible()
            else:
                expect(page.locator('.scene-discussion-mode')).to_have_count(0)
            if mode=='pending':expect(page.locator('.scene-agent-review-link')).to_be_visible()
            # Only the exact initial notice collapses; substantive notices and replies survive.
            page.evaluate('''()=>{
              thread.messages=[{id:'a',role:'assistant',kind:'reply',content:{text:'新的讨论已经建立。我会读取当前作品的正式上下文，但不会把其他对话当作已经确认的事实。'}},{id:'b',role:'assistant',kind:'notice',content:{text:'保存失败，请重试'}}];
              renderSceneAgentInspector();
            }''')
            expect(page.locator('.scene-start-note')).to_have_count(0)
            expect(page.locator('.scene-message-body').last).to_contain_text('保存失败，请重试')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        finally:
            browser.close()
@pytest.mark.parametrize('width',[1280,390])
@pytest.mark.parametrize('initial',['','未发送的原始要求'])
def test_discuss_action_preserves_unsent_text_and_focuses_composer(width,initial):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'writing-workbench.js').read_text(encoding='utf8')
    start=source.index("    if(event.target.closest('[data-show-scene-agent]')){")
    handler=source[start:source.index("    const startDraft=event.target.closest('[data-start-scene-drafting]');",start)]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':width,'height':844})
            page.set_content('<button data-show-scene-agent data-scene-entry-prompt="按大纲讨论，不直接写入正文">与助手讨论</button><button data-writing-mobile-view="agent">Agent</button><form id="sceneConversationForm"><textarea name="text" aria-label="指令">未发送的原始要求</textarea></form>')
            page.get_by_role('textbox',name='指令').fill(initial)
            page.add_script_tag(content='''
              const state={inspector:'agent'};let renders=0,opens=0,sends=0;
              const claimAppEvent=()=>{},renderSceneAgentInspector=()=>{renders++};
              window.HaloCuePanels={open:()=>{opens++}};
              document.querySelector('form').onsubmit=e=>{e.preventDefault();sends++};
              document.querySelector('[data-writing-mobile-view]').onclick=e=>requestAnimationFrame(()=>e.target.focus());
              document.addEventListener('click',event=>{'''+handler+'''});
            ''')
            page.get_by_role('button',name='与助手讨论',exact=True).click()
            expect(page.get_by_role('textbox',name='指令')).to_be_focused()
            expect(page.get_by_role('textbox',name='指令')).to_have_value(initial or '按大纲讨论，不直接写入正文')
            assert page.evaluate('renders')==0
            assert page.evaluate('sends')==0
        finally:
            browser.close()
