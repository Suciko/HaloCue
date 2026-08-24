from __future__ import annotations

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


def assert_harness(
    status: dict,
    *,
    outcome: str,
    phase: str,
    primary_action: str,
) -> None:
    assert status["schema_version"] == "writing-harness-status/1.0"
    assert status["outcome"] == outcome
    assert status["phase"] == phase
    assert isinstance(status["headline"], str) and status["headline"].strip()
    assert isinstance(status["blockers"], list)
    assert isinstance(status["warnings"], list)
    assert isinstance(status["secondary_actions"], list)
    assert status["primary_action"]["id"] == primary_action
    assert isinstance(status["primary_action"]["label"], str)
    assert status["primary_action"]["label"].strip()
    assert status["primary_action"]["enabled"] is True
    steps = status["progress"]["steps"]
    assert steps
    assert all(step["id"] and step["label"] for step in steps)
    assert {step["status"] for step in steps} <= {
        "completed", "current", "upcoming", "blocked"
    }


def save_confirmed_brief(service: WritingService, work: dict) -> dict:
    return service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "爱丽丝与凯伊调查深夜亮起的旧终端。",
            "mode": "bond_short",
            "characters": ["爱丽丝", "凯伊"],
        },
    )["work"]


def save_blueprint(service: WritingService, work: dict) -> dict:
    return service.generate_blueprint(
        work["id"], {"expected_version": work["version"]}
    )["work"]


def save_chapter(service: WritingService, work: dict) -> dict:
    return service.create_chapter(
        work["id"],
        {"expected_version": work["version"], "title": "夜间调查"},
    )["work"]


def save_scene(service: WritingService, work: dict) -> tuple[dict, str]:
    created = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {
            "expected_version": work["version"],
            "title": "终端亮起",
            "location": "游戏开发部活动室",
            "goal": "确认异常提示灯的来源",
        },
    )
    return created["work"], created["scene_id"]


def save_manuscript(service: WritingService, work: dict, scene_id: str) -> dict:
    return service.save_scene_manuscript(
        work["id"],
        scene_id,
        {
            "expected_version": work["version"],
            "base_revision_id": None,
            "blocks": [
                {
                    "id": "block-action",
                    "type": "action",
                    "speaker": "",
                    "text": "深夜，旧终端忽然亮起。",
                },
                {
                    "id": "block-dialogue",
                    "type": "dialogue",
                    "speaker": "爱丽丝",
                    "text": "先确认它有没有连接网络。",
                },
            ],
        },
    )["work"]


def build_scene(service: WritingService) -> tuple[dict, str]:
    work = service.create_work({"title": "WritingHarness 状态矩阵"})
    work = save_confirmed_brief(service, work)
    work = save_blueprint(service, work)
    work = save_chapter(service, work)
    return save_scene(service, work)


def build_manuscript(service: WritingService) -> tuple[dict, str]:
    work, scene_id = build_scene(service)
    return save_manuscript(service, work, scene_id), scene_id


def test_new_work_points_to_brief_build(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "新作品"})

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="ready",
        phase="brief",
        primary_action="brief.build",
    )
    assert status["resume"] is None
    assert status["decision_basis"] == "当前作品还没有已确认的创意简报，先保存创作意图。"


def test_confirmed_brief_without_blueprint_points_to_blueprint(tmp_path):
    service = WritingService(tmp_path)
    work = save_confirmed_brief(service, service.create_work({"title": "只有 Brief"}))

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="ready",
        phase="blueprint",
        primary_action="blueprint.generate",
    )


def test_blueprint_without_real_chapter_points_to_chapter_creation(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "等待章节"})
    work = save_blueprint(service, save_confirmed_brief(service, work))

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="ready",
        phase="structure",
        primary_action="chapter.create",
    )
    assert work["chapters"][0]["status"] == "placeholder"


def test_real_chapter_without_scene_points_to_scene_creation(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "等待场景"})
    work = save_chapter(
        service,
        save_blueprint(service, save_confirmed_brief(service, work)),
    )

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="ready",
        phase="structure",
        primary_action="scene.create",
    )


