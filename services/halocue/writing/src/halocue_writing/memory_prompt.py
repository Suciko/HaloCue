"""Compact model inputs while keeping revision snapshots and evidence intact."""

from __future__ import annotations


def _compact_manuscript(manuscript: dict) -> dict:
    blocks = manuscript.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return manuscript
    lines = []
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            return manuscript
        kind = block.get("type")
        if kind == "dialogue":
            if not isinstance(block.get("speaker"), str):
                return manuscript
            lines.append(f"{block['speaker']}: {block['text']}")
        elif kind == "narration":
            lines.append(f"旁白: {block['text']}")
        elif kind == "action":
            lines.append(block["text"])
        else:
            return manuscript
    if manuscript.get("text") != "\n".join(lines) + "\n":
        return manuscript
    return {key: value for key, value in manuscript.items() if key != "text"}


def compact_memory_prompt_context(context: dict) -> dict:
    """Omit only manuscript text exactly reconstructable from cited blocks."""
    manuscript = context.get("manuscript")
    if isinstance(manuscript, dict):
        compact = _compact_manuscript(manuscript)
        if compact is not manuscript:
            return {**context, "manuscript": compact}
    scenes = context.get("scenes")
    if isinstance(scenes, list):
        compact_scenes = []
        changed = False
        for scene in scenes:
            if not isinstance(scene, dict) or not isinstance(scene.get("manuscript"), dict):
                compact_scenes.append(scene)
                continue
            compact = _compact_manuscript(scene["manuscript"])
            changed |= compact is not scene["manuscript"]
            compact_scenes.append({**scene, "manuscript": compact})
        if changed:
            return {**context, "scenes": compact_scenes}
    return context
