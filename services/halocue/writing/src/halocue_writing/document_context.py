from __future__ import annotations

import json
import re

from .errors import DomainError
from .repository import canonical_json, now, sha256_text


EXTRACT_LIMIT = 1_000_000
CONTEXT_LIMIT = 9_000
CHUNK_LIMIT = 1_400
EXTRACT_MARKER = "\n\n[文档内容已在 1000000 字符处截断]"


def normalize_text(text: str) -> tuple[str, int, bool]:
    normalized = "\n".join(line.rstrip() for line in text.replace("\x00", "").splitlines()).strip()
    original_characters = len(normalized)
    truncated = original_characters > EXTRACT_LIMIT
    if truncated:
        normalized = normalized[:EXTRACT_LIMIT].rstrip() + EXTRACT_MARKER
    return normalized, original_characters, truncated


def search_terms(text: str) -> list[str]:
    normalized = text.lower()
    terms = set(re.findall(r"[a-z0-9][a-z0-9_.-]{1,40}", normalized))
    cjk_runs = re.findall(r"[\u3400-\u9fff]{2,80}", normalized)
    for run in cjk_runs:
        for width in (2, 3, 4):
            terms.update(run[index:index + width] for index in range(max(0, len(run) - width + 1)))
    ignored = {
        "这个", "那个", "一下", "一些", "一个", "我们", "你们", "他们", "请问",
        "文档", "文件", "内容", "资料", "总结", "说明", "看看", "里面", "关于",
    }
    return sorted((term for term in terms if term not in ignored), key=lambda value: (-len(value), value))[:800]


def split_chunks(text: str) -> list[dict]:
    source = text.removesuffix(EXTRACT_MARKER).strip()
    raw_paragraphs = [item.strip() for item in re.split(r"\n\s*\n+", source) if item.strip()]
    paragraphs = []
    for raw in raw_paragraphs:
        pending = [raw]
        if len(raw) > CHUNK_LIMIT:
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            pending = lines if len(lines) > 1 else [raw]
        for unit in pending:
            while len(unit) > CHUNK_LIMIT:
                boundary = max(
                    unit.rfind(marker, 0, CHUNK_LIMIT)
                    for marker in ("。", "！", "？", ";", "；", "\n")
                )
                cut = boundary + 1 if boundary >= CHUNK_LIMIT // 2 else CHUNK_LIMIT
                paragraphs.append(unit[:cut].strip())
                unit = unit[cut:].strip()
            if unit:
                paragraphs.append(unit)
    chunks = []
    current = []
    current_start = 1
    for paragraph_number, paragraph in enumerate(paragraphs, start=1):
        candidate = "\n\n".join([*current, paragraph])
        if current and len(candidate) > CHUNK_LIMIT:
            chunks.append({
                "paragraph_start": current_start,
                "paragraph_end": paragraph_number - 1,
                "content": "\n\n".join(current),
            })
            current = [paragraph]
            current_start = paragraph_number
        else:
            current.append(paragraph)
    if current:
        chunks.append({
            "paragraph_start": current_start,
            "paragraph_end": len(paragraphs),
            "content": "\n\n".join(current),
        })
    return chunks


def index_attachment(connection, attachment: dict, extracted_text: str) -> int:
    existing = connection.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE attachment_id=?", (attachment["id"],)
    ).fetchone()[0]
    if existing:
        return int(existing)
    timestamp = now()
    chunks = split_chunks(extracted_text)
    for ordinal, chunk in enumerate(chunks, start=1):
        content = chunk["content"]
        connection.execute(
            "INSERT INTO document_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"{attachment['id']}:chunk:{ordinal:06d}", attachment["id"],
                attachment["work_id"], attachment["thread_id"], ordinal,
                chunk["paragraph_start"], chunk["paragraph_end"], content,
                sha256_text(content), canonical_json(search_terms(content)),
                len(content), timestamp,
            ),
        )
    return len(chunks)


