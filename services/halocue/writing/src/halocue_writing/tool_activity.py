"""Public tool vocabulary and bounded summaries; never serialize raw outputs."""

from __future__ import annotations

from typing import Any


TOOL_PRESENTATION = {
    "load_workflow_template": ("查看当前写作指引", "写作指引"),
    "read_work_context": ("查看作品资料与章节", "作品资料"),
    "read_conversation_history": ("回看对话", "对话"),
    "search_character_cards": ("查找本作人物卡", "人物资料"),
    "search_bundled_character_metadata": ("查找随包人物参考", "人物资料"),
    "search_world_bible": ("查找本作世界观", "作品资料"),
    "search_work_canon": ("查找本作剧情事实", "作品资料"),
    "draft_character_card": ("整理人物卡草稿", "人物资料"),
    "draft_world_card": ("整理世界观草稿", "作品资料"),
    "draft_world_rule": ("整理世界规则草稿", "作品资料"),
    "draft_canon_fact": ("整理剧情事实草稿", "作品资料"),
    "check_knowledge_conflicts": ("检查资料重复与冲突", "资料检查"),
    "organize_current_plan": ("整理当前构思", "创作整理"),
    "create_knowledge_proposal": ("提交资料候选", "创作整理"),
    "read_scene_text_window": ("读取目标正文段落", "正文"),
    "propose_scene_text_edit": ("准备正文修改对比", "正文"),
    "store_conversation_attachments": ("保存对话附件", "附件"),
    "document.retrieve": ("检索相关文档片段", "文档检索"),
    "provider_call": ("调用写作模型", "模型"),
}

PUBLIC_TOOL_LABELS = {name: item[0] for name, item in TOOL_PRESENTATION.items()}


def tool_category(name: str) -> str:
    return TOOL_PRESENTATION.get(name, ("执行工具", "其他工具"))[1]


def _names(items: list) -> str:
    names = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        name = str(content.get("name") or content.get("title") or "").strip()[:60]
        if name:
            names.append(name)
    return "、".join(names)


def tool_summary(name: str, value: Any) -> str:
    if isinstance(value, list):
        label = "张人物卡" if name == "search_character_cards" else "条记录"
        names = _names(value)
        return f"找到 {len(value)} {label}" + (f"：{names}" if names else "")
    if not isinstance(value, dict):
        return "执行完成" if value is not None else ""
    if isinstance(value.get("items"), list):
        items = value["items"]
        names = _names(items)
        return f"找到 {len(items)} 份人物参考" + (f"：{names}" if names else "")
    if isinstance(value.get("artifacts"), list):
        return (
            f"读取 {len(value['artifacts'])} 项作品资料、{len(value.get('chapters') or [])} 个章节"
        )
    if value.get("status") == "discussion_draft":
        return f"已整理「{value.get('title') or '资料'}」草稿，等待核对"
    if name == "propose_scene_text_edit" and isinstance(value.get("edits"), list):
        return f"准备修改 {len(value['edits'])} 个正文段落，等待核对"
    if name == "read_scene_text_window":
        return f"已读取 {len(value.get('blocks') or [])} 个正文段落"
    if value.get("next") == "user_confirmation":
        return "资料候选等待确认"
    if value.get("next") == "create_proposal":
        return "已请求整理当前构思，候选将交给你核对"
    if isinstance(value.get("conflicts"), list):
        return (
            f"发现 {len(value['conflicts'])} 项重复或冲突"
            if value["conflicts"]
            else "未发现重复或冲突"
        )
    if "scope" in value:
        return {
            "work": "查看全作写作指引",
            "chapter": "查看本章写作指引",
            "scene": "查看本场写作指引",
        }.get(str(value["scope"]), "已查看当前写作指引")
    if name == "read_conversation_history":
        return "已读取指定的对话片段"
    if "count" in value:
        return f"已保存 {value['count']} 个附件"
    return "执行完成"
