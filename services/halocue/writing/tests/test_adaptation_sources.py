import base64
import io
import zipfile

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService
from halocue_writing.source_catalog import source_windows
from halocue_writing.story_import import parse_story_bytes


def upload(text, **kwargs):
    return {"filename": "fiction.txt", "content_base64": base64.b64encode(text.encode("utf-8")).decode("ascii"), **kwargs}


def apply_source(service, work_id, payload):
    preview = service.sources.preview(work_id, payload)
    return service.sources.apply(work_id, {**payload, "preview_digest": preview["preview_digest"]})


def test_same_titles_and_scenes_keep_source_order():
    parsed = parse_story_bytes("fiction.txt", "第一章序章\n第一场重逢\n旁白：甲\n第二场转场\n旁白：乙\n第一场重逢\n旁白：丙\n第一章序章\n旁白：丁".encode())
    groups = WritingService._import_lines_by_chapter(parsed, source_kind="story")
    assert len(groups) == 2
    assert [scene["lines"] for scene in groups[0]["scenes"]] == [["旁白：甲"], ["旁白：乙"], ["旁白：丙"]]
    assert groups[1]["scenes"][0]["lines"] == ["旁白：丁"]


def test_docx_final_text_matches_attachment_parser():
    body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第一章序章</w:t></w:r></w:p><w:p><w:del><w:r><w:delText>删除内容</w:delText></w:r></w:del><w:moveFrom><w:r><w:t>旧位置</w:t></w:r></w:moveFrom><w:ins><w:r><w:t>保留内容</w:t><w:tab/><w:t>对白</w:t></w:r></w:ins></w:p></w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", body)
    raw = buffer.getvalue()
    parsed = parse_story_bytes("fiction.docx", raw)
    attachment, _, _ = WritingService._extract_document_text(".docx", raw)
    assert "删除" not in parsed["normalized_text"]
    assert "旧位置" not in attachment
    assert "保留内容" in parsed["normalized_text"] and "保留内容" in attachment


def test_append_update_and_duplicate_preserve_immutable_versions(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "连载测试"})
    first = apply_source(service, work["id"], upload("第一章序章\n共同段落\n他没有说完。"))["source"]
    first_chapter = first["chapters"][0]
    second_payload = upload("第一章序章\n新章仍未结束。", base_version_id=first["id"])
    second = apply_source(service, work["id"], second_payload)["source"]
    assert second["chapters"][0] == first_chapter
    assert second["chapters"][1]["id"] != first_chapter["id"]
    duplicate = apply_source(service, work["id"], {**second_payload, "base_version_id": second["id"]})
    assert duplicate["duplicate"] and duplicate["source"]["id"] == second["id"]
    update = upload("第一章序章\n共同段落\n新的未完段落", mode="update", chapter_ids=[first_chapter["id"]], base_version_id=second["id"])
    third = apply_source(service, work["id"], update)["source"]
    assert third["chapters"][0]["id"] == first_chapter["id"]
    assert third["chapters"][0]["paragraphs"][0]["id"] == first_chapter["paragraphs"][0]["id"]
    assert third["chapters"][1] == second["chapters"][1]
    assert service.sources.get(work["id"], first["id"])["chapters"] == first["chapters"]
    assert third["completion_state"] == "ongoing"
    assert service.get_work(work["id"])["version"] == work["version"]


def test_source_update_requires_current_preview(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "冲突测试"})
    original = upload("原文尚未结束")
    preview = service.sources.preview(work["id"], original)
    with pytest.raises(DomainError, match="差异"):
        service.sources.apply(work["id"], {**upload("已被改动"), "preview_digest": preview["preview_digest"]})
    first = apply_source(service, work["id"], original)["source"]
    with pytest.raises(DomainError) as rejected:
        service.sources.preview(work["id"], original)
    assert rejected.value.code == "source_version_conflict"
    assert service.sources.get(work["id"])["id"] == first["id"]


@pytest.mark.parametrize("characters", [99000, 100000, 500000])
def test_long_source_windows_cover_every_character_once(characters):
    text = ("这是未完结的原文段落。" * characters)[:characters]
    chapters = [{"id": "chapter-a", "title": "长章", "paragraphs": [{"id": "p-a", "text": text}]}]
    windows = source_windows(chapters, 8000)
    spans = [span for window in windows for span in window["spans"]]
    assert "".join(span["text"] for span in spans) == text
    assert spans[0]["start"] == 0 and spans[-1]["end"] == characters
    assert all(left["end"] == right["start"] for left, right in zip(spans, spans[1:]))
    assert all(sum(len(span["text"]) for span in window["spans"]) <= 8000 for window in windows)
