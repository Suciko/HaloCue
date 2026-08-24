from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.service import WritingService


def _service(tmp_path: Path) -> WritingService:
    service = WritingService(tmp_path / "data")
    service.start()
    return service


def _thread(work: dict) -> dict:
    return next(item for item in work["conversation_threads"] if item["scope_type"] == "work")


def _assert_json_schema_instance(instance, schema: dict, *, root: dict | None = None, path: str = "$") -> None:
    """Validate the JSON Schema features used by this versioned contract."""
    root = root or schema
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        _assert_json_schema_instance(instance, target, root=root, path=path)
        return

    if "const" in schema:
        assert instance == schema["const"], f"{path}: expected const {schema['const']!r}"
    if "enum" in schema:
        assert instance in schema["enum"], f"{path}: {instance!r} is not in the contract enum"

    expected_types = schema.get("type")
    if expected_types:
        expected_types = [expected_types] if isinstance(expected_types, str) else expected_types
        matches = {
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "null": lambda value: value is None,
        }
        assert any(matches[item](instance) for item in expected_types), (
            f"{path}: expected JSON type {expected_types}, got {type(instance).__name__}"
        )

    if isinstance(instance, dict):
        required = schema.get("required", [])
        missing = [key for key in required if key not in instance]
        assert not missing, f"{path}: missing required properties {missing}"
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                _assert_json_schema_instance(value, properties[key], root=root, path=f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise AssertionError(f"{path}: unexpected property {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                _assert_json_schema_instance(
                    value, schema["additionalProperties"], root=root, path=f"{path}.{key}"
                )
    elif isinstance(instance, list) and "items" in schema:
        for index, value in enumerate(instance):
            _assert_json_schema_instance(value, schema["items"], root=root, path=f"{path}[{index}]")
    elif isinstance(instance, str) and "pattern" in schema:
        assert re.search(schema["pattern"], instance), f"{path}: value does not match {schema['pattern']!r}"


def test_agent_presentation_is_stable_read_only_projection(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "表现层合同", "idea": "夜里的机器开始回应。"})
    thread = _thread(work)
    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)

    assert view["schema_version"] == "agent-presentation/1.0"
    assert view["work"]["id"] == work["id"]
    assert view["thread"]["id"] == thread["id"]
    assert view["guidance"]["source_schema_version"] == "writing-harness-status/1.0"
    assert view["guidance"]["work_version"] == view["snapshot"]["work_version"]
    assert view["guidance"]["primary_action"]["id"] == "brief.build"
    assert view["guidance"]["blockers"] == []
    assert view["integrity"]["presentation_digest"]
    assert all("input_snapshot_uri" not in json.dumps(event, ensure_ascii=False) for event in view["events"])
    assert all("policy_json" not in json.dumps(event, ensure_ascii=False) for event in view["events"])
    assert any(event["event_type"] == "message.user" for event in view["events"])


def test_initial_work_thread_guidance_uses_brief_build_workflow(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "初始引导", "idea": "从一句尚未整理的想法开始。"})
    thread = _thread(work)

    guidance = service.get_agent_presentation(work["id"], thread["id"], limit=200)["guidance"]

    assert guidance["primary_action"]["id"] == "brief.build"
    assert guidance["primary_action"]["enabled"] is True


def test_current_thread_pending_proposal_becomes_primary_guidance_action(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "待审建议", "idea": "旧终端在深夜叫出了爱丽丝的名字。"})
    thread = _thread(work)
    proposed = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {
            "expected_version": work["version"],
            "expected_thread_version": thread["version"],
        },
    )

    guidance = service.get_agent_presentation(work["id"], thread["id"], limit=200)["guidance"]

    assert guidance["primary_action"]["id"] == "proposal.apply"
    assert guidance["primary_action"]["target_id"] == proposed["proposal_id"]


