"""Empty manuscript entry and compact Agent hints use shipping markup/CSS."""
from pathlib import Path
import pytest
from playwright.sync_api import expect

WEB=Path(__file__).resolve().parents[1]/'web'

def function(source,name,next_name):
    return source[source.index('function '+name+'('):source.index('function '+next_name+'(')]

@pytest.mark.parametrize('width,theme',[(1280,'light'),(1280,'dark'),(390,'light'),(390,'dark')])
def test_empty_writing_entry_focus_save_and_hint_layout(width,theme):
    pw=pytest.importorskip('playwright.sync_api')
    source=(WEB/'app.js').read_text(encoding='utf8')
    workbench=(WEB/'writing-workbench.js').read_text(encoding='utf8')
    entry=function(source,'manuscriptListMarkup','manuscriptSpeakerTones')
    inline=source[source.index('function chapterInlineManuscriptMarkup('):source.index('\nchapterReadonlySceneMarkup=')]
    dirty=function(source,'syncTopManuscriptSave','discardManuscriptDraft')+function(source,'markManuscriptDirty','manuscriptCaretOffset')
    hint=workbench[workbench.index('      if(nextCommand){'):workbench.index('      // The continuous chapter renderer owns the command bar.')]
    blocks=function(source,'blockRowMarkup','manuscriptInsertBarMarkup')
    insert=function(source,'manuscriptInsertBarMarkup','manuscriptListMarkup')
    tones=function(source,'manuscriptSpeakerTones','activeManuscriptBlocks')
    editing=source[source.index('function manuscriptCaretOffset('):source.index("document.addEventListener('submit',async event=>{const form=event.target;if(form.id!=='sceneManuscriptForm')")]
    with pw.sync_playwright() as driver:
        browser=driver.chromium.launch()
        try:
            page=browser.new_page(viewport={'width':width,'height':844})
            page.set_content(f'<html data-theme="{theme}"><body><div id="app" class="hc-redesign writing-workbench-stage" data-surface="writing"><span id="saveStatus">已保存</span><main style="width:calc(100% - 48px);max-width:820px;margin:auto"><section class="next-command"><div><small>当前下一步</small><strong></strong><p></p></div><div class="command-actions"></div></section><div id="editor"></div></main></div></body></html>')
            for name in ['styles.css','tokens.css','shell.css','writing-workbench.css','redesign.css','theme.css','authoring-ui.css']:
                page.add_style_tag(content=(WEB/name).read_text(encoding='utf8'))
            page.on('pageerror', lambda error: pytest.fail(str(error)))
            page.add_style_tag(content='#app#app{display:block !important;width:100% !important;height:auto !important}')
            page.add_script_tag(content='''
              const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
              const esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
              const state={manuscriptDirty:false,context:{},manuscriptBlockCounter:0};
              const activeManuscriptBlocks=()=>[]; const selectedScene=()=>({id:'s'}); const pendingProposal=()=>null;
              const nextCommand=document.querySelector('.next-command'); const readiness={canRun:false};
              const clearSceneTextSelection=()=>{}; const captureManuscriptDraft=()=>{};
              const claimAppEvent=()=>{}; const makeClientBlockId=()=> 'block-local';
              const registerAppClick=fn=>document.addEventListener('click',fn);
            '''+blocks+insert+entry+tones+inline+dirty+editing+hint+'''
              document.querySelector('#editor').innerHTML=chapterInlineManuscriptMarkup({id:'s'},null);
            ''')
            expect(page.locator('#sceneManuscriptForm button[type=submit]')).to_be_disabled()
            expect(page.locator('#sceneManuscriptForm button[type=submit]')).to_be_hidden()
            expect(page.locator('#manuscriptSaveState')).to_be_hidden()
            expect(page.locator('#manuscriptSaveState')).to_have_text('尚未开始')
            expect(page.get_by_role('button',name='自己写',exact=True)).to_have_count(0)
            expect(page.get_by_role('button',name='补齐人物卡',exact=True)).to_have_count(0)
            expect(page.get_by_role('button',name='按大纲讨论',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='导入已有文稿',exact=True)).to_be_visible()
            assert page.get_by_role('button',name='导入已有文稿').get_attribute('data-aap-import') is not None
            expect(page.locator('.manuscript-writing-entry')).to_contain_text('粘贴已有片段')
            box=page.locator('.next-command').bounding_box()
            assert box['height']<145
            assert page.locator('.manuscript-writing-entry').bounding_box()['y'] - (box['y']+box['height']) < 40
            assert page.locator('.manuscript-empty').bounding_box()['height'] < 200
            expect(page.locator('.next-command button')).to_have_count(0)
            assert page.locator('.next-command > div').first.bounding_box()['width']>160
            page.get_by_role('button',name='开始写作',exact=True).press('Enter')
            field=page.get_by_role('textbox',name='正文内容',exact=True)
            expect(field).to_be_focused()
            expect(page.locator('.manuscript-entry-options')).to_have_count(0)
            field.fill('直接写下第一句，不需要 Agent。')
            expect(page.get_by_role('button',name='保存正文',exact=True)).to_be_enabled()
            expect(page.locator('#manuscriptSaveState')).to_have_text('未保存修改')
            expect(page.locator('#saveStatus')).to_have_text('正文未保存')
            assert page.locator('[data-manuscript-block]').count()==1
        finally:
            browser.close()