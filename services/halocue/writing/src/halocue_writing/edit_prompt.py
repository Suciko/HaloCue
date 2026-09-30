"""A read projection for editing; the full revision and overlay stay on disk."""

from copy import deepcopy
import re
from .repository import sha256_text


WINDOW_BLOCKS = 40
WINDOW_TOKEN_BUDGET = 12_000


def text_window(blocks, *, start=1, limit=WINDOW_BLOCKS, query=""):
    limit = max(1, min(WINDOW_BLOCKS, int(limit)))
    if query:
        indices = [i for i, block in enumerate(blocks) if query.casefold() in block.get("text", "").casefold()]
        start = indices[0] + 1 if indices else len(blocks) + 1
    begin = max(0, int(start) - 1)
    selected = []
    estimated_tokens = 0
    for block in blocks[begin:begin + limit]:
        text = block.get("text", "")
        unicode_chars = sum(ord(char) > 127 for char in text)
        estimate = unicode_chars * 2 + (len(text) - unicode_chars) // 3 + 96
        if selected and estimated_tokens + estimate > WINDOW_TOKEN_BUDGET:
            break
        selected.append(block)
        estimated_tokens += estimate
    return {
        "blocks": [{**block, "paragraph_number": begin + i + 1,
                    "text_sha256": sha256_text(block["text"])}
                   for i, block in enumerate(selected)],
        "total_blocks": len(blocks), "start": begin + 1,
        "next_start": begin + len(selected) + 1 if selected and begin + len(selected) < len(blocks) else None,
        "complete": begin == 0 and len(selected) == len(blocks),
        "estimated_tokens": estimated_tokens,
        "oversized_paragraph": len(selected) == 1 and estimated_tokens > WINDOW_TOKEN_BUDGET,
    }


def project_edit_context(context, instruction):
    if context.get("task_contract", {}).get("id") != "scene.draft.rewrite":
        return context
    scene = context.get("scene_conversation_context")
    if not isinstance(scene, dict) or not isinstance(scene.get("current_manuscript"), dict):
        return context
    projected = deepcopy(context)
    scene = projected["scene_conversation_context"]
    formal = scene["current_manuscript"]
    active = scene.get("pending_text_edit") or formal
    blocks = active.get("content", {}).get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return context
    targets = [int(n) for n in re.findall(r"第\s*(\d+)\s*段", instruction)]
    selection = context.get("task_contract", {}).get("task_scope", {}).get("selection") or {}
    targets.extend(i + 1 for i, b in enumerate(blocks) if b.get("id") == selection.get("block_id"))
    # An explicit paragraph starts a small neighborhood. An unlocated target
    # can be found with the scoped read tool; never pretend omitted text was read.
    start = max(1, min(targets) - 2) if targets else 1
    limit = min(WINDOW_BLOCKS, max(targets) - start + 3) if targets else WINDOW_BLOCKS
    active["content"] = text_window(blocks, start=start, limit=limit)
    if targets and not any(block["paragraph_number"] == min(targets) for block in active["content"]["blocks"]):
        active["content"] = text_window(blocks, start=min(targets), limit=limit)
    if scene.get("pending_text_edit"):
        scene["current_manuscript"] = {"revision_id": formal["revision_id"],
                                       "content": {"blocks": [], "loaded": False},
                                       "role": "immutable_review_base"}
    scene["editing_context"] = {
        "effective_text": "pending_text_edit" if scene.get("pending_text_edit") else "current_manuscript",
        "unloaded_text": "read_scene_text_window retrieves exact paragraphs; do not invent omitted text",
        "merge_policy": "server preserves every unsubmitted paragraph and pending change",
    }
    return projected