def test_guidance_does_not_leak_proposal_or_run_actions_between_work_threads(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "引导隔离", "idea": "主对话保留原始方向。"})
    first_thread = _thread(work)
    created = service.create_conversation_thread(
        work["id"],
        {"expected_version": work["version"], "title": "备选方向"},
    )
    second_thread = next(
        item for item in created["work"]["conversation_threads"]
        if item["id"] != first_thread["id"]
    )
    discussed = service.post_conversation_message(
        work["id"],
        second_thread["id"],
        {
            "expected_thread_version": second_thread["version"],
            "text": "这条备选方向只属于第二个对话。",
        },
    )
    second_thread = next(
        item for item in discussed["work"]["conversation_threads"]
        if item["id"] == second_thread["id"]
    )
    proposed = service.organize_conversation_proposal(
        work["id"],
        second_thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": second_thread["version"],
        },
    )

    first_guidance = service.get_agent_presentation(work["id"], first_thread["id"], limit=200)["guidance"]
    second_guidance = service.get_agent_presentation(work["id"], second_thread["id"], limit=200)["guidance"]

    assert first_guidance["primary_action"]["id"] == "brief.build"
    assert proposed["proposal_id"] not in json.dumps(first_guidance, ensure_ascii=False)
    assert second_guidance["primary_action"]["id"] == "proposal.apply"
    assert second_guidance["primary_action"]["target_id"] == proposed["proposal_id"]

    rejected = service.reject_proposal(
        work["id"],
        proposed["proposal_id"],
        {"expected_version": proposed["work"]["version"], "note": "仅用于隔离测试"},
    )
    input_uri, input_digest = service.repo.atomic_write_text(
        "agent-inputs/thread-guidance-isolation.json",
        json.dumps({"instruction": "只恢复第二个对话"}, ensure_ascii=False),
    )
    run_id = "agent-run-second-thread"
    timestamp = "2099-01-01T00:00:00+00:00"
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                work["id"],
                "work",
                work["id"],
                "只恢复第二个对话",
                "failed",
                json.dumps({"thread_id": second_thread["id"]}, ensure_ascii=False),
                input_uri,
                input_digest,
                None,
                json.dumps({"code": "provider_unavailable", "message": "暂时不可用"}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )

    first_after_failure = service.get_agent_presentation(work["id"], first_thread["id"], limit=200)["guidance"]
    second_after_failure = service.get_agent_presentation(work["id"], second_thread["id"], limit=200)["guidance"]

    assert first_after_failure["primary_action"]["id"] == "brief.build"
    assert run_id not in json.dumps(first_after_failure, ensure_ascii=False)
    assert second_after_failure["primary_action"]["id"] == "agent.retry"
    assert second_after_failure["primary_action"]["target_id"] == run_id
    assert rejected["work"]["id"] == work["id"]


def test_actual_agent_presentation_response_validates_against_versioned_schema(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "Schema 实例", "idea": "验证真实投影，而不是手写样例。"})
    thread = _thread(work)
    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    schema = json.loads(
        Path(__file__).parents[1]
        .joinpath("docs/contracts/agent-presentation-1.0.schema.json")
        .read_text(encoding="utf-8")
    )

    _assert_json_schema_instance(view, schema)


def test_agent_presentation_cursor_pages_fixed_snapshot(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "游标合同", "idea": "先说一句。"})
    thread = _thread(work)
    first = service.get_agent_presentation(work["id"], thread["id"], limit=1)
    assert first["cursor"]["has_more"] is True
    second = service.get_agent_presentation(work["id"], thread["id"], limit=1, cursor=first["cursor"]["next"])
    assert second["events"][0]["event_id"] != first["events"][0]["event_id"]


def test_agent_presentation_rejects_stale_cursor(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "过期游标", "idea": "先说一句。"})
    thread = _thread(work)
    first = service.get_agent_presentation(work["id"], thread["id"], limit=1)
    service.post_conversation_message(work["id"], thread["id"], {"expected_thread_version": thread["version"], "text": "追加约束。"})
    with pytest.raises(DomainError) as exc:
        service.get_agent_presentation(work["id"], thread["id"], limit=1, cursor=first["cursor"]["next"])
    assert exc.value.code == "agent_presentation_cursor_stale"


def test_agent_presentation_keeps_work_item_and_attempt_source_status(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "任务状态", "idea": "先说一句。"})
    thread = _thread(work)
    timestamp = "2026-08-17T00:00:00+00:00"
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO production_runs VALUES (?,?,?,?,?,?,?,?)",
            ("run-presentation", work["id"], "writing", "review", "planned", "[]", timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "item-presentation", "run-presentation", "scene.review", "work", work["id"],
                "ready", "[]", "[]", json.dumps({"thread_id": thread["id"]}),
                1, None, timestamp, timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO job_attempts VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("attempt-presentation", "item-presentation", 1, "fake", "digest", "succeeded", "result", None, timestamp, timestamp),
        )
    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    item = next(event for event in view["events"] if event["event_id"] == "work-item:item-presentation:created")
    attempt = next(event for event in view["events"] if event["event_id"] == "attempt:attempt-presentation:started")
    assert item["state"] == "queued"
    assert item["source_status"] == "ready"
    assert attempt["source_status"] == "succeeded"


