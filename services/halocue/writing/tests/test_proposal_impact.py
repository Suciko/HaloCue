from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class CharacterProposalProvider(FakeWritingProvider):
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        return {
            "text": "我整理了一份凯伊的人物卡候选。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "character_card",
                "title": "凯伊",
                "status": "discussion_draft",
                "content": {
                    "name": "凯伊",
                    "role": "负责核对终端留下的访问记录。",
                    "ooc_constraints": ["证据不足时不会直接归因于敌对行为。"],
                },
            },
        }


class CharacterUpdateProvider(FakeWritingProvider):
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        return {
            "text": "我整理了凯伊的现场职责更新。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "character_card",
                "title": "凯伊",
                "status": "discussion_draft",
                "content": {
                    "name": "凯伊",
                    "role": "负责核对现场留下的访问记录。",
                },
            },
        }


def create_character_proposal(service: WritingService) -> tuple[dict, dict]:
    work = service.create_work({"title": "影响预览验收"})
    service.provider = CharacterProposalProvider()
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "把凯伊目前确定的职责和行为边界整理为人物卡。",
        },
    )
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(
        item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"]
    )
    return proposed, proposal


def request_json(url: str):
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_knowledge_proposal_persists_deterministic_domain_impact(tmp_path):
    service = WritingService(tmp_path)
    proposed, proposal = create_character_proposal(service)
    impact = proposal["candidate"]["impact_preview"]

    assert impact["schema_version"] == "proposal-impact/1.0"
    assert impact["operation"] == "create"
    assert impact["target"]["artifact_kind"] == "character_card"
    assert impact["target"]["scope_id"] == proposal["candidate"]["scope_id"]
    assert impact["target"]["title"] == "凯伊"
    assert impact["conflict_summary"] == {
        "status": "clear",
        "count": 0,
        "blocking_count": 0,
        "items": [],
    }
    assert {item["id"] for item in impact["affected_consumers"]} == {
        "scene_context",
        "ooc_review",
        "release_review",
    }
    assert impact["decision"] == {
        "requires_user_confirmation": True,
        "partial_accept_supported": False,
    }
    assert impact["digest"].startswith("sha256:")
    assert len(impact["digest"]) == 71

    restored = WritingService(tmp_path).get_work(proposed["work"]["id"])
    restored_proposal = next(item for item in restored["proposals"] if item["id"] == proposal["id"])
    assert restored_proposal["candidate"]["impact_preview"] == impact


def test_impact_view_reports_live_revision_and_digest_guards_acceptance(tmp_path):
    service = WritingService(tmp_path)
    proposed, proposal = create_character_proposal(service)
    work_id = proposed["work"]["id"]
    impact = service.get_proposal_impact(work_id, proposal["id"])

    assert impact["schema_version"] == "proposal-impact-view/1.0"
    assert impact["live_validation"]["base_revision_matches"] is True
    assert impact["live_validation"]["ready_for_decision"] is True

    with pytest.raises(DomainError) as mismatch:
        service.accept_proposal(
            work_id,
            proposal["id"],
            {
                "expected_version": proposed["work"]["version"],
                "expected_impact_digest": "0" * 64,
            },
        )
    assert mismatch.value.code == "proposal_impact_mismatch"
    assert service.get_proposal_impact(work_id, proposal["id"])["proposal_status"] == "pending"

    accepted = service.accept_proposal(
        work_id,
        proposal["id"],
        {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": impact["impact"]["digest"],
        },
    )
    assert accepted["revision_id"].startswith("revision-")
    decided = service.get_proposal_impact(work_id, proposal["id"])
    assert decided["proposal_status"] == "accepted"
    assert decided["live_validation"]["ready_for_decision"] is False
    assert decided["live_validation"]["base_revision_matches"] is False


