import base64
import json

from halocue_writing.document_context import CONTEXT_LIMIT
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class ContextCaptureProvider(FakeWritingProvider):
    def __init__(self):
        self.contexts = []

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        self.contexts.append(work_context)
        return super().discuss_work(messages, work_context)


def _long_document() -> bytes:
    paragraphs = []
    for number in range(180):
        detail = "这一段只是用于验证稳定分块的普通背景记录。" * 12
        if number == 132:
            detail += "月光钥匙被保存在东侧观测塔的第三层抽屉。"
        if number == 165:
            detail += "青铜门的确认口令是白昼之后，不得改写为其他说法。"
        paragraphs.append(f"第 {number + 1} 段\n{detail}")
    return "\n\n".join(paragraphs).encode("utf-8")


def _upload_long_document(service: WritingService, work: dict, thread: dict):
    return service.create_conversation_attachment(
        work["id"], thread["id"],
        {
            "expected_thread_version": thread["version"],
            "filename": "archive-notes.md",
            "media_type": "text/markdown",
            "content_base64": base64.b64encode(_long_document()).decode("ascii"),
        },
    )


def test_long_document_is_persistently_chunked_and_only_relevant_context_reaches_provider(tmp_path):
    service = WritingService(tmp_path)
    provider = ContextCaptureProvider()
    service.provider = provider
    work = service.create_work({"title": "长文档检索", "idea": "核对资料里的明确事实。"})
    thread = work["conversation_threads"][0]
    uploaded = _upload_long_document(service, work, thread)
    uploaded_thread = uploaded["work"]["conversation_threads"][0]
    attachment = uploaded_thread["attachments"][0]
    assert attachment["document_index"]["version"] == "document-chunks/1.0"
    assert attachment["document_index"]["chunk_count"] > 20

    with service.repo.connect() as connection:
        chunks = connection.execute(
            """SELECT id,ordinal,paragraph_start,paragraph_end,content_hash,character_count
               FROM document_chunks WHERE attachment_id=? ORDER BY ordinal""",
            (attachment["id"],),
        ).fetchall()
    assert len(chunks) > 20
    assert chunks[0]["id"] == f"{attachment['id']}:chunk:000001"
    assert [row["ordinal"] for row in chunks] == list(range(1, len(chunks) + 1))
    assert all(row["paragraph_start"] <= row["paragraph_end"] for row in chunks)
    assert all(row["content_hash"].startswith("sha256:") for row in chunks)

    sent = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "请查找月光钥匙具体保存在什么地方，并标明来源。",
            "attachment_ids": [attachment["id"]],
        },
    )

    context = provider.contexts[-1]
    assert "extracted_text" not in context["attachments"][0]
    retrieval = context["document_context"]
    assert retrieval["selected_characters"] <= CONTEXT_LIMIT
    assert sum(len(item["quote"]) for item in retrieval["citations"]) == retrieval["selected_characters"]
    assert len(json.dumps(context, ensure_ascii=False)) < 20_000
    citation = next(item for item in retrieval["citations"] if "月光钥匙" in item["quote"])
    assert citation["filename"] == "archive-notes.md"
    assert citation["chunk_id"].startswith(f"{attachment['id']}:chunk:")
    assert citation["paragraph_ids"]
    assert citation["display_label"].startswith("archive-notes.md · 段落 p")
    assert citation["matched_terms"]
    assert retrieval["trust"] == "untrusted_user_document"
    assert retrieval["write_boundary"] == "proposal_only"

    sent_thread = sent["work"]["conversation_threads"][0]
    assistant = sent_thread["messages"][-1]["content"]
    assert assistant["citations"] == retrieval["citations"]
    assert assistant["document_context"]["max_characters"] == CONTEXT_LIMIT
    assert not any(item["kind"] in {"character_card", "world_bible", "work_canon"} for item in sent["work"]["artifacts"])
    run = next(item for item in sent["work"]["agent_runs"] if item["id"] == sent["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["document_context"]["citations"][0]["filename"] == "archive-notes.md"
    assert snapshot["document_skill"]["id"] == "document.read"


def test_document_index_survives_restart_and_is_reused_on_later_turn(tmp_path):
    service = WritingService(tmp_path)
    first_provider = ContextCaptureProvider()
    service.provider = first_provider
    work = service.create_work({"title": "跨轮文档", "idea": "逐项核对档案。"})
    thread = work["conversation_threads"][0]
    uploaded = _upload_long_document(service, work, thread)
    uploaded_thread = uploaded["work"]["conversation_threads"][0]
    attachment = uploaded_thread["attachments"][0]
    first = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "先查找月光钥匙。",
            "attachment_ids": [attachment["id"]],
        },
    )
    with service.repo.connect() as connection:
        before = connection.execute(
            "SELECT id,content_hash FROM document_chunks WHERE attachment_id=? ORDER BY ordinal",
            (attachment["id"],),
        ).fetchall()

    restarted = WritingService(tmp_path)
    second_provider = ContextCaptureProvider()
    restarted.provider = second_provider
    restored = restarted.get_work(work["id"])
    restored_thread = restored["conversation_threads"][0]
    second = restarted.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": restored_thread["version"],
            "text": "再核对青铜门的确认口令，不需要重新上传文档。",
        },
    )

    retrieval = second_provider.contexts[-1]["document_context"]
    assert second_provider.contexts[-1]["attachments"] == []
    citation = next(item for item in retrieval["citations"] if "青铜门" in item["quote"])
    assert citation["filename"] == "archive-notes.md"
    assert "白昼之后" in citation["quote"]
    with restarted.repo.connect() as connection:
        after = connection.execute(
            "SELECT id,content_hash FROM document_chunks WHERE attachment_id=? ORDER BY ordinal",
            (attachment["id"],),
        ).fetchall()
    assert [(row["id"], row["content_hash"]) for row in after] == [
        (row["id"], row["content_hash"]) for row in before
    ]
    assert second["work"]["version"] == first["work"]["version"]


def test_existing_attachment_without_index_is_lazily_migrated_and_context_is_bounded(tmp_path):
    service = WritingService(tmp_path)
    provider = ContextCaptureProvider()
    service.provider = provider
    work = service.create_work({"title": "旧附件兼容", "idea": "读取旧附件。"})
    thread = work["conversation_threads"][0]
    uploaded = _upload_long_document(service, work, thread)
    uploaded_thread = uploaded["work"]["conversation_threads"][0]
    attachment = uploaded_thread["attachments"][0]
    with service.repo.transaction() as connection:
        connection.execute("DELETE FROM document_chunks WHERE attachment_id=?", (attachment["id"],))

    sent = service.post_conversation_message(
        work["id"], thread["id"],
        {
            "expected_thread_version": uploaded_thread["version"],
            "text": "请通读这份文档并说明你实际读取了哪些段落。",
            "attachment_ids": [attachment["id"]],
        },
    )

    retrieval = provider.contexts[-1]["document_context"]
    assert retrieval["selected_characters"] <= CONTEXT_LIMIT
    assert len(retrieval["citations"]) <= 8
    assert retrieval["explanation"] == "当前指令没有明确检索词，选择本轮或最近文档的开头片段。"
    with service.repo.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE attachment_id=?", (attachment["id"],)
        ).fetchone()[0]
    assert count > 20
    assert sent["work"]["conversation_threads"][0]["attachments"][0]["status"] == "attached"
