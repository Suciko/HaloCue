from __future__ import annotations

import base64
import io
import zipfile

import pytest

from halocue_writing.story_import import parse_story_payload


def _encoded(filename: str, content: bytes) -> dict:
    return {
        "filename": filename,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return target.getvalue()


def test_txt_preview_detects_chapters_scenes_and_dialogue_without_writing():
    preview = parse_story_payload(
        _encoded(
            "午后故事.txt",
            "第一章 走廊\n场景一 午后\n星野：天气真好。\n阳光落在地板上。\n\n第二章 车站\n爱丽丝：听见广播了。".encode("utf-8"),
        )
    )

    assert preview["schema_version"] == "story-import/1.0"
    assert preview["source_type"] == "txt"
    assert preview["write_boundary"] == "preview_only_until_user_confirmation"
    assert preview["counts"]["chapters"] == 2
    assert preview["counts"]["scenes"] == 2
    assert preview["counts"]["dialogues"] == 2
    assert {item["name"] for item in preview["characters"]} == {"星野", "爱丽丝"}


def test_docx_preview_reads_paragraphs_and_returns_repair_guidance():
    preview = parse_story_payload(
        _encoded("旧小说.docx", _docx(["没有标准章节标题", "爱丽丝：这里是哪里？", "她推开门。"])),
    )

    assert preview["source_type"] == "docx"
    assert preview["counts"]["paragraphs"] == 3
    assert preview["counts"]["chapters"] == 1
    assert preview["characters"] == [{"name": "爱丽丝", "line_count": 1}]
    assert any("章节标题" in item for item in preview["repair_suggestions"])


def test_story_preview_rejects_unsupported_or_broken_documents():
    with pytest.raises(ValueError, match="TXT 或 DOCX"):
        parse_story_payload(_encoded("旧稿.pdf", b"not a story"))
    with pytest.raises(ValueError, match="无法读取"):
        parse_story_payload(_encoded("损坏.docx", b"not a zip"))