def test_character_proposal_rechecks_cross_card_name_conflicts_at_decision_time(tmp_path):
    service = WritingService(tmp_path)
    proposed, proposal = create_character_proposal(service)
    work_id = proposed["work"]["id"]

    concurrent = service.save_character_card(
        work_id,
        {
            "expected_version": proposed["work"]["version"],
            "card_id": "character-kei-concurrent",
            "name": "凯伊",
            "source_type": "custom",
            "source_refs": ["用户并发建立"],
            "trust_status": "confirmed",
        },
    )
    impact = service.get_proposal_impact(work_id, proposal["id"])
    assert impact["live_validation"]["base_revision_matches"] is True
    assert impact["live_validation"]["ready_for_decision"] is False
    assert impact["live_validation"]["blocking_conflicts"][0]["existing_id"] == "character-kei-concurrent"

    with pytest.raises(DomainError) as conflict:
        service.accept_proposal(
            work_id,
            proposal["id"],
            {
                "expected_version": concurrent["work"]["version"],
                "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            },
        )
    assert conflict.value.code == "knowledge_conflict"
    restored = service.get_work(work_id)
    assert next(item for item in restored["proposals"] if item["id"] == proposal["id"])["status"] == "pending"


def test_knowledge_impact_lists_scene_refs_and_rejects_changed_scope(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料影响范围"})
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "凯伊调查温室门禁记录。",
            "mode": "bond_short",
            "characters": ["凯伊"],
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter_id = blueprint["work"]["chapters"][0]["id"]
    scene = service.create_scene(
        work["id"],
        chapter_id,
        {
            "expected_version": blueprint["work"]["version"],
            "title": "核对门禁",
            "location": "温室",
            "goal": "确认访问记录",
        },
    )
    card = service.save_character_card(
        work["id"],
        {
            "expected_version": scene["work"]["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "role": "负责核对记录。",
            "source_type": "custom",
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
    )
    configured = service.configure_scene_context(
        work["id"],
        scene["scene_id"],
        {
            "expected_version": card["work"]["version"],
            "character_card_ids": ["character-kei"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    service.provider = CharacterUpdateProvider()
    thread = configured["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "更新凯伊的现场职责。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "character_card",
        },
    )
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    affected = proposal["candidate"]["impact_preview"]["affected_refs"]
    assert affected == [{
        "kind": "scene",
        "id": scene["scene_id"],
        "label": "场景《核对门禁》",
        "effect": "reassemble_context",
        "status": "current",
    }]
    presentation = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    card = next(
        event["details"]["card"]
        for event in presentation["events"]
        if event["event_type"] == "proposal.presented"
        and event.get("refs", {}).get("proposal_id") == proposal["id"]
    )
    assert card["impact_refs"] == affected

    other = service.save_character_card(
        work["id"],
        {
            "expected_version": proposed["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "role": "负责观察。",
            "source_type": "custom",
            "source_refs": ["用户确认"],
            "trust_status": "confirmed",
        },
    )
    changed_scope = service.configure_scene_context(
        work["id"],
        scene["scene_id"],
        {
            "expected_version": other["work"]["version"],
            "character_card_ids": ["character-aris"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    impact = service.get_proposal_impact(work["id"], proposal["id"])
    assert impact["live_validation"]["affected_refs"] == []
    assert impact["live_validation"]["affected_refs_match"] is False
    assert impact["live_validation"]["ready_for_decision"] is False

    with pytest.raises(DomainError) as changed:
        service.accept_proposal(
            work["id"],
            proposal["id"],
            {
                "expected_version": changed_scope["work"]["version"],
                "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
            },
        )
    assert changed.value.code == "proposal_impact_changed"


def test_proposal_impact_http_route_returns_stable_contract(tmp_path):
    service = WritingService(tmp_path / "data")
    proposed, proposal = create_character_proposal(service)
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        status, response = request_json(
            base
            + f"/api/v1/works/{proposed['work']['id']}/proposals/{proposal['id']}/impact"
        )
        assert status == 200
        assert response["ok"] is True
        assert response["data"]["proposal_id"] == proposal["id"]
        assert response["data"]["impact"]["digest"] == proposal["candidate"]["impact_preview"]["digest"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()


def test_agent_run_exposes_compact_ordered_timeline_without_raw_arguments(tmp_path):
    service = WritingService(tmp_path)
    proposed, _ = create_character_proposal(service)
    run = proposed["work"]["agent_runs"][0]
    timeline = run["timeline"]

    assert timeline["schema_version"] == "agent-run-timeline/1.0"
    assert timeline["visibility"] == "user_summary"
    assert timeline["event_count"] == len(timeline["events"])
    assert [item["sequence"] for item in timeline["events"]] == list(
        range(1, timeline["event_count"] + 1)
    )
    assert timeline["events"][0]["type"] == "run_started"
    assert timeline["events"][-1]["type"] == "run_finished"
    assert "tool" in {item["type"] for item in timeline["events"]}
    assert "response" in {item["type"] for item in timeline["events"]}
    assert all("args" not in item and "input_tokens" not in item for item in timeline["events"])

    restored = WritingService(tmp_path).get_agent_run(proposed["work"]["id"], run["id"])
    assert restored["timeline"] == timeline
