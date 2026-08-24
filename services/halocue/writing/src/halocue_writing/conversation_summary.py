from __future__ import annotations

import json
import re

from .errors import DomainError
from .repository import canonical_json, sha256_text


SCHEMA_VERSION = "conversation-summary/1.1"
RECENT_MESSAGE_COUNT = 12
MAX_ACTIVE_CONSTRAINTS = 48
MAX_CORRECTIONS = 24
MAX_OPEN_QUESTIONS = 16
MAX_EXCERPTS = 16

_CORRECTION_MARKERS = ("改成", "改为", "更正", "反悔", "不再", "不要", "取消", "放弃", "不是")
_QUESTION_MARKERS = ("？", "?", "是否", "为什么", "怎么", "什么", "哪一个", "哪个")


def _message_digest(row) -> str:
    return sha256_text(canonical_json({
        "id": row["id"],
        "ordinal": row["ordinal"],
        "role": row["role"],
        "kind": row["kind"],
        "content": json.loads(row["content_json"] or "{}"),
    }))


def _entry(row, text: str) -> dict:
    return {
        "text": text[:600],
        "source_message_ids": [row["id"]],
        "ordinal": row["ordinal"],
        "message_digest": _message_digest(row),
    }


def _normalized_text(row) -> str:
    content = json.loads(row["content_json"] or "{}")
    return " ".join(str(content.get("text") or content.get("summary") or "").split())


def _rejected_fragments(text: str) -> list[str]:
    fragments = []
    for match in re.finditer(r"(?:不再|不要|取消|放弃|不是)([^，。；！？!?]{2,40})", text):
        value = re.sub(r"^(?:继续|采用|使用|保留|选择|把)", "", match.group(1)).strip()
        if value:
            fragments.append(value)
    return fragments


def _superseded(previous: dict, correction_text: str) -> bool:
    previous_text = re.sub(r"\s+", "", str(previous.get("text") or ""))
    if not previous_text:
        return False
    for fragment in _rejected_fragments(correction_text):
        compact = re.sub(r"\s+", "", fragment)
        if compact in previous_text:
            return True
        bigrams = {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}
        if len(bigrams) >= 2 and sum(token in previous_text for token in bigrams) >= 2:
            return True
    return False


def _initial_source_digest(thread_id: str) -> str:
    return sha256_text(canonical_json({
        "schema_version": "conversation-summary-source/1.0",
        "thread_id": thread_id,
    }))


def _empty_summary(thread_id: str) -> dict:
    summary = {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "thread_id": thread_id,
        "archived_message_count": 0,
        "through_ordinal": 0,
        "source": {
            "from_ordinal": 0,
            "to_ordinal": 0,
            "message_count": 0,
            "digest_algorithm": "sha256-chain/1",
            "digest": _initial_source_digest(thread_id),
        },
        "active_user_constraints": [],
        "corrections_and_rejections": [],
        "open_questions": [],
        "excerpts": [],
        "source_message_ids": [],
        "overflowed_user_context_count": 0,
        "omitted_message_count": 0,
        "continuation_note": "",
        "trust": {
            "kind": "derived_conversation_context",
            "formal_fact": False,
            "proposal_evidence_allowed": False,
            "precedence": "formal_artifacts_then_recent_user_messages_then_summary",
        },
        "text": "",
    }
    summary["digest"] = _summary_digest(summary)
    return summary


def _summary_digest(summary: dict) -> str:
    body = {key: value for key, value in summary.items() if key != "digest"}
    return sha256_text(canonical_json(body))


def _append_bounded(items: list[dict], entry: dict, limit: int) -> int:
    items.append(entry)
    overflow = max(0, len(items) - limit)
    if overflow:
        del items[:overflow]
    return overflow


def _add_archived_row(summary: dict, row) -> None:
    text = _normalized_text(row)
    message_digest = _message_digest(row)
    source = summary["source"]
    source["digest"] = sha256_text(canonical_json({
        "previous_digest": source["digest"],
        "message_digest": message_digest,
    }))
    source["from_ordinal"] = source["from_ordinal"] or row["ordinal"]
    source["to_ordinal"] = row["ordinal"]
    source["message_count"] += 1
    summary["archived_message_count"] += 1
    summary["through_ordinal"] = row["ordinal"]
    summary["revision"] += 1

    if text:
        excerpt = {
            "message_id": row["id"],
            "ordinal": row["ordinal"],
            "role": row["role"],
            "kind": row["kind"],
            "text": text[:360],
            "message_digest": message_digest,
        }
        summary["excerpts"].append(excerpt)
        if len(summary["excerpts"]) > MAX_EXCERPTS:
            # Keep the earliest four messages for orientation and the latest messages for continuation.
            summary["excerpts"] = summary["excerpts"][:4] + summary["excerpts"][-(MAX_EXCERPTS - 4):]

    if row["role"] != "user" or not text:
        return

    entry = _entry(row, text)
    is_correction = any(marker in text for marker in _CORRECTION_MARKERS)
    if is_correction:
        superseded_ids = []
        retained = []
        for previous in summary["active_user_constraints"]:
            if _superseded(previous, text):
                superseded_ids.extend(previous.get("source_message_ids", []))
            else:
                retained.append(previous)
        summary["active_user_constraints"] = retained
        correction = {**entry, "supersedes_message_ids": superseded_ids}
        summary["overflowed_user_context_count"] += _append_bounded(
            summary["corrections_and_rejections"], correction, MAX_CORRECTIONS
        )

    if any(marker in text for marker in _QUESTION_MARKERS):
        summary["overflowed_user_context_count"] += _append_bounded(
            summary["open_questions"], entry, MAX_OPEN_QUESTIONS
        )
    else:
        summary["overflowed_user_context_count"] += _append_bounded(
            summary["active_user_constraints"], entry, MAX_ACTIVE_CONSTRAINTS
        )


