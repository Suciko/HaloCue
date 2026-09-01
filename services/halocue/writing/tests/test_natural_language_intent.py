import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from halocue_writing.app import make_handler
from halocue_writing.repository import canonical_json, new_id, now
from halocue_writing.service import WritingService


def test_intent_plan_ui_distinguishes_read_only_discussion(tmp_path):
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "target.discussion_only?'查看这一幕':'去写这一幕'" in source
    assert "已完成，可继续讨论" in source
    assert "本轮只讨论，没有修改正式作品。" in source


def test_decision_dock_does_not_repeat_confirmed_waiting_intent():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "const intentNeedsConfirmation=item=>" in source
    assert "item.result?.confirmed===true" in source
    assert "action.id==='user.confirm'&&action.status==='completed'" in source
    assert "state.activeAgentRunId?'确认已记录，Agent 正在继续处理':'确认已记录，等待审查候选'" in source


def test_empty_workspace_intent_creates_unnamed_work_and_scene(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({
        "message": "我想写一个爱丽丝在废弃车站遇到老师的短篇同人故事，先从第一幕开始。",
        "idempotency_key": "intent-empty-1",
    })

    assert result["status"] == "waiting_user"
    assert result["requires_confirmation"] is False
    assert result["work"]["title"] == "未命名作品"
    assert len(result["work"]["volumes"]) == 1
    assert len(result["work"]["chapters"]) == 1
    assert len(result["work"]["chapters"][0]["scenes"]) == 1
    assert result["target"]["scene_id"] == result["work"]["chapters"][0]["scenes"][0]["id"]
    assert result["target"]["scene_title"] == result["work"]["chapters"][0]["scenes"][0]["title"]
    assert "work_canon" in result["read_refs"]
    assert [action["status"] for action in result["actions"]] == ["completed", "completed", "completed"]
    assert result["result"]["run_status"] == "waiting_user"
    service.close()


def test_intent_resolves_third_chapter_without_manual_form(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({
        "message": "继续写第三章，先安排开场场景。",
        "idempotency_key": "intent-third-1",
    })

    assert result["target"]["chapter_title"] == "第三章"
    assert len(result["work"]["chapters"]) == 3
    assert result["work"]["chapters"][2]["scenes"]
    service.close()


def test_high_risk_intent_waits_for_confirmation(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "已有作品"})
    result = service.plan_intent({
        "work_id": work["id"],
        "message": "覆盖正式正文并发布这一章。",
        "idempotency_key": "intent-risk-1",
    })

    assert result["status"] == "awaiting_confirmation"
    assert result["requires_confirmation"] is True
    assert result["actions"][-1]["status"] == "blocked"
    assert "覆盖正式正文" in result["actions"][-1]["label"]
    service.close()


def test_intent_risk_ignores_explicit_chinese_negation(tmp_path):
    service = WritingService(tmp_path)
    risk, requires_confirmation, matched = service._intent_risk("请不要覆盖正式正文，也不要发布，只讨论方向。")

    assert risk == "low"
    assert requires_confirmation is False
    assert matched == []
    service.close()


def test_intent_explicit_read_only_discussion_does_not_select_scene_rewrite(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({
        "message": "只讨论当前第一章第一幕的写作目标，不写入正式正文，不生成候选。",
        "idempotency_key": "intent-discussion-only-1",
    })

    assert result["target"]["discussion_only"] is True
    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["result"]["agent_run_id"])
    assert run["policy"]["task_id"] == "chapter.plan"
    assert not [item for item in result["work"]["proposals"] if item["status"] == "pending"]
    service.close()


def test_intent_reuses_planned_scene_and_resolves_requested_act(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({"message": "先建立第一章第一幕。", "idempotency_key": "intent-planned-base-1"})
    work = result["work"]
    chapter = work["chapters"][0]
    second_id = new_id("scene")
    timestamp = now()
    with service.repo.transaction() as connection:
        connection.execute("UPDATE chapters SET title=?,status='planned' WHERE id=?", ("车站第一章", chapter["id"]))
        connection.execute(
            "INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (second_id, work["id"], chapter["id"], "000002", "第二幕：相遇", "planned", 1, None, canonical_json({"goal": "遇见老师", "location": "站台", "writing_mode": "bond_short", "stop_boundary": "相遇成立后停止"}), timestamp, timestamp),
        )
        connection.execute("UPDATE works SET version=version+1,updated_at=? WHERE id=?", (timestamp, work["id"]))
    result = service.plan_intent({"work_id": work["id"], "message": "开始写第一章第二幕。", "idempotency_key": "intent-planned-act-1"})

    assert result["target"]["chapter_id"] == chapter["id"]
    assert result["target"]["scene_id"] == second_id
    assert len(result["work"]["chapters"]) == 1
    assert len(result["work"]["chapters"][0]["scenes"]) == 2
    service.close()


def test_intent_plan_projection_keeps_target_for_navigation(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({"message": "先从第一幕开始。", "idempotency_key": "intent-target-projection-1"})
    loaded = service.get_work(result["work_id"])
    assert loaded["intent_plans"][0]["target"]["scene_id"] == result["target"]["scene_id"]
    service.close()


def test_intent_target_survives_completed_agent_projection(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({"message": "先从第一幕开始。", "idempotency_key": "intent-target-terminal-1"})
    plan = service.get_intent_plan(result["plan_id"])
    work = service.get_work(result["work_id"])
    run_id = plan["result"]["agent_run_id"]
    projected = service._project_intent_plan_execution(
        plan,
        {
            **work,
            "agent_runs": [
                {**run, "status": "completed"} if run["id"] == run_id else run
                for run in work["agent_runs"]
            ],
        },
    )

    assert projected["status"] in {"completed", "waiting_user"}
    assert projected["result"]["status"] == "completed"
    assert projected["result"]["run_status"] == "completed"
    assert projected["target"]["scene_id"] == result["target"]["scene_id"]
    service.close()


def test_intent_projection_counts_scoped_context_search_as_context_read(tmp_path):
    service = WritingService(tmp_path)
    projected = service._project_intent_plan_execution(
        {
            "status": "running",
            "actions": [
                {"id": "context.read", "status": "planned"},
                {"id": "agent.discuss", "status": "planned"},
            ],
            "result": {"agent_run_id": "agent-scoped-context"},
        },
        {
            "agent_runs": [
                {
                    "id": "agent-scoped-context",
                    "status": "completed",
                    "tool_calls": [
                        {
                            "tool_name": "search_character_cards",
                            "status": "succeeded",
                        }
                    ],
                }
            ]
        },
    )

    assert projected["actions"][0]["status"] == "completed"
    assert projected["actions"][1]["status"] == "completed"
    service.close()


def test_stale_intent_target_offers_structure_recovery_action():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "原场景已不在当前作品结构中，请先检查当前章节结构" in source
    assert 'data-stage-jump="structure">打开章节结构' in source


def test_mobile_scene_missing_input_stays_in_scene_agent_and_can_open_cards():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "button.closest('.scene-workbench, .scene-harness')" in source
    assert "state.writingMobileView='agent'" in source
    assert "button.dataset.agentCompleteCards!==undefined" in source
    assert "state.libraryView='characters'" in source
    assert "state.libraryEditorOpen=true" in source


def test_writing_target_persists_anchor_scene_for_resume(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({
        "message": "第一章叫废弃车站，第一幕叫抵达与等待，第二幕叫广播响起，先开始写第二幕。",
        "idempotency_key": "intent-anchor-resume-1",
    })
    work = service.get_work(result["work_id"])
    chapter = work["chapters"][0]
    scene = chapter["scenes"][1]
    saved = service.set_writing_target(
        result["work_id"],
        {
            "expected_version": work["version"],
            "chapter_id": chapter["id"],
            "anchor_scene_id": scene["id"],
        },
    )
    target = next(item for item in saved["work"]["artifacts"] if item["kind"] == "writing_target")
    assert target["current_revision"]["content"]["chapter_id"] == chapter["id"]
    assert target["current_revision"]["content"]["anchor_scene_id"] == scene["id"]
    service.close()


def test_intent_applies_explicit_chapter_and_act_titles_to_placeholders(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({"message": "第一章叫废弃车站，第一幕叫抵达与等待。", "idempotency_key": "intent-titles-1"})
    chapter = result["work"]["chapters"][0]
    scene = chapter["scenes"][0]

    assert chapter["title"] == "废弃车站"
    assert scene["title"] == "抵达与等待"
    service.close()


def test_intent_builds_all_named_acts_and_targets_explicit_write_act(tmp_path):
    service = WritingService(tmp_path)
    result = service.plan_intent({
        "message": "第一章叫废弃车站，第一幕叫抵达与等待，第二幕叫广播响起。先开始写第二幕。",
        "idempotency_key": "intent-all-act-titles-1",
    })

    scenes = result["work"]["chapters"][0]["scenes"]
    assert [scene["title"] for scene in scenes] == ["抵达与等待", "广播响起"]
    assert result["target"]["scene_id"] == scenes[1]["id"]
    assert result["target"]["scene_title"] == "广播响起"
    service.close()


def test_intent_renames_previous_intent_scene_but_preserves_manual_title(tmp_path):
    service = WritingService(tmp_path)
    first = service.plan_intent({
        "message": "第一章第二幕叫爱丽丝在废弃车站听见异常广播，先开始写第二幕。",
        "idempotency_key": "intent-title-rename-first",
    })
    renamed = service.plan_intent({
        "work_id": first["work_id"],
        "message": "第一章第二幕叫广播响起。",
        "idempotency_key": "intent-title-rename-second",
    })
    scene = renamed["work"]["chapters"][0]["scenes"][1]
    assert scene["title"] == "广播响起"

    contract = scene["contract"]
    manual = service.update_scene_contract(
        first["work_id"],
        scene["id"],
        {
            "expected_version": renamed["work"]["version"],
            "title": "人工保留标题",
            "location": contract.get("location", ""),
            "goal": "保留手工标题的场景目标",
            "stop_boundary": contract.get("stop_boundary") or "必要事实成立后停止",
            "writing_mode": contract.get("writing_mode") or "bond_short",
        },
    )
    final = service.plan_intent({
        "work_id": first["work_id"],
        "message": "第一章第二幕叫再次改名。",
        "idempotency_key": "intent-title-rename-third",
    })
    final_scene = final["work"]["chapters"][0]["scenes"][1]
    assert manual["work"]["version"] == final["work"]["version"] - 1
    assert final_scene["title"] == "人工保留标题"
    service.close()


def test_intent_idempotency_does_not_duplicate_structure(tmp_path):
    service = WritingService(tmp_path)
    payload = {"message": "从第一章开始写夜间车站。", "idempotency_key": "intent-idempotent-1"}
    first = service.plan_intent(payload)
    second = service.plan_intent(payload)

    assert second["existing_work"] is True
    assert second["plan_id"] == first["plan_id"]
    loaded = service.get_work(first["work_id"])
    assert len(loaded["volumes"]) == 1
    assert len(loaded["chapters"]) == 1
    assert len(loaded["chapters"][0]["scenes"]) == 1
    assert len(loaded["intent_plans"]) == 1
    assert loaded["intent_plans"][0]["result"]["run_status"] == "waiting_user"
    service.close()


def test_intent_scene_bridge_starts_scene_agent_only_after_context_is_ready(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "场景桥接测试"})
    structure = service._ensure_intent_structure(work["id"], "从第一幕开始写", 1, [], 1)
    calls = []

    monkeypatch.setattr(
        service,
        "assemble_context",
        lambda work_id, scene_id: {
            "readiness": {"real_ba_writing": "ready_for_provider", "missing_runtime_character_cards": []},
            "skill_runtime": {"missing_files": []},
        },
    )

    def fake_scene_agent(work_id, scene_id, payload):
        calls.append((work_id, scene_id, payload))
        return {"agent_run_id": "agent-scene-bridge", "proposal_id": "proposal-scene-bridge", "simulation": True}

    monkeypatch.setattr(service, "run_scene_agent", fake_scene_agent)
    result = service._auto_execute_intent_scene(
        work["id"],
        {
            "request_source": "intent",
            "text": "开始写第一幕，先让角色在车站碰面。",
            "task_scope": {
                "surface": "scene",
                "scene_id": structure["scene_id"],
                "discussion_only": False,
            },
        },
        expected_provider={"config_digest": "simulation"},
    )

    assert result["status"] == "waiting_user"
    assert result["proposal_id"] == "proposal-scene-bridge"
    assert calls[0][0:2] == (work["id"], structure["scene_id"])
    assert calls[0][2]["discussion_constraints"]["source"] == "natural_language_intent"
    service.close()


def test_intent_scene_does_not_substitute_unrelated_confirmed_characters(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物边界测试"})
    structure = service._ensure_intent_structure(work["id"], "爱丽丝在车站开始写第一幕", 1, [], 1)
    work = service.get_work(work["id"])
    for card_id, name in (("character-hoshino", "星野"), ("character-kai", "凯伊")):
        work = service.save_character_card(
            work["id"],
            {
                "expected_version": work["version"],
                "card_id": card_id,
                "name": name,
                "source_refs": ["用户确认"],
                "voice_anchors": ["保持角色声音"],
                "trust_status": "confirmed",
            },
        )["work"]
    monkeypatch.setattr(
        service,
        "assemble_context",
        lambda *args: (_ for _ in ()).throw(AssertionError("人物不匹配时不得装配 Provider 上下文")),
    )

    result = service._auto_execute_intent_scene(
        work["id"],
        {
            "request_source": "intent",
            "text": "开始写第一幕：爱丽丝在废弃车站听见异常广播。",
            "task_scope": {"surface": "scene", "scene_id": structure["scene_id"], "discussion_only": False},
        },
        expected_provider={"config_digest": "simulation"},
    )

    assert result["status"] == "blocked"
    assert result["code"] == "intent_character_context_missing"
    scene = next(
        scene
        for chapter in result.get("work", {}).get("chapters", [])
        for scene in chapter.get("scenes", [])
        if scene["id"] == structure["scene_id"]
    ) if result.get("work") else None
    assert scene is None or scene["contract"].get("context_selection", {}).get("character_card_ids") != ["character-hoshino", "character-kai"]
    service.close()


def test_intent_scene_matches_only_named_confirmed_card(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "人物匹配测试"})
    structure = service._ensure_intent_structure(work["id"], "爱丽丝在车站开始写第一幕", 1, [], 1)
    work = service.get_work(work["id"])
    for card_id, name in (("character-alice", "爱丽丝"), ("character-hoshino", "星野")):
        work = service.save_character_card(
            work["id"],
            {
                "expected_version": work["version"],
                "card_id": card_id,
                "name": name,
                "source_refs": ["用户确认"],
                "voice_anchors": ["保持角色声音"],
                "trust_status": "confirmed",
            },
        )["work"]
    monkeypatch.setattr(
        service,
        "assemble_context",
        lambda *args: {"readiness": {"real_ba_writing": "ready_for_provider", "missing_runtime_character_cards": []}, "skill_runtime": {"missing_files": []}},
    )
    monkeypatch.setattr(
        service,
        "run_scene_agent",
        lambda *args: {"agent_run_id": "agent-match", "proposal_id": "proposal-match", "simulation": True},
    )

    result = service._auto_execute_intent_scene(
        work["id"],
        {
            "request_source": "intent",
            "text": "开始写第一幕：爱丽丝在废弃车站听见异常广播。",
            "task_scope": {"surface": "scene", "scene_id": structure["scene_id"], "discussion_only": False},
        },
        expected_provider={"config_digest": "simulation"},
    )

    assert result["status"] == "waiting_user"
    refreshed = service.get_work(work["id"])
    scene = next(scene for chapter in refreshed["chapters"] for scene in chapter["scenes"] if scene["id"] == structure["scene_id"])
    selection = scene["contract"]["context_selection"]
    assert selection["source"] == "intent_auto"
    assert selection["character_card_ids"] == ["character-alice"]
    service.close()


def test_intent_projection_exposes_pending_scene_proposal_as_next_decision(tmp_path):
    service = WritingService(tmp_path)
    projected = service._project_intent_plan_execution(
        {
            "status": "completed",
            "target": {"surface": "scene", "scene_id": "scene-bridge", "discussion_only": False},
            "actions": [{"id": "agent.discuss", "status": "planned"}],
            "result": {
                "agent_run_id": "agent-discussion",
                "intent_execution": {"status": "waiting_user", "proposal_id": "proposal-scene"},
            },
        },
        {
            "agent_runs": [
                {"id": "agent-discussion", "status": "completed", "tool_calls": []},
                {"id": "agent-scene", "status": "waiting_user", "proposal_id": "proposal-scene"},
            ],
            "proposals": [
                {"id": "proposal-scene", "kind": "scene_script", "scope_id": "scene-bridge", "status": "pending"}
            ],
        },
    )

    assert projected["status"] == "waiting_user"
    assert projected["result"]["proposal_id"] == "proposal-scene"
    assert projected["result"]["proposal_agent_run_id"] == "agent-scene"
    service.close()


def test_intent_projection_keeps_scene_execution_blocker_visible(tmp_path):
    service = WritingService(tmp_path)
    projected = service._project_intent_plan_execution(
        {
            "status": "blocked",
            "target": {"surface": "scene", "scene_id": "scene-blocked", "discussion_only": False},
            "actions": [{"id": "agent.discuss", "status": "completed"}],
            "result": {
                "agent_run_id": "agent-discussion",
                "intent_execution": {
                    "status": "blocked",
                    "code": "intent_character_context_missing",
                    "message": "本场人物尚未匹配。",
                },
            },
        },
        {
            "agent_runs": [{"id": "agent-discussion", "status": "completed", "tool_calls": []}],
            "proposals": [],
        },
    )

    assert projected["status"] == "blocked"
    assert projected["result"]["status"] == "blocked"
    assert projected["result"]["intent_execution"]["code"] == "intent_character_context_missing"
    service.close()


def test_intent_projection_does_not_claim_another_plans_scene_proposal(tmp_path):
    service = WritingService(tmp_path)
    projected = service._project_intent_plan_execution(
        {
            "status": "completed",
            "target": {"surface": "scene", "scene_id": "scene-shared", "discussion_only": False},
            "actions": [{"id": "agent.discuss", "status": "completed"}],
            "result": {"agent_run_id": "agent-old"},
        },
        {
            "agent_runs": [
                {"id": "agent-old", "status": "completed", "tool_calls": []},
                {"id": "agent-new", "status": "waiting_user", "proposal_id": "proposal-new"},
            ],
            "proposals": [
                {"id": "proposal-new", "kind": "scene_script", "scope_id": "scene-shared", "status": "pending"}
            ],
        },
    )

    assert projected["status"] == "completed"
    assert "proposal_id" not in projected["result"]
    service.close()


def test_blocked_intent_retry_reuses_fixed_message_and_stable_structure(tmp_path, monkeypatch):
    service = WritingService(tmp_path)
    created = service.plan_intent(
        {"message": "第一章第一幕写爱丽丝抵达车站。", "idempotency_key": "intent-retry-fixed-1"}
    )
    plan_id = created["plan_id"]
    work_id = created["work_id"]
    before = service.get_work(work_id)
    target = created["target"]
    with service.repo.transaction() as connection:
        result = dict(created["result"])
        result["intent_execution"] = {
            "status": "blocked",
            "code": "intent_character_context_missing",
            "message": "缺少爱丽丝人物卡。",
        }
        connection.execute(
            "UPDATE intent_plans SET status='blocked',result_json=? WHERE id=?",
            (canonical_json(result), plan_id),
        )

    calls = []

    def resume(work_id_arg, request, expected_provider=None):
        calls.append((work_id_arg, request, expected_provider))
        return {
            "status": "waiting_user",
            "proposal_id": "proposal-recovered",
            "proposal_agent_run_id": "agent-recovered",
            "message": "已生成场景候选。",
        }

    monkeypatch.setattr(service, "_auto_execute_intent_scene", resume)
    retried = service.retry_intent(plan_id, {"expected_version": before["version"]})

    assert retried["status"] == "waiting_user"
    assert retried["result"]["retry"]["fixed_original_message"] is True
    assert retried["result"]["retry"]["stable_target"] == {
        "chapter_id": target["chapter_id"],
        "scene_id": target["scene_id"],
    }
    assert calls[0][0] == work_id
    assert calls[0][1]["text"] == created["original_message"]
    assert calls[0][1]["task_scope"]["scene_id"] == target["scene_id"]
    after = service.get_work(work_id)
    assert [chapter["id"] for chapter in after["chapters"]] == [chapter["id"] for chapter in before["chapters"]]
    assert [scene["id"] for chapter in after["chapters"] for scene in chapter["scenes"]] == [
        scene["id"] for chapter in before["chapters"] for scene in chapter["scenes"]
    ]
    service.close()


def test_http_intent_route_returns_a_persisted_plan(tmp_path):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/intent",
            data=json.dumps({"message": "先从第一章开始写。", "idempotency_key": "http-intent-1"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 202
        assert payload["data"]["plan_id"].startswith("intent-")
        assert payload["data"]["work"]["title"] == "未命名作品"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()


def test_http_blocked_intent_retry_route_uses_current_work_version(tmp_path, monkeypatch):
    service = WritingService(tmp_path / "data")
    static = Path(__file__).resolve().parents[1] / "web"
    called = []

    def retry(plan_id, payload):
        called.append((plan_id, payload))
        return {"id": plan_id, "status": "blocked", "work": {"id": "work-http"}}

    monkeypatch.setattr(service, "retry_intent", retry)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/intent-plans/intent-http:retry",
            data=json.dumps({"expected_version": 7}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 202
        assert payload["data"]["status"] == "blocked"
        assert called == [("intent-http", {"expected_version": 7})]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()


def test_http_intent_confirmation_route_continues_fixed_high_risk_plan(tmp_path):
    service = WritingService(tmp_path / "data")
    work = service.create_work({"title": "确认路由测试"})
    plan = service.plan_intent({
        "work_id": work["id"],
        "message": "覆盖正式正文并发布这一章。",
        "idempotency_key": "http-intent-confirm-1",
    })
    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/intent-plans/{plan['plan_id']}:confirm",
            data=json.dumps({"confirmed": True}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 202
        assert payload["data"]["status"] in {"running", "waiting_user", "completed"}
        assert payload["data"]["status"] != "awaiting_confirmation"
        assert payload["data"]["result"]["confirmed"] is True
        assert payload["data"]["result"]["agent_run_id"].startswith("agent-")
        confirmation = next(action for action in payload["data"]["actions"] if action["id"] == "user.confirm")
        assert confirmation["status"] == "completed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        service.close()


def test_empty_workspace_composer_binds_its_live_form_controls():
    web = Path(__file__).resolve().parents[1] / "web"
    source = (web / "app.js").read_text(encoding="utf-8")

    assert "function bindIntentComposer(root)" in source
    assert "form.dataset.intentBound='true'" in source
    assert "showIntentClarifyPreview(form)" in source
    assert "void submitIntent(form)" in source
    assert "bindIntentComposer(el)" in source
    assert "data-intent-open-scene" in source
    assert "function openIntentTarget(button)" in source
    assert "waiting_user:'已交给创作导演'" in source
    assert "blocked:'需要补齐写作输入'" in source
    assert "visibleStatuses.has(item.status)" in source
    assert "intent-plan-card ${plan.status}" in source
    assert "function persistWritingTarget(chapterId,anchorSceneId=null)" in source
    assert "anchor_scene_id:normalizedAnchor" in source
    assert "目标已变化" in source
    assert "标题已变化，仍按稳定场景 ID 定位" in source
    assert "intent-plan-history" in source
    assert "const primary=plans[0]" in source
    assert "较早的待处理决定" in source
    assert "pendingOlder=plans.slice(1).filter" in source
    assert "historical?'查看原目标'" in source
    assert "plan.result?.intent_execution" in source
    assert "data-retry-intent" in source
    assert "/intent-plans/${retryIntent.dataset.retryIntent}:retry" in source


def test_empty_workspace_clarification_controls_use_capture_level_handler():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    branch = source.split("// The empty-work composer is the first action", 1)[1].split("// Handle the inline first-use controls", 1)[0]
    assert "window.addEventListener('click'" in branch
    assert "[data-intent-clarify]" in branch
    assert "[data-intent-use-optimized],[data-intent-use-original]" in branch
    assert "event.stopImmediatePropagation()" in branch
    assert "showIntentClarifyPreview(form)" in branch
    assert "useIntentExpression(form,choice)" in branch


def test_empty_workspace_primary_submit_uses_capture_level_handler():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    branch = source.split("// The legacy delegated click graph predates", 1)[1].split("// Handle the inline first-use controls", 1)[0]
    assert "window.addEventListener('click'" in branch
    assert "[data-intent-submit]" in branch
    assert "event.stopImmediatePropagation()" in branch
    assert "void submitIntent(" in branch


def test_empty_workspace_hides_manual_workflow_entries_and_disables_flow_navigation():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    chrome = source.split("function renderChrome(){", 1)[1].split("function stageLabel", 1)[0]
    assert "const workSurfaceNote=$('.work-surface-note')" in chrome
    assert "workSurfaceNote.hidden=!work" in chrome
    assert "const stageList=$('#stageList')" in chrome
    assert "stageList.hidden=!work" in chrome
    assert "if(note)note.hidden=!state.work||active" in source

    navigation = source.split("function syncFlowNavigation(){", 1)[1].split("const renderBeforeFlowNavigation", 1)[0]
    assert "if(!state.work)" in navigation
    assert "button.disabled=true" in navigation
    assert "button.title='建立作品后可用'" in navigation
    assert "if(!state.work)requestAnimationFrame(()=>requestAnimationFrame(()=>{$('#intentMessage')?.focus();startOnboardingTour()}))" in source


def test_intent_target_uses_dedicated_navigation_without_generic_scene_capture():
    web = Path(__file__).resolve().parents[1] / "web"
    source = (web / "app.js").read_text(encoding="utf-8")

    assert "data-intent-open-scene" in source
    target_markup = source.split("const targetMarkup=(plan,historical=false)=>{", 1)[1].split("};", 1)[0]
    assert 'data-scene="${esc(target.scene_id)}"' not in target_markup
    assert 'data-intent-target-href="${href}"' in target_markup
    assert "function openIntentTarget(button)" in source
    assert "history.pushState({halocue:true},'',targetUrl)" in source
    assert "persistWritingTarget(chapter.id,scene.id)" in source


def test_deep_link_route_canonicalizes_scene_identity_and_exposes_stale_target():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    assert "const requestedScene = sceneId && scenes().find(scene => scene.id === sceneId);" in source
    assert "state.writingChapterId = requestedScene.chapter_id;" in source
    assert "routeTarget = { chapterId: requestedScene.chapter_id, sceneId: requestedScene.id };" in source
    assert "await persistWritingTarget(routeTarget.chapterId, routeTarget.sceneId);" in source
    assert "state._routeWarning = '目标场景已变化，已回到当前章节中可用的位置。';" in source
    assert "if (state._routeWarning) toast(state._routeWarning, true);" in source


def test_manual_chapter_selection_persists_the_new_scene_anchor_before_rendering():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    branch = source.split("const chapter = event.target.closest('[data-writing-chapter]');", 1)[1].split("const mobileView", 1)[0]
    assert "(nextChapter?.scenes || []).some(scene => scene.id === state.sceneId)" in branch
    assert "nextChapter?.scenes?.[0]?.id || null" in branch
    assert "persistWritingTarget(chapterId, nextScene)" in branch
    assert "state.sceneId = nextScene;" in branch
    assert "state.stage = 'structure';" in branch
    assert "render();" in branch


def test_manual_scene_navigation_saves_the_durable_target_before_rendering():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    branch = source.split("async function openScene(sceneId, control = null)", 1)[1].split("function moveInspectorToMobilePane", 1)[0]
    save = branch.index("await persistWritingTarget(chapter.id, scene.id);")
    update = branch.index("state.sceneId = scene.id;")
    render = branch.index("render();")
    assert save < update < render
    assert "场景没有切换：恢复位置保存失败" in branch


def test_compact_chapter_scene_rows_expose_an_explicit_writing_action():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    structure = source.split("function renderCompactStructureWorkspace()", 1)[1].split("function decorateWritingInspector", 1)[0]
    assert 'class="scene-writing-action"' in structure
    assert "scene.current_revision_id ? '查看正文' : '去写本场'" in structure
    assert 'data-scene-open="${esc(scene.id)}"' in structure


def test_scene_readiness_primary_action_opens_character_card_recovery_directly():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    workspace = source.split("function decorateWritingWorkspace()", 1)[1].split("decorateSceneAgent();", 1)[0]
    assert "const nextAction = writingReady" in workspace
    assert "readiness.needsCharacterCard" in workspace
    assert "data-agent-complete-cards>补齐人物卡" in workspace
    assert "data-inspector=\"agent\">查看缺少的输入" in workspace


def test_scene_next_action_follows_proposal_revision_review_release_order():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    workspace = source.split("function decorateWritingWorkspace()", 1)[1].split("decorateSceneAgent();", 1)[0]
    proposal_branch = workspace.split("if (proposal) {", 1)[1].split("} else if (hasCurrentRevision", 1)[0]
    assert "查看候选与 Diff" in proposal_branch
    assert "检查本场" not in proposal_branch
    assert "正文已采纳，先检查本场" in workspace
    assert "新的正式 Revision 已建立" in workspace
    assert 'data-action="review-scene">检查本场' in workspace
    assert "本场检查有" in workspace
    assert "data-focus-scene-review>查看审查结果" in workspace
    assert "本场检查已完成" in workspace
    assert "data-scene-open" in workspace
    assert 'data-stage="release">进入检查与发布' in workspace


def test_scene_review_focus_targets_current_review_surface_and_recheck_after_resolution():
    source = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.js").read_text(encoding="utf-8")

    assert "'.scene-review-summary, .review-findings'" in source
    workspace = source.split("function decorateWritingWorkspace()", 1)[1].split("decorateSceneAgent();", 1)[0]
    blocked_branch = workspace.split("} else if (hasCurrentRevision && review.gate?.status === 'blocked')", 1)[1]
    assert "review.blockers.length" in blocked_branch
    assert "阻塞项已处理，需重新检查" in workspace
    assert 'data-action="review-scene">重新检查本场' in workspace


def test_review_finding_resolution_uses_an_in_app_dialog_instead_of_native_prompt():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    styles = (Path(__file__).resolve().parents[1] / "web" / "shell.css").read_text(encoding="utf-8")

    assert "function openFindingResolutionDialog(findingId)" in source
    assert "findingResolveDialog" in source
    assert "data-finding-resolve-form" in source
    assert "openFindingResolutionDialog(button.dataset.resolveFinding)" in source
    assert "prompt('请说明为什么处理这条审查发现" not in source
    assert ".finding-resolve-dialog" in styles


def test_revision_fixture_server_isolated_and_fake_only():
    source = (Path(__file__).resolve().parents[1] / "tests" / "in_app_browser_revision_fixture_server.py").read_text(encoding="utf-8")

    assert "TemporaryDirectory" in source
    assert '"provider": "fake / local-rules"' in source
    assert "make_handler" in source
    assert "accept_proposal" in source


def test_blocked_review_fixture_keeps_open_finding_for_browser_acceptance():
    source = (Path(__file__).resolve().parents[1] / "tests" / "in_app_browser_blocked_review_fixture_server.py").read_text(encoding="utf-8")

    assert "TemporaryDirectory" in source
    assert "service.review_scene" in source
    assert 'item["severity"] == "blocking"' in source
    assert '"provider": "fake / local-rules"' in source


def test_scene_character_card_recovery_keeps_its_prefill_through_library_draft_rendering():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "state.characterCardDraft={name:state.prefillCharacter}" in source
    assert "form.elements.name.value=draft.name||'';" in source


def test_writing_target_save_retries_a_single_revision_conflict_from_fresh_work():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    branch = source.split("async function persistWritingTarget(chapterId,anchorSceneId=null)", 1)[1].split("function writingChapter()", 1)[0]
    assert "if(error.code!=='revision_conflict'||state.work?.id!==workId)throw error;" in branch
    assert "const refreshed=await api(`/works/${workId}`);" in branch
    assert branch.count("result=await save();") == 2


def test_mobile_scene_agent_keeps_history_scrollable_and_composer_in_view():
    css = (Path(__file__).resolve().parents[1] / "web" / "writing-workbench.css").read_text(encoding="utf-8")

    assert ".writing-mobile-pane {" in css
    assert "height: calc(100dvh - 340px);" not in css
    assert css.count("\n    height: calc(100dvh - 330px) !important;") == 1
    assert ".writing-mobile-pane .scene-conversation-scroll" in css
    assert "flex: 1 1 auto;" in css
    assert ".writing-mobile-pane .scene-agent-panel.scene-harness" in css
    assert "Scene Agent uses the page as its mobile scroll owner." not in css
    assert ".writing-mobile-pane {\n    height: auto;" not in css
    assert ".writing-mobile-pane .scene-agent-panel.scene-harness {\n    height: auto;" not in css
    assert ".writing-mobile-pane .scene-conversation-scroll {\n    flex: 0 0 auto;" not in css
    assert ".writing-workbench-stage .writing-mobile-pane[hidden]" in css
    assert "overflow-y: auto !important;" in css


def test_scene_character_recovery_keeps_a_stable_return_anchor_without_auto_writing():
    source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "function captureSceneRecovery(scene=selectedScene())" in source
    assert "sessionStorage.setItem(sceneRecoveryStorageKey(target.work_id),JSON.stringify(target))" in source
    assert "data-return-recovery-scene" in source
    assert "await persistWritingTarget(chapter.id,scene.id);" in source
    assert "stage=draft&chapter_id=" in source
    assert "不会自动运行 Agent" in source
    assert "function sceneRecoveryCharacterName(scene=selectedScene())" in source
    assert "if(unique.length===1)return unique[0];" in source
    assert "const inferred=String(scene?.title||'').trim().match" in source
    assert "return inferred||'';" in source
    assert "function focusCharacterCardName()" in source
    assert "requestAnimationFrame(()=>requestAnimationFrame" in source
    assert source.count("focusCharacterCardName();") >= 3
