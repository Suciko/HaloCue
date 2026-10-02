from copy import deepcopy

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService
from test_scene_conversation_harness import create_ready_scene, create_scene_thread


class EditProvider(FakeWritingProvider):
    def __init__(self):
        self.mode = 'edit'

    def discuss_work(self, messages, context):
        manuscript = context['scene_conversation_context']['current_manuscript']
        pending = context['scene_conversation_context'].get('pending_text_edit') if self.mode == 'refine' else None
        block = (pending or manuscript)['content']['blocks'][0]
        if self.mode == 'discuss':
            return {'text': '可以让这句更简洁，保留雨夜气氛。', 'questions': [], 'ready_for_proposal': False}
        edits = [{'block_id': block['id'], 'old_text': block['text'], 'new_text': '窗外只剩零星雨声。' if pending else '窗外的雨渐渐停了。'}]
        if self.mode == 'multi':
            other = manuscript['content']['blocks'][1]
            edits.append({'block_id': other['id'], 'old_text': other['text'], 'new_text': '提示灯亮起来了。'})
        if self.mode == 'invalid':
            edits[0]['old_text'] = '模型猜测的原文'
        return {'text': '缩短了开头，保留雨停的氛围。', 'questions': [], 'ready_for_proposal': False,
                'tool_calls': [{'id': 'edit-1', 'tool': 'propose_scene_text_edit', 'arguments': {
                    'base_revision_id': manuscript['revision_id'], 'reason': '按作者要求润色开头', 'edits': edits,
                    **({'replace_proposal_id': pending['id']} if pending else {}),
                }}]}