def test_agent_presentation_does_not_leak_runs_between_threads_with_same_scope(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "对话隔离", "idea": "先讨论第一条线。"})
    first_thread = _thread(work)
    created = service.create_conversation_thread(
        work["id"],
        {"expected_version": work["version"], "title": "第二条线"},
    )
    second_thread = next(
        item for item in created["work"]["conversation_threads"]
        if item["id"] != first_thread["id"]
    )
    second_turn = service.post_conversation_message(
        work["id"],
        second_thread["id"],
        {"expected_thread_version": second_thread["version"], "text": "这条消息只属于第二个对话。"},
    )
    timestamp = "2026-08-17T00:00:00+00:00"
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO production_runs VALUES (?,?,?,?,?,?,?,?)",
            ("run-second-thread", work["id"], "writing", "review", "planned", "[]", timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO work_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "item-second-thread", "run-second-thread", "conversation.followup", "work", work["id"],
                "ready", "[]", "[]", json.dumps({"agent_run_id": second_turn["agent_run_id"]}),
                0, None, timestamp, timestamp,
            ),
        )

    first_view = service.get_agent_presentation(work["id"], first_thread["id"], limit=200)
    leaked = [
        event for event in first_view["events"]
        if event.get("refs", {}).get("agent_run_id") == second_turn["agent_run_id"]
    ]

    assert leaked == []
    assert not any(
        event.get("refs", {}).get("work_item_id") == "item-second-thread"
        for event in first_view["events"]
    )


def test_agent_presentation_exposes_pinned_provider_runtime(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "Provider 身份", "idea": "确认本轮运行身份。"})
    thread = _thread(work)

    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)

    assert view["snapshot"]["provider_runtime"]["provider"] == "fake"
    assert view["snapshot"]["provider_runtime"]["is_simulation"] is True
    run = next(event for event in view["events"] if event["event_type"] == "run.started")
    assert run["details"]["provider_runtime"]["provider"] == "fake"


def test_failed_run_only_offers_recovery_when_fixed_input_is_intact(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "恢复卡", "idea": ""})
    thread = _thread(work)
    uri, digest = service.repo.atomic_write_text("agent-inputs/recovery.json", '{"instruction":"继续讨论"}')
    timestamp = "2026-08-17T00:00:00+00:00"
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "agent-recovery", work["id"], "work", work["id"], "继续讨论", "failed",
                json.dumps({"thread_id": thread["id"], "mode": "review"}, ensure_ascii=False),
                uri, digest, None, json.dumps({
                    "code": "writing_provider_failed",
                    "message": "模型暂时不可用",
                    "status": 504,
                    "retryable": True,
                    "failure_kind": "provider_timeout",
                }, ensure_ascii=False),
                timestamp, timestamp,
            ),
        )
    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    recovery = next(event for event in view["events"] if event["event_type"] == "recovery.available")
    failed = next(event for event in view["events"] if event["event_type"] == "run.failed")
    assert failed["details"]["failure"] == {
        "code": "writing_provider_failed",
        "message": "模型暂时不可用",
        "status": 504,
        "retryable": True,
        "failure_kind": "provider_timeout",
    }
    assert recovery["refs"]["agent_run_id"] == "agent-recovery"
    assert recovery["details"]["action"] == "agent.retry"
    assert view["integrity"]["complete"] is True

    service.repo.atomic_write_text("agent-inputs/recovery.json", '{"instruction":"tampered"}')
    damaged = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    assert not any(event["event_type"] == "recovery.available" for event in damaged["events"])
    assert damaged["integrity"]["complete"] is False

    (service.repo.data_dir / uri).unlink()
    missing = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    assert not any(event["event_type"] == "recovery.available" for event in missing["events"])
    assert any(
        issue["code"] == "agent_input_integrity_failed"
        for issue in missing["integrity"]["issues"]
    )


