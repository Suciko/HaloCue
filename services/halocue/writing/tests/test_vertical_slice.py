import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.errors import DomainError, RevisionConflict
from halocue_writing import service as service_module
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService
from halocue_writing.workflow_pack import MODE_SOURCES


class ReviewUsageProvider(FakeWritingProvider):
    is_simulation = False
    kind = "review-usage-test"
    display_name = "Review usage test provider"

    def last_usage(self):
        return {
            "input_tokens": 120,
            "output_tokens": 40,
            "cache_read_tokens": 60,
            "cache_write_tokens": 10,
            "estimated_cost": 0.0025,
        }


def build_to_proposal(service: WritingService):
    work = service.create_work({"title": "迟到的线索"})
    result = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "凯伊发现旧机器在深夜自行启动",
            "mode": "bond_short",
            "characters": ["爱丽丝", "凯伊"],
        },
    )
    result = service.generate_blueprint(work["id"], {"expected_version": result["work"]["version"]})
    result = service.create_chapter(work["id"], {"expected_version": result["work"]["version"], "title": "第一章"})
    chapter_id = result["chapter_id"]
    result = service.create_scene(
        work["id"],
        chapter_id,
        {
            "expected_version": result["work"]["version"],
            "title": "提示灯",
            "location": "游戏开发部活动室",
            "goal": "确认异常提示灯的来源",
        },
    )
    scene_id = result["scene_id"]
    context = service.assemble_context(work["id"], scene_id)
    assert context["scene_id"] == scene_id
    assert context["readiness"]["fake_provider"] == "ready"
    assert context["readiness"]["real_ba_writing"] == "blocked"
    result = service.generate_scene_candidate(
        work["id"], scene_id, {"expected_version": result["work"]["version"]}
    )
    return work["id"], scene_id, result["proposal_id"], result["work"]


def skip_memory_for_current_scenes(service: WritingService, work: dict) -> dict:
    current = work
    scene_ids = [
        scene["id"]
        for chapter in work["chapters"]
        for scene in chapter["scenes"]
        if scene.get("current_revision_id")
    ]
    for scene_id in scene_ids:
        current = service.skip_scene_memory_maintenance(
            work["id"], scene_id,
            {"expected_version": current["version"], "note": "测试明确跳过记忆维护。"},
        )["work"]
    return current


def review_for_release(service: WritingService, work: dict) -> dict:
    continuity = service.review_continuity(
        work["id"], {"expected_version": work["version"]},
    )
    return service.review_release(
        work["id"], {"expected_version": continuity["work"]["version"]},
    )


def test_feedback_report_is_persisted_with_page_context(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "反馈验收", "idea": "测试反馈入口"})

    report = service.submit_feedback(
        {
            "work_id": work["id"],
            "category": "usability",
            "summary": "侧栏不知道下一步点哪里",
            "details": "希望突出当前步骤并减少重复入口。",
            "context": {"stage": "structure", "viewport": {"width": 1440, "height": 900}},
        }
    )

    restarted = WritingService(tmp_path)
    with restarted.repo.connect() as connection:
        saved = connection.execute(
            "SELECT * FROM feedback_reports WHERE id=?", (report["id"],)
        ).fetchone()
    assert saved["status"] == "open"
    assert saved["work_id"] == work["id"]
    assert saved["summary"] == "侧栏不知道下一步点哪里"
    assert json.loads(saved["context_json"])["stage"] == "structure"

    with pytest.raises(DomainError) as error:
        service.submit_feedback({"category": "usability", "summary": "", "details": ""})
    assert error.value.code == "validation_error"

    without_work = service.submit_feedback(
        {"work_id": None, "category": "suggestion", "summary": "空作品反馈", "details": "尚未建立作品时也应允许反馈。"}
    )
    assert without_work["stored_locally"] is True


def test_feedback_syncs_server_side_and_retries_without_duplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("HALOCUE_FEEDBACK_REMOTE_URL", "http://feedback.test/api/halocue/feedback")
    monkeypatch.setenv("HALOCUE_FEEDBACK_REMOTE_TOKEN", "server-secret")
    calls = []

    def unavailable(request, timeout):
        calls.append((request, timeout))
        raise OSError("offline")

    monkeypatch.setattr(service_module.urllib.request, "urlopen", unavailable)
    service = WritingService(tmp_path)
    report = service.submit_feedback(
        {
            "category": "runtime_error",
            "summary": "生成候选时报错",
            "details": "点击生成后出现 502。",
            "severity": "blocker",
            "context": {"stage": "draft"},
            "error": {"code": "writing_provider_failed", "http_status": 502},
        }
    )
    assert report["remote"]["status"] == "pending"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"id":"feedback-remote-1","status":"open"}'

    def available(request, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr(service_module.urllib.request, "urlopen", available)
    retry = service.sync_pending_feedback()
    assert retry == {"status": "completed", "synced": 1, "pending": 0}
    sent = json.loads(calls[-1][0].data.decode("utf-8"))
    assert sent["source_id"] == report["id"]
    assert sent["error"]["code"] == "writing_provider_failed"
    assert calls[-1][0].headers["Authorization"] == "Bearer server-secret"
    with service.repo.connect() as connection:
        saved = connection.execute("SELECT * FROM feedback_reports WHERE id=?", (report["id"],)).fetchone()
    assert saved["remote_status"] == "synced"
    assert saved["remote_id"] == "feedback-remote-1"


def test_real_vertical_slice_persists_and_reloads(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    edited = "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": edited},
    )
    reviewed = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = review_for_release(service, memory_ready)
    assert release_review["status"] == "passed"
    release = service.freeze_release(
        work_id, {"expected_version": release_review["work"]["version"]}
    )

    restarted = WritingService(tmp_path)
    loaded = restarted.get_work(work_id)
    loaded_scene = loaded["chapters"][0]["scenes"][0]
    assert loaded_scene["id"] == scene_id
    assert loaded_scene["current_revision_id"] == accepted["revision_id"]
    frozen = restarted.get_release(release["release_id"])
    assert frozen["text"] == "## 提示灯\n" + edited.rstrip() + "\n"
    assert frozen["manifest"]["scenes"][0]["scene_id"] == scene_id
    assert frozen["content_hash"].startswith("sha256:")


def test_scene_continuity_and_release_review_usage_enters_agent_total(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"},
    )
    alice = service.save_character_card(
        work_id,
        {
            "expected_version": accepted["work"]["version"],
            "name": "爱丽丝",
            "voice_anchors": ["先确认眼前的情况。"],
            "ooc_constraints": ["不替其他人猜测动机"],
            "source_refs": ["用户确认"],
        },
    )
    kay = service.save_character_card(
        work_id,
        {
            "expected_version": alice["work"]["version"],
            "name": "凯伊",
            "voice_anchors": ["让我先看看日志。"],
            "ooc_constraints": ["不无端泄露未知事实"],
            "source_refs": ["用户确认"],
        },
    )
    service.provider = ReviewUsageProvider()

    scene_review = service.review_scene(
        work_id, scene_id, {"expected_version": kay["work"]["version"]},
    )
    usage = service.agent_usage(work_id)
    assert usage["input_tokens"] == 120
    assert usage["estimated_cost"] == pytest.approx(0.0025)

    memory_ready = skip_memory_for_current_scenes(service, scene_review["work"])
    continuity = service.review_continuity(
        work_id, {"expected_version": memory_ready["version"]},
    )
    usage = service.agent_usage(work_id)
    assert usage["input_tokens"] == 240
    assert usage["estimated_cost"] == pytest.approx(0.005)

    release_review = service.review_release(
        work_id, {"expected_version": continuity["work"]["version"]},
    )
    usage = service.agent_usage(work_id)
    assert usage["input_tokens"] == 360
    assert usage["cache_read_tokens"] == 180
    assert usage["cache_hit_rate"] == pytest.approx(0.5)
    assert usage["estimated_cost"] == pytest.approx(0.0075)

    review_runs = [
        run for run in release_review["work"]["agent_runs"]
        if run["policy"].get("workflow") in {"scene.review", "continuity.review", "release.review"}
    ]
    assert len(review_runs) == 3
    assert all(run["policy"]["usage"]["input_tokens"] == 120 for run in review_runs)


def test_manual_scene_blocks_are_versioned_restart_safe_and_release_compatible(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"},
    )
    pending = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]}
    )
    blocks = [
        {"id": "block-narration", "type": "narration", "text": "灯光在桌面上缓慢移动。"},
        {"id": "block-opening", "type": "action", "text": "深夜的活动室里，旧显示器先亮了一格。"},
        {"id": "block-aris-01", "type": "dialogue", "speaker": "爱丽丝", "text": "先确认电源。"},
        {"id": "block-kay-01", "type": "dialogue", "speaker": "凯伊", "text": "我去看背面的线路。"},
    ]
    saved = service.save_scene_manuscript(
        work_id,
        scene_id,
        {
            "expected_version": pending["work"]["version"],
            "expected_base_revision_id": accepted["revision_id"],
            "blocks": blocks,
        },
    )
    assert saved["superseded_proposal_ids"] == [pending["proposal_id"]]
    scene = saved["work"]["chapters"][0]["scenes"][0]
    artifact = next(item for item in saved["work"]["artifacts"] if item["kind"] == "scene_script")
    assert scene["current_revision_id"] == saved["revision_id"]
    assert artifact["current_revision"]["schema_version"] == "scene-blocks/1.0"
    assert artifact["current_revision"]["content"]["blocks"] == blocks
    assert artifact["current_revision"]["content"]["text"] == (
        "旁白: 灯光在桌面上缓慢移动。\n深夜的活动室里，旧显示器先亮了一格。\n爱丽丝: 先确认电源。\n凯伊: 我去看背面的线路。\n"
    )
    superseded = next(item for item in saved["work"]["proposals"] if item["id"] == pending["proposal_id"])
    assert superseded["status"] == "superseded"

    with pytest.raises(RevisionConflict):
        service.save_scene_manuscript(
            work_id,
            scene_id,
            {"expected_version": pending["work"]["version"], "expected_base_revision_id": saved["revision_id"], "blocks": blocks},
        )
    with pytest.raises(DomainError) as error:
        service.save_scene_manuscript(
            work_id,
            scene_id,
            {
                "expected_version": saved["work"]["version"],
                "expected_base_revision_id": accepted["revision_id"],
                "blocks": blocks,
            },
        )
    assert error.value.code == "manuscript_conflict"

    restarted = WritingService(tmp_path)
    restored = restarted.get_work(work_id)
    restored_artifact = next(item for item in restored["artifacts"] if item["kind"] == "scene_script")
    assert [block["id"] for block in restored_artifact["current_revision"]["content"]["blocks"]] == [
        "block-narration", "block-opening", "block-aris-01", "block-kay-01"
    ]
    reviewed = restarted.review_scene(work_id, scene_id, {"expected_version": restored["version"]})
    memory_ready = skip_memory_for_current_scenes(restarted, reviewed["work"])
    release_review = review_for_release(restarted, memory_ready)
    release = restarted.freeze_release(work_id, {"expected_version": release_review["work"]["version"]})
    assert restarted.get_release(release["release_id"])["text"] == (
        "## 提示灯\n"
        "旁白: 灯光在桌面上缓慢移动。\n"
        "深夜的活动室里，旧显示器先亮了一格。\n"
        "爱丽丝: 先确认电源。\n"
        "凯伊: 我去看背面的线路。\n"
    )


def test_scene_proposal_exposes_character_level_diff_evidence(tmp_path):
    service = WritingService(tmp_path)
    base = [
        {"id": "block-aris", "type": "dialogue", "speaker": "爱丽丝", "text": "先确认电源。"},
    ]
    changes = service._scene_block_change_plan(
        base,
        "爱丽丝: 先确认电源和线路。\n",
        "sha256:candidate",
    )

    assert len(changes) == 1
    inline = changes[0]["inline_diff"]
    assert inline[0]["old_block_id"] == "block-aris"
    assert {segment["kind"] for segment in inline[0]["segments"]} == {"equal", "insert"}
    assert any(segment["text"] == "和线路" for segment in inline[0]["segments"] if segment["kind"] == "insert")

    work_id, _scene_id, proposal_id, work = build_to_proposal(service)
    proposal = next(item for item in work["proposals"] if item["id"] == proposal_id)
    assert proposal["block_changes"]
    assert proposal["block_changes"][0]["inline_diff"]


def test_scene_proposal_aligns_a_full_rewrite_into_reviewable_block_changes(tmp_path):
    service = WritingService(tmp_path)
    base = [
        {"id": "block-old-1", "type": "narration", "text": "午后的光落在走廊上。"},
        {"id": "block-old-2", "type": "dialogue", "speaker": "星野", "text": "真适合睡一觉。"},
        {"id": "block-old-3", "type": "dialogue", "speaker": "凯伊", "text": "这里并不适合休息。"},
        {"id": "block-old-4", "type": "dialogue", "speaker": "凯伊", "text": "而且你并不困。"},
        {"id": "block-old-5", "type": "dialogue", "speaker": "星野", "text": "被你发现了呢。"},
        {"id": "block-old-6", "type": "narration", "text": "凯伊转身离开。"},
    ]
    candidate = (
        "旁白: 阳光把窗格的影子拉得很长。\n"
        "星野: 偶尔偷懒一下也没关系吧。\n"
        "凯伊: 你的状态并不符合困倦特征。\n"
        "星野: 还是被你拆穿了呢。\n"
        "旁白: 凯伊抱着终端走向转角。\n"
    )

    changes = service._scene_block_change_plan(base, candidate, "sha256:rewrite")

    assert len(changes) == 6
    assert [change["kind"] for change in changes].count("delete") == 1
    replacements = [change for change in changes if change["kind"] == "replace"]
    assert all(len(change["old_blocks"]) == len(change["new_blocks"]) == 1 for change in replacements)
    assert [
        (change["old_blocks"][0].get("speaker"), change["new_blocks"][0].get("speaker"))
        for change in replacements
        if change["old_blocks"][0]["type"] == "dialogue"
    ] == [("星野", "星野"), ("凯伊", "凯伊"), ("星野", "星野")]

    first_change = changes[0]
    partially_applied = service._apply_scene_block_changes(
        base, changes, {first_change["id"]}
    )
    assert "阳光把窗格的影子拉得很长" in partially_applied
    assert "真适合睡一觉" in partially_applied
    assert "而且你并不困" in partially_applied
    assert "偶尔偷懒一下" not in partially_applied