@pytest.fixture
def prepared(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    saved = service.save_scene_manuscript(work_id, scene_id, {
        'expected_version': work['version'], 'base_revision_id': None,
        'blocks': [{'id': 'block-a', 'type': 'narration', 'text': '窗外下着一场雨。'},
                   {'id': 'block-b', 'type': 'dialogue', 'speaker': '爱丽丝', 'text': '提示灯亮了。'}],
    })
    current, thread = create_scene_thread(service, work_id, scene_id, saved['work'])
    provider = EditProvider()
    service.provider = provider
    yield service, provider, work_id, scene_id, current, thread
    service.close()


def send(prepared, text='润色开头的雨景，其他段落不改。', discussion_only=False):
    service, _, work_id, scene_id, _, thread = prepared
    return service.post_conversation_message(work_id, thread['id'], {
        'expected_thread_version': thread['version'], 'text': text,
        'task_scope': {'surface': 'scene', 'scene_id': scene_id, 'discussion_only': discussion_only},
    })


def test_chat_tool_links_review_and_keeps_formal_manuscript_until_application(prepared):
    service, _, work_id, scene_id, work, thread = prepared
    old = deepcopy(work['chapters'][0]['scenes'][0])
    result = send(prepared)
    proposal = next(p for p in result['work']['proposals'] if p['id'] == result['auto_proposal_id'])
    current = result['work']['chapters'][0]['scenes'][0]
    assert current['current_revision_id'] == old['current_revision_id']
    assert len(proposal['block_changes']) == 1
    assert proposal['block_changes'][0]['new_blocks'][0]['text'] == '窗外的雨渐渐停了。'
    message = next(t for t in result['work']['conversation_threads'] if t['id'] == thread['id'])['messages'][-1]
    assert message['proposal_id'] == proposal['id']
    run = next(r for r in result['work']['agent_runs'] if r['id'] == result['agent_run_id'])
    assert run['status'] == 'waiting_user'
    assert run['proposal_id'] == proposal['id']
    applied = service.accept_proposal(work_id, proposal['id'], {'expected_version': result['work']['version']})
    revision = next(a for a in applied['work']['artifacts'] if a['kind'] == 'scene_script' and a['scope_id'] == scene_id)['current_revision']['content']
    assert revision['blocks'][0]['text'] == '窗外的雨渐渐停了。'
    assert revision['blocks'][1]['text'] == '提示灯亮了。'


def test_pure_discussion_does_not_generate_edits(prepared):
    prepared[1].mode = 'discuss'
    result = send(prepared, '这句为什么不顺，只讨论，不要改正文。', True)
    assert 'auto_proposal_id' not in result
    assert not any(p['kind'] == 'scene_script' and p['status'] == 'pending' for p in result['work']['proposals'])


@pytest.mark.parametrize('discussion_only,mode', [(True, 'edit'), (False, 'invalid')])
def test_invalid_or_read_only_tool_cannot_propose(prepared, discussion_only, mode):
    prepared[1].mode = mode
    with pytest.raises(DomainError):
        send(prepared, discussion_only=discussion_only)
    work = prepared[0].get_work(prepared[2])
    assert not any(p['kind'] == 'scene_script' and p['status'] == 'pending' for p in work['proposals'])
    assert any(r['status'] == 'failed' for r in work['agent_runs'])


def test_explicit_no_edit_in_plain_chat_blocks_model_edit_tool(prepared):
    with pytest.raises(DomainError):
        send(prepared, '这句为什么不顺，只讨论，不要改正文。')
    work = prepared[0].get_work(prepared[2])
    assert not any(p['kind'] == 'scene_script' and p['status'] == 'pending' for p in work['proposals'])


def test_continue_chat_refines_pending_edit_without_applying_or_losing_other_text(prepared):
    service, provider, work_id, scene_id, work, thread = prepared
    provider.mode = 'multi'
    first = send(prepared)
    provider.mode = 'refine'
    updated = service.get_work(work_id)
    current_thread = next(t for t in updated['conversation_threads'] if t['id'] == thread['id'])
    second = service.post_conversation_message(work_id, thread['id'], {
        'expected_thread_version': current_thread['version'], 'text': '这份修改再克制一点，其他不改。',
        'task_scope': {'surface': 'scene', 'scene_id': scene_id}})
    proposals = {p['id']: p for p in second['work']['proposals']}
    assert proposals[first['auto_proposal_id']]['status'] == 'superseded'
    assert proposals[second['auto_proposal_id']]['status'] == 'pending'
    assert '窗外只剩零星雨声。' in proposals[second['auto_proposal_id']]['candidate']
    assert '提示灯亮起来了。' in proposals[second['auto_proposal_id']]['candidate']
    artifact = next(a for a in second['work']['artifacts'] if a['kind'] == 'scene_script' and a['scope_id'] == scene_id)
    assert artifact['current_revision']['content']['blocks'][0]['text'] == '窗外下着一场雨。'


@pytest.mark.parametrize('overlap', [False, True])
def test_disjoint_batches_merge_atomically_and_overlaps_fail(prepared, overlap):
    from halocue_writing.repository import sha256_text

    service, _, work_id, scene_id, work, thread = prepared
    class BatchProvider(FakeWritingProvider):
        def discuss_work(self, messages, context):
            manuscript = context['scene_conversation_context']['current_manuscript']
            blocks = manuscript['content']['blocks']
            calls = []
            for index in range(2):
                block = blocks[0 if overlap else index]
                calls.append({'id': f'edit-{index}', 'tool': 'propose_scene_text_edit', 'arguments': {
                    'base_revision_id': manuscript['revision_id'], 'reason': '按作者要求修改两段',
                    'edits': [{'block_id': block['id'], 'old_text_sha256': sha256_text(block['text']),
                               'new_text': f'改后第{index + 1}段。'}]}})
            return {'text': '已准备两段修改。', 'questions': [], 'ready_for_proposal': False, 'tool_calls': calls}
    service.provider = BatchProvider()
    if overlap:
        with pytest.raises(DomainError):
            send(prepared)
        assert not any(p['status'] == 'pending' and p['kind'] == 'scene_script' for p in service.get_work(work_id)['proposals'])
    else:
        try:
            result = send(prepared)
        except DomainError as error:
            pytest.fail(str(error.details))
        proposal = next(p for p in result['work']['proposals'] if p['id'] == result['auto_proposal_id'])
        assert len(proposal['block_changes']) == 2
        assert '改后第1段。' in proposal['candidate'] and '改后第2段。' in proposal['candidate']
    artifact = next(a for a in service.get_work(work_id)['artifacts'] if a['kind'] == 'scene_script' and a['scope_id'] == scene_id)
    assert artifact['current_revision']['content']['blocks'][0]['text'] == '窗外下着一场雨。'


def test_scoped_window_reads_pending_text_and_rejects_stale_or_foreign_base(prepared):
    service, _, work_id, scene_id, work, _ = prepared
    result = send(prepared)
    base_id = work['chapters'][0]['scenes'][0]['current_revision_id']
    arguments = {'base_revision_id': base_id, 'replace_proposal_id': result['auto_proposal_id'], 'query': '雨渐渐停'}
    with service.repo.transaction() as connection:
        window = service._read_scene_text_window(connection, work_id, scene_id, arguments)
        assert window['blocks'][0]['text'] == '窗外的雨渐渐停了。'
        assert window['blocks'][0]['paragraph_number'] == 1
        with pytest.raises(ValueError):
            service._read_scene_text_window(connection, work_id, scene_id, {**arguments, 'replace_proposal_id': 'wrong'})
        with pytest.raises(ValueError):
            service._read_scene_text_window(connection, 'other-work', scene_id, arguments)


def test_hash_edit_requires_exact_original_and_never_bypasses_version(prepared):
    service, _, work_id, scene_id, work, _ = prepared
    manuscript = next(a for a in work['artifacts'] if a['kind'] == 'scene_script' and a['scope_id'] == scene_id)['current_revision']
    block = manuscript['content']['blocks'][0]
    args = {'base_revision_id': manuscript['id'], 'reason': '润色', 'edits': [
        {'block_id': block['id'], 'old_text_sha256': '0' * 64, 'new_text': '改后正文。'}]}
    with service.repo.transaction() as connection:
        with pytest.raises(ValueError, match='原文不一致'):
            service._prepare_scene_text_edit(connection, work_id, scene_id, args)
        args['edits'][0].pop('old_text_sha256')
        with pytest.raises(ValueError, match='校验值'):
            service._prepare_scene_text_edit(connection, work_id, scene_id, args)
