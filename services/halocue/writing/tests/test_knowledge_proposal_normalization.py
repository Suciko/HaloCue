from __future__ import annotations

import json
from pathlib import Path

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService
from .test_agent_presentation import _assert_json_schema_instance


CONTRACTS = Path(__file__).resolve().parents[1] / "docs" / "contracts"


def assert_knowledge_contract(candidate: dict) -> None:
    proposal_schema = json.loads(
        (CONTRACTS / "conversation-knowledge-proposal-1.2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    impact_schema = json.loads(
        (CONTRACTS / "proposal-impact-1.0.schema.json").read_text(encoding="utf-8")
    )
    impact_defs = impact_schema.pop("$defs")
    def rewrite_impact_refs(value) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("$ref"), str) and value["$ref"].startswith("#/$defs/"):
                value["$ref"] = value["$ref"].replace("#/$defs/", "#/$defs/impact_", 1)
            for child in value.values():
                rewrite_impact_refs(child)
        elif isinstance(value, list):
            for child in value:
                rewrite_impact_refs(child)

    rewrite_impact_refs(impact_schema)
    proposal_schema["$defs"] = {
        "impact": impact_schema,
        **{f"impact_{name}": value for name, value in impact_defs.items()},
    }
    proposal_schema["properties"]["impact_preview"] = {"$ref": "#/$defs/impact"}
    _assert_json_schema_instance(candidate, proposal_schema)


class WorldRuleUpdateProvider(FakeWritingProvider):
    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        return {
            "text": "我整理了温室夜间门禁的例外条件。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "world_rule",
                "title": "温室夜间门禁",
                "status": "discussion_draft",
                "content": {
                    "name": "温室夜间门禁",
                    "text": "夜间进入温室必须持有生物委员会许可。",
                    "exceptions": ["紧急救援时可由值班教师授权"],
                    "source": "作品主对话补充",
                    "source_refs": ["用户补充说明"],
                    "confidence_status": "confirmed",
                    "scope": "work",
                },
            },
        }


class InvalidKnowledgeProvider(FakeWritingProvider):
    def __init__(self, kind: str):
        self.invalid_kind = kind

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        if self.invalid_kind == "character_card":
            return {
                "text": "这是一张包含非法状态的人物卡草稿。",
                "ready_for_proposal": True,
                "artifact_preview": {
                    "kind": "character_card",
                    "title": "凯伊",
                    "status": "discussion_draft",
                    "content": {
                        "name": "凯伊",
                        "source_type": "custom",
                        "source_refs": ["用户说明"],
                        "trust_status": "trusted",
                    },
                },
            }
        return {
            "text": "这是一张包含非法类别的世界观草稿。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "world_card",
                "title": "旧终端",
                "status": "discussion_draft",
                "content": {
                    "name": "旧终端",
                    "kind": "planet",
                    "summary": "只在午夜后响应。",
                    "source": "用户说明",
                    "source_type": "custom",
                    "confidence_status": "confirmed",
                },
            },
        }


class CanonFactProvider(FakeWritingProvider):
    def __init__(self, *, operation: str, fact_id: str | None = None):
        self.operation = operation
        self.fact_id = fact_id

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        content = {
            "operation": self.operation,
            "text": "温室夜间门禁由值班教师授权后可以临时解除。",
            "source": "Agent 整理的新来源",
            "source_refs": ["本轮作品讨论"],
            "scope": "scene",
        }
        if self.fact_id:
            content["fact_id"] = self.fact_id
        return {
            "text": "我已整理这条作品事实的修改建议。",
            "ready_for_proposal": True,
            "artifact_preview": {
                "kind": "canon_fact",
                "title": "温室夜间门禁",
                "status": "discussion_draft",
                "content": content,
            },
        }


def _propose_canon_fact(service: WritingService, work: dict) -> dict:
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "请整理温室门禁事实。"},
    )
    return service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": "canon_fact",
        },
    )


def test_world_bible_normalizer_preserves_rule_and_entity_extension_fields(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界资料规范化"})
    entity_source = {"filename": "world.md", "paragraph_ids": ["p-1"]}
    rule_source = {"filename": "rules.md", "paragraph_ids": ["p-2"]}

    saved = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            "title": "本作世界观",
            "source_type": "custom",
            "entities": [
                {
                    "id": "world-terminal",
                    "name": "旧终端",
                    "kind": "technology",
                    "summary": "只在午夜后响应。",
                    "source": "用户确认",
                    "source_refs": [entity_source],
                    "confidence_status": "confirmed",
                }
            ],
            "rules": [
                {
                    "id": "world-rule-greenhouse",
                    "name": "温室夜间门禁",
                    "text": "夜间进入温室必须持有生物委员会许可。",
                    "exceptions": ["紧急救援"],
                    "source": "用户确认",
                    "source_refs": [rule_source],
                    "confidence_status": "confirmed",
                }
            ],
        },
    )

    restored = WritingService(tmp_path).get_work(work["id"])
    bible = next(item for item in restored["artifacts"] if item["kind"] == "world_bible")
    content = bible["current_revision"]["content"]
    assert content["entities"][0]["id"] == "world-terminal"
    assert content["entities"][0]["source_refs"] == [entity_source]
    assert content["rules"][0]["id"] == "world-rule-greenhouse"
    assert content["rules"][0]["name"] == "温室夜间门禁"
    assert content["rules"][0]["exceptions"] == ["紧急救援"]
    assert content["rules"][0]["source_refs"] == [rule_source]
    assert bible["current_revision_id"] == saved["revision_id"]


