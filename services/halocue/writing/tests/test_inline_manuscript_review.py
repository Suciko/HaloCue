"""Changed ranges replace paragraphs in the shipping chapter reading flow."""
import pytest
from pathlib import Path
from playwright.sync_api import expect

from test_authoring_workspace_browser import browser, local_authoring  # noqa: F401
from test_scene_conversation_harness import create_ready_scene, create_scene_thread
from halocue_writing.providers import FakeWritingProvider


class MultiEditProvider(FakeWritingProvider):
    target_indices = (1, 3)
    def discuss_work(self, messages, context):
        manuscript = context['scene_conversation_context']['current_manuscript']
        blocks = manuscript['content']['blocks']
        return {'text': '已润色两处，修改显示在对应正文里。', 'questions': [],
                'ready_for_proposal': False, 'tool_calls': [{
                    'id': 'edit-inline', 'tool': 'propose_scene_text_edit', 'arguments': {
                        'base_revision_id': manuscript['revision_id'], 'reason': '润色两段',
                        'edits': [{'block_id': blocks[i]['id'], 'old_text': blocks[i]['text'],
                                   'new_text': f'润色后的第{i+1}段。'} for i in self.target_indices]}}]}


@pytest.mark.parametrize('width', [1366, 390])
def test_inline_review_preserves_positions_and_partial_application(local_authoring, browser, width):
    service, url = local_authoring
    work_id, scene_id, work = create_ready_scene(service)
    chapter_id = work['chapters'][0]['id']
    originals = [{'id': f'block-{i}', 'type': 'narration', 'speaker': '',
                  'text': f'原来的第{i+1}段。'} for i in range(5)]
    saved = service.save_scene_manuscript(work_id, scene_id, {
        'expected_version': work['version'], 'blocks': originals})
    current, thread = create_scene_thread(service, work_id, scene_id, saved['work'])
    service.provider = MultiEditProvider()
    result = service.post_conversation_message(work_id, thread['id'], {
        'expected_thread_version': thread['version'], 'text': '润色第二段和第四段，其余不改。',
        'task_scope': {'surface': 'scene', 'scene_id': scene_id}})
    proposal = next(p for p in result['work']['proposals'] if p['id'] == result['auto_proposal_id'])
    assert len(proposal['block_changes']) == 2
    page = browser.new_page(viewport={'width': width, 'height': 900})
    page.goto(f'{url}/?section=writing&stage=draft&work_id={work_id}&chapter_id={chapter_id}&scene_id={scene_id}')
    # Mobile starts in manuscript; both changes are visible without a disclosure.
    expect(page.locator('.chapter-inline-change')).to_have_count(2)
    expect(page.locator('.chapter-authoring-related').filter(has_text='本场有待审')).to_have_count(0)
    order = page.locator('[data-chapter-blocks] > .chapter-inline-review').evaluate(
        "node=>[...node.children].filter(x=>x.matches('[data-chapter-block],.chapter-inline-change')).map(x=>x.getAttribute('aria-label'))")
    assert order == ['第 1 段', '段落修改 · 第 2 段', '第 3 段', '段落修改 · 第 4 段', '第 5 段']
    # Switching view captures the original text, never candidate text.
    page.get_by_role('button', name='阅读', exact=True).click()
    expect(page.locator('[data-chapter-save]')).to_be_disabled()
    page.get_by_role('button', name='编辑', exact=True).click()
    page.locator('[data-scene-change]').nth(1).uncheck()
    expect(page.locator('[data-apply-scene-changes]').first).to_have_text('应用 1 项修改')
    expect(page.locator('[data-apply-scene-changes]').last).to_have_text('应用 1 项修改')
    page.locator('[data-apply-scene-changes]').first.click()
    expect(page.locator('.chapter-inline-change')).to_have_count(0)
    actual = service.get_work(work_id)
    blocks = next(a for a in actual['artifacts'] if a['kind'] == 'scene_script' and a['scope_id'] == scene_id)['current_revision']['content']['blocks']
    assert [b['text'] for b in blocks] == ['原来的第1段。', '润色后的第2段。', '原来的第3段。', '原来的第4段。', '原来的第5段。']
    page.close()


