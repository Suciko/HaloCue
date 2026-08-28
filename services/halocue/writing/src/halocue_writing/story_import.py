"""Read-only TXT and DOCX inspection for the story-import/1.0 workflow."""

from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from collections import Counter
from pathlib import PurePath
from xml.etree import ElementTree

from .repository import sha256_bytes


MAX_STORY_BYTES = 16_000_000
MAX_EXTRACTED_CHARACTERS = 2_000_000
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CHAPTER_RE = re.compile(
    r"^\s*(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[章节卷部篇]|chapter\s+\d+)\b.*$",
    re.IGNORECASE,
)
SCENE_RE = re.compile(
    r"^\s*(?:第\s*[0-9零〇一二三四五六七八九十百千万两]+\s*[场幕]|场景\s*[0-9零〇一二三四五六七八九十百千万两]+|scene\s+\d+)\b.*$",
    re.IGNORECASE,
)
SPEAKER_RE = re.compile(r"^\s*([^：:\n]{1,20})[：:]\s*(.+)$")


def _safe_filename(filename: str) -> str:
    return str(filename or "").strip().replace("\\", "/").split("/")[-1]


def _decode_txt(raw: bytes) -> tuple[list[str], str]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("TXT 需要使用 UTF-8 或常见中文编码。")
    if "\x00" in text:
        raise ValueError("TXT 包含无法识别的二进制内容。")
    return [line.strip() for line in text.splitlines() if line.strip()], encoding


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag in {WORD_NS + "t", WORD_NS + "delText"} and node.text:
            parts.append(node.text)
        elif node.tag == WORD_NS + "tab":
            parts.append("\t")
        elif node.tag in {WORD_NS + "br", WORD_NS + "cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _decode_docx(raw: bytes) -> tuple[list[str], str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise ValueError("DOCX 缺少正文内容。")
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_EXTRACTED_CHARACTERS * 8:
                raise ValueError("DOCX 正文过大，当前版本无法安全预览。")
            document = ElementTree.fromstring(archive.read(info))
    except ValueError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError) as exc:
        raise ValueError("DOCX 无法读取，请先用 Word 或 LibreOffice 重新保存。") from exc

    paragraphs = [text for item in document.iter(WORD_NS + "p") if (text := _docx_paragraph_text(item))]
    return paragraphs, "wordprocessingml"


def _analyse_paragraphs(paragraphs: list[str]) -> dict:
    if sum(len(item) for item in paragraphs) > MAX_EXTRACTED_CHARACTERS:
        raise ValueError("文档正文超过 200 万字，建议按卷或章节拆分后导入。")
    if not paragraphs:
        raise ValueError("文档中没有可识别的正文。")

    explicit_chapters = any(CHAPTER_RE.match(item) for item in paragraphs)
    explicit_scenes = any(SCENE_RE.match(item) for item in paragraphs)
    chapters: list[dict] = []
    scenes: list[dict] = []
    characters: Counter[str] = Counter()
    lines: list[dict] = []
    current_chapter: dict | None = None
    current_scene: dict | None = None

    def ensure_chapter() -> dict:
        nonlocal current_chapter
        if current_chapter is None:
            current_chapter = {"title": "未分章内容", "paragraph_count": 0, "scene_count": 0}
            chapters.append(current_chapter)
        return current_chapter

    def ensure_scene() -> dict:
        nonlocal current_scene
        chapter = ensure_chapter()
        if current_scene is None:
            current_scene = {
                "title": "正文",
                "chapter_title": chapter["title"],
                "paragraph_count": 0,
                "first_paragraph": len(lines) + 1,
                "last_paragraph": len(lines) + 1,
            }
            scenes.append(current_scene)
            chapter["scene_count"] += 1
        return current_scene

    for source_index, paragraph in enumerate(paragraphs, start=1):
        if CHAPTER_RE.match(paragraph):
            current_chapter = {"title": paragraph, "paragraph_count": 0, "scene_count": 0}
            chapters.append(current_chapter)
            current_scene = None
            continue
        if SCENE_RE.match(paragraph):
            chapter = ensure_chapter()
            current_scene = {
                "title": paragraph,
                "chapter_title": chapter["title"],
                "paragraph_count": 0,
                "first_paragraph": len(lines) + 1,
                "last_paragraph": len(lines) + 1,
            }
            scenes.append(current_scene)
            chapter["scene_count"] += 1
            continue

        chapter = ensure_chapter()
        scene = ensure_scene()
        speaker_match = SPEAKER_RE.match(paragraph)
        speaker = speaker_match.group(1).strip() if speaker_match else ""
        text = speaker_match.group(2).strip() if speaker_match else paragraph
        kind = "dialogue" if speaker else "action" if paragraph.startswith(("（", "(", "【", "[")) else "narration"
        if speaker:
            characters[speaker] += 1
        chapter["paragraph_count"] += 1
        scene["paragraph_count"] += 1
        scene["last_paragraph"] = len(lines) + 1
        lines.append(
            {
                "source_paragraph": source_index,
                "chapter": chapter["title"],
                "scene": scene["title"],
                "kind": kind,
                "speaker": speaker,
                "text": text,
            }
        )

    suggestions: list[str] = []
    if not explicit_chapters:
        suggestions.append("没有识别到章节标题；确认前可以先补成“第一章 ……”这样的标题。")
    if not explicit_scenes:
        suggestions.append("没有识别到场景标题；系统会先把每章视为一个连续场景。")
    if not characters:
        suggestions.append("没有识别到“角色：对白”格式；后续需要确认角色与旁白的对应关系。")

    return {
        "counts": {
            "chapters": len(chapters),
            "scenes": len(scenes),
            "paragraphs": len(lines),
            "dialogues": sum(item["kind"] == "dialogue" for item in lines),
            "characters": len(characters),
        },
        "chapters": chapters,
        "scenes": scenes,
        "characters": [{"name": name, "line_count": count} for name, count in characters.most_common()],
        "lines": lines,
        "repair_suggestions": suggestions,
    }


def parse_story_bytes(filename: str, raw: bytes) -> dict:
    safe_name = _safe_filename(filename)
    suffix = PurePath(safe_name).suffix.lower()
    if suffix not in {".txt", ".docx"}:
        raise ValueError("请选择 TXT 或 DOCX 文档。")
    if not raw:
        raise ValueError("导入文件为空。")
    if len(raw) > MAX_STORY_BYTES:
        raise ValueError("TXT 或 DOCX 不能超过 16 MB。")

    paragraphs, encoding = _decode_txt(raw) if suffix == ".txt" else _decode_docx(raw)
    analysis = _analyse_paragraphs(paragraphs)
    return {
        "schema_version": "story-import/1.0",
        "source_type": suffix.removeprefix("."),
        "filename": safe_name,
        "source_digest": sha256_bytes(raw),
        "source_size": len(raw),
        "source_encoding": encoding,
        "project_title": PurePath(safe_name).stem,
        **analysis,
        "write_boundary": "preview_only_until_user_confirmation",
    }


def parse_story_payload(payload: dict) -> dict:
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or not encoded.strip():
        raise ValueError("导入文件内容为空。")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("导入文件编码无效。") from exc
    return parse_story_bytes(str(payload.get("filename") or ""), raw)