def _finish_summary(summary: dict) -> dict:
    referenced_ids = []
    for key in ("active_user_constraints", "corrections_and_rejections", "open_questions"):
        for entry in summary[key]:
            referenced_ids.extend(entry.get("source_message_ids", []))
    referenced_ids.extend(item["message_id"] for item in summary["excerpts"])
    summary["source_message_ids"] = list(dict.fromkeys(referenced_ids))
    summary["omitted_message_count"] = max(
        0, summary["archived_message_count"] - len(summary["source_message_ids"])
    )
    if summary["overflowed_user_context_count"]:
        summary["continuation_note"] = (
            f"有 {summary['overflowed_user_context_count']} 条更早的用户上下文未展开。"
            "需要据此形成正式资料时，必须回查原始消息，不能只依赖本摘要。"
        )
    else:
        summary["continuation_note"] = "摘要仅用于继续讨论；正式事实仍以已采纳资料和原始来源为准。"
    lines = []
    for label, key in (
        ("当前约束", "active_user_constraints"),
        ("修正或否决", "corrections_and_rejections"),
        ("待确认问题", "open_questions"),
    ):
        lines.extend(f"{label} [{item['ordinal']}]: {item['text']}" for item in summary[key])
    summary["text"] = "\n".join(lines)[:12000]
    summary["digest"] = _summary_digest(summary)
    return summary


def refresh_conversation_summary(connection, thread_id: str, *, force_rebuild: bool = False) -> dict:
    total = connection.execute(
        "SELECT COUNT(*) AS count FROM conversation_messages WHERE thread_id=?", (thread_id,)
    ).fetchone()["count"]
    archived_count = max(0, total - RECENT_MESSAGE_COUNT)
    if not archived_count:
        return _empty_summary(thread_id)

    stored_row = connection.execute(
        "SELECT summary_json FROM conversation_threads WHERE id=?", (thread_id,)
    ).fetchone()
    try:
        stored = json.loads(stored_row["summary_json"] or "{}") if stored_row else {}
    except json.JSONDecodeError:
        stored = {}
    incremental = (
        not force_rebuild
        and
        stored.get("schema_version") == SCHEMA_VERSION
        and stored.get("thread_id") == thread_id
        and int(stored.get("archived_message_count") or 0) <= archived_count
        and stored.get("digest") == _summary_digest(stored)
        and isinstance(stored.get("source"), dict)
        and all(isinstance(stored.get(key), list) for key in (
            "active_user_constraints", "corrections_and_rejections", "open_questions", "excerpts"
        ))
    )
    summary = stored if incremental else _empty_summary(thread_id)
    through = int(summary.get("through_ordinal") or 0)
    rows = connection.execute(
        """SELECT id,ordinal,role,kind,content_json FROM conversation_messages
           WHERE thread_id=? AND ordinal>? ORDER BY ordinal LIMIT ?""",
        (thread_id, through, archived_count - int(summary.get("archived_message_count") or 0)),
    ).fetchall()
    for row in rows:
        _add_archived_row(summary, row)
    return _finish_summary(summary)


