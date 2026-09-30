import base64
from pathlib import Path
import pytest

from halocue_writing.errors import DomainError
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


def test_adaptation_list_is_scoped_to_work_and_newest_first(tmp_path: Path):
    service = WritingService(tmp_path)
    first_work = service.create_work({"title": "第一部"})
    second_work = service.create_work({"title": "第二部"})
    first_source = source(service, first_work["id"], "第一章\n甲在门口停下。")
    second_source = source(service, second_work["id"], "第一章\n乙在窗边回头。")
    older = service.adaptations.create(first_work["id"], {"source_version_id": first_source["id"]})
    newer = service.adaptations.create(first_work["id"], {"source_version_id": first_source["id"]})
    service.adaptations.create(second_work["id"], {"source_version_id": second_source["id"]})
    listed = service.adaptations.list(first_work["id"])
    assert [item["id"] for item in listed] == [newer["id"], older["id"]]
    assert all(item["work_id"] == first_work["id"] for item in listed)


def test_novel_chapters_keep_their_explicit_destination(tmp_path: Path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "小说改编"})
    current = source(service, work["id"], "第一章\n灯亮了。\n第二章\n门打开了。")
    first = service.create_chapter(work["id"], {"expected_version": work["version"], "title": "第一章"})
    second = service.create_chapter(work["id"], {"expected_version": first["work"]["version"], "title": "第二章"})
    ids = [ch["id"] for ch in current["chapters"]]
    destinations = {ids[0]: first["chapter_id"], ids[1]: second["chapter_id"]}
    plan = service.adaptations.create(work["id"], {
        "source_version_id": current["id"], "chapter_ids": ids,
        "target_chapter_ids": destinations,
    })
    assert plan["plan"]["target_chapter_ids"] == destinations
    assert [row["resolved_target"]["chapter_id"] for row in plan["chapters"]] == list(destinations.values())
    service.adaptations.approve_plan(plan["id"], {"plan_digest": plan["plan_digest"]})
    generated = service.adaptations.generate_chapter_candidate(plan["id"], ids[1])
    assert generated["candidate"]["target"]["chapter_id"] == second["chapter_id"]
    adopted = service.accept_proposal(work["id"], generated["proposal_id"], {
        "expected_version": second["work"]["version"]
    })
    assert any(scene["id"] == adopted["scene_id"] for scene in adopted["work"]["chapters"][1]["scenes"])


def test_oversized_chapter_stops_before_model_call_or_budget_charge(tmp_path: Path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "长篇原文"})
    current = source(service, work["id"], "第一章\n" + "灯" * 30001)
    plan = service.adaptations.create(work["id"], {"source_version_id": current["id"], "max_calls": 1})
    service.adaptations.approve_plan(plan["id"], {"plan_digest": plan["plan_digest"]})
    with pytest.raises(DomainError) as blocked:
        service.adaptations.generate_chapter_candidate(plan["id"], current["chapters"][0]["id"])
    assert blocked.value.code == "adaptation_chapter_too_large"
    assert service.adaptations.get(plan["id"])["budget"]["reserved_calls"] == 0
