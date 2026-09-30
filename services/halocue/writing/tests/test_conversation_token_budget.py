import pytest
import halocue_writing.conversation_summary as summary_module

from halocue_writing.agent_tools import ToolExecutionContext
from halocue_writing.conversation_summary import recent_conversation_history, validate_conversation_summary
from halocue_writing.service import WritingService
from halocue_writing.repository import canonical_json
from halocue_writing.errors import DomainError


def test_long_history_is_archived_with_sources_and_original_can_be_read_in_chunks(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({'title': '长对话预算'})
    thread = work['conversation_threads'][0]
    long_text = '不要改变结局。' + '背景细节。' * 9000
    with service.repo.transaction() as connection:
        original_id = service._append_conversation_message(connection, thread['id'], 'user', 'text', {'text': long_text})
        service._append_conversation_message(connection, thread['id'], 'assistant', 'text', {'text': '已记录。'})
        service._append_conversation_message(connection, thread['id'], 'user', 'text', {'text': '继续润色开头，保留结局。'})
        history = recent_conversation_history(connection, thread['id'])
        assert [m['text'] for m in history] == ['已记录。', '继续润色开头，保留结局。']
        summary = service._conversation_summary(connection, thread['id'])
        validate_conversation_summary(connection, thread['id'], summary)
        assert summary['truncated_user_context_count']
        entry = next(item for item in summary['active_user_constraints'] if original_id in item['source_message_ids'])
        assert entry['text_truncated']
        context = ToolExecutionContext(connection, service, work['id'], thread['id'], 'work', work['id'], 'review', history)
        result = service.agent_tools.execute(context, 'read_conversation_history', {'message_id': original_id, 'length': 1000})
        assert result.status == 'succeeded' and result.output['text'] == long_text[:1000]
        assert result.output['next_offset'] == 1000 and result.output['text_truncated']
        foreign = service.agent_tools.execute(context, 'read_conversation_history', {'message_id': 'foreign'})
        assert foreign.status == 'failed'
    service.close()


@pytest.mark.parametrize('tampered', [False, True])
def test_old_history_budget_migrates_only_after_source_validation(tmp_path, monkeypatch, tampered):
    service = WritingService(tmp_path)
    thread_id = service.create_work({'title': '旧对话预算迁移'})['conversation_threads'][0]['id']
    with service.repo.transaction() as connection:
        service._append_conversation_message(connection, thread_id, 'user', 'text', {'text': '背景细节。' * 9000})
        service._append_conversation_message(connection, thread_id, 'assistant', 'text', {'text': '已记录。'})
        with monkeypatch.context() as previous:
            previous.setattr(summary_module, 'recent_message_count', lambda *_: 12)
            old = summary_module.refresh_conversation_summary(connection, thread_id, force_rebuild=True)
        old.pop('budget_policy')
        old['digest'] = summary_module._summary_digest(old)
        if tampered:
            old['through_ordinal'] = 999
        connection.execute('UPDATE conversation_threads SET summary_json=? WHERE id=?', (canonical_json(old), thread_id))
        if tampered:
            with pytest.raises(DomainError, match='原始消息'):
                service._conversation_summary(connection, thread_id)
        else:
            migrated = service._conversation_summary(connection, thread_id)
            assert migrated['budget_policy'] == summary_module.BUDGET_POLICY
            assert migrated['archived_message_count'] == 1
            summary_module.validate_conversation_summary(connection, thread_id, migrated)
    service.close()