def _ensure_index(repo, connection, attachment: dict) -> int:
    count = connection.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE attachment_id=?", (attachment["id"],)
    ).fetchone()[0]
    if count:
        return int(count)
    try:
        extracted_text = repo.read_text(str(attachment["content_uri"]) + ".extracted.txt")
    except (OSError, UnicodeError, ValueError) as exc:
        raise DomainError("document_text_missing", "文档的文本快照不存在，请重新上传。", status=409) from exc
    return index_attachment(connection, attachment, extracted_text)


def retrieve_context(
    repo, connection, work_id: str, thread_id: str, instruction: str,
    current_attachment_ids: list[str],
) -> dict | None:
    attachments = repo.rows(connection.execute(
        """SELECT * FROM conversation_attachments
           WHERE work_id=? AND thread_id=? AND media_type NOT LIKE 'image/%'
             AND (status='attached' OR id IN ({placeholders}))
           ORDER BY created_at DESC""".format(
            placeholders=",".join("?" for _ in current_attachment_ids) or "NULL"
        ),
        (work_id, thread_id, *current_attachment_ids),
    ))
    if not attachments:
        return None
    filenames = {item["id"]: item["filename"] for item in attachments}
    for attachment in attachments:
        _ensure_index(repo, connection, attachment)
    attachment_ids = list(filenames)
    rows = repo.rows(connection.execute(
        """SELECT * FROM document_chunks WHERE attachment_id IN ({})
           ORDER BY attachment_id,ordinal""".format(",".join("?" for _ in attachment_ids)),
        attachment_ids,
    ))
    query_terms = search_terms(instruction)
    query_set = set(query_terms)
    ranked = []
    for row in rows:
        chunk_terms = set(json.loads(row["search_terms_json"]))
        matches = query_set & chunk_terms
        score = sum(min(len(term), 6) for term in matches)
        if row["attachment_id"] in current_attachment_ids:
            score += 2
        ranked.append((score, len(matches), row))
    has_lexical_match = any(match_count for _, match_count, _ in ranked)
    if has_lexical_match:
        ranked = [item for item in ranked if item[1] > 0]
        ranked.sort(key=lambda item: (-item[0], item[2]["ordinal"], item[2]["attachment_id"]))
    else:
        fallback_ids = set(current_attachment_ids or attachment_ids[:1])
        ranked = [item for item in ranked if item[2]["attachment_id"] in fallback_ids]
        ranked.sort(key=lambda item: (item[2]["attachment_id"], item[2]["ordinal"]))
    citations = []
    selected_characters = 0
    for score, _, row in ranked:
        if len(citations) >= 8:
            break
        if selected_characters + row["character_count"] > CONTEXT_LIMIT:
            continue
        paragraph_ids = [
            f"p{number:06d}"
            for number in range(row["paragraph_start"], row["paragraph_end"] + 1)
        ]
        matched_terms = sorted(
            query_set & set(json.loads(row["search_terms_json"])),
            key=lambda value: (-len(value), value),
        )[:8]
        label = (
            f"{filenames[row['attachment_id']]} · 段落 {paragraph_ids[0]}"
            if len(paragraph_ids) == 1
            else f"{filenames[row['attachment_id']]} · 段落 {paragraph_ids[0]}-{paragraph_ids[-1]}"
        )
        citations.append({
            "attachment_id": row["attachment_id"], "filename": filenames[row["attachment_id"]],
            "chunk_id": row["id"], "paragraph_ids": paragraph_ids,
            "display_label": label, "matched_terms": matched_terms,
            "score": score, "quote": row["content"],
        })
        selected_characters += row["character_count"]
    return {
        "schema_version": "document-retrieval/1.0",
        "index_version": "document-chunks/1.0",
        "query": instruction,
        "strategy": "lexical_cjk_ngram_with_current_document_fallback",
        "query_terms": query_terms[:24],
        "selected_characters": selected_characters,
        "max_characters": CONTEXT_LIMIT,
        "citations": citations,
        "trust": "untrusted_user_document",
        "write_boundary": "proposal_only",
        "explanation": (
            "按当前指令的词语命中选择片段。" if has_lexical_match
            else "当前指令没有明确检索词，选择本轮或最近文档的开头片段。"
        ),
    }
