# -*- coding: utf-8 -*-
"""Structured unresolved background requests emitted by the annotator."""

from __future__ import annotations

import re
from pathlib import Path


def resolve_registered_background(value, background_map):
    """Return the catalog's exact spelling before AA's case-sensitive hash."""
    selected = str(value or "").strip()
    if not selected or selected in background_map:
        return selected
    matches = [str(name) for name in background_map if str(name).casefold() == selected.casefold()]
    if len(matches) > 1:
        raise ValueError(f"背景名大小写对应多个素材，请选择完整名称：{selected}")
    if matches:
        return matches[0]
    if selected.isdigit():
        matches = [str(name) for name, identifier in background_map.items() if str(identifier) == selected]
        if len(matches) == 1:
            return matches[0]
    return selected

_REQUEST = re.compile(
    r"^\s*#\s*待生成自定义背景\s*[：:]\s*(.+?)\s*$",
    re.MULTILINE,
)


class UnresolvedBackgroundError(RuntimeError):
    def __init__(self, requests: list[str]):
        self.requests = requests
        details = "\n".join(
            f"{index}. {request}\n   提示词：{background_generation_prompt(request)}"
            for index, request in enumerate(requests, start=1)
        )
        super().__init__(
            "工程仍有未生成、未登记的自定义背景，已阻止安装到 AA。\n"
            "请生成图片、在网页端登记背景，再把对应注释替换为 @bg 指令：\n"
            + details
        )


def collect_background_requests(text_or_path: str | Path) -> list[str]:
    if isinstance(text_or_path, Path):
        text = text_or_path.read_text(encoding="utf-8")
    else:
        text = str(text_or_path)
    requests: list[str] = []
    for match in _REQUEST.finditer(text):
        description = match.group(1).strip()
        if description and description not in requests:
            requests.append(description)
    return requests


def background_generation_prompt(description: str) -> str:
    scene = str(description).strip()
    return (
        "请生成一张横向 16:9 的日系二次元视觉小说场景背景。"
        f"场景内容：{scene}。"
        "画面采用自然的人眼高度与适合角色立绘叠加的中景构图，"
        "空间关系清楚，前景不过度遮挡，光线和时间氛围与场景描述一致，"
        "细节完整但不要抢夺对白人物的视觉中心。"
        "不要出现人物、人物剪影、文字、字幕、标志、水印或对话框。"
        "输出干净的纯背景图，适合直接导入 AzureArchive 作为剧情背景。"
    )