def test_recovery_event_is_removed_after_a_non_failed_retry(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "恢复完成", "idea": "确认重试后状态。"})
    thread = _thread(work)
    uri, digest = service.repo.atomic_write_text("agent-inputs/retried.json", '{"instruction":"继续讨论"}')
    timestamp = "2026-08-17T00:00:00+00:00"
    with service.repo.transaction() as connection:
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "agent-recovery-original", work["id"], "work", work["id"], "继续讨论", "failed",
                json.dumps({"thread_id": thread["id"], "mode": "review"}, ensure_ascii=False),
                uri, digest, None, json.dumps({"code": "provider_unavailable", "message": "模型暂时不可用"}, ensure_ascii=False),
                timestamp, timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "agent-recovery-retry", work["id"], "work", work["id"], "继续讨论", "waiting_user",
                json.dumps({"thread_id": thread["id"], "mode": "review", "retry_of": "agent-recovery-original"}, ensure_ascii=False),
                uri, digest, None, None, timestamp, timestamp,
            ),
        )

    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    assert not any(event["event_type"] == "recovery.available" for event in view["events"])


def test_agent_presentation_degrades_when_proposal_candidate_is_missing(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "候选缺失", "idea": "整理一个故事方向。"})
    thread = _thread(work)
    proposed = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {
            "expected_version": work["version"],
            "expected_thread_version": thread["version"],
        },
    )
    proposal = next(
        item for item in proposed["work"]["proposals"]
        if item["id"] == proposed["proposal_id"]
    )
    (service.repo.data_dir / proposal["candidate_uri"]).unlink()

    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    event = next(
        item for item in view["events"]
        if item["event_id"] == f"proposal:{proposal['id']}:created"
    )

    assert event["details"]["candidate_integrity"]["valid"] is False
    assert view["integrity"]["complete"] is False
    assert any(
        issue["code"] == "proposal_candidate_integrity_failed"
        for issue in view["integrity"]["issues"]
    )


def test_agent_presentation_contract_file_has_expected_version():
    schema = json.loads(Path(__file__).parents[1].joinpath("docs/contracts/agent-presentation-1.0.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == "agent-presentation/1.0"
    assert "events" in schema["required"]
    assert "guidance" in schema["required"]
    assert "card" in schema["$defs"]
    event_types = schema["$defs"]["event"]["properties"]["event_type"]["enum"]
    assert {"artifact.presented", "proposal.presented", "recovery.available"}.issubset(event_types)


def test_agent_presentation_guidance_does_not_leak_another_work_thread_proposal(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "主操作隔离", "idea": "先讨论第一条线。"})
    first_thread = _thread(work)
    created = service.create_conversation_thread(
        work["id"],
        {"expected_version": work["version"], "title": "第二条线"},
    )
    second_thread = next(
        item for item in created["work"]["conversation_threads"]
        if item["id"] != first_thread["id"]
    )
    discussed = service.post_conversation_message(
        work["id"], second_thread["id"],
        {
            "expected_thread_version": second_thread["version"],
            "text": "第二条线只讨论温室夜间的异常广播。",
        },
    )
    second_thread = next(
        item for item in discussed["work"]["conversation_threads"]
        if item["id"] == second_thread["id"]
    )
    proposed = service.organize_conversation_proposal(
        work["id"], second_thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": second_thread["version"],
        },
    )

    first_view = service.get_agent_presentation(work["id"], first_thread["id"], limit=200)
    second_view = service.get_agent_presentation(work["id"], second_thread["id"], limit=200)

    assert first_view["guidance"]["primary_action"].get("target_id") != proposed["proposal_id"]
    assert second_view["guidance"]["primary_action"] == {
        "id": "proposal.apply",
        "label": "审阅并应用修改",
        "enabled": True,
        "target_id": proposed["proposal_id"],
    }


def test_direction_proposal_is_projected_as_a_bounded_card(tmp_path):
    service = _service(tmp_path)
    work = service.create_work({"title": "方向卡合同", "idea": "深夜旧广播叫出了不该存在的名字。"})
    thread = _thread(work)
    proposed = service.organize_conversation_proposal(
        work["id"], thread["id"],
        {"expected_version": work["version"], "expected_thread_version": thread["version"]},
    )
    view = service.get_agent_presentation(work["id"], thread["id"], limit=200)
    event = next(item for item in view["events"] if item["event_type"] == "proposal.presented")
    card = event["details"]["card"]

    assert card["schema_version"] == "agent-card/1.0"
    assert card["component"] == "DirectionProposalCard"
    assert card["decision"]["proposal_id"] == proposed["proposal_id"]
    assert card["decision"]["expected_work_version"] == proposed["work"]["version"]
    assert card["decision"]["can_apply"] is True
    serialized = json.dumps(view, ensure_ascii=False)
    assert "candidate_uri" not in serialized
    assert "artifact_preview" not in serialized