def test_world_rule_update_can_partially_accept_selected_fields(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "世界规则部分采纳"})
    saved = service.save_world_bible(
        work["id"],
        {
            "expected_version": work["version"],
            "title": "本作世界观",
            "source_type": "custom",
            "rules": [
                {
                    "id": "world-rule-greenhouse",
                    "name": "温室夜间门禁",
                    "text": "夜间禁止进入温室。",
                    "exceptions": [],
                    "source": "用户初始设定",
                    "source_refs": ["初始来源"],
                    "confidence_status": "confirmed",
                }
            ],
        },
    )
    service.provider = WorldRuleUpdateProvider()
    thread = saved["work"]["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "只补充温室门禁的紧急救援例外，正文规则先不要改。",
        },
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "world_rule",
        },
    )
    proposal = next(
        item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"]
    )
    assert proposal["candidate"]["operation"] == "update"
    assert proposal["candidate"]["scope_id"] == "world-rule-greenhouse"
    assert proposal["candidate"]["impact_preview"]["decision"]["partial_accept_supported"] is True

    accepted = service.accept_proposal(
        work["id"],
        proposal["id"],
        {
            "expected_version": proposed["work"]["version"],
            "selected_fields": ["exceptions"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        },
    )
    bible = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "world_bible")
    rule = bible["current_revision"]["content"]["rules"][0]
    assert rule["id"] == "world-rule-greenhouse"
    assert rule["name"] == "温室夜间门禁"
    assert rule["text"] == "夜间禁止进入温室。"
    assert rule["source"] == "用户初始设定"
    assert rule["source_refs"] == ["初始来源"]
    assert rule["exceptions"] == ["紧急救援时可由值班教师授权"]
    assert bible["current_revision"]["parent_revision_id"] == saved["revision_id"]
    assert bible["current_revision"]["provenance"]["applied_fields"] == ["exceptions"]
    assert bible["current_revision"]["provenance"]["partial_accept"] is True


def test_work_canon_update_uses_stable_id_supports_partial_accept_and_is_idempotent(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "事实稳定更新"})
    saved = service.save_work_canon(
        work["id"],
        {
            "expected_version": work["version"],
            "facts": [
                {
                    "id": "fact-greenhouse-curfew",
                    "text": "温室夜间禁止进入。",
                    "source": "用户初始设定",
                    "source_refs": [{"filename": "canon.md", "paragraph_ids": ["p-1"]}],
                    "confidence_status": "confirmed",
                    "scope": "work",
                    "status": "active",
                }
            ],
        },
    )
    service.provider = CanonFactProvider(operation="update", fact_id="fact-greenhouse-curfew")
    proposed = _propose_canon_fact(service, saved["work"])
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert_knowledge_contract(proposal["candidate"])
    digest = proposal["candidate"]["impact_preview"]["digest"]
    assert proposal["candidate"]["operation"] == "update"
    assert proposal["candidate"]["scope_id"] == "fact-greenhouse-curfew"
    assert proposal["candidate"]["impact_preview"]["decision"]["partial_accept_supported"] is True

    decision = {
        "expected_version": proposed["work"]["version"],
        "selected_fields": ["text"],
        "expected_impact_digest": digest,
    }
    accepted = service.accept_proposal(work["id"], proposal["id"], decision)
    canon = next(item for item in accepted["work"]["artifacts"] if item["kind"] == "work_canon")
    fact = canon["current_revision"]["content"]["facts"][0]
    assert fact["id"] == "fact-greenhouse-curfew"
    assert fact["text"] == "温室夜间门禁由值班教师授权后可以临时解除。"
    assert fact["source"] == "用户初始设定"
    assert fact["scope"] == "work"
    assert fact["source_refs"] == [{"filename": "canon.md", "paragraph_ids": ["p-1"]}]
    assert canon["current_revision"]["parent_revision_id"] == saved["revision_id"]
    assert canon["current_revision"]["provenance"]["applied_fields"] == ["text"]

    repeated = service.accept_proposal(work["id"], proposal["id"], decision)
    assert repeated["idempotent"] is True
    assert repeated["revision_id"] == accepted["revision_id"]
    with service.repo.connect() as connection:
        artifact_id = connection.execute(
            "SELECT id FROM artifacts WHERE work_id=? AND kind='work_canon'", (work["id"],)
        ).fetchone()["id"]
        assert connection.execute(
            "SELECT COUNT(*) FROM revisions WHERE artifact_id=?", (artifact_id,)
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE target_id=?", (proposal["id"],)
        ).fetchone()[0] == 1

    with pytest.raises(DomainError) as mismatched:
        service.accept_proposal(
            work["id"],
            proposal["id"],
            {**decision, "selected_fields": ["source"]},
        )
    assert mismatched.value.code == "proposal_decision_mismatch"

    restarted = WritingService(tmp_path).get_work(work["id"])
    restored_canon = next(item for item in restarted["artifacts"] if item["kind"] == "work_canon")
    assert restored_canon["current_revision"]["content"]["facts"] == [fact]


