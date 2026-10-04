"""Explicit, traceable links from a scene conversation to its ideation source."""

from __future__ import annotations

import json

from .conversation_summary import recent_conversation_history
from .errors import DomainError


SCHEMA_VERSION = "discussion-continuation/1.0"


def source_link(connection, thread_id: str) -> dict | None:
    row = connection.execute(
        """SELECT content_json FROM conversation_messages
           WHERE thread_id=? AND kind='discussion_link' ORDER BY ordinal DESC LIMIT 1""",
        (thread_id,),
    ).fetchone()
    return json.loads(row["content_json"]).get("discussion_source") if row else None


def link_source(service, connection, work_id: str, thread_id: str, source_id: str) -> None:
    target = connection.execute(
        "SELECT scope_type,scope_id FROM conversation_threads WHERE id=? AND work_id=?",
        (thread_id, work_id),
    ).fetchone()
    source = connection.execute(
        "SELECT id,title,scope_type,scope_id FROM conversation_threads WHERE id=? AND work_id=? AND status='active'",
        (source_id, work_id),
    ).fetchone()
    if (
        not target
        or target["scope_type"] != "scene"
        or not source
        or source["scope_type"] not in {"work", "chapter"}
    ):
        raise DomainError(
            "invalid_discussion_source", "只能承接本作品的构思或本章对话。", status=409
        )
    chapter = connection.execute(
        "SELECT chapter_id FROM scenes WHERE id=? AND work_id=?", (target["scope_id"], work_id)
    ).fetchone()
    if source["scope_type"] == "chapter" and (
        not chapter or source["scope_id"] != chapter["chapter_id"]
    ):
        raise DomainError("invalid_discussion_source", "这段对话属于其他章节。", status=409)
    if (source_link(connection, thread_id) or {}).get("thread_id") == source_id:
        return
    service._append_conversation_message(
        connection,
        thread_id,
        "assistant",
        "discussion_link",
        {
            "text": "已承接构思对话，之前的要求会带入本场写作。",
            "discussion_source": {
                "schema_version": "discussion-source-link/1.0",
                "thread_id": source_id,
                "title": source["title"],
            },
        },
    )


def read_continuation(service, connection, work_id: str, thread_id: str) -> dict | None:
    link = source_link(connection, thread_id)
    if not link:
        return None
    source = connection.execute(
        "SELECT id,title,version,scope_type FROM conversation_threads WHERE id=? AND work_id=?",
        (link["thread_id"], work_id),
    ).fetchone()
    if not source or source["scope_type"] not in {"work", "chapter"}:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "thread_id": source["id"],
        "title": source["title"],
        "thread_version": source["version"],
        "summary": service._conversation_summary(connection, source["id"]),
        "recent_messages": recent_conversation_history(connection, source["id"]),
        "trust_boundary": "这些是可追溯的构思讨论，不是已确认事实；本场较新的作者要求优先，正式事实以已采纳资料为准。",
    }
