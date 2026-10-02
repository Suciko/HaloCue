"""Quick review reduces routine work while retaining provenance and blockers."""

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService
from test_vertical_slice import build_to_proposal


def _accepted_scene(service):
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"]}
    )
    return work_id, scene_id, accepted["work"]


def test_quick_review_can_freeze_without_per_scene_check_or_memory_decisions(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = _accepted_scene(service)
    standard = service.review_release(work_id, {"expected_version": work["version"]})
    assert standard["status"] == "blocked"
    assert standard["snapshot"]["unreviewed_revision_ids"]
    assert standard["snapshot"]["incomplete_memory_scene_ids"] == [scene_id]

    continuity = service.review_continuity(
        work_id, {"expected_version": standard["work"]["version"]}
    )
    quick = service.review_release(
        work_id,
        {"expected_version": continuity["work"]["version"], "review_profile": "quick"},
    )
    assert continuity["status"] == "passed"
    assert quick["status"] == "passed"
    assert quick["snapshot"]["review_profile"] == "quick"
    assert quick["snapshot"]["unreviewed_revision_ids"]
    assert quick["snapshot"]["incomplete_memory_scene_ids"] == [scene_id]
    frozen = service.freeze_release(work_id, {"expected_version": quick["work"]["version"]})
    assert frozen["manifest"]["memory_maintenance"][0]["complete"] is False
    assert service.get_release(frozen["release_id"])["manifest"]["release_id"] == frozen["release_id"]


def test_quick_review_still_blocks_real_review_findings(tmp_path):
    class BlockingProvider(FakeWritingProvider):
        def review_release(self, context):
            scene = context["scenes"][0]
            return [{
                "scene_id": scene["scene_id"],
                "revision_id": scene["revision_id"],
                "kind": "unresolved_payoff",
                "severity": "blocking",
                "message": "关键线索尚未交代。",
                "evidence": {"scene_id": scene["scene_id"]},
            }]

    service = WritingService(tmp_path)
    work_id, _scene_id, work = _accepted_scene(service)
    continuity = service.review_continuity(work_id, {"expected_version": work["version"]})
    service.provider = BlockingProvider()
    quick = service.review_release(
        work_id,
        {"expected_version": continuity["work"]["version"], "review_profile": "quick"},
    )
    assert quick["status"] == "blocked"
    assert quick["findings"][0]["severity"] == "blocking"
    with pytest.raises(DomainError) as rejected:
        service.freeze_release(work_id, {"expected_version": quick["work"]["version"]})
    assert rejected.value.code == "release_blocked"


def test_quick_review_rejects_unknown_profile(tmp_path):
    service = WritingService(tmp_path)
    work_id, _scene_id, work = _accepted_scene(service)
    with pytest.raises(DomainError) as rejected:
        service.review_release(work_id, {"expected_version": work["version"], "review_profile": "skip_all"})
    assert rejected.value.code == "invalid_review_profile"
    assert service.get_work(work_id)["version"] == work["version"]


def test_retry_keeps_quick_review_profile(tmp_path):
    class FailingProvider(FakeWritingProvider):
        def review_release(self, context):
            raise DomainError("provider_failed", "模拟提供方中断。", status=502)

    service = WritingService(tmp_path)
    work_id, _scene_id, work = _accepted_scene(service)
    service.provider = FailingProvider()
    with pytest.raises(DomainError):
        service.review_release(
            work_id, {"expected_version": work["version"], "review_profile": "quick"}
        )
    failed = next(run for run in service.get_work(work_id)["agent_runs"] if run["status"] == "failed")
    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work_id, failed["id"], {"expected_version": work["version"]}
    )
    assert retried["status"] == "passed"
    assert retried["snapshot"]["review_profile"] == "quick"