def test_work_canon_retire_preserves_identity_without_duplicate_and_survives_restart(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "事实退役"})
    saved = service.save_work_canon(
        work["id"],
        {
            "expected_version": work["version"],
            "facts": [{
                "id": "fact-greenhouse-curfew",
                "text": "温室夜间禁止进入。",
                "source": "用户初始设定",
                "source_refs": ["初始讨论"],
                "confidence_status": "confirmed",
                "scope": "work",
                "status": "active",
            }],
        },
    )
    service.provider = CanonFactProvider(operation="retire", fact_id="fact-greenhouse-curfew")
    proposed = _propose_canon_fact(service, saved["work"])
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["candidate"]["operation"] == "retire"
    assert proposal["candidate"]["impact_preview"]["decision"]["partial_accept_supported"] is False

    accepted = service.accept_proposal(
        work["id"],
        proposal["id"],
        {
            "expected_version": proposed["work"]["version"],
            "expected_impact_digest": proposal["candidate"]["impact_preview"]["digest"],
        },
    )
    restarted = WritingService(tmp_path).get_work(work["id"])
    canon = next(item for item in restarted["artifacts"] if item["kind"] == "work_canon")
    facts = canon["current_revision"]["content"]["facts"]
    assert len(facts) == 1
    assert facts[0]["id"] == accepted["fact_id"] == "fact-greenhouse-curfew"
    assert facts[0]["status"] == "archived"
    assert facts[0]["confidence_status"] == "retired"


def test_knowledge_acceptance_requires_matching_impact_digest(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "影响摘要必填"})
    service.provider = CanonFactProvider(operation="create")
    proposed = _propose_canon_fact(service, work)
    proposal = next(item for item in proposed["work"]["proposals"] if item["id"] == proposed["proposal_id"])

    with pytest.raises(DomainError) as missing:
        service.accept_proposal(
            work["id"], proposal["id"], {"expected_version": proposed["work"]["version"]}
        )
    assert missing.value.code == "proposal_impact_required"
    with pytest.raises(DomainError) as mismatch:
        service.accept_proposal(
            work["id"],
            proposal["id"],
            {"expected_version": proposed["work"]["version"], "expected_impact_digest": "0" * 64},
        )
    assert mismatch.value.code == "proposal_impact_mismatch"
    restored = service.get_work(work["id"])
    assert next(item for item in restored["proposals"] if item["id"] == proposal["id"])["status"] == "pending"


@pytest.mark.parametrize(
    ("kind", "artifact_kind"),
    [("character_card", "character_card"), ("world_card", "world_bible")],
)
def test_invalid_agent_knowledge_is_rejected_before_formal_revision(tmp_path, kind, artifact_kind):
    service = WritingService(tmp_path)
    work = service.create_work({"title": f"{kind} 非法候选"})
    service.provider = InvalidKnowledgeProvider(kind)
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "请整理这条资料。"},
    )
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": discussed["work"]["conversation_threads"][0]["version"],
            "kind": kind,
        },
    )

    with pytest.raises(DomainError) as invalid:
        service.accept_proposal(
            work["id"],
            proposed["proposal_id"],
            {
                "expected_version": proposed["work"]["version"],
                "expected_impact_digest": next(
                    item for item in proposed["work"]["proposals"]
                    if item["id"] == proposed["proposal_id"]
                )["candidate"]["impact_preview"]["digest"],
            },
        )
    assert invalid.value.code == "validation_error"
    restored = service.get_work(work["id"])
    assert not any(item["kind"] == artifact_kind for item in restored["artifacts"])
    proposal = next(item for item in restored["proposals"] if item["id"] == proposed["proposal_id"])
    assert proposal["status"] == "pending"
