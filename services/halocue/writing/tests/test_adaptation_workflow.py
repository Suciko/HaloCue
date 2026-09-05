import base64
from pathlib import Path

from halocue_writing.service import WritingService


def payload(text, **extra):
    return {"filename": "chapters.txt", "content_base64": base64.b64encode(text.encode()).decode(), **extra}


def source(service, work_id, value, **extra):
    request = payload(value, **extra)
    preview = service.sources.preview(work_id, request)
    return service.sources.apply(work_id, {**request, "preview_digest": preview["preview_digest"]})["source"]


def test_adaptation_plan_approval_and_checkpointed_analysis(tmp_path: Path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "十万字以下未完结改编"})
    current = source(service, work["id"], "第一章\n老师没有说完。\n第二章\n灯还亮着。", completion_state="ongoing")
    adaptation = service.adaptations.create(work["id"], {"source_version_id": current["id"], "max_calls": 4})
    assert adaptation["status"] == "awaiting_plan"
    assert adaptation["plan"]["unfinished_policy"] == "provided_scope_only"
    approved = service.adaptations.approve_plan(adaptation["id"], {"plan_digest": adaptation["plan_digest"]})
    assert approved["status"] == "ready"
    result = service.adaptations.run(adaptation["id"], {"window_characters": 256})
    assert result["status"] == "running"
    assert all(chapter["status"] == "analyzed" for chapter in result["chapters"])
    assert all(chapter["candidate"]["source_only"] for chapter in result["chapters"])
    assert all(chapter["candidate"]["coverage"] for chapter in result["chapters"])


def test_chapter_candidate_is_source_bound_and_non_formal(tmp_path: Path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "候选测试"})
    current = source(service, work["id"], "第一章\n老师没有说完。", completion_state="ongoing")
    adaptation = service.adaptations.create(work["id"], {"source_version_id": current["id"]})
    adaptation = service.adaptations.approve_plan(adaptation["id"], {"plan_digest": adaptation["plan_digest"]})
    chapter_id = adaptation["selected_chapter_ids"][0]
    generated = service.adaptations.generate_chapter_candidate(adaptation["id"], chapter_id)
    candidate = generated["adaptation"]
    row = next(item for item in candidate["chapters"] if item["source_chapter_id"] == chapter_id)
    assert row["status"] == "candidate"
    assert row["candidate"]["formal"] is False
    assert row["candidate"]["source_version_id"] == current["id"]
    accepted = service.accept_proposal(work["id"], generated["proposal_id"], {"expected_version": work["version"]})
    accepted_row = next(item for item in service.adaptations.get(adaptation["id"])["chapters"] if item["source_chapter_id"] == chapter_id)
    assert accepted["revision_id"]
    assert accepted_row["status"] == "accepted"
    assert accepted_row["candidate"]["formal"] is True