def test_stale_work_version_is_rejected(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "冲突测试"})
    service.save_brief(
        work["id"],
        {"expected_version": work["version"], "idea": "第一次保存", "mode": "bond_short"},
    )
    with pytest.raises(RevisionConflict) as error:
        service.save_brief(
            work["id"],
            {"expected_version": work["version"], "idea": "过期写入", "mode": "bond_short"},
        )
    assert error.value.details == {"expected_version": 1, "actual_version": 2}


def test_stale_proposal_cannot_overwrite_new_revision(tmp_path):
    service = WritingService(tmp_path)
    work_id, _, first_proposal, work = build_to_proposal(service)
    second = service.generate_scene_candidate(
        work_id,
        work["chapters"][0]["scenes"][0]["id"],
        {"expected_version": work["version"]},
    )
    accepted = service.accept_proposal(
        work_id,
        second["proposal_id"],
        {"expected_version": second["work"]["version"]},
    )
    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work_id,
            first_proposal,
            {"expected_version": accepted["work"]["version"]},
        )
    assert error.value.code == "proposal_superseded"
    with service.repo.connect() as connection:
        proposal = connection.execute(
            "SELECT status,decided_at FROM proposals WHERE id=?", (first_proposal,)
        ).fetchone()
        decision = connection.execute(
            "SELECT decision FROM decisions WHERE target_id=? ORDER BY created_at DESC LIMIT 1",
            (first_proposal,),
        ).fetchone()
    assert proposal["status"] == "superseded"
    assert proposal["decided_at"]
    assert decision["decision"] == "superseded"


