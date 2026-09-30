from copy import deepcopy
import json

from halocue_writing.edit_prompt import project_edit_context, text_window
from halocue_writing.providers import LLMWritingProvider


def context(count=120):
    return {"task_contract": {"id": "scene.draft.rewrite"}, "scene_conversation_context": {
        "confirmed_materials": [{"revision_id": "card-r1", "content": {"voice": "简短直接"}}],
        "current_manuscript": {"revision_id": "r1", "content": {"blocks": [
            {"id": f"b{i}", "type": "narration", "text": f"原文{i}。"} for i in range(count)]}},
        "pending_text_edit": {"id": "p1", "base_revision_id": "r1", "content": {"blocks": [
            {"id": f"p{i}", "type": "narration", "text": f"候选{i}。"} for i in range(count)]}},
    }}


def test_pending_window_keeps_exact_text_and_base_without_duplicate_formal_prose():
    original = context()
    before = deepcopy(original)
    projected = project_edit_context(original, "请润色第80段，保留其他修改。")
    scene = projected["scene_conversation_context"]
    window = scene["pending_text_edit"]["content"]
    assert [b["paragraph_number"] for b in window["blocks"]] == list(range(78, 83))
    assert window["blocks"][2]["text"] == "候选79。"
    assert window["blocks"][2]["id"] == "p79"
    assert len(window["blocks"][2]["text_sha256"]) == 71
    assert scene["current_manuscript"]["revision_id"] == "r1"
    assert scene["current_manuscript"]["content"]["blocks"] == []
    assert original == before
    assert scene["confirmed_materials"] == original["scene_conversation_context"]["confirmed_materials"]


def test_unlocated_large_passage_is_paged_instead_of_silently_read_in_full():
    projected = project_edit_context(context(200), "把全文节奏收紧。")
    window = projected["scene_conversation_context"]["pending_text_edit"]["content"]
    assert len(window["blocks"]) == 40 and window["next_start"] == 41 and not window["complete"]
    assert text_window(context()["scene_conversation_context"]["pending_text_edit"]["content"]["blocks"], query="找不到")["blocks"] == []


def test_edit_tool_followup_omits_full_candidate_and_formal_body():
    encoded = LLMWritingProvider._result_content({"status": "succeeded", "output": {
        "kind": "scene_text_edit", "status": "prepared", "base_revision_id": "r1", "candidate": "很长的候选正文",
        "base_text": "很长的正式正文", "edits": [{"block_id": "b1", "new_text": "新文"}], "reason": "润色"}})
    decoded = json.loads(encoded)
    assert "candidate" not in decoded["output"] and "base_text" not in decoded["output"]
    assert decoded["output"]["changed_blocks"] == ["b1"]


def test_large_paragraph_window_respects_budget_but_never_summarizes_target_text():
    blocks = [{"id": f"b{i}", "type": "narration", "text": "原文。" * 1000} for i in range(50)]
    window = text_window(blocks)
    assert len(window["blocks"]) == 1 and window["next_start"] == 2
    assert window["blocks"][0]["text"] == blocks[0]["text"]
    assert not window["complete"]
    blocks[0]["text"] *= 20
    oversized = text_window(blocks)
    assert len(oversized["blocks"]) == 1 and oversized["oversized_paragraph"]
    assert oversized["blocks"][0]["text"] == blocks[0]["text"]