def test_scene_without_manuscript_points_to_context_then_draft(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = build_scene(service)

    status = service.get_harness_status(
        work["id"], scope_type="scene", scope_id=scene_id
    )

    assert_harness(
        status,
        outcome="ready",
        phase="scene_draft",
        primary_action="scene.context.assemble",
    )
    assert "scene.draft.generate" in {
        action["id"] for action in status["secondary_actions"]
    }


def test_pending_scene_proposal_requires_user_apply_decision(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = build_scene(service)
    generated = service.generate_scene_candidate(
        work["id"], scene_id, {"expected_version": work["version"]}
    )

    status = service.get_harness_status(
        work["id"], scope_type="scene", scope_id=scene_id
    )

    assert_harness(
        status,
        outcome="needs_user",
        phase="proposal_review",
        primary_action="proposal.apply",
    )
    assert status["primary_action"]["target_id"] == generated["proposal_id"]


def test_manuscript_with_unresolved_memory_points_to_memory_maintenance(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = build_manuscript(service)

    status = service.get_harness_status(
        work["id"], scope_type="scene", scope_id=scene_id
    )

    assert_harness(
        status,
        outcome="in_progress",
        phase="memory",
        primary_action="memory.extract",
    )
    assert status["primary_action"]["target_id"] == scene_id


class BlockingReleaseReviewProvider(FakeWritingProvider):
    kind = "harness-release-review-test"
    is_simulation = False

    def review_release(self, context: dict) -> list[dict]:
        scene = context["scenes"][0]
        return [
            {
                "scene_id": scene["scene_id"],
                "revision_id": scene["revision_id"],
                "kind": "unresolved_payoff",
                "severity": "blocking",
                "message": "结尾承诺的线索尚未回收。",
                "evidence": {"scene_id": scene["scene_id"]},
            }
        ]


def prepare_release_review(service: WritingService) -> tuple[dict, str]:
    work, scene_id = build_manuscript(service)
    reviewed = service.review_scene(
        work["id"], scene_id, {"expected_version": work["version"]}
    )["work"]
    skipped = service.skip_scene_memory_maintenance(
        work["id"],
        scene_id,
        {
            "expected_version": reviewed["version"],
            "note": "状态矩阵测试显式跳过。",
        },
    )["work"]
    return skipped, scene_id


def test_blocking_release_review_points_back_to_review(tmp_path):
    service = WritingService(tmp_path)
    work, _scene_id = prepare_release_review(service)
    service.provider = BlockingReleaseReviewProvider()
    reviewed = service.review_release(
        work["id"], {"expected_version": work["version"]}
    )
    assert reviewed["status"] == "blocked"

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="blocked",
        phase="release_review",
        primary_action="release.review",
    )
    assert status["blockers"]


def test_frozen_script_release_completes_writing_and_points_to_production(tmp_path):
    service = WritingService(tmp_path)
    work, _scene_id = prepare_release_review(service)
    continuity = service.review_continuity(
        work["id"], {"expected_version": work["version"]}
    )
    reviewed = service.review_release(
        work["id"], {"expected_version": continuity["work"]["version"]}
    )
    assert reviewed["status"] == "passed"
    release = service.freeze_release(
        work["id"], {"expected_version": reviewed["work"]["version"]}
    )

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="completed",
        phase="released",
        primary_action="production.open",
    )
    assert status["primary_action"]["target_id"] == release["release_id"]


def test_failed_agent_run_with_fixed_snapshot_exposes_retry_resume(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "可恢复 Agent"})
    thread = work["conversation_threads"][0]

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "临时网络错误。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "继续分析。"},
        )
    run_id = failed.value.details["agent_run_id"]
    run = service.get_agent_run(work["id"], run_id)
    assert run["status"] == "failed"
    assert service.repo.read_text(run["input_snapshot_uri"])

    status = service.get_harness_status(work["id"])

    assert_harness(
        status,
        outcome="needs_user",
        phase="agent_recovery",
        primary_action="agent.retry",
    )
    assert status["resume"] == {
        "available": True,
        "agent_run_id": run_id,
        "input_snapshot_uri": run["input_snapshot_uri"],
        "input_digest": run["input_digest"],
    }