def test_tampered_scene_candidate_cannot_be_bypassed_by_partial_accept(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    with service.repo.connect() as connection:
        proposal = connection.execute(
            "SELECT candidate_uri FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
    (tmp_path / proposal["candidate_uri"]).write_text("旁白: 被篡改。\n", encoding="utf-8")

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work_id,
            proposal_id,
            {
                "expected_version": work["version"],
                "text": "旁白: 即使局部采纳也不能绕过完整性检查。\n",
            },
        )

    assert error.value.code == "proposal_integrity_failed"
    assert error.value.details["proposal_id"] == proposal_id
    with service.repo.connect() as connection:
        persisted = connection.execute(
            "SELECT status,decided_at FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        decision = connection.execute(
            "SELECT decision FROM decisions WHERE target_id=? ORDER BY created_at DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        scene = connection.execute(
            "SELECT current_revision_id FROM scenes WHERE id=?", (scene_id,)
        ).fetchone()
    assert persisted["status"] == "rejected"
    assert persisted["decided_at"]
    assert decision["decision"] == "integrity_failed"
    assert scene["current_revision_id"] is None
    restored = WritingService(tmp_path).get_work(work_id)
    restored_proposal = next(
        item for item in restored["proposals"] if item["id"] == proposal_id
    )
    assert restored_proposal["candidate"] is None
    assert restored_proposal["candidate_integrity"]["valid"] is False


@pytest.mark.parametrize(
    "proposal_kind",
    ["brief_blueprint", "chapter_plan", "story_structure", "character_card", "world_entity", "canon_fact"],
)
def test_all_structured_proposal_acceptance_paths_reject_tampered_candidate(
    tmp_path, proposal_kind
):
    service = WritingService(tmp_path)
    work = service.create_work({"title": f"{proposal_kind} 完整性"})
    proposal_id = f"proposal-integrity-{proposal_kind}"
    candidate_uri, candidate_hash = service.repo.atomic_write_text(
        f"artifacts/proposals/{proposal_id}.txt",
        json.dumps({"original": True}, ensure_ascii=False),
    )
    with service.repo.transaction() as connection:
        connection.execute(
            """INSERT INTO proposals
               (id,work_id,kind,scope_type,scope_id,base_revision_id,candidate_uri,
                candidate_hash,diff_json,evidence_json,risk,status,provider_json,created_at,decided_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                proposal_id, work["id"], proposal_kind, "work", work["id"], None,
                candidate_uri, candidate_hash, "[]", "[]", "medium", "pending", "{}",
                "2026-08-15T00:00:00+00:00", None,
            ),
        )
    (tmp_path / candidate_uri).write_text(
        json.dumps({"original": False}, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work["id"], proposal_id, {"expected_version": work["version"]}
        )

    assert error.value.code == "proposal_integrity_failed"
    with service.repo.connect() as connection:
        proposal = connection.execute(
            "SELECT status FROM proposals WHERE id=?", (proposal_id,)
        ).fetchone()
        decision = connection.execute(
            "SELECT decision FROM decisions WHERE target_id=?", (proposal_id,)
        ).fetchone()
    assert proposal["status"] == "rejected"
    assert decision["decision"] == "integrity_failed"


def test_rejecting_scene_proposal_closes_waiting_work_item(tmp_path):
    service = WritingService(tmp_path)
    work_id, _scene_id, proposal_id, work = build_to_proposal(service)
    rejected = service.reject_proposal(
        work_id, proposal_id, {"expected_version": work["version"], "note": "本轮方向不采用"}
    )
    item = next(
        item
        for run in rejected["work"]["runs"]
        for item in run["work_items"]
        if proposal_id in item["output_refs_json"]
    )
    assert item["status"] == "cancelled"
    assert json.loads(item["acceptance_json"])["decision"] == "rejected"
    assert next(run for run in rejected["work"]["runs"] if run["id"] == item["run_id"])["status"] == "running"


def test_scene_rewrite_agent_pins_manuscript_and_stays_proposal_only(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"], "text": "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"})
    prepared = service.save_character_card(work_id, {"expected_version": accepted["work"]["version"], "card_id": "character-aris", "name": "爱丽丝", "source_refs": ["用户确认"], "voice_anchors": ["先确认眼前的情况。"], "trust_status": "confirmed"})
    configured = service.configure_scene_context(work_id, scene_id, {"expected_version": prepared["work"]["version"], "character_card_ids": ["character-aris"], "world_item_ids": [], "reference_file_ids": []})
    rewritten = service.run_scene_rewrite_agent(work_id, scene_id, {"expected_version": configured["work"]["version"], "instruction": "调整本场节奏，保留停顿。"})
    proposal = next(item for item in rewritten["work"]["proposals"] if item["id"] == rewritten["proposal_id"])
    assert proposal["base_revision_id"] == accepted["revision_id"]
    assert proposal["status"] == "pending"
    current_scene = rewritten["work"]["chapters"][0]["scenes"][0]
    assert current_scene["current_revision_id"] == accepted["revision_id"]
    agent = next(item for item in rewritten["work"]["agent_runs"] if item["id"] == rewritten["agent_run_id"])
    assert agent["policy"]["workflow"] == "scene.draft.rewrite"
    assert [call["tool_name"] for call in agent["tool_calls"]] == ["assemble_scene_context", "validate_runtime_character_cards", "read_pinned_scene_revision", "generate_single_proposal"]
    restored = WritingService(tmp_path).get_work(work_id)
    restored_proposal = next(item for item in restored["proposals"] if item["id"] == rewritten["proposal_id"])
    assert restored_proposal["base_revision_id"] == accepted["revision_id"]


def test_accepting_scene_rewrite_preserves_only_exact_unchanged_block_ids(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    manuscript = "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n凯伊: 我去检查线路。\n"
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": manuscript},
    )
    base_artifact = next(
        item
        for item in accepted["work"]["artifacts"]
        if item["kind"] == "scene_script" and item["scope_id"] == scene_id
    )
    base_blocks = base_artifact["current_revision"]["content"]["blocks"]
    base_ids = {service._scene_block_identity(block): block["id"] for block in base_blocks}

    prepared = service.save_character_card(
        work_id,
        {
            "expected_version": accepted["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_refs": ["用户确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "trust_status": "confirmed",
        },
    )
    configured = service.configure_scene_context(
        work_id,
        scene_id,
        {
            "expected_version": prepared["work"]["version"],
            "character_card_ids": ["character-aris"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    rewritten = service.run_scene_rewrite_agent(
        work_id,
        scene_id,
        {"expected_version": configured["work"]["version"], "instruction": "开头增加环境声，并收敛爱丽丝的语气。"},
    )
    edited = "风声敲过窗框。\n旁白: 灯亮了。\n爱丽丝: 先看电源。\n凯伊: 我去检查线路。\n"
    applied = service.accept_proposal(
        work_id,
        rewritten["proposal_id"],
        {"expected_version": rewritten["work"]["version"], "text": edited},
    )
    artifact = next(
        item
        for item in applied["work"]["artifacts"]
        if item["kind"] == "scene_script" and item["scope_id"] == scene_id
    )
    blocks = artifact["current_revision"]["content"]["blocks"]
    current_ids = {service._scene_block_identity(block): block["id"] for block in blocks}

    assert current_ids[("narration", "", "灯亮了。")] == base_ids[("narration", "", "灯亮了。")]
    assert current_ids[("dialogue", "凯伊", "我去检查线路。")] == base_ids[("dialogue", "凯伊", "我去检查线路。")]
    assert current_ids[("dialogue", "爱丽丝", "先看电源。")] != base_ids[("dialogue", "爱丽丝", "先确认电源。")]
    assert len({block["id"] for block in blocks}) == len(blocks)
    assert all(block["id"].startswith("block-") for block in blocks)


def test_scene_block_reconciliation_does_not_misidentify_duplicate_lines(tmp_path):
    service = WritingService(tmp_path)
    base = [
        {"id": "block-first", "type": "action", "text": "相同的脚步声。"},
        {"id": "block-middle", "type": "action", "text": "门被推开。"},
        {"id": "block-last", "type": "action", "text": "相同的脚步声。"},
    ]

    content = service._scene_content_preserving_unchanged_blocks(
        "相同的脚步声。\n新的停顿。\n门被推开。\n相同的脚步声。\n",
        base,
    )

    assert [block["id"] for block in content["blocks"] if block["text"] != "新的停顿。"] == [
        "block-first", "block-middle", "block-last",
    ]
    assert content["blocks"][1]["id"] not in {"block-first", "block-middle", "block-last"}


def test_scene_proposal_applies_selected_block_changes_on_the_server(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"},
    )
    prepared = service.save_character_card(
        work_id,
        {
            "expected_version": accepted["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_refs": ["用户确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "trust_status": "confirmed",
        },
    )
    configured = service.configure_scene_context(
        work_id,
        scene_id,
        {
            "expected_version": prepared["work"]["version"],
            "character_card_ids": ["character-aris"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    rewritten = service.run_scene_rewrite_agent(
        work_id,
        scene_id,
        {"expected_version": configured["work"]["version"], "instruction": "在结尾补一个克制的环境动作。"},
    )
    proposal = next(item for item in rewritten["work"]["proposals"] if item["id"] == rewritten["proposal_id"])
    assert proposal["block_changes"]
    selected_id = proposal["block_changes"][0]["id"]

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work_id,
            proposal["id"],
            {"expected_version": rewritten["work"]["version"], "selected_change_ids": ["change-missing"]},
        )
    assert error.value.code == "proposal_change_unknown"

    applied = service.accept_proposal(
        work_id,
        proposal["id"],
        {"expected_version": rewritten["work"]["version"], "selected_change_ids": [selected_id]},
    )
    artifact = next(
        item
        for item in applied["work"]["artifacts"]
        if item["kind"] == "scene_script" and item["scope_id"] == scene_id
    )
    revision = artifact["current_revision"]
    assert revision["content"]["text"] == proposal["candidate"]
    assert revision["provenance"]["partial_accept"] is True
    assert revision["provenance"]["selected_change_ids"] == [selected_id]


def test_scene_rewrite_agent_pins_a_verified_selected_excerpt(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    manuscript = "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"], "text": manuscript})
    prepared = service.save_character_card(work_id, {"expected_version": accepted["work"]["version"], "card_id": "character-aris", "name": "爱丽丝", "source_refs": ["用户确认"], "voice_anchors": ["先确认眼前的情况。"], "trust_status": "confirmed"})
    configured = service.configure_scene_context(work_id, scene_id, {"expected_version": prepared["work"]["version"], "character_card_ids": ["character-aris"], "world_item_ids": [], "reference_file_ids": []})
    quote = "爱丽丝: 先确认电源。"
    start = manuscript.index(quote)
    rewritten = service.run_scene_rewrite_agent(work_id, scene_id, {
        "expected_version": configured["work"]["version"],
        "instruction": "把选中对白改得更克制。",
        "selection": {"quote": quote, "start": start, "end": start + len(quote)},
    })
    agent = next(item for item in rewritten["work"]["agent_runs"] if item["id"] == rewritten["agent_run_id"])
    assert agent["policy"]["selection_scope"] == "selected_excerpt_only"
    with service.repo.connect() as connection:
        input_uri = connection.execute("SELECT input_snapshot_uri FROM agent_runs WHERE id=?", (rewritten["agent_run_id"],)).fetchone()["input_snapshot_uri"]
    snapshot = json.loads(service.repo.read_text(input_uri))
    assert snapshot["selection"] == {"quote": quote, "start": start, "end": start + len(quote)}


def test_scene_rewrite_agent_rejects_stale_selected_excerpt(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"], "text": "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"})
    prepared = service.save_character_card(work_id, {"expected_version": accepted["work"]["version"], "card_id": "character-aris", "name": "爱丽丝", "source_refs": ["用户确认"], "voice_anchors": ["先确认眼前的情况。"], "trust_status": "confirmed"})
    configured = service.configure_scene_context(work_id, scene_id, {"expected_version": prepared["work"]["version"], "character_card_ids": ["character-aris"], "world_item_ids": [], "reference_file_ids": []})
    with pytest.raises(DomainError) as error:
        service.run_scene_rewrite_agent(work_id, scene_id, {
            "expected_version": configured["work"]["version"],
            "instruction": "修改选中的对白。",
            "selection": {"quote": "爱丽丝: 已经不存在的文本。", "start": 0, "end": 13},
        })
    assert error.value.code == "stale_text_selection"


def _prepare_block_local_scene_rewrite(service: WritingService):
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    manuscript = "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n"
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": manuscript},
    )
    prepared = service.save_character_card(
        work_id,
        {
            "expected_version": accepted["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_refs": ["用户确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "trust_status": "confirmed",
        },
    )
    configured = service.configure_scene_context(
        work_id,
        scene_id,
        {
            "expected_version": prepared["work"]["version"],
            "character_card_ids": ["character-aris"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    scene_artifact = next(
        artifact
        for artifact in configured["work"]["artifacts"]
        if artifact["kind"] == "scene_script" and artifact["scope_id"] == scene_id
    )
    return work_id, scene_id, accepted["revision_id"], scene_artifact["current_revision"]["content"], configured["work"]


def test_scene_rewrite_agent_resolves_block_local_selection_to_absolute_offsets(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, revision_id, content, work = _prepare_block_local_scene_rewrite(service)
    block = next(item for item in content["blocks"] if item.get("speaker") == "爱丽丝")
    quote = "确认电源"
    local_start = block["text"].index(quote)

    rewritten = service.run_scene_rewrite_agent(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "instruction": "把选中的短语改得更克制。",
            "selection": {
                "revision_id": revision_id,
                "block_id": block["id"],
                "local_start": local_start,
                "local_end": local_start + len(quote),
                "quote": quote,
            },
        },
    )

    run = next(item for item in rewritten["work"]["agent_runs"] if item["id"] == rewritten["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["selection"] == {
        "revision_id": revision_id,
        "block_id": block["id"],
        "local_start": local_start,
        "local_end": local_start + len(quote),
        "quote": quote,
        "start": content["text"].index(quote),
        "end": content["text"].index(quote) + len(quote),
    }


def test_scene_rewrite_agent_resolves_narration_block_selection_after_prefix(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, revision_id, content, work = _prepare_block_local_scene_rewrite(service)
    block = next(item for item in content["blocks"] if item["type"] == "narration")
    quote = "灯亮"
    local_start = block["text"].index(quote)

    rewritten = service.run_scene_rewrite_agent(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "instruction": "让选中的旁白更有画面感。",
            "selection": {
                "revision_id": revision_id,
                "block_id": block["id"],
                "local_start": local_start,
                "local_end": local_start + len(quote),
                "quote": quote,
            },
        },
    )

    run = next(item for item in rewritten["work"]["agent_runs"] if item["id"] == rewritten["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["selection"]["start"] == content["text"].index(quote)
    assert snapshot["selection"]["end"] == content["text"].index(quote) + len(quote)


@pytest.mark.parametrize(
    ("selection_patch", "expected_code"),
    [
        ({"block_id": "block-missing"}, "stale_text_selection"),
        ({"local_start": -1}, "invalid_text_selection"),
        ({"local_start": 4, "local_end": 2}, "invalid_text_selection"),
        ({"local_end": 999}, "invalid_text_selection"),
        ({"quote": "不存在"}, "stale_text_selection"),
    ],
)
def test_scene_rewrite_agent_rejects_invalid_block_local_selection(tmp_path, selection_patch, expected_code):
    service = WritingService(tmp_path)
    work_id, scene_id, revision_id, content, work = _prepare_block_local_scene_rewrite(service)
    block = next(item for item in content["blocks"] if item.get("speaker") == "爱丽丝")
    selection = {
        "revision_id": revision_id,
        "block_id": block["id"],
        "local_start": 0,
        "local_end": 2,
        "quote": block["text"][:2],
        **selection_patch,
    }

    with pytest.raises(DomainError) as error:
        service.run_scene_rewrite_agent(
            work_id,
            scene_id,
            {
                "expected_version": work["version"],
                "instruction": "修改选中的正文。",
                "selection": selection,
            },
        )

    assert error.value.code == expected_code


def test_scene_rewrite_agent_rejects_block_selection_from_old_revision(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, revision_id, content, work = _prepare_block_local_scene_rewrite(service)
    block = next(item for item in content["blocks"] if item.get("speaker") == "爱丽丝")
    saved = service.save_scene_manuscript(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "expected_base_revision_id": revision_id,
            "blocks": content["blocks"],
        },
    )

    with pytest.raises(DomainError) as error:
        service.run_scene_rewrite_agent(
            work_id,
            scene_id,
            {
                "expected_version": saved["work"]["version"],
                "instruction": "修改选中的正文。",
                "selection": {
                    "revision_id": revision_id,
                    "block_id": block["id"],
                    "local_start": 0,
                    "local_end": 2,
                    "quote": block["text"][:2],
                },
            },
        )

    assert error.value.code == "stale_text_selection"


def test_second_service_does_not_reclassify_legacy_attempt_without_lease_evidence(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "恢复测试"})
    with service.repo.transaction() as connection:
        run_id = connection.execute(
            "SELECT id FROM production_runs WHERE work_id=?", (work["id"],)
        ).fetchone()["id"]
        connection.execute(
            "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "item-crashed", run_id, "scene.draft.generate", "scene", "scene-x",
                "running", "[]", "[]", "{}", 1, None, "now", "now",
            ),
        )
        connection.execute(
            "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("attempt-crashed", "item-crashed", 1, "fake", "sha256:x", "started", None, None, "now", None),
        )

    WritingService(tmp_path)
    with sqlite3.connect(tmp_path / "writing.db") as connection:
        attempt = connection.execute(
            "SELECT status, error_code FROM job_attempts WHERE id='attempt-crashed'"
        ).fetchone()
        item = connection.execute(
            "SELECT status, error_json FROM work_items WHERE id='item-crashed'"
        ).fetchone()
    assert attempt == ("started", None)
    assert item == ("running", None)


def test_restart_preserves_unleased_scene_agent_until_explicit_cancel_and_retry(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, ready = _prepare_ba_agent_scene(service)
    completed = service.run_scene_agent(
        work_id, scene_id,
        {"expected_version": ready["version"], "instruction": "起草本场"},
    )
    work_item_id = next(
        item["id"] for run in completed["work"]["runs"] for item in run["work_items"]
        if item["acceptance"].get("agent_run_id") == completed["agent_run_id"]
    )
    rejected = service.reject_proposal(
        work_id, completed["proposal_id"],
        {"expected_version": completed["work"]["version"], "note": "模拟进程在结果提交前中断"},
    )
    with service.repo.transaction() as connection:
        run_id = completed["agent_run_id"]
        connection.execute(
            "UPDATE agent_runs SET status='running',proposal_id=NULL,failure_json=NULL,finished_at=NULL WHERE id=?",
            (run_id,),
        )
        connection.execute(
            "UPDATE work_items SET status='running',output_refs_json='[]',acceptance_json=?,error_json=NULL WHERE id=?",
            (json.dumps({"proposal_only": True, "agent_run_id": run_id}), work_item_id),
        )
        connection.execute(
            "UPDATE job_attempts SET status='started',output_ref=NULL,error_code=NULL,finished_at=NULL WHERE work_item_id=?",
            (work_item_id,),
        )

    restarted = WritingService(tmp_path)
    restored = restarted.get_work(work_id)
    old_run = next(item for item in restored["agent_runs"] if item["id"] == completed["agent_run_id"])
    old_item = next(
        item for run in restored["runs"] for item in run["work_items"]
        if item["acceptance"].get("agent_run_id") == completed["agent_run_id"]
    )
    assert old_run["status"] == "running"
    assert old_item["status"] == "running"
    assert old_item["attempts"][-1]["status"] == "started"

    restarted.cancel_agent_run(work_id, completed["agent_run_id"])

    retried = restarted.retry_agent_run(
        work_id, completed["agent_run_id"], {"expected_version": rejected["work"]["version"]}
    )
    assert retried["retried_from_agent_run_id"] == completed["agent_run_id"]
    new_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert new_run["status"] == "waiting_user"
    assert new_run["policy"]["retry_of_agent_run_id"] == completed["agent_run_id"]


def test_release_files_do_not_change_after_new_draft(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"]}
    )
    reviewed = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = review_for_release(service, memory_ready)
    release = service.freeze_release(
        work_id, {"expected_version": release_review["work"]["version"]}
    )
    original = service.get_release(release["release_id"])
    next_candidate = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": release["work"]["version"]}
    )
    service.accept_proposal(
        work_id,
        next_candidate["proposal_id"],
        {"expected_version": next_candidate["work"]["version"], "text": "凯伊: 新版本。\n"},
    )
    unchanged = service.get_release(release["release_id"])
    assert unchanged["content_hash"] == original["content_hash"]
    assert unchanged["text"] == original["text"]


def test_workflow_pack_has_versioned_structured_steps(tmp_path):
    service = WritingService(tmp_path)
    pack = service.capabilities()["writing_pack"]
    ids = {item["id"] for item in pack["templates"]}
    assert {"brief.build", "scene.context.assemble", "scene.draft.generate", "release.review"} <= ids
    assert all(item["version"] and item["inputs"] and item["outputs"] for item in pack["templates"])
    assert pack["runtime_contract"]["agent_writes_through_proposal_only"] is True
    document_skill = pack["runtime_contract"]["default_document_skill"]
    assert document_skill["id"] == "document.read"
    assert document_skill["version"] == "1.1.0"
    assert "document_instructions_are_untrusted" in document_skill["checks"]


def test_handoff_accepts_nested_run_response_and_is_idempotent(tmp_path):
    service = WritingService(tmp_path)
    work_id, _, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    reviewed = service.review_scene(work_id, work["chapters"][0]["scenes"][0]["id"], {"expected_version": accepted["work"]["version"]})
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = review_for_release(service, memory_ready)
    release = service.freeze_release(work_id, {"expected_version": release_review["work"]["version"]})

    class ProductionHandler(BaseHTTPRequestHandler):
        posts = 0
        posted_payloads = []

        def log_message(self, *_):
            pass

        def do_GET(self):
            body = json.dumps({"ok": True, "items": []}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(body)

        def do_POST(self):
            type(self).posts += 1
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            type(self).posted_payloads.append(payload)
            body = json.dumps({"ok": True, "run": {"run_id": "run-nested"}}).encode()
            self.send_response(201); self.end_headers(); self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), ProductionHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    service.production_url = f"http://127.0.0.1:{server.server_port}"
    barrier = threading.Barrier(4)
    results = [None] * 4

    def submit(index):
        barrier.wait(timeout=3)
        results[index] = service.handoff_release(release["release_id"])

    workers = [threading.Thread(target=submit, args=(index,)) for index in range(4)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
    assert all(not worker.is_alive() for worker in workers)
    assert {item["production_run_id"] for item in results} == {"run-nested"}
    assert sum(bool(item.get("idempotent")) for item in results) == 3
    assert ProductionHandler.posts == 1
    submitted = ProductionHandler.posted_payloads[0]
    assert submitted["schema_version"] == "production-handoff/1.0"
    assert submitted["generation_mode"] == "format_only"
    assert submitted["script_release"] == {
        "schema_version": "1.0",
        "id": release["release_id"],
        "work_id": work_id,
        "display_version": "v1",
        "content_hash": release["manifest"]["content_hash"].removeprefix("sha256:"),
        "writing_pack_version": release["manifest"]["writing_pack_version"],
        "ba_writing_source_digest": release["manifest"]["ba_writing_source_digest"],
        "source_set_digest": release["manifest"]["source_set_digest"],
    }
    contracts = Path(__file__).parents[1] / "docs" / "contracts"
    release_schema = json.loads(
        (contracts / "script-release-1.0.schema.json").read_text(encoding="utf-8")
    )
    handoff_schema = json.loads(
        (contracts / "production-handoff-1.0.schema.json").read_text(encoding="utf-8")
    )
    assert release["manifest"]["schema_version"] == release_schema["properties"]["schema_version"]["const"]
    assert set(release_schema["required"]) <= set(release["manifest"])
    assert set(release["manifest"]) <= set(release_schema["properties"])
    assert submitted["schema_version"] == handoff_schema["properties"]["schema_version"]["const"]
    assert set(handoff_schema["required"]) <= set(submitted)
    assert set(submitted) <= set(handoff_schema["properties"])


def test_release_read_and_handoff_reject_tampered_content(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]},
    )
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = review_for_release(service, memory_ready)
    release = service.freeze_release(
        work_id, {"expected_version": release_review["work"]["version"]},
    )
    with service.repo.connect() as connection:
        row = connection.execute(
            "SELECT content_uri,manifest_uri FROM script_releases WHERE id=?", (release["release_id"],)
        ).fetchone()
    content_path = service.repo.data_dir / row["content_uri"]
    original_text = content_path.read_text(encoding="utf-8")
    content_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(DomainError) as read_error:
        service.get_release(release["release_id"])
    assert read_error.value.code == "release_integrity_failed"

    with pytest.raises(DomainError) as handoff_error:
        service.handoff_release(release["release_id"])
    assert handoff_error.value.code == "release_integrity_failed"

    content_path.write_text(original_text, encoding="utf-8")
    manifest_path = service.repo.data_dir / row["manifest_uri"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_id"] = "release-tampered"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DomainError) as manifest_error:
        service.get_release(release["release_id"])
    assert manifest_error.value.code == "release_integrity_failed"


def test_ba_writing_source_change_invalidates_release_review(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]},
    )
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = service.review_release(
        work_id, {"expected_version": memory_ready["version"]},
    )
    original = service.ba_skill.descriptor()
    monkeypatch.setattr(
        service.ba_skill,
        "descriptor",
        lambda: {**original, "source_digest": "sha256:" + "0" * 64},
    )

    with pytest.raises(DomainError) as error:
        service.freeze_release(
            work_id, {"expected_version": release_review["work"]["version"]},
        )
    assert error.value.code == "release_blocked"
    assert error.value.details["reason"] == "release_review_not_current"


def test_references_are_durable_and_make_runtime_cards_provider_ready(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    canon = service.save_work_canon(
        work_id,
        {
            "expected_version": work["version"],
            "facts": [{"text": "旧机器没有接通外部电源", "source": "用户确认", "confidence_status": "confirmed"}],
        },
    )
    alice = service.save_character_card(
        work_id,
        {
            "expected_version": canon["work"]["version"],
            "name": "爱丽丝",
            "voice_anchors": ["先确认眼前的情况。"],
            "ooc_constraints": ["不替其他人猜测动机"],
            "source_refs": ["用户确认"],
        },
    )
    kay = service.save_character_card(
        work_id,
        {
            "expected_version": alice["work"]["version"],
            "name": "凯伊",
            "voice_anchors": ["让我先看看日志。"],
            "ooc_constraints": ["不无端泄露未知事实"],
            "source_refs": ["用户确认"],
        },
    )
    stored = service.create_reference_file(
        work_id,
        {
            "expected_version": kay["work"]["version"],
            "title": "活动室观察笔记",
            "source_label": "用户导入",
            "content": "提示灯在零点后闪烁。",
        },
    )
    context = service.assemble_context(work_id, scene_id)
    assert context["readiness"]["real_ba_writing"] == "ready_for_provider"
    assert {card["name"] for card in context["runtime_character_cards"]} == {"爱丽丝", "凯伊"}
    assert len(context["source_revision_ids"]) >= 3
    assert context["reference_files"][0]["id"] == stored["reference_file_id"]
    assert context["reference_files"][0]["content"].startswith("提示灯")
    assert context["reference_file_refs"][0].startswith("reference:")

    restarted = WritingService(tmp_path).get_work(work_id)
    assert restarted["artifacts"]
    assert len(restarted["reference_files"]) == 1
    assert restarted["reference_files"][0]["content_hash"].startswith("sha256:")
    assert stored["reference_file_id"] == restarted["reference_files"][0]["id"]


def test_creative_bible_keeps_world_and_character_sources_across_restart(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    original = service.save_character_card(
        work_id,
        {
            "expected_version": work["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "canonical_name": "天童爱丽丝",
            "source_type": "official_reference",
            "voice_anchors": ["把眼前的异常当作任务确认。"],
            "relationships": [{"target": "凯伊", "kind": "队友", "summary": "共同调查异常。"}],
            "source_refs": ["官方剧情索引"],
        },
    )
    custom = service.save_character_card(
        work_id,
        {
            "expected_version": original["work"]["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "source_type": "custom",
            "voice_anchors": ["先确认日志。"],
            "source_refs": ["用户确认"],
        },
    )
    first_bible = service.save_world_bible(
        work_id,
        {
            "expected_version": custom["work"]["version"],
            "title": "本作世界观",
            "source_type": "mixed",
            "rules": [{"text": "旧游戏机只在零点后接收匿名指令。", "category": "技术", "source": "用户确认", "confidence_status": "confirmed"}],
            "timeline": [{"text": "异常提示灯第一次亮起。", "category": "当前剧情", "source": "第一章设定", "confidence_status": "confirmed"}],
        },
    )
    updated_bible = service.save_world_bible(
        work_id,
        {
            "expected_version": first_bible["work"]["version"],
            "title": "本作世界观",
            "source_type": "mixed",
            "rules": [{"text": "旧游戏机只在零点后接收匿名指令。", "category": "技术", "source": "用户确认", "confidence_status": "confirmed"}],
            "timeline": [
                {"text": "异常提示灯第一次亮起。", "category": "当前剧情", "source": "第一章设定", "confidence_status": "confirmed"},
                {"text": "匿名发件人身份本卷不公开。", "category": "伏笔", "source": "用户确认", "confidence_status": "confirmed"},
            ],
        },
    )
    restarted = WritingService(tmp_path)
    loaded = restarted.get_work(work_id)
    cards = {
        artifact["scope_id"]: artifact["current_revision"]["content"]
        for artifact in loaded["artifacts"]
        if artifact["kind"] == "character_card"
    }
    bible = next(artifact["current_revision"]["content"] for artifact in loaded["artifacts"] if artifact["kind"] == "world_bible")
    context = restarted.assemble_context(work_id, scene_id)
    assert cards["character-aris"]["source_type"] == "official_reference"
    assert cards["character-aris"]["relationships"][0]["target"] == "凯伊"
    assert cards["character-kei"]["source_type"] == "custom"
    assert bible["source_type"] == "mixed"
    assert len(bible["timeline"]) == 2
    assert updated_bible["revision_id"] == next(artifact["current_revision_id"] for artifact in loaded["artifacts"] if artifact["kind"] == "world_bible")
    assert context["world_bible"]["rules"][0]["text"].startswith("旧游戏机")


def test_character_card_history_and_archive_are_versioned_and_restart_safe(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物资料库验证"})
    work_id = work["id"]
    created = service.save_character_card(
        work_id,
        {
            "expected_version": work["version"],
            "card_id": "character-original",
            "name": "原创角色",
            "source_type": "custom",
            "voice_anchors": ["先确认现场。"],
            "source_refs": ["用户确认"],
        },
    )
    revised = service.save_character_card(
        work_id,
        {
            "expected_version": created["work"]["version"],
            "card_id": "character-original",
            "name": "原创角色",
            "source_type": "custom",
            "voice_anchors": ["先确认现场，再报告判断。"],
            "source_refs": ["用户确认"],
        },
    )
    archived = service.archive_character_card(
        work_id,
        "character-original",
        {"expected_version": revised["work"]["version"]},
    )
    restored = service.restore_character_card(
        work_id,
        "character-original",
        {"expected_version": archived["work"]["version"]},
    )
    loaded = WritingService(tmp_path).get_work(work_id)
    card = next(item for item in loaded["artifacts"] if item["kind"] == "character_card")
    assert card["scope_id"] == "character-original"
    assert [revision["ordinal"] for revision in card["revisions"]] == [4, 3, 2, 1]
    assert card["current_revision"]["content"]["status"] == "active"
    assert card["current_revision"]["parent_revision_id"] == archived["revision_id"]
    assert restored["revision_id"] == card["current_revision_id"]


def test_world_cards_keep_stable_identity_history_and_archive_out_of_context(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    created = service.save_world_bible(
        work_id,
        {
            "expected_version": work["version"],
            "title": "本作世界观",
            "source_type": "mixed",
            "entities": [{
                "id": "world-card-schaale",
                "name": "夏莱临时指挥室",
                "kind": "place",
                "summary": "本作中用于汇总异常记录的临时据点。",
                "aliases": ["临时指挥室"],
                "source": "official-corpus:scenario_7:42; 用户确认",
                "source_type": "mixed",
                "confidence_status": "confirmed",
                "participants": ["爱丽丝"],
            }],
        },
    )
    revised = service.save_world_bible(
        work_id,
        {
            "expected_version": created["work"]["version"],
            "title": "本作世界观",
            "source_type": "mixed",
            "entities": [{
                "id": "world-card-schaale",
                "name": "夏莱临时指挥室",
                "kind": "place",
                "summary": "本作中汇总异常记录并安排调查的临时据点。",
                "aliases": ["临时指挥室"],
                "source": "official-corpus:scenario_7:42; 用户确认",
                "source_type": "mixed",
                "confidence_status": "confirmed",
                "participants": ["爱丽丝", "凯伊"],
            }],
        },
    )
    archived = service.save_world_bible(
        work_id,
        {
            "expected_version": revised["work"]["version"],
            "title": "本作世界观",
            "source_type": "mixed",
            "entities": [{
                "id": "world-card-schaale",
                "name": "夏莱临时指挥室",
                "kind": "place",
                "summary": "本作中汇总异常记录并安排调查的临时据点。",
                "aliases": ["临时指挥室"],
                "source": "official-corpus:scenario_7:42; 用户确认",
                "source_type": "mixed",
                "confidence_status": "confirmed",
                "participants": ["爱丽丝", "凯伊"],
                "status": "archived",
            }],
        },
    )
    restarted = WritingService(tmp_path)
    loaded = restarted.get_work(work_id)
    artifact = next(item for item in loaded["artifacts"] if item["kind"] == "world_bible")
    entity = artifact["current_revision"]["content"]["entities"][0]
    context = restarted.assemble_context(work_id, scene_id)
    assert entity["id"] == "world-card-schaale"
    assert entity["status"] == "archived"
    assert [revision["ordinal"] for revision in artifact["revisions"]] == [3, 2, 1]
    assert archived["revision_id"] == artifact["current_revision_id"]
    assert context["world_bible"]["entities"] == []


def test_official_reference_search_and_import_is_work_owned_and_restart_safe(tmp_path):
    corpus = tmp_path / "official-corpus"
    corpus.mkdir()
    record = {
        "record_uid": "scenario_7:42",
        "source_file": "ScenarioScriptExcel_7.json",
        "source_row_index": 42,
        "primary_story_membership": {
            "category": "main_story",
            "character_name": "爱丽丝",
            "title": "前往夏莱",
        },
        "speakers": ["爱丽丝", "老师"],
        "text": {"zh_cn": "爱丽丝: 先确认夏莱的门锁。", "localization_status": "official_zh"},
    }
    (corpus / "scenario_7.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    service = WritingService(tmp_path / "data", official_corpus_dir=corpus)
    work = service.create_work({"title": "原作资料导入"})

    search = service.search_official_references("夏莱")
    assert search["catalog"]["available"] is True
    assert search["items"][0]["record_uid"] == "scenario_7:42"
    assert search["items"][0]["zh_cn"].startswith("爱丽丝")

    imported = service.import_official_reference(
        work["id"],
        {"expected_version": work["version"], "record_uid": "scenario_7:42"},
    )
    loaded = WritingService(tmp_path / "data", official_corpus_dir=corpus).get_work(work["id"])
    reference = loaded["reference_files"][0]
    assert reference["id"] == imported["reference_file_id"]
    assert reference["source_label"] == "official-corpus:scenario_7:42"
    assert reference["trust_status"] == "official_reference"
    assert (tmp_path / "data" / "references" / f"{reference['id']}.md").read_text(encoding="utf-8").find("不是自动确认") >= 0
    assert (corpus / "scenario_7.jsonl").read_text(encoding="utf-8") == json.dumps(record, ensure_ascii=False) + "\n"


def test_official_catalog_permission_error_is_reported_as_unavailable(tmp_path, monkeypatch):
    """Optional evidence must not make the writing service unavailable."""
    corpus = tmp_path / "official-corpus"
    corpus.mkdir()
    service = WritingService(tmp_path / "data", official_corpus_dir=corpus)

    def denied(_path):
        raise PermissionError("corpus access changed")

    monkeypatch.setattr(type(corpus), "is_dir", denied)

    capabilities = service.capabilities()
    assert capabilities["official_references"]["available"] is False


def test_blocking_scene_review_prevents_release(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": "旁白: 作者已经安排好了这一幕。\n"},
    )
    review = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]}
    )
    assert any(item["kind"] == "meta_boundary" and item["severity"] == "blocking" for item in review["findings"])
    with pytest.raises(DomainError) as error:
        service.freeze_release(work_id, {"expected_version": review["work"]["version"]})
    assert error.value.code == "release_blocked"
    assert error.value.details["finding_ids"]


def test_release_review_must_cover_current_scene_revisions(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    reviewed = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = service.review_release(work_id, {"expected_version": memory_ready["version"]})
    assert release_review["status"] == "passed"
    next_candidate = service.generate_scene_candidate(work_id, scene_id, {"expected_version": release_review["work"]["version"]})
    accepted_next = service.accept_proposal(work_id, next_candidate["proposal_id"], {"expected_version": next_candidate["work"]["version"]})
    with pytest.raises(DomainError) as error:
        service.freeze_release(work_id, {"expected_version": accepted_next["work"]["version"]})
    assert error.value.code == "release_blocked"
    assert error.value.details["reason"] == "release_review_not_current"


def test_accepting_new_scene_candidate_requires_fresh_scene_review(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    first = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"]},
    )
    scene_review = service.review_scene(
        work_id, scene_id, {"expected_version": first["work"]["version"]},
    )
    memory_ready = skip_memory_for_current_scenes(service, scene_review["work"])
    release_review = review_for_release(service, memory_ready)
    assert release_review["status"] == "passed"

    rewrite = service.generate_scene_candidate(
        work_id, scene_id, {"expected_version": release_review["work"]["version"]},
    )
    second = service.accept_proposal(
        work_id, rewrite["proposal_id"], {"expected_version": rewrite["work"]["version"]},
    )
    scene = next(
        scene
        for chapter in second["work"]["chapters"]
        for scene in chapter["scenes"]
        if scene["id"] == scene_id
    )

    assert scene["current_revision_id"] == second["revision_id"]
    assert second["revision_id"] != first["revision_id"]
    old_scene_gates = [
        gate for gate in second["work"]["gates"]
        if gate["kind"] == "scene.review"
        and gate["scope_id"] == scene_id
        and gate["snapshot"].get("revision_id") == first["revision_id"]
    ]
    current_scene_gates = [
        gate for gate in second["work"]["gates"]
        if gate["kind"] == "scene.review"
        and gate["scope_id"] == scene_id
        and gate["snapshot"].get("revision_id") == second["revision_id"]
    ]
    assert old_scene_gates
    assert current_scene_gates == []


def test_freeze_requires_current_continuity_gate_even_after_release_review(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]},
    )
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = service.review_release(
        work_id, {"expected_version": memory_ready["version"]},
    )
    assert release_review["status"] == "passed"

    with pytest.raises(DomainError) as error:
        service.freeze_release(
            work_id, {"expected_version": release_review["work"]["version"]},
        )
    assert error.value.code == "release_blocked"
    assert error.value.details["reason"] == "continuity_review_missing"


def test_world_bible_change_invalidates_release_review_gate(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"]}
    )
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]}
    )
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = service.review_release(
        work_id, {"expected_version": memory_ready["version"]}
    )
    assert release_review["status"] == "passed"

    changed = service.save_world_bible(
        work_id,
        {
            "expected_version": release_review["work"]["version"],
            "entities": [
                {
                    "id": "world-greenhouse",
                    "kind": "place",
                    "name": "温室",
                    "summary": "夜间门禁规则已经更新。",
                    "source": "用户确认",
                    "scope": "work",
                    "status": "active",
                    "confidence_status": "confirmed",
                    "source_type": "custom",
                    "source_refs": ["用户确认"],
                }
            ],
            "rules": [],
            "timeline": [],
        },
    )

    with pytest.raises(DomainError) as error:
        service.freeze_release(
            work_id, {"expected_version": changed["work"]["version"]}
        )
    assert error.value.code == "release_blocked"
    assert error.value.details["reason"] == "release_review_not_current"


def test_release_review_requires_memory_maintenance_or_explicit_skip(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"]}
    )
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]}
    )
    blocked = service.review_release(
        work_id, {"expected_version": reviewed["work"]["version"]}
    )
    assert blocked["status"] == "blocked"
    assert blocked["snapshot"]["incomplete_memory_scene_ids"] == [scene_id]

    skipped = service.skip_scene_memory_maintenance(
        work_id,
        scene_id,
        {
            "expected_version": blocked["work"]["version"],
            "note": "本场只是状态复述，不新增长期事实。",
        },
    )
    assert skipped["status"] == "skipped"
    passed = service.review_release(
        work_id, {"expected_version": skipped["work"]["version"]}
    )
    assert passed["status"] == "passed"
    assert passed["snapshot"]["incomplete_memory_scene_ids"] == []
    capabilities = service.capabilities()["capabilities"]
    assert "long_term_memory" in capabilities
    assert "memory_bundle_proposal" in capabilities
    assert "memory_context_retrieval" in capabilities
    assert "chapter_memory_sweep_agent" in capabilities


def test_release_review_accepts_clean_scene_review_without_findings(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": "旁白: 灯光在桌面上安静下来。\n"},
    )
    scene_review = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    assert scene_review["findings"] == []
    assert scene_review["metrics"]["narration_block_count"] == 1
    assert scene_review["metrics"]["narration_ratio"] == 1.0
    memory_ready = skip_memory_for_current_scenes(service, scene_review["work"])
    release_review = service.review_release(work_id, {"expected_version": memory_ready["version"]})
    assert release_review["status"] == "passed"


def test_scene_review_persists_narration_and_pacing_findings(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    manuscript = "\n".join(
        [
            "旁白: 温室里没有人先开口。",
            "旁白: 门禁灯保持着异常的颜色。",
            "旁白: 脚步声停在门外。",
            "旁白: 记录页仍然没有刷新。",
            "旁白: 所有人都在等下一条证据。",
            "旁白: " + "灯光缓慢移动。" * 20,
        ]
    ) + "\n"
    accepted = service.accept_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "text": manuscript},
    )
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]}
    )

    by_kind = {finding["kind"]: finding for finding in reviewed["findings"]}
    assert by_kind["narration_ratio"]["severity"] == "warning"
    assert by_kind["narration_ratio"]["evidence"]["narration_ratio"] == 1.0
    assert by_kind["pacing_long_block"]["severity"] == "warning"
    assert by_kind["pacing_long_block"]["evidence"]["long_blocks"][0]["line"] == 6
    assert reviewed["metrics"]["block_count"] == 6
    gate = next(item for item in reviewed["work"]["gates"] if item["id"] == reviewed["gate_id"])
    assert gate["snapshot"]["metrics"] == reviewed["metrics"]


def test_empty_work_cannot_pass_release_review(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "空作品审查"})
    review = service.review_release(work["id"], {"expected_version": work["version"]})
    assert review["status"] == "blocked"
    assert review["snapshot"]["no_scenes"] is True


def test_resolving_finding_requires_a_reason_and_is_audited(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"], "text": "旁白: 作者走进活动室。\n"}
    )
    review = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    finding_id = review["findings"][0]["id"]
    with pytest.raises(DomainError) as error:
        service.resolve_review_finding(work_id, finding_id, {"expected_version": review["work"]["version"], "note": ""})
    assert error.value.code == "validation_error"
    resolved = service.resolve_review_finding(
        work_id, finding_id, {"expected_version": review["work"]["version"], "note": "已在下一稿中安排修改"}
    )
    assert resolved["work"]["version"] == review["work"]["version"] + 1
    with service.repo.connect() as connection:
        finding = connection.execute("SELECT status FROM review_findings WHERE id=?", (finding_id,)).fetchone()
        decision = connection.execute("SELECT decision,note FROM decisions WHERE target_id=?", (finding_id,)).fetchone()
    assert finding["status"] == "resolved"
    assert tuple(decision) == ("resolved", "已在下一稿中安排修改")


def test_release_scene_order_follows_chapter_order_not_identifier(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "顺序测试"})
    result = service.save_brief(work["id"], {"expected_version": work["version"], "idea": "测试", "mode": "bond_short"})
    result = service.generate_blueprint(work["id"], {"expected_version": result["work"]["version"]})
    first = service.create_chapter(work["id"], {"expected_version": result["work"]["version"], "title": "第一章"})
    second = service.create_chapter(work["id"], {"expected_version": first["work"]["version"], "title": "第二章"})
    one = service.create_scene(work["id"], first["chapter_id"], {"expected_version": second["work"]["version"], "title": "先发生"})
    two = service.create_scene(work["id"], second["chapter_id"], {"expected_version": one["work"]["version"], "title": "后发生"})
    for scene_id, text, version in [(one["scene_id"], "旁白: 一。\n", two["work"]["version"]), (two["scene_id"], "旁白: 二。\n", None)]:
        current = service.get_work(work["id"])
        with service.repo.transaction() as connection:
            artifact = service._artifact(connection, work["id"], "scene_script", "scene", scene_id)
            revision_id = service._add_revision(connection, artifact, {"text": text}, "user", {"test": True})
            connection.execute("UPDATE scenes SET current_revision_id=?, status='review' WHERE id=?", (revision_id, scene_id))
            service._bump_work(connection, work["id"], current["version"])
        reviewed = service.review_scene(work["id"], scene_id, {"expected_version": service.get_work(work["id"])["version"]})
    memory_ready = skip_memory_for_current_scenes(service, reviewed["work"])
    release_review = review_for_release(service, memory_ready)
    release = service.freeze_release(work["id"], {"expected_version": release_review["work"]["version"]})
    assert [scene["title"] for scene in release["manifest"]["scenes"]] == ["先发生", "后发生"]


def test_structure_reorder_keeps_scene_identity_manuscript_and_requires_current_release_review(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "章节调整"})
    brief = service.save_brief(
        work["id"], {"expected_version": work["version"], "idea": "调整故事结构", "mode": "bond_short"}
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    first = service.create_chapter(work["id"], {"expected_version": blueprint["work"]["version"], "title": "第一章"})
    second = service.create_chapter(work["id"], {"expected_version": first["work"]["version"], "title": "第二章"})
    one = service.create_scene(work["id"], first["chapter_id"], {"expected_version": second["work"]["version"], "title": "先发生", "goal": "建立线索"})
    two = service.create_scene(work["id"], second["chapter_id"], {"expected_version": one["work"]["version"], "title": "后发生", "goal": "确认线索"})
    first_candidate = service.generate_scene_candidate(work["id"], one["scene_id"], {"expected_version": two["work"]["version"]})
    first_accepted = service.accept_proposal(work["id"], first_candidate["proposal_id"], {"expected_version": first_candidate["work"]["version"], "text": "旁白: 先发生。\n"})
    second_candidate = service.generate_scene_candidate(work["id"], two["scene_id"], {"expected_version": first_accepted["work"]["version"]})
    second_accepted = service.accept_proposal(work["id"], second_candidate["proposal_id"], {"expected_version": second_candidate["work"]["version"], "text": "旁白: 后发生。\n"})
    reviewed_one = service.review_scene(work["id"], one["scene_id"], {"expected_version": second_accepted["work"]["version"]})
    reviewed_two = service.review_scene(work["id"], two["scene_id"], {"expected_version": reviewed_one["work"]["version"]})
    memory_ready = skip_memory_for_current_scenes(service, reviewed_two["work"])
    release_review = service.review_release(work["id"], {"expected_version": memory_ready["version"]})

    reordered = service.reorder_structure(
        work["id"],
        {
            "expected_version": release_review["work"]["version"],
            "chapter_ids": [second["chapter_id"], first["chapter_id"]],
            "scene_placements": [
                {"scene_id": two["scene_id"], "chapter_id": second["chapter_id"]},
                {"scene_id": one["scene_id"], "chapter_id": first["chapter_id"]},
            ],
        },
    )
    assert reordered["changed"] is True
    restored = WritingService(tmp_path).get_work(work["id"])
    assert [chapter["id"] for chapter in restored["chapters"]] == [second["chapter_id"], first["chapter_id"]]
    ordered_scenes = [scene for chapter in restored["chapters"] for scene in chapter["scenes"]]
    assert [scene["id"] for scene in ordered_scenes] == [two["scene_id"], one["scene_id"]]
    assert [scene["current_revision_id"] for scene in ordered_scenes] == [second_accepted["revision_id"], first_accepted["revision_id"]]

    with pytest.raises(DomainError) as error:
        service.freeze_release(work["id"], {"expected_version": reordered["work"]["version"]})
    assert error.value.code == "release_blocked"
    assert error.value.details["reason"] == "release_review_not_current"


def test_structure_reorder_rejects_missing_and_external_ids(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "结构校验"})
    brief = service.save_brief(
        work["id"],
        {"expected_version": work["version"], "idea": "整理一个小事件", "mode": "bond_short"},
    )
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    chapter = service.create_chapter(work["id"], {"expected_version": blueprint["work"]["version"], "title": "第一章"})
    scene = service.create_scene(work["id"], chapter["chapter_id"], {"expected_version": chapter["work"]["version"], "title": "场景", "goal": "有变化"})
    with pytest.raises(DomainError) as missing:
        service.reorder_structure(work["id"], {"expected_version": scene["work"]["version"], "chapter_ids": [], "scene_placements": []})
    assert missing.value.code == "invalid_structure_order"
    with pytest.raises(DomainError) as external:
        service.reorder_structure(
            work["id"],
            {
                "expected_version": scene["work"]["version"],
                "chapter_ids": [chapter["chapter_id"]],
                "scene_placements": [{"scene_id": scene["scene_id"], "chapter_id": "chapter-outside"}],
            },
        )
    assert external.value.code == "invalid_structure_order"


def test_multi_volume_binder_order_and_membership_survive_restart(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "多卷 Binder"})
    with pytest.raises(DomainError) as blocked:
        service.create_volume(
            work["id"],
            {"expected_version": work["version"], "title": "过早建立的卷"},
        )
    assert blocked.value.code == "blueprint_required"

    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "从第一卷的异常延伸到第二卷",
            "mode": "bond_short",
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    first_volume_id = blueprint["work"]["volumes"][0]["id"]
    first = service.create_chapter(
        work["id"],
        {
            "expected_version": blueprint["work"]["version"],
            "volume_id": first_volume_id,
            "title": "第一卷第一章",
        },
    )
    second_volume = service.create_volume(
        work["id"],
        {"expected_version": first["work"]["version"], "title": "第二卷"},
    )
    second = service.create_chapter(
        work["id"],
        {
            "expected_version": second_volume["work"]["version"],
            "volume_id": second_volume["volume_id"],
            "title": "第二卷第一章",
        },
    )

    restored = WritingService(tmp_path).get_work(work["id"])
    assert [volume["title"] for volume in restored["volumes"]] == ["第一卷", "第二卷"]
    assert [[chapter["title"] for chapter in volume["chapters"]] for volume in restored["volumes"]] == [
        ["第一卷第一章"],
        ["第二卷第一章"],
    ]
    assert [chapter["id"] for chapter in restored["chapters"]] == [
        first["chapter_id"],
        second["chapter_id"],
    ]


def test_intent_proposal_confirmation_and_scene_mode_are_durable(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "混合作品", "world_seed": "ba_starter"})
    card = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_type": "official_reference",
            "trust_status": "confirmed",
            "source_refs": ["用户核对"],
        },
    )
    intent = service.save_brief(
        work["id"],
        {
            "expected_version": card["work"]["version"],
            "idea": "爱丽丝与凯伊先查线索，随后进入行动。",
            "intent_only": True,
        },
    )
    assert next(item for item in intent["work"]["artifacts"] if item["kind"] == "brief")["current_revision"]["content"]["status"] == "analysis_pending"
    proposed = service.generate_blueprint(work["id"], {"expected_version": intent["work"]["version"]})
    proposal = next(item for item in proposed["work"]["artifacts"] if item["kind"] == "story_blueprint")["current_revision"]["content"]
    assert proposal["status"] == "proposed"
    with pytest.raises(DomainError) as blocked:
        service.create_chapter(work["id"], {"expected_version": proposed["work"]["version"], "title": "第一章"})
    assert blocked.value.code == "blueprint_unconfirmed"

    confirmed = service.confirm_blueprint(
        work["id"],
        {
            "expected_version": proposed["work"]["version"],
            "mode": "bond_short",
            "character_card_ids": ["character-aris"],
            "sensei_presence": "auto",
        },
    )
    chapter = service.create_chapter(work["id"], {"expected_version": confirmed["work"]["version"], "title": "第一章"})
    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "前半场",
            "goal": "先确认线索",
            "writing_mode": "long_comedy",
        },
    )
    context = service.assemble_context(work["id"], scene["scene_id"])
    assert context["scene_contract"]["writing_mode"] == "long_comedy"
    assert context["rules"]["mode_key"] == "long_comedy"
    assert context["rules"]["mode"] == MODE_SOURCES["long_comedy"]

    restarted = WritingService(tmp_path)
    restored = restarted.get_work(work["id"])
    assert restored["chapters"][0]["scenes"][0]["contract"]["writing_mode"] == "long_comedy"
    with pytest.raises(DomainError) as invalid:
        restarted.update_scene_contract(
            work["id"],
            scene["scene_id"],
            {
                "expected_version": restored["version"],
                "title": "前半场",
                "goal": "先确认线索",
                "stop_boundary": "线索确认后停止",
                "writing_mode": "whole_work_everything",
            },
        )
    assert invalid.value.code == "validation_error"


def test_ba_agent_requires_runtime_character_cards(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    with service.repo.connect() as connection:
        existing_runs = connection.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
    with pytest.raises(DomainError) as error:
        service.run_scene_agent(
            work_id, scene_id, {"expected_version": work["version"], "instruction": "起草本场"}
        )
    assert error.value.code == "agent_blocked"
    with service.repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == existing_runs


def test_compat_scene_candidate_failure_has_fixed_snapshot_and_can_retry(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    rejected = service.reject_proposal(
        work_id,
        proposal_id,
        {"expected_version": work["version"], "note": "验证旧候选重试"},
    )
    original_generate = service.provider.generate_scene

    def fail_once(_context):
        raise RuntimeError("temporary provider outage")

    service.provider.generate_scene = fail_once
    with pytest.raises(DomainError) as error:
        service.generate_scene_candidate(
            work_id, scene_id, {"expected_version": rejected["work"]["version"]}
        )
    assert error.value.code == "writing_provider_failed"
    failed = service.get_work(work_id)
    failed_run = next(
        item for item in reversed(failed["agent_runs"])
        if item["policy"].get("workflow") == "scene.candidate.generate"
        and item["status"] == "failed"
    )
    assert failed_run["input_digest"].startswith("sha256:")
    failed_item = next(
        item for run in failed["runs"] for item in run["work_items"]
        if item["acceptance"].get("agent_run_id") == failed_run["id"]
    )
    assert failed_item["error"]["retryable"] is True
    assert failed_item["attempts"][0]["status"] == "failed"

    service.provider.generate_scene = original_generate
    retried = service.retry_agent_run(
        work_id,
        failed_run["id"],
        {"expected_version": failed["version"]},
    )
    assert retried["retried_from_agent_run_id"] == failed_run["id"]
    assert retried["proposal_id"]
    new_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert new_run["status"] == "waiting_user"
    assert new_run["policy"]["retry_of_agent_run_id"] == failed_run["id"]


def test_ba_agent_creates_audited_single_proposal(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, initial_proposal, work = build_to_proposal(service)
    rejected = service.reject_proposal(work_id, initial_proposal, {"expected_version": work["version"], "note": "改由 BA Agent 起草"})
    alice = service.save_character_card(
        work_id,
            {"expected_version": rejected["work"]["version"], "name": "爱丽丝", "voice_anchors": ["先确认。"], "source_refs": ["测试来源"]},
    )
    kay = service.save_character_card(
        work_id,
        {"expected_version": alice["work"]["version"], "name": "凯伊", "voice_anchors": ["我先看日志。"], "source_refs": ["测试来源"]},
    )
    result = service.run_scene_agent(
        work_id, scene_id, {"expected_version": kay["work"]["version"], "instruction": "让两人先处理眼前的提示灯。"}
    )
    assert result["simulation"] is True
    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"])
    assert run["status"] == "waiting_user"
    assert run["proposal_id"] == result["proposal_id"]
    assert run["policy"]["write_policy"] == "one_candidate_zero_edit_proposal_only"
    assert [call["tool_name"] for call in run["tool_calls"]] == ["assemble_scene_context", "validate_runtime_character_cards", "generate_single_proposal"]
    with pytest.raises(DomainError) as error:
        service.run_scene_agent(
            work_id, scene_id, {"expected_version": result["work"]["version"], "instruction": "再写一份"}
        )
    assert error.value.code == "agent_waiting_user"


def _prepare_ba_agent_scene(service: WritingService):
    work_id, scene_id, initial_proposal, work = build_to_proposal(service)
    rejected = service.reject_proposal(
        work_id, initial_proposal,
        {"expected_version": work["version"], "note": "改由 BA Agent 起草"},
    )
    alice = service.save_character_card(
        work_id,
        {
            "expected_version": rejected["work"]["version"],
            "name": "爱丽丝",
            "voice_anchors": ["先确认。"],
            "source_refs": ["测试来源"],
        },
    )
    kay = service.save_character_card(
        work_id,
        {
            "expected_version": alice["work"]["version"],
            "name": "凯伊",
            "voice_anchors": ["我先看日志。"],
            "source_refs": ["测试来源"],
        },
    )
    return work_id, scene_id, kay["work"]


def test_ba_agent_provider_failure_persists_run_attempt_and_work_item(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, ready = _prepare_ba_agent_scene(service)

    def fail_generate(_context):
        raise RuntimeError("provider offline")

    service.provider.generate_scene = fail_generate
    with pytest.raises(DomainError) as failed:
        service.run_scene_agent(
            work_id, scene_id,
            {"expected_version": ready["version"], "instruction": "起草本场"},
        )
    assert failed.value.code == "agent_failed"
    assert failed.value.details["agent_run_id"]

    restored = WritingService(tmp_path).get_work(work_id)
    run = next(
        item for item in restored["agent_runs"]
        if item["scope_id"] == scene_id and item["instruction"] == "起草本场"
    )
    assert run["status"] == "failed"
    assert run["failure"]["code"] == "writing_provider_failed"
    assert run["failure"]["retryable"] is True
    with service.repo.connect() as connection:
        item = connection.execute(
            "SELECT * FROM work_items WHERE scope_id=? AND type='agent.scene.draft.generate' ORDER BY created_at DESC LIMIT 1",
            (scene_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT * FROM job_attempts WHERE work_item_id=? ORDER BY ordinal DESC LIMIT 1",
            (item["id"],),
        ).fetchone()
    assert item["status"] == "failed"
    assert attempt["status"] == "failed"
    assert attempt["error_code"] == "writing_provider_failed"


@pytest.mark.parametrize(
    ("workflow", "failure_kind", "provider_status"),
    [
        ("scene.draft.generate", "provider_timeout", 504),
        ("scene.draft.generate", "provider_rate_limited", 429),
        ("scene.draft.rewrite", "provider_timeout", 504),
        ("scene.draft.rewrite", "provider_rate_limited", 429),
    ],
)
def test_scene_agent_provider_failure_preserves_recovery_evidence_and_retries(
    tmp_path, workflow, failure_kind, provider_status
):
    service = WritingService(tmp_path)
    if workflow == "scene.draft.generate":
        work_id, scene_id, ready = _prepare_ba_agent_scene(service)
        base_revision_id = None
        provider_method = "generate_scene"
    else:
        work_id, scene_id, proposal_id, work = build_to_proposal(service)
        accepted = service.accept_proposal(
            work_id,
            proposal_id,
            {
                "expected_version": work["version"],
                "text": "旁白: 灯亮了。\n爱丽丝: 先确认电源。\n凯伊: 我去检查线路。\n",
            },
        )
        prepared = service.save_character_card(
            work_id,
            {
                "expected_version": accepted["work"]["version"],
                "card_id": "character-aris",
                "name": "爱丽丝",
                "source_refs": ["用户确认"],
                "voice_anchors": ["先确认眼前的情况。"],
                "trust_status": "confirmed",
            },
        )
        configured = service.configure_scene_context(
            work_id,
            scene_id,
            {
                "expected_version": prepared["work"]["version"],
                "character_card_ids": ["character-aris"],
                "world_item_ids": [],
                "reference_file_ids": [],
            },
        )
        ready = configured["work"]
        base_revision_id = accepted["revision_id"]
        provider_method = "rewrite_scene"

    original_provider_method = getattr(service.provider, provider_method)

    def fail_provider(*_args):
        raise DomainError(
            "writing_provider_failed",
            "模型服务暂时无法完成本场写作。",
            status=provider_status,
            details={
                "operation": workflow,
                "failure_kind": failure_kind,
                "http_status": provider_status,
            },
        )

    setattr(service.provider, provider_method, fail_provider)
    run_method = (
        service.run_scene_agent
        if workflow == "scene.draft.generate"
        else service.run_scene_rewrite_agent
    )
    with pytest.raises(DomainError) as failed:
        run_method(
            work_id,
            scene_id,
            {"expected_version": ready["version"], "instruction": "按固定输入处理本场。"},
        )

    assert failed.value.code == "agent_failed"
    assert failed.value.status == provider_status
    assert failed.value.details["failure"]["code"] == "writing_provider_failed"
    assert failed.value.details["failure"]["failure_kind"] == failure_kind
    failed_run_id = failed.value.details["agent_run_id"]

    restored = WritingService(tmp_path).get_work(work_id)
    failed_run = next(item for item in restored["agent_runs"] if item["id"] == failed_run_id)
    assert failed_run["status"] == "failed"
    assert failed_run["failure"] == failed.value.details["failure"]
    assert failed_run["failure"]["message"] == "模型服务暂时无法完成本场写作。"
    assert failed_run["failure"]["status"] == provider_status
    assert failed_run["failure"]["retryable"] is True
    assert failed_run["failure"]["details"]["failure_kind"] == failure_kind

    failed_item = next(
        item
        for run in restored["runs"]
        for item in run["work_items"]
        if item["acceptance"].get("agent_run_id") == failed_run_id
    )
    assert failed_item["status"] == "failed"
    assert failed_item["error"] == failed_run["failure"]
    assert failed_item["attempts"][0]["status"] == "failed"
    assert failed_item["attempts"][0]["error_code"] == "writing_provider_failed"
    scene = next(
        scene
        for chapter in restored["chapters"]
        for scene in chapter["scenes"]
        if scene["id"] == scene_id
    )
    assert scene["current_revision_id"] == base_revision_id
    assert not any(
        proposal["scope_id"] == scene_id and proposal["status"] == "pending"
        for proposal in restored["proposals"]
    )

    setattr(service.provider, provider_method, original_provider_method)
    retried = service.retry_agent_run(
        work_id,
        failed_run_id,
        {"expected_version": restored["version"]},
    )
    assert retried["retried_from_agent_run_id"] == failed_run_id
    assert retried["proposal_id"]
    retry_run = next(
        item for item in retried["work"]["agent_runs"]
        if item["id"] == retried["agent_run_id"]
    )
    assert retry_run["status"] == "waiting_user"
    assert retry_run["policy"]["retry_of_agent_run_id"] == failed_run_id
    scene = next(
        scene
        for chapter in retried["work"]["chapters"]
        for scene in chapter["scenes"]
        if scene["id"] == scene_id
    )
    assert scene["current_revision_id"] == base_revision_id


def test_ba_agent_version_conflict_marks_durable_failure(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, ready = _prepare_ba_agent_scene(service)

    def mutate_then_generate(_context):
        with service.repo.connect() as connection:
            connection.execute(
                "UPDATE works SET version=version+1 WHERE id=?",
                (work_id,),
            )
            connection.commit()
        return "旁白: 提示灯亮起。\n爱丽丝: 先确认电源。\n"

    service.provider.generate_scene = mutate_then_generate
    with pytest.raises(RevisionConflict):
        service.run_scene_agent(
            work_id, scene_id,
            {"expected_version": ready["version"], "instruction": "并发冲突测试"},
        )

    restored = WritingService(tmp_path).get_work(work_id)
    run = next(
        item for item in restored["agent_runs"]
        if item["scope_id"] == scene_id and item["instruction"] == "并发冲突测试"
    )
    assert run["status"] == "failed"
    assert run["failure"]["code"] == "revision_conflict"
    with service.repo.connect() as connection:
        item = connection.execute(
            "SELECT * FROM work_items WHERE scope_id=? AND type='agent.scene.draft.generate' ORDER BY created_at DESC LIMIT 1",
            (scene_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT * FROM job_attempts WHERE work_item_id=? ORDER BY ordinal DESC LIMIT 1",
            (item["id"],),
        ).fetchone()
    assert item["status"] == "failed"
    assert attempt["status"] == "failed"
    assert attempt["error_code"] == "revision_conflict"


def test_explicit_scene_context_selection_is_durable_and_limits_runtime_inputs(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    rejected = service.reject_proposal(work_id, proposal_id, {"expected_version": work["version"], "note": "准备指定本场资料"})
    first = service.save_character_card(
        work_id,
        {"expected_version": rejected["work"]["version"], "card_id": "character-aris", "name": "爱丽丝", "source_refs": ["用户确认"]},
    )
    second = service.save_character_card(
        work_id,
        {"expected_version": first["work"]["version"], "card_id": "character-kei", "name": "凯伊", "source_refs": ["用户确认"]},
    )
    world = service.save_world_bible(
        work_id,
        {
            "expected_version": second["work"]["version"],
            "title": "场景世界观",
            "source_type": "custom",
            "entities": [
                {"id": "world-room", "name": "活动室", "kind": "place", "source": "用户确认", "confidence_status": "confirmed"},
                {"id": "world-lab", "name": "实验室", "kind": "place", "source": "用户确认", "confidence_status": "confirmed"},
            ],
        },
    )
    first_ref = service.create_reference_file(
        work_id,
        {"expected_version": world["work"]["version"], "title": "活动室笔记", "source_label": "用户导入", "content": "活动室只在夜间开放。"},
    )
    second_ref = service.create_reference_file(
        work_id,
        {"expected_version": first_ref["work"]["version"], "title": "实验室笔记", "source_label": "用户导入", "content": "实验室不在本场。"},
    )
    configured = service.configure_scene_context(
        work_id,
        scene_id,
        {
            "expected_version": second_ref["work"]["version"],
            "character_card_ids": ["character-aris"],
            "world_item_ids": ["world-room"],
            "reference_file_ids": [first_ref["reference_file_id"]],
        },
    )
    context = service.assemble_context(work_id, scene_id)
    assert context["context_selection"]["mode"] == "explicit"
    assert [item["name"] for item in context["runtime_character_cards"]] == ["爱丽丝"]
    assert [item["name"] for item in context["world_bible"]["entities"]] == ["活动室"]
    assert [item["title"] for item in context["reference_files"]] == ["活动室笔记"]

    restarted = WritingService(tmp_path)
    restored = restarted.assemble_context(work_id, scene_id)
    assert restored["context_selection"] == configured["context_selection"]
    candidate = restarted.generate_scene_candidate(
        work_id, scene_id, {"expected_version": configured["work"]["version"]}
    )
    proposal = next(item for item in candidate["work"]["proposals"] if item["id"] == candidate["proposal_id"])
    assert "凯伊:" not in proposal["candidate"]
    assert "老师:" not in proposal["candidate"]

    rejected_candidate = restarted.reject_proposal(
        work_id,
        candidate["proposal_id"],
        {"expected_version": candidate["work"]["version"], "note": "转为 Agent 输入快照检查"},
    )
    agent_ready = restarted.run_scene_agent(
        work_id,
        scene_id,
        {"expected_version": rejected_candidate["work"]["version"], "instruction": "检查本场范围"},
    )
    snapshot_path = tmp_path / "agent-runs" / agent_ready["agent_run_id"] / "input.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert [card["name"] for card in snapshot["runtime_character_cards"]] == ["爱丽丝"]
    assert [item["name"] for item in snapshot["world_bible"]["entities"]] == ["活动室"]
    assert [item["title"] for item in snapshot["reference_files"]] == ["活动室笔记"]


def test_scene_context_selection_rejects_unconfirmed_or_stale_inputs(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    open_card = service.save_character_card(
        work_id,
        {"expected_version": work["version"], "card_id": "character-open", "name": "爱丽丝", "source_refs": ["待核对"], "trust_status": "open"},
    )
    with pytest.raises(DomainError) as unconfirmed:
        service.configure_scene_context(
            work_id,
            scene_id,
            {"expected_version": open_card["work"]["version"], "character_card_ids": ["character-open"], "world_item_ids": [], "reference_file_ids": []},
        )
    assert unconfirmed.value.code == "invalid_context_selection"

    confirmed = service.save_character_card(
        work_id,
        {"expected_version": open_card["work"]["version"], "card_id": "character-open", "name": "爱丽丝", "source_refs": ["用户确认"], "trust_status": "confirmed"},
    )
    with pytest.raises(RevisionConflict):
        service.configure_scene_context(
            work_id,
            scene_id,
            {"expected_version": open_card["work"]["version"], "character_card_ids": ["character-open"], "world_item_ids": [], "reference_file_ids": []},
        )
    configured = service.configure_scene_context(
        work_id,
        scene_id,
        {"expected_version": confirmed["work"]["version"], "character_card_ids": ["character-open"], "world_item_ids": [], "reference_file_ids": []},
    )
    assert configured["work"]["version"] == confirmed["work"]["version"] + 1


def test_scene_contract_is_durable_invalidates_pending_proposal_and_keeps_context_selection(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    rejected = service.reject_proposal(work_id, proposal_id, {"expected_version": work["version"], "note": "先固定资料"})
    card = service.save_character_card(
        work_id,
        {"expected_version": rejected["work"]["version"], "card_id": "character-aris", "name": "爱丽丝", "source_refs": ["用户确认"]},
    )
    configured = service.configure_scene_context(
        work_id,
        scene_id,
        {"expected_version": card["work"]["version"], "character_card_ids": ["character-aris"], "world_item_ids": [], "reference_file_ids": []},
    )
    candidate = service.generate_scene_candidate(work_id, scene_id, {"expected_version": configured["work"]["version"]})
    updated = service.update_scene_contract(
        work_id,
        scene_id,
        {
            "expected_version": candidate["work"]["version"],
            "title": "校订后的场景",
            "location": "夏莱临时指挥室",
            "goal": "确认机器并非普通故障。",
            "known_facts": ["机器没有接通外部电源。"],
            "forbidden_reveals": ["匿名发件人的身份。"],
            "stop_boundary": "确认异常来源后停止。",
        },
    )
    assert candidate["proposal_id"] in updated["superseded_proposal_ids"]
    scene = next(scene for scene in updated["work"]["chapters"][0]["scenes"] if scene["id"] == scene_id)
    assert scene["title"] == "校订后的场景"
    assert scene["contract"]["context_selection"]["character_card_ids"] == ["character-aris"]
    assert scene["contract"]["forbidden_reveals"] == ["匿名发件人的身份。"]
    superseded = next(item for item in updated["work"]["proposals"] if item["id"] == candidate["proposal_id"])
    assert superseded["status"] == "superseded"
    with pytest.raises(DomainError) as error:
        service.accept_proposal(work_id, candidate["proposal_id"], {"expected_version": updated["work"]["version"]})
    assert error.value.code == "proposal_not_pending"
    context = WritingService(tmp_path).assemble_context(work_id, scene_id)
    assert context["scene_contract"]["location"] == "夏莱临时指挥室"
    assert context["scene_contract"]["known_facts"] == ["机器没有接通外部电源。"]


def test_scene_contract_rejects_stale_work_version(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    service.create_reference_file(
        work_id,
        {"expected_version": work["version"], "title": "变更", "source_label": "用户", "content": "内容"},
    )
    with pytest.raises(RevisionConflict):
        service.update_scene_contract(
            work_id,
            scene_id,
            {"expected_version": work["version"], "title": "过期", "goal": "目标", "stop_boundary": "停止"},
        )


def test_open_character_card_is_durable_but_cannot_unlock_agent_context(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    draft = service.save_character_card(
        work_id,
        {
            "expected_version": work["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_type": "official_reference",
            "trust_status": "open",
            "source_refs": ["official-corpus:scenario_7:42"],
        },
    )
    context = service.assemble_context(work_id, scene_id)
    assert "爱丽丝" in context["readiness"]["missing_runtime_character_cards"]
    assert context["readiness"]["unverified_character_cards"] == {"爱丽丝": "open"}
    assert context["runtime_character_cards"] == []

    confirmed = service.save_character_card(
        work_id,
        {
            "expected_version": draft["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_type": "official_reference",
            "trust_status": "confirmed",
            "voice_anchors": ["先确认眼前的情况。"],
            "source_refs": ["official-corpus:scenario_7:42", "用户核对"],
        },
    )
    restarted = WritingService(tmp_path)
    context = restarted.assemble_context(work_id, scene_id)
    card_artifact = next(item for item in confirmed["work"]["artifacts"] if item["scope_id"] == "character-aris")
    assert card_artifact["scope_id"] == "character-aris"
    assert [revision["ordinal"] for revision in card_artifact["revisions"]] == [2, 1]
    assert [card["name"] for card in context["runtime_character_cards"]] == ["爱丽丝"]


def test_work_canon_identity_history_and_context_trust_survive_restart(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    created = service.save_work_canon(
        work_id,
        {
            "expected_version": work["version"],
            "facts": [
                {"id": "fact-power", "text": "旧机器没有接通电源。", "source": "用户确认", "confidence_status": "confirmed", "scope": "work"},
                {"id": "fact-sender", "text": "发件人可能来自夏莱。", "source": "剧情推断", "confidence_status": "inferred", "scope": "chapter"},
            ],
        },
    )
    revised = service.save_work_canon(
        work_id,
        {
            "expected_version": created["work"]["version"],
            "facts": [
                {"id": "fact-power", "text": "旧机器仍未接通外部电源。", "source": "用户确认", "confidence_status": "confirmed", "scope": "work"},
                {"id": "fact-sender", "text": "发件人可能来自夏莱。", "source": "剧情推断", "confidence_status": "inferred", "scope": "chapter"},
            ],
        },
    )
    service.save_work_canon(
        work_id,
        {
            "expected_version": revised["work"]["version"],
            "facts": [
                {"id": "fact-power", "text": "旧机器仍未接通外部电源。", "source": "用户确认", "confidence_status": "confirmed", "scope": "work", "status": "archived"},
                {"id": "fact-sender", "text": "发件人可能来自夏莱。", "source": "剧情推断", "confidence_status": "inferred", "scope": "chapter"},
            ],
        },
    )
    restarted = WritingService(tmp_path)
    loaded = restarted.get_work(work_id)
    artifact = next(item for item in loaded["artifacts"] if item["kind"] == "work_canon")
    context = restarted.assemble_context(work_id, scene_id)
    assert [revision["ordinal"] for revision in artifact["revisions"]] == [3, 2, 1]
    assert {fact["id"] for fact in artifact["current_revision"]["content"]["facts"]} == {"fact-power", "fact-sender"}
    assert context["work_canon"]["facts"] == []


def test_work_canon_archived_fact_can_be_restored_as_a_new_revision(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    created = service.save_work_canon(
        work_id,
        {
            "expected_version": work["version"],
            "facts": [{
                "id": "fact-restorable",
                "text": "广播室的异常频段需要先做技术复核。",
                "source": "用户确认",
                "confidence_status": "confirmed",
                "scope": "work",
            }],
        },
    )
    archived = service.save_work_canon(
        work_id,
        {
            "expected_version": created["work"]["version"],
            "facts": [{
                "id": "fact-restorable",
                "text": "广播室的异常频段需要先做技术复核。",
                "source": "用户确认",
                "confidence_status": "confirmed",
                "scope": "work",
                "status": "archived",
            }],
        },
    )
    restored = service.save_work_canon(
        work_id,
        {
            "expected_version": archived["work"]["version"],
            "facts": [{
                "id": "fact-restorable",
                "text": "广播室的异常频段需要先做技术复核。",
                "source": "用户确认",
                "confidence_status": "confirmed",
                "scope": "work",
                "status": "active",
            }],
        },
    )

    artifact = next(item for item in restored["work"]["artifacts"] if item["kind"] == "work_canon")
    context = service.assemble_context(work_id, scene_id)
    assert [revision["ordinal"] for revision in artifact["revisions"]] == [3, 2, 1]
    assert artifact["current_revision"]["content"]["facts"][0]["status"] == "active"
    assert context["work_canon"]["facts"][0]["id"] == "fact-restorable"


def test_unconfirmed_world_card_stays_in_library_but_out_of_scene_context(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _, work = build_to_proposal(service)
    saved = service.save_world_bible(
        work_id,
        {
            "expected_version": work["version"],
            "title": "本作世界观",
            "source_type": "official_reference",
            "entities": [{
                "id": "world-card-schaale",
                "name": "夏莱",
                "kind": "organization",
                "source": "official-corpus:scenario_7:42",
                "source_type": "official_reference",
                "confidence_status": "open",
            }],
        },
    )
    context = WritingService(tmp_path).assemble_context(work_id, scene_id)
    artifact = next(item for item in saved["work"]["artifacts"] if item["kind"] == "world_bible")
    assert artifact["current_revision"]["content"]["entities"][0]["id"] == "world-card-schaale"
    assert context["world_bible"]["entities"] == []
    assert context["readiness"]["unverified_world_items"][0]["id"] == "world-card-schaale"


def test_ba_world_starter_is_work_owned_open_and_restart_safe(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界观起始架构"})

    applied = service.apply_ba_world_starter(
        work["id"], {"expected_version": work["version"]}
    )
    bible = next(
        item for item in applied["work"]["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    assert bible["source_type"] == "ba_starter"
    assert {
        "ba-starter-kivotos",
        "ba-starter-schale",
        "ba-starter-general-student-council",
        "ba-starter-academy-network",
    }.issubset({item["id"] for item in bible["entities"]})
    assert len(bible["entities"]) >= 10
    assert {item["confidence_status"] for item in bible["entities"]} == {"open"}

    restarted = WritingService(tmp_path)
    loaded = restarted.get_work(work["id"])
    saved = next(item for item in loaded["artifacts"] if item["kind"] == "world_bible")
    assert saved["current_revision"]["content"] == bible

    with pytest.raises(DomainError) as error:
        restarted.apply_ba_world_starter(
            work["id"], {"expected_version": loaded["version"]}
        )
    assert error.value.code == "world_starter_already_applied"


def test_ba_world_starter_merges_into_existing_custom_world_without_overwrite(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "混合世界观"})
    custom = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            "title": "我的自定义世界",
            "source_type": "custom",
            "entities": [{
                "id": "world-custom-lab",
                "name": "地下实验室",
                "kind": "place",
                "summary": "本作原创地点。",
                "source": "用户确认",
                "source_type": "custom",
                "confidence_status": "confirmed",
            }],
        },
    )
    applied = service.apply_ba_world_starter(
        work["id"], {"expected_version": custom["work"]["version"]}
    )
    bible = next(
        item for item in applied["work"]["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    assert bible["title"] == "我的自定义世界"
    assert bible["source_type"] == "mixed"
    assert [item["id"] for item in bible["entities"]][:1] == ["world-custom-lab"]
    assert len(bible["entities"]) >= 11

    revised = service.save_world_bible(
        work["id"],
        {
            "expected_version": applied["work"]["version"],
            **bible,
            "entities": [
                {**item, "confidence_status": "confirmed"}
                if item["id"] == "ba-starter-kivotos" else item
                for item in bible["entities"]
            ],
        },
    )
    updated = next(
        item for item in revised["work"]["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    assert updated["source_type"] == "mixed"


def test_work_can_start_with_a_versioned_ba_world_library(tmp_path):
    service = WritingService(tmp_path)

    work = service.create_work({"title": "从 BA 底稿开始", "world_seed": "ba_starter"})
    bible = next(
        item for item in work["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]

    assert bible["source_type"] == "ba_starter"
    assert len(bible["entities"]) >= 10
    assert {item["confidence_status"] for item in bible["entities"]} == {"open"}
    assert all(item["status"] == "active" for item in bible["entities"])
    assert all(item["source_type"] == "ba_starter" for item in bible["entities"])

    restarted = WritingService(tmp_path)
    restored = next(
        item for item in restarted.get_work(work["id"])["artifacts"]
        if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    assert restored == bible


def test_ba_starter_and_custom_world_remain_distinguishable_after_a_card_revision(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "混合底稿", "world_seed": "ba_starter"})
    bible = next(
        item for item in work["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]

    updated = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            **bible,
            "entities": [
                *bible["entities"],
                {
                    "id": "world-custom-clubroom",
                    "name": "旧社团活动室",
                    "kind": "place",
                    "summary": "本作原创场景地点。",
                    "source": "用户确认",
                    "source_type": "custom",
                    "confidence_status": "confirmed",
                },
            ],
        },
    )
    saved = next(
        item for item in updated["work"]["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]

    assert saved["source_type"] == "mixed"
    assert next(item for item in saved["entities"] if item["id"] == "ba-starter-kivotos")["source_type"] == "ba_starter"
    assert next(item for item in saved["entities"] if item["id"] == "world-custom-clubroom")["source_type"] == "custom"


def test_ba_starter_card_can_be_confirmed_without_losing_its_provenance(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "确认 BA 底稿", "world_seed": "ba_starter"})
    bible = next(
        item for item in work["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    updated_entities = [
        {**item, "confidence_status": "confirmed"}
        if item["id"] == "ba-starter-kivotos" else item
        for item in bible["entities"]
    ]

    saved = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            **bible,
            "entities": updated_entities,
        },
    )
    persisted = next(
        item for item in saved["work"]["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    kivotos = next(item for item in persisted["entities"] if item["id"] == "ba-starter-kivotos")

    assert persisted["source_type"] == "ba_starter"
    assert kivotos["confidence_status"] == "confirmed"
    assert kivotos["source_type"] == "ba_starter"
    assert WritingService(tmp_path).get_work(work["id"])["version"] == saved["work"]["version"]


def test_world_card_links_are_versioned_validated_and_restored(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界关系", "world_seed": "ba_starter"})
    bible = next(
        item for item in work["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]

    linked = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            **bible,
            "entities": [
                {
                    **item,
                    "related_world_ids": ["ba-starter-schale"],
                }
                if item["id"] == "ba-starter-kivotos" else item
                for item in bible["entities"]
            ],
        },
    )
    restarted = WritingService(tmp_path).get_work(work["id"])
    restored = next(
        item for item in restarted["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["content"]
    kivotos = next(item for item in restored["entities"] if item["id"] == "ba-starter-kivotos")
    assert kivotos["related_world_ids"] == ["ba-starter-schale"]
    assert linked["revision_id"] != next(
        item for item in work["artifacts"] if item["kind"] == "world_bible"
    )["current_revision"]["id"]

    with pytest.raises(DomainError) as error:
        service.save_world_bible(
            work["id"],
            {
                "expected_version": linked["work"]["version"],
                **restored,
                "entities": [
                    {**item, "related_world_ids": ["world-missing"]}
                    if item["id"] == "ba-starter-kivotos" else item
                    for item in restored["entities"]
                ],
            },
        )
    assert error.value.details["field"] == "related_world_ids"


def test_library_rejects_invalid_trust_scope_and_status(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料校验"})
    with pytest.raises(DomainError) as character_error:
        service.save_character_card(work["id"], {"expected_version": work["version"], "name": "角色", "source_refs": ["用户"], "trust_status": "trusted"})
    assert character_error.value.details == {"field": "trust_status"}
    with pytest.raises(DomainError) as canon_error:
        service.save_work_canon(work["id"], {"expected_version": work["version"], "facts": [{"text": "事实", "source": "用户", "scope": "global"}]})
    assert canon_error.value.code == "validation_error"
    with pytest.raises(DomainError) as world_error:
        service.save_world_bible(work["id"], {"expected_version": work["version"], "rules": [{"text": "规则", "source": "用户", "status": "deleted"}]})
    assert world_error.value.code == "validation_error"


def test_scene_contract_supports_dual_track_fields_and_scene_sensei_override(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    rejected = service.reject_proposal(
        work_id, proposal_id, {"expected_version": work["version"], "note": "补充双轨合同"}
    )
    service.update_scene_contract(
        work_id,
        scene_id,
        {
            "expected_version": rejected["work"]["version"],
            "title": "老师介入的提示灯",
            "location": "游戏开发部活动室",
            "goal": "确认提示灯来源",
            "stop_boundary": "确认第一条可验证线索后停止",
            "scene_type": "investigation",
            "external_trigger": "提示灯再次闪烁",
            "hidden_expectation": "爱丽丝希望老师认可她的判断",
            "defense": "用技术术语回避不安",
            "choice": "先查日志而不是拆机",
            "plot_delta": "确认异常并非电源故障",
            "emotion_delta": "戒备转为有限合作",
            "residue": "匿名发件人的身份仍未知",
            "ending_payoff": "得到下一场可追查的日志编号",
            "has_sensei": True,
            "sensei_scene_function": "只负责确认行动边界，不替学生解题",
            "render_mode": "dialogue_first",
            "information_ownership": {"爱丽丝": ["日志异常"], "老师": ["任务边界"]},
            "exchange_chain": [{"from": "爱丽丝", "to": "老师", "purpose": "请求确认"}],
        },
    )

    context = service.assemble_context(work_id, scene_id)
    assert context["scene_contract"]["plot_delta"] == "确认异常并非电源故障"
    assert context["scene_contract"]["exchange_chain"][0]["purpose"] == "请求确认"
    assert context["rules"]["sensei"] == "knowledge/老师在场规则.md"
    assert context["skill_runtime"]["has_sensei"] is True


def test_invalid_provider_script_is_rejected_without_silent_line_dropping(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "严格正文格式"})
    brief = service.save_brief(
        work["id"],
        {"expected_version": work["version"], "idea": "测试非法输出", "mode": "bond_short", "characters": ["爱丽丝"]},
    )
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    chapter = service.create_chapter(work["id"], {"expected_version": blueprint["work"]["version"], "title": "第一章"})
    scene = service.create_scene(
        work["id"], chapter["chapter_id"],
        {"expected_version": chapter["work"]["version"], "title": "非法输出", "goal": "验证格式"},
    )
    service.provider.generate_scene = lambda _context: "下面是正文：\n旁白: 灯亮了。\n未知角色: 我知道答案。\n"

    with pytest.raises(DomainError) as error:
        service.generate_scene_candidate(
            work["id"], scene["scene_id"], {"expected_version": scene["work"]["version"]}
        )
    assert error.value.code == "provider_output_invalid"
    assert {item["reason"] for item in error.value.details["invalid_lines"]} == {
        "empty_speaker_or_content", "unknown_speaker"
    }
    with service.repo.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM proposals WHERE scope_id=?", (scene["scene_id"],)).fetchone()[0] == 0


def test_official_script_normalizes_an_unambiguous_character_short_name():
    context = {
        "runtime_character_cards": [{
            "name": "天童爱丽丝",
            "canonical_name": "天童爱丽丝",
            "aliases": [],
        }],
        "scene_contract": {},
        "brief": {},
    }

    normalized = WritingService._normalize_official_script(
        "旁白: 广播又响了一次。\n爱丽丝: 我来确认信号来源。\n",
        context,
    )

    assert normalized == "旁白: 广播又响了一次。\n天童爱丽丝: 我来确认信号来源。\n"


def test_scene_review_agent_persists_provider_findings_and_fingerprints(tmp_path):
    from halocue_writing.providers import FakeWritingProvider

    class ReviewProvider(FakeWritingProvider):
        kind = "review-test"
        display_name = "Review Test Provider"
        is_simulation = False

        def review_scene(self, context, text):
            assert context["fingerprints"]["static_rule_pack"].startswith("sha256:")
            return [{
                "kind": "ooc",
                "severity": "warning",
                "message": "爱丽丝的判断缺少证据缓冲。",
                "evidence": {"speaker": "爱丽丝"},
            }]

    service = WritingService(tmp_path)
    work_id, scene_id, ready = _prepare_ba_agent_scene(service)
    drafted = service.run_scene_agent(
        work_id, scene_id, {"expected_version": ready["version"], "instruction": "起草本场"}
    )
    accepted = service.accept_proposal(
        work_id, drafted["proposal_id"], {"expected_version": drafted["work"]["version"]}
    )
    service.provider = ReviewProvider()
    reviewed = service.review_scene(
        work_id, scene_id, {"expected_version": accepted["work"]["version"]}
    )

    assert reviewed["simulation"] is False
    provider_finding = next(item for item in reviewed["findings"] if item["kind"] == "ooc")
    assert provider_finding["evidence"]["source"] == "provider"
    run = next(item for item in reviewed["work"]["agent_runs"] if item["id"] == reviewed["agent_run_id"])
    assert run["status"] == "succeeded"
    assert run["policy"]["write_policy"] == "findings_and_gate_only_manuscript_read_only"
    assert run["policy"]["fingerprints"]["scene_writing_pack"].startswith("sha256:")
    assert [item["tool_name"] for item in run["tool_calls"]] == [
        "assemble_scene_context", "read_pinned_scene_revision", "create_review_findings", "evaluate_scene_gate"
    ]
    gate = next(item for item in reviewed["work"]["gates"] if item["id"] == reviewed["gate_id"])
    assert gate["snapshot"]["agent_run_id"] == reviewed["agent_run_id"]


def test_scene_review_conflict_persists_terminal_failure(tmp_path):
    from halocue_writing.providers import FakeWritingProvider

    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})

    class MutatingReviewProvider(FakeWritingProvider):
        kind = "mutating-review-test"

        def review_scene(self, context, text):
            with service.repo.transaction() as connection:
                connection.execute("UPDATE works SET version=version+1 WHERE id=?", (work_id,))
            return []

    service.provider = MutatingReviewProvider()
    with pytest.raises(RevisionConflict):
        service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})

    with service.repo.connect() as connection:
        run = connection.execute(
            "SELECT * FROM agent_runs WHERE work_id=? ORDER BY created_at DESC LIMIT 1", (work_id,)
        ).fetchone()
        attempt = connection.execute(
            """SELECT attempt.* FROM job_attempts attempt
               JOIN work_items item ON item.id=attempt.work_item_id
               WHERE item.scope_id=? ORDER BY attempt.started_at DESC LIMIT 1""",
            (scene_id,),
        ).fetchone()
        item = connection.execute(
            "SELECT * FROM work_items WHERE scope_id=? ORDER BY created_at DESC LIMIT 1", (scene_id,)
        ).fetchone()
        assert run["status"] == "failed"
        assert json.loads(run["failure_json"])["code"] == "revision_conflict"
        assert attempt["status"] == "failed"
        assert attempt["error_code"] == "revision_conflict"
        assert item["status"] == "failed"
        assert connection.execute("SELECT COUNT(*) FROM gates WHERE result_json LIKE ?", (f'%"agent_run_id":"{run["id"]}"%',)).fetchone()[0] == 0


def test_continuity_review_persists_cross_scene_evidence_and_agent_trace(tmp_path):
    from halocue_writing.providers import FakeWritingProvider

    class ContinuityProvider(FakeWritingProvider):
        kind = "continuity-test"
        is_simulation = False

        def review_continuity(self, context):
            assert context["schema_version"] == "work-review-pack/1.0"
            first, second = context["scenes"]
            return [{
                "scene_id": second["scene_id"],
                "revision_id": second["revision_id"],
                "kind": "knowledge_order",
                "severity": "warning",
                "message": "第二场提前使用了第一场尚未确认的线索。",
                "evidence": {
                    "revision_refs": [
                        {"scene_id": first["scene_id"], "revision_id": first["revision_id"]},
                        {"scene_id": second["scene_id"], "revision_id": second["revision_id"]},
                    ]
                },
            }]

    service = WritingService(tmp_path)
    work_id, first_scene_id, proposal_id, work = build_to_proposal(service)
    first = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    chapter_id = first["work"]["chapters"][0]["id"]
    second_scene = service.create_scene(
        work_id, chapter_id,
        {"expected_version": first["work"]["version"], "title": "第二场", "goal": "承接线索"},
    )
    second_candidate = service.generate_scene_candidate(
        work_id, second_scene["scene_id"], {"expected_version": second_scene["work"]["version"]}
    )
    second = service.accept_proposal(
        work_id, second_candidate["proposal_id"], {"expected_version": second_candidate["work"]["version"]}
    )
    service.provider = ContinuityProvider()
    reviewed = service.review_continuity(work_id, {"expected_version": second["work"]["version"]})

    assert reviewed["status"] == "passed"
    assert reviewed["simulation"] is False
    assert len(reviewed["findings"][0]["revision_refs"]) == 2
    stored = next(item for item in reviewed["work"]["review_findings"] if item["id"] == reviewed["findings"][0]["id"])
    assert stored["scope_type"] == "work"
    assert stored["scope_id"] == work_id
    assert {item["scene_id"] for item in stored["revision_refs"]} == {first_scene_id, second_scene["scene_id"]}
    run = next(item for item in reviewed["work"]["agent_runs"] if item["id"] == reviewed["agent_run_id"])
    assert run["status"] == "succeeded"
    assert run["policy"]["workflow"] == "continuity.review"
    assert [call["tool_name"] for call in run["tool_calls"]] == [
        "assemble_work_review_pack", "create_review_findings", "evaluate_review_gate"
    ]


def test_release_review_provider_blocker_blocks_gate(tmp_path):
    from halocue_writing.providers import FakeWritingProvider

    class ReleaseProvider(FakeWritingProvider):
        kind = "release-review-test"
        is_simulation = False

        def review_release(self, context):
            scene = context["scenes"][0]
            return [{
                "scene_id": scene["scene_id"],
                "revision_id": scene["revision_id"],
                "kind": "unresolved_payoff",
                "severity": "blocking",
                "message": "结尾承诺的线索尚未回收。",
                "evidence": {"scene_id": scene["scene_id"]},
            }]

    service = WritingService(tmp_path)
    work_id, scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    scene_review = service.review_scene(work_id, scene_id, {"expected_version": accepted["work"]["version"]})
    service.provider = ReleaseProvider()
    memory_ready = skip_memory_for_current_scenes(service, scene_review["work"])
    release_review = service.review_release(
        work_id, {"expected_version": memory_ready["version"]}
    )

    assert release_review["status"] == "blocked"
    assert release_review["findings"][0]["severity"] == "blocking"
    assert release_review["snapshot"]["agent_run_id"] == release_review["agent_run_id"]
    with pytest.raises(DomainError) as error:
        service.freeze_release(work_id, {"expected_version": release_review["work"]["version"]})
    assert error.value.code == "release_blocked"


def test_failed_work_review_retries_from_integrity_checked_snapshot(tmp_path):
    from halocue_writing.providers import FakeWritingProvider

    class FailingContinuityProvider(FakeWritingProvider):
        kind = "continuity-failure-test"

        def review_continuity(self, context):
            raise DomainError("provider_failed", "测试中的模型失败。", status=502)

    service = WritingService(tmp_path)
    work_id, _scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    service.provider = FailingContinuityProvider()
    with pytest.raises(DomainError) as error:
        service.review_continuity(work_id, {"expected_version": accepted["work"]["version"]})
    assert error.value.code == "provider_failed"
    failed_run = service.get_work(work_id)["agent_runs"][0]
    assert failed_run["status"] == "failed"

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work_id,
        failed_run["id"],
        {"expected_version": accepted["work"]["version"]},
    )
    assert retried["status"] == "passed"
    new_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert new_run["status"] == "succeeded"
    assert new_run["policy"]["retry_of_agent_run_id"] == failed_run["id"]
    assert (
        new_run["policy"]["fingerprints"]["work_review_pack"]
        == failed_run["policy"]["fingerprints"]["work_review_pack"]
    )


def test_failed_work_review_with_missing_snapshot_returns_stable_integrity_error(tmp_path):
    class FailingContinuityProvider(FakeWritingProvider):
        kind = "continuity-missing-snapshot-test"

        def review_continuity(self, context):
            raise DomainError("provider_failed", "测试中的模型失败。", status=502)

    service = WritingService(tmp_path)
    work_id, _scene_id, proposal_id, work = build_to_proposal(service)
    accepted = service.accept_proposal(work_id, proposal_id, {"expected_version": work["version"]})
    service.provider = FailingContinuityProvider()
    with pytest.raises(DomainError) as error:
        service.review_continuity(work_id, {"expected_version": accepted["work"]["version"]})
    assert error.value.code == "provider_failed"
    failed_run = service.get_work(work_id)["agent_runs"][0]
    (service.repo.data_dir / failed_run["input_snapshot_uri"]).unlink()

    with pytest.raises(DomainError) as rejected:
        service.retry_agent_run(
            work_id,
            failed_run["id"],
            {"expected_version": accepted["work"]["version"]},
        )

    assert rejected.value.code == "agent_snapshot_integrity_failed"
    assert rejected.value.details == {"agent_run_id": failed_run["id"]}


def test_scene_writing_pack_compresses_references_and_includes_previous_middle_and_tail(tmp_path):
    service = WritingService(tmp_path)
    work_id, first_scene_id, proposal_id, work = build_to_proposal(service)
    long_previous = "旁白: " + ("上一场内容" * 1500) + "\n"
    accepted = service.accept_proposal(
        work_id, proposal_id, {"expected_version": work["version"], "text": long_previous}
    )
    reference = service.create_reference_file(
        work_id,
        {
            "expected_version": accepted["work"]["version"],
            "title": "长篇证据",
            "source_label": "用户导入",
            "content": "资料段落" * 2200,
        },
    )
    chapter_id = reference["work"]["chapters"][0]["id"]
    second = service.create_scene(
        work_id,
        chapter_id,
        {"expected_version": reference["work"]["version"], "title": "承接场", "goal": "承接上一场线索"},
    )

    context = service.assemble_context(work_id, second["scene_id"])
    packed_reference = context["scene_writing_pack"]["reference_files"][0]
    previous = context["scene_writing_pack"]["previous_scene_context"]
    assert packed_reference["content_truncated"] is True
    assert {item["label"] for item in packed_reference["excerpt_segments"]} == {"start", "middle", "tail"}
    assert previous["scene_id"] == first_scene_id
    assert previous["truncated"] is True
    assert [item["label"] for item in previous["excerpt_segments"]] == ["middle", "tail"]
    assert context["scene_writing_pack"]["digest"] == context["fingerprints"]["scene_writing_pack"]