def conversation_summary_evidence_ids(
    connection,
    thread_id: str,
    summary: dict,
    *,
    before_ordinal: int | None = None,
) -> list[str]:
    """Resolve summary-backed user sources to original, verified messages.

    This deliberately ignores assistant excerpts. A derived summary is never
    evidence by itself; callers receive only original user message IDs whose
    content digest still matches the pinned summary.
    """
    if not isinstance(summary, dict) or summary.get("schema_version") != SCHEMA_VERSION:
        return []
    if summary.get("thread_id") != thread_id or summary.get("digest") != _summary_digest(summary):
        raise DomainError(
            "conversation_summary_integrity_failed",
            "对话摘要与原始消息不一致，不能据此建立正式资料候选。",
            status=409,
            details={"thread_id": thread_id, "reason": "summary_digest"},
        )
    trust = summary.get("trust") if isinstance(summary.get("trust"), dict) else {}
    if trust.get("formal_fact") is not False or trust.get("proposal_evidence_allowed") is not False:
        raise DomainError(
            "conversation_summary_integrity_failed",
            "对话摘要的可信边界无效，不能据此建立正式资料候选。",
            status=409,
            details={"thread_id": thread_id, "reason": "trust_boundary"},
        )

    entries: dict[str, str] = {}
    for key in ("active_user_constraints", "corrections_and_rejections", "open_questions"):
        for item in summary.get(key, []):
            if not isinstance(item, dict):
                continue
            for message_id in item.get("source_message_ids", []):
                message_id = str(message_id).strip()
                if message_id:
                    entries[message_id] = str(item.get("message_digest") or "")
    if not entries:
        return []

    placeholders = ",".join("?" for _ in entries)
    rows = connection.execute(
        f"""SELECT id,ordinal,role,kind,content_json FROM conversation_messages
            WHERE thread_id=? AND id IN ({placeholders}) ORDER BY ordinal""",
        (thread_id, *entries),
    ).fetchall()
    if len(rows) != len(entries):
        raise DomainError(
            "conversation_summary_integrity_failed",
            "摘要引用的原始消息不完整，不能据此建立正式资料候选。",
            status=409,
            details={"thread_id": thread_id, "reason": "missing_source_message"},
        )
    resolved = []
    for row in rows:
        if row["role"] != "user" or entries[row["id"]] != _message_digest(row):
            raise DomainError(
                "conversation_summary_integrity_failed",
                "摘要引用的原始消息校验失败，不能据此建立正式资料候选。",
                status=409,
                details={"thread_id": thread_id, "reason": "source_message_digest"},
            )
        if before_ordinal is not None and int(row["ordinal"]) >= int(before_ordinal):
            raise DomainError(
                "conversation_summary_integrity_failed",
                "摘要引用了候选形成之后的消息，不能据此建立正式资料候选。",
                status=409,
                details={"thread_id": thread_id, "reason": "source_message_order"},
            )
        resolved.append(row["id"])
    return resolved


def validate_conversation_summary(
    connection,
    thread_id: str,
    summary: dict,
    *,
    pinned: bool = False,
) -> dict:
    def fail(reason: str):
        raise DomainError(
            "conversation_summary_integrity_failed",
            "对话摘要与原始消息不一致，已停止把摘要发送给模型。原始消息仍完整保留。",
            status=409,
            details={"thread_id": thread_id, "reason": reason},
        )

    if not isinstance(summary, dict) or summary.get("schema_version") != SCHEMA_VERSION:
        fail("schema_version")
    if summary.get("thread_id") != thread_id:
        fail("thread_id")
    if summary.get("digest") != _summary_digest(summary):
        fail("summary_digest")
    trust = summary.get("trust") if isinstance(summary.get("trust"), dict) else {}
    if trust.get("formal_fact") is not False or trust.get("proposal_evidence_allowed") is not False:
        fail("trust_boundary")

    if pinned:
        through_ordinal = int(summary.get("through_ordinal") or 0)
        expected_archived = connection.execute(
            """SELECT COUNT(*) AS count FROM conversation_messages
               WHERE thread_id=? AND ordinal<=?""",
            (thread_id, through_ordinal),
        ).fetchone()["count"]
    else:
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM conversation_messages WHERE thread_id=?", (thread_id,)
        ).fetchone()["count"]
        expected_archived = max(0, total - RECENT_MESSAGE_COUNT)
    if int(summary.get("archived_message_count") or 0) != expected_archived:
        fail("message_count")
    source = summary.get("source") if isinstance(summary.get("source"), dict) else {}
    if int(source.get("message_count") or 0) != expected_archived:
        fail("source_message_count")

    ids = [str(item) for item in summary.get("source_message_ids", []) if str(item)]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"SELECT id,ordinal,role,kind,content_json FROM conversation_messages WHERE thread_id=? AND id IN ({placeholders})",
            (thread_id, *ids),
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        if len(by_id) != len(set(ids)):
            fail("missing_source_message")
        expected_digests = {}
        for key in ("active_user_constraints", "corrections_and_rejections", "open_questions"):
            for item in summary.get(key, []):
                for message_id in item.get("source_message_ids", []):
                    expected_digests[message_id] = item.get("message_digest")
        for item in summary.get("excerpts", []):
            expected_digests[item.get("message_id")] = item.get("message_digest")
        for message_id, expected_digest in expected_digests.items():
            row = by_id.get(message_id)
            if not row or expected_digest != _message_digest(row):
                fail("source_message_digest")
            if row["ordinal"] > int(summary.get("through_ordinal") or 0):
                fail("source_range")
    return summary


def recent_conversation_history(connection, thread_id: str, limit: int = RECENT_MESSAGE_COUNT) -> list[dict]:
    rows = connection.execute(
        """SELECT id,role,content_json FROM conversation_messages
           WHERE thread_id=? ORDER BY ordinal DESC LIMIT ?""",
        (thread_id, limit),
    ).fetchall()
    history = []
    for row in reversed(rows):
        content = json.loads(row["content_json"] or "{}")
        history.append({"id": row["id"], "role": row["role"], "text": content.get("text", "")})
    return history