def test_later_successful_run_supersedes_old_failed_resume(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "恢复后继续"})
    thread = work["conversation_threads"][0]

    def fail_discussion(_messages, _context):
        raise DomainError("writing_provider_failed", "临时网络错误。", status=502)

    service.provider.discuss_work = fail_discussion
    with pytest.raises(DomainError) as failed:
        service.post_conversation_message(
            work["id"],
            thread["id"],
            {"expected_thread_version": thread["version"], "text": "先分析。"},
        )
    failed_run_id = failed.value.details["agent_run_id"]
    current = service.get_work(work["id"])
    current_thread = current["conversation_threads"][0]
    service.provider = FakeWritingProvider()
    service.retry_agent_run(
        work["id"],
        failed_run_id,
        {"expected_thread_version": current_thread["version"]},
    )

    status = service.get_harness_status(work["id"])

    assert status["phase"] != "agent_recovery"
    assert status["resume"] is None


def test_changed_canon_invalidates_old_release_review_gate(tmp_path):
    service = WritingService(tmp_path)
    work, _scene_id = prepare_release_review(service)
    reviewed = service.review_release(
        work["id"], {"expected_version": work["version"]}
    )
    assert reviewed["status"] == "passed"
    changed = service.save_work_canon(
        work["id"],
        {
            "expected_version": reviewed["work"]["version"],
            "facts": [
                {
                    "id": "fact-after-review",
                    "text": "旧终端没有接入外部网络。",
                    "source": "用户确认",
                    "scope": "work",
                    "confidence_status": "confirmed",
                }
            ],
        },
    )

    status = service.get_harness_status(changed["work"]["id"])

    assert status["phase"] == "release_review"
    assert status["primary_action"]["id"] == "continuity.review"


def test_changed_character_card_invalidates_old_release_review_gate(tmp_path):
    service = WritingService(tmp_path)
    work, _scene_id = prepare_release_review(service)
    card = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": "先核对风险再行动。",
            "source_type": "custom",
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
    )
    review_pack = service._assemble_work_review_pack(work["id"], "release.review")
    assert review_pack["character_cards"][0]["content"]["name"] == "凯伊"
    reviewed = service.review_release(
        work["id"], {"expected_version": card["work"]["version"]}
    )
    assert reviewed["status"] == "passed"
    character_ref = next(
        item
        for item in reviewed["snapshot"]["dependency_refs"]
        if item["kind"] == "character_card"
    )
    assert character_ref["scope_id"] == "character-kei"

    changed = service.save_character_card(
        work["id"],
        {
            "expected_version": reviewed["work"]["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": "封闭空间会放大警觉，证据不足时暂停结论。",
            "source_type": "custom",
            "source_refs": ["用户确认", "审查后修订"],
            "trust_status": "confirmed",
        },
    )

    status = service.get_harness_status(changed["work"]["id"])

    assert status["phase"] == "release_review"
    assert status["primary_action"]["id"] == "continuity.review"
    with pytest.raises(DomainError) as stale:
        service.freeze_release(
            work["id"], {"expected_version": changed["work"]["version"]}
        )
    assert stale.value.details["reason"] == "release_review_not_current"


def test_doctor_reports_simulation_as_warning_but_keeps_data_healthy(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "只读体检"})
    service.start()

    report = service.diagnose_writing_harness(work["id"])

    assert report["schema_version"] == "writing-harness-doctor/1.0"
    assert report["ok"] is True
    assert report["outcome"] == "partial"
    checks = {item["id"]: item for item in report["checks"]}
    assert checks["database.integrity"]["status"] == "ok"
    assert checks["revisions.integrity"]["status"] == "ok"
    assert checks["proposals.integrity"]["status"] == "ok"
    assert checks["ba_writing_pack.ready"]["status"] == "ok"
    assert checks["agent_dispatcher.running"]["status"] == "ok"
    assert checks["provider.available"]["status"] == "warning"
    service.close()