@pytest.mark.parametrize('kind,start,end', [('insert',0,0),('replace',1,3),('delete',1,3)])
def test_projection_handles_complete_multi_paragraph_ranges(browser, kind, start, end):
    web = Path(__file__).resolve().parents[1]/'web'
    source = (web/'chapter-authoring-ui.js').read_text(encoding='utf-8')
    helper = source[source.index('  function manuscriptRows('):source.index('  const section=')]
    page = browser.new_page(viewport={'width':390,'height':844})
    page.set_content('<div class="chapter-authoring" id="host"></div>')
    page.add_style_tag(content=(web/'chapter-authoring-ui.css').read_text(encoding='utf-8'))
    page.add_script_tag(content='''
      const state={sceneDiffSelections:{}},escape=value=>String(value).replaceAll('<','&lt;'),entry=()=>null,base=()=> 'rev';
      const row=(scene,block,index)=>`<article data-chapter-block aria-label="第 ${index+1} 段">${block.text}</article>`;
      const readRow=row,insertRow=()=>'';
    '''+helper)
    page.evaluate('''({kind,start,end})=>{
      const blocks=Array.from({length:4},(_,i)=>({id:'b'+i,type:'narration',text:'原文'+i}));
      const changes=[{id:'change',kind,base_start:start,base_end:end,old_blocks:blocks.slice(start,end),new_blocks:kind==='delete'?[]:[{type:'narration',text:'改后甲'},{type:'narration',text:'改后乙'}]}];
      document.querySelector('#host').innerHTML=manuscriptRows({id:'scene'},blocks,false,{id:'proposal',base_revision_id:'rev',block_changes:changes});
    }''', {'kind':kind,'start':start,'end':end})
    expect(page.locator('.chapter-inline-change')).to_have_count(1)
    expect(page.locator('.chapter-inline-before .chapter-inline-copy')).to_have_count(end-start)
    expect(page.locator('.chapter-inline-after .chapter-inline-copy')).to_have_count(0 if kind=='delete' else 2)
    original_order=page.locator('[data-chapter-block]').all_text_contents()
    assert original_order==['原文0','原文1','原文2','原文3']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.close()


def test_chat_result_locates_changed_paragraph_without_review_button(local_authoring, browser):
    service, url = local_authoring
    work_id, scene_id, work = create_ready_scene(service)
    chapter_id = work['chapters'][0]['id']
    blocks = [{'id': f'block-{i}', 'type': 'narration', 'speaker': '', 'text': f'原来的第{i+1}段。'} for i in range(12)]
    saved = service.save_scene_manuscript(work_id, scene_id, {'expected_version': work['version'], 'blocks': blocks})
    create_scene_thread(service, work_id, scene_id, saved['work'])
    service.provider = MultiEditProvider()
    service.provider.target_indices = (8, 10)
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    page.goto(f'{url}/?section=writing&stage=draft&work_id={work_id}&chapter_id={chapter_id}&scene_id={scene_id}')
    composer = page.locator('#sceneConversationForm textarea')
    expect(composer).to_be_enabled()
    composer.fill('润色第二段和第四段，其余不改。')
    page.locator('#sceneConversationForm').get_by_role('button', name='发送', exact=True).click()
    expect(page.locator('.chapter-inline-change')).to_have_count(2, timeout=20000)
    # Check against the actual scroll container; is_visible alone includes
    # offscreen paragraphs and would miss the navigation regression.
    page.wait_for_function("""()=>{const change=document.querySelector('.chapter-inline-change'),workspace=document.querySelector('#workspace');if(!change||!workspace)return false;const a=change.getBoundingClientRect(),b=workspace.getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom;}""")
    # The chapter review response refreshes the manuscript independently later.
    # Verify the settled position as well as the first animation frame.
    page.wait_for_timeout(1200)
    assert page.evaluate("""()=>{const change=document.querySelector('.chapter-inline-change'),workspace=document.querySelector('#workspace');const a=change.getBoundingClientRect(),b=workspace.getBoundingClientRect();return a.top>=b.top&&a.bottom<=b.bottom;}""")
    page.close()
