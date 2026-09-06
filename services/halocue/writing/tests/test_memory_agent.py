import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


def saved_scene(service: WritingService, *, title: str = "终端亮起"):
    work = service.create_work({"title": "长期记忆纵切"})
    chapter_id = work["chapters"][0]["id"]
    created = service.create_scene(
        work["id"], chapter_id,
        {"expected_version": work["version"], "title": title, "goal": "确认终端会回应口令"},
    )
    saved = service.save_scene_manuscript(
        work["id"], created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "base_revision_id": None,
            "blocks": [
                {"id": "block-action", "type": "action", "speaker": "", "text": "终端在口令后亮起。"},
                {"id": "block-dialogue", "type": "dialogue", "speaker": "爱丽丝", "text": "它真的回应了。"},
            ],
        },
    )
    scene = next(
        item for item in saved["work"]["chapters"][0]["scenes"]
        if item["id"] == created["scene_id"]
    )
    return saved["work"], scene


def accepted_blueprint(service: WritingService):
    work = service.create_work({"title": "记忆上下文", "idea": "两位学生调查夜间亮起的旧终端。"})
    thread = work["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        work["id"], thread["id"],
        {"expected_version": work["version"], "expected_thread_version": thread["version"]},
    )
    accepted = service.accept_proposal(
        work["id"], proposed["proposal_id"], {"expected_version": proposed["work"]["version"]}
    )
    return accepted["work"]


def test_memory_bundle_is_proposal_only_and_partial_acceptance_is_versioned(tmp_path):
    service = WritingService(tmp_path)
    work, scene = saved_scene(service)

    generated = service.generate_memory_proposal(
        work["id"], scene["id"], {"expected_version": work["version"]}
    )

    assert generated["simulation"] is True
    assert generated["work"]["memories"] == []
    proposal = next(item for item in generated["work"]["proposals"] if item["id"] == generated["proposal_id"])
    assert proposal["kind"] == "memory_bundle"
    assert proposal["candidate"]["schema_version"] == "memory-bundle-proposal/1.0"
    assert len(proposal["candidate"]["items"]) == 2
    work_item = next(
        item for run in generated["work"]["runs"] for item in run["work_items"]
        if item["id"] == generated["work_item_id"]
    )
    assert work_item["status"] == "waiting_user"
    assert work_item["attempts"][0]["status"] == "succeeded"

    selected_id = proposal["candidate"]["items"][0]["id"]
    accepted = service.accept_proposal(
        work["id"], proposal["id"],
        {
            "expected_version": generated["work"]["version"],
            "selected_item_ids": [selected_id],
        },
    )
    assert accepted["decision"] == "partially_accepted"
    assert accepted["memory_ids"] == [selected_id]
    memory = accepted["work"]["memories"][0]
    assert memory["id"] == selected_id
    assert memory["confidence_status"] == "confirmed"
    assert memory["version"] == 1
    assert memory["source_revision_id"] == scene["current_revision_id"]
    assert memory["source_refs"][0]["revision_id"] == scene["current_revision_id"]
    artifact = next(
        item for item in accepted["work"]["artifacts"]
        if item["kind"] == "long_term_memory" and item["scope_id"] == selected_id
    )
    assert artifact["current_revision"]["content"]["memory_id"] == selected_id

    restored = WritingService(tmp_path).get_work(work["id"])
    assert restored["memories"][0]["id"] == selected_id
    assert restored["memories"][0]["current_revision_id"] == memory["current_revision_id"]


def test_memory_bundle_is_superseded_when_source_scene_changes(tmp_path):
    service = WritingService(tmp_path)
    work, scene = saved_scene(service)
    generated = service.generate_memory_proposal(
        work["id"], scene["id"], {"expected_version": work["version"]}
    )
    changed = service.save_scene_manuscript(
        work["id"], scene["id"],
        {
            "expected_version": generated["work"]["version"],
            "expected_base_revision_id": scene["current_revision_id"],
            "blocks": [
                {"id": "block-action", "type": "action", "speaker": "", "text": "终端没有亮起。"},
            ],
        },
    )

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work["id"], generated["proposal_id"], {"expected_version": changed["work"]["version"]}
        )
    assert error.value.code == "proposal_not_pending"
    restored = WritingService(tmp_path).get_work(work["id"])
    assert restored["memories"] == []
    proposal = next(item for item in restored["proposals"] if item["id"] == generated["proposal_id"])
    assert proposal["status"] == "superseded"


def test_confirmed_active_memories_enter_next_scene_context_and_archive_is_versioned(tmp_path):
    service = WritingService(tmp_path)
    work = accepted_blueprint(service)
    chapter_id = work["chapters"][0]["id"]
    first = service.create_scene(
        work["id"], chapter_id,
        {"expected_version": work["version"], "title": "确认口令", "goal": "确认终端回应口令"},
    )
    saved = service.save_scene_manuscript(
        work["id"], first["scene_id"],
        {
            "expected_version": first["work"]["version"],
            "base_revision_id": None,
            "blocks": [{"id": "block-1", "type": "action", "speaker": "", "text": "终端在口令后亮起。"}],
        },
    )
    generated = service.generate_memory_proposal(
        work["id"], first["scene_id"], {"expected_version": saved["work"]["version"]}
    )
    accepted = service.accept_proposal(
        work["id"], generated["proposal_id"], {"expected_version": generated["work"]["version"]}
    )
    second = service.create_scene(
        work["id"], chapter_id,
        {"expected_version": accepted["work"]["version"], "title": "追查来源", "goal": "追查口令来源"},
    )

    context = service.assemble_context(work["id"], second["scene_id"])
    assert {item["kind"] for item in context["long_term_memories"]} == {
        "episode_memory", "scene_state_snapshot"
    }
    assert context["scene_writing_pack"]["long_term_memories"]

    memory = next(item for item in second["work"]["memories"] if item["kind"] == "episode_memory")
    archived = service.archive_memory(
        work["id"], memory["id"], {"expected_version": second["work"]["version"]}
    )
    context = service.assemble_context(work["id"], second["scene_id"])
    assert memory["id"] not in {item["id"] for item in context["long_term_memories"]}
    archived_memory = next(item for item in archived["work"]["memories"] if item["id"] == memory["id"])
    assert archived_memory["version"] == 2
    assert archived_memory["lifecycle_status"] == "archived"

    restored = service.restore_memory(
        work["id"], memory["id"], {"expected_version": archived["work"]["version"]}
    )
    restored_memory = next(item for item in restored["work"]["memories"] if item["id"] == memory["id"])
    assert restored_memory["version"] == 3
    assert restored_memory["lifecycle_status"] == "active"
    context = service.assemble_context(work["id"], second["scene_id"])
    assert memory["id"] in {item["id"] for item in context["long_term_memories"]}


def memory_work_item(work: dict) -> dict:
    return next(
        item
        for run in work["runs"]
        for item in run["work_items"]
        if item["type"] == "memory.extract"
    )


def memory_agent_run(work: dict) -> dict:
    return next(
        item
        for item in work["agent_runs"]
        if item["policy"].get("workflow") == "memory.extract"
    )


def test_invalid_provider_bundle_fails_every_runtime_record_without_proposal(tmp_path):
    class InvalidMemoryProvider(FakeWritingProvider):
        kind = "invalid-memory-test"

        def extract_memory_bundle(self, memory_context: dict) -> dict:
            return {"schema_version": "memory-bundle/1.0", "items": []}

    service = WritingService(tmp_path)
    service.provider = InvalidMemoryProvider()
    work, scene = saved_scene(service)

    with pytest.raises(DomainError) as error:
        service.generate_memory_proposal(
            work["id"], scene["id"], {"expected_version": work["version"]}
        )

    assert error.value.code == "provider_output_invalid"
    assert error.value.status == 502
    restored = WritingService(tmp_path).get_work(work["id"])
    assert not [item for item in restored["proposals"] if item["kind"] == "memory_bundle"]
    item = memory_work_item(restored)
    assert item["status"] == "failed"
    assert item["error"]["code"] == "provider_output_invalid"
    assert item["attempts"][0]["status"] == "failed"
    assert item["attempts"][0]["error_code"] == "provider_output_invalid"
    run = next(run for run in restored["runs"] if run["id"] == item["run_id"])
    assert run["status"] == "failed"
    agent_run = memory_agent_run(restored)
    assert agent_run["status"] == "failed"
    assert agent_run["failure"]["code"] == "provider_output_invalid"
    assert all(run["status"] != "running" for run in restored["runs"])


def test_failed_memory_agent_can_retry_from_its_fixed_snapshot(tmp_path):
    class InvalidMemoryProvider(FakeWritingProvider):
        kind = "invalid-memory-retry-test"

        def extract_memory_bundle(self, memory_context: dict) -> dict:
            return {"schema_version": "memory-bundle/1.0", "items": []}

    service = WritingService(tmp_path)
    service.provider = InvalidMemoryProvider()
    work, scene = saved_scene(service)
    with pytest.raises(DomainError):
        service.generate_memory_proposal(
            work["id"], scene["id"], {"expected_version": work["version"]}
        )
    failed = service.get_work(work["id"])
    failed_run = memory_agent_run(failed)
    assert failed_run["failure"]["retryable"] is True

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work["id"], failed_run["id"], {"expected_version": failed["version"]}
    )
    assert retried["retried_from_agent_run_id"] == failed_run["id"]
    assert retried["proposal_id"]
    new_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert new_run["status"] == "waiting_user"
    assert new_run["policy"]["retry_of_agent_run_id"] == failed_run["id"]


def test_memory_extract_fails_when_work_or_scene_changes_during_provider_call(tmp_path):
    service = WritingService(tmp_path)
    work, scene = saved_scene(service)

    class MutatingMemoryProvider(FakeWritingProvider):
        kind = "mutating-memory-test"

        def extract_memory_bundle(self, memory_context: dict) -> dict:
            current = service.get_work(work["id"])
            service.save_scene_manuscript(
                work["id"],
                scene["id"],
                {
                    "expected_version": current["version"],
                    "expected_base_revision_id": scene["current_revision_id"],
                    "blocks": [
                        {
                            "id": "block-changed-during-call",
                            "type": "action",
                            "speaker": "",
                            "text": "模型调用期间，终端熄灭了。",
                        }
                    ],
                },
            )
            return super().extract_memory_bundle(memory_context)

    service.provider = MutatingMemoryProvider()
    with pytest.raises(DomainError) as error:
        service.generate_memory_proposal(
            work["id"], scene["id"], {"expected_version": work["version"]}
        )

    assert error.value.code == "memory_extract_inputs_changed"
    restored = service.get_work(work["id"])
    assert restored["memories"] == []
    assert not [item for item in restored["proposals"] if item["kind"] == "memory_bundle"]
    memory_items = [
        item for run in restored["runs"] for item in run["work_items"]
        if item["type"] == "memory.extract"
    ]
    item = next(item for item in memory_items if item["status"] == "failed")
    assert item["attempts"][0]["status"] == "failed"
    assert item["attempts"][0]["error_code"] == "memory_extract_inputs_changed"
    replacement = next(item for item in memory_items if item["status"] == "ready")
    assert replacement["input_refs"]["scene_revision_id"] != scene["current_revision_id"]
    assert memory_agent_run(restored)["status"] == "failed"
    running_runs = [run for run in restored["runs"] if run["status"] == "running"]
    assert running_runs
    assert all(
        item["status"] == "ready" and item["attempts"] == []
        for run in running_runs for item in run["work_items"]
    )


@pytest.mark.parametrize("operation", ["update", "retire"])
def test_memory_update_and_retire_proposals_reject_stale_base_revision(tmp_path, operation):
    service = WritingService(tmp_path)
    work, scene = saved_scene(service)
    initial = service.generate_memory_proposal(
        work["id"], scene["id"], {"expected_version": work["version"]}
    )
    accepted = service.accept_proposal(
        work["id"], initial["proposal_id"], {"expected_version": initial["work"]["version"]}
    )
    memory = accepted["work"]["memories"][0]

    class ExistingMemoryProvider(FakeWritingProvider):
        kind = f"memory-{operation}-test"

        def extract_memory_bundle(self, memory_context: dict) -> dict:
            return {
                "schema_version": "memory-bundle/1.0",
                "summary": "更新已有记忆。",
                "items": [
                    {
                        "kind": memory["kind"],
                        "operation": operation,
                        "target_memory_id": memory["id"],
                        "title": memory["content"]["title"],
                        "summary": "这条候选建立在旧的记忆修订上。",
                        "details": {},
                        "scope_type": memory["scope_type"],
                        "scope_id": memory["scope_id"],
                        "confidence_status": "open",
                        "source_block_ids": ["block-action"],
                    }
                ],
            }

    service.provider = ExistingMemoryProvider()
    generated = service.generate_memory_proposal(
        work["id"], scene["id"], {"expected_version": accepted["work"]["version"]}
    )
    changed = service.archive_memory(
        work["id"], memory["id"], {"expected_version": generated["work"]["version"]}
    )

    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work["id"], generated["proposal_id"], {"expected_version": changed["work"]["version"]}
        )

    assert error.value.code == "proposal_superseded"
    restored = service.get_work(work["id"])
    proposal = next(item for item in restored["proposals"] if item["id"] == generated["proposal_id"])
    assert proposal["status"] == "superseded"
    candidate_item = proposal["candidate"]["items"][0]
    assert candidate_item["base_revision_id"] == memory["current_revision_id"]
    current = next(item for item in restored["memories"] if item["id"] == memory["id"])
    assert current["current_revision_id"] != candidate_item["base_revision_id"]
    item = memory_work_item(restored)
    assert item["status"] == "cancelled"


def test_rejected_memory_proposal_cancels_waiting_work_item_and_survives_restart(tmp_path):
    service = WritingService(tmp_path)
    work, scene = saved_scene(service)
    generated = service.generate_memory_proposal(
        work["id"], scene["id"], {"expected_version": work["version"]}
    )

    rejected = service.reject_proposal(
        work["id"],
        generated["proposal_id"],
        {"expected_version": generated["work"]["version"], "note": "这次不写入长期记忆。"},
    )
    proposal = next(item for item in rejected["work"]["proposals"] if item["id"] == generated["proposal_id"])
    assert proposal["status"] == "rejected"
    item = memory_work_item(rejected["work"])
    assert item["status"] == "cancelled"
    assert item["acceptance"] == {
        "decision": "rejected",
        "proposal_id": generated["proposal_id"],
    }
    assert rejected["work"]["memories"] == []

    restarted = WritingService(tmp_path).get_work(work["id"])
    proposal = next(item for item in restarted["proposals"] if item["id"] == generated["proposal_id"])
    assert proposal["status"] == "rejected"
    item = memory_work_item(restarted)
    assert item["status"] == "cancelled"
    assert item["attempts"][0]["status"] == "succeeded"
    assert memory_agent_run(restarted)["status"] == "completed"
    assert restarted["memories"] == []


def saved_chapter(service: WritingService):
    work = service.create_work({"title": "章节记忆清扫"})
    chapter_id = work["chapters"][0]["id"]
    scene_ids = []
    for index, text in enumerate(("终端在口令后亮起。", "爱丽丝决定追查口令来源。"), start=1):
        created = service.create_scene(
            work["id"], chapter_id,
            {"expected_version": work["version"], "title": f"场景 {index}", "goal": "推进调查"},
        )
        work = created["work"]
        saved = service.save_scene_manuscript(
            work["id"], created["scene_id"],
            {
                "expected_version": work["version"],
                "expected_base_revision_id": None,
                "blocks": [{
                    "id": f"block-chapter-{index}", "type": "action", "speaker": "", "text": text,
                }],
            },
        )
        work = saved["work"]
        scene_ids.append(created["scene_id"])
    return work, chapter_id, scene_ids


def test_chapter_memory_sweep_is_durable_proposal_only_and_accepts_after_restart(tmp_path):
    service = WritingService(tmp_path)
    work, chapter_id, scene_ids = saved_chapter(service)

    swept = service.sweep_chapter_memory(
        work["id"], chapter_id, {"expected_version": work["version"]}
    )

    assert swept["simulation"] is True
    assert swept["work"]["memories"] == []
    proposal = next(item for item in swept["work"]["proposals"] if item["id"] == swept["proposal_id"])
    assert proposal["kind"] == "memory_bundle"
    assert proposal["scope_type"] == "chapter"
    assert proposal["scope_id"] == chapter_id
    assert proposal["candidate"]["source_chapter_id"] == chapter_id
    assert [item["scene_id"] for item in proposal["candidate"]["source_scene_revisions"]] == scene_ids
    item = next(
        item for run in swept["work"]["runs"] for item in run["work_items"]
        if item["id"] == swept["work_item_id"]
    )
    assert item["type"] == "memory.sweep"
    assert item["status"] == "waiting_user"
    assert item["attempts"][0]["status"] == "succeeded"
    run = next(item for item in swept["work"]["agent_runs"] if item["id"] == swept["agent_run_id"])
    assert run["policy"]["workflow"] == "memory.sweep"

    restarted = WritingService(tmp_path)
    accepted = restarted.accept_proposal(
        work["id"], swept["proposal_id"], {"expected_version": swept["work"]["version"]}
    )
    assert accepted["decision"] == "accepted"
    assert accepted["work"]["memories"][0]["scope_id"] == chapter_id
    assert accepted["work"]["memories"][0]["source_refs"][0]["scene_id"] == scene_ids[-1]


def test_failed_chapter_memory_sweep_retries_only_from_unchanged_fixed_input(tmp_path):
    class InvalidSweepProvider(FakeWritingProvider):
        kind = "invalid-memory-sweep-test"

        def sweep_memory_bundle(self, memory_context: dict) -> dict:
            return {"schema_version": "memory-bundle/1.0", "items": []}

    service = WritingService(tmp_path)
    work, chapter_id, _ = saved_chapter(service)
    service.provider = InvalidSweepProvider()
    with pytest.raises(DomainError) as error:
        service.sweep_chapter_memory(
            work["id"], chapter_id, {"expected_version": work["version"]}
        )
    assert error.value.code == "provider_output_invalid"
    failed = service.get_work(work["id"])
    run = next(item for item in failed["agent_runs"] if item["policy"].get("workflow") == "memory.sweep")
    assert run["status"] == "failed"
    work_item = next(
        item for production in failed["runs"] for item in production["work_items"]
        if item["type"] == "memory.sweep"
    )
    assert work_item["status"] == "failed"
    assert work_item["attempts"][0]["status"] == "failed"

    service.provider = FakeWritingProvider()
    retried = service.retry_agent_run(
        work["id"], run["id"], {"expected_version": failed["version"]}
    )
    assert retried["retried_from_agent_run_id"] == run["id"]
    replacement = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert replacement["policy"]["retry_of_agent_run_id"] == run["id"]
    assert retried["work"]["memories"] == []


def test_chapter_memory_sweep_proposal_is_superseded_when_any_scene_changes(tmp_path):
    service = WritingService(tmp_path)
    work, chapter_id, scene_ids = saved_chapter(service)
    swept = service.sweep_chapter_memory(
        work["id"], chapter_id, {"expected_version": work["version"]}
    )
    target = next(
        scene for scene in swept["work"]["chapters"][0]["scenes"] if scene["id"] == scene_ids[0]
    )
    changed = service.save_scene_manuscript(
        work["id"], scene_ids[0],
        {
            "expected_version": swept["work"]["version"],
            "expected_base_revision_id": target["current_revision_id"],
            "blocks": [{"id": "block-chapter-new", "type": "action", "speaker": "", "text": "终端保持熄灭。"}],
        },
    )
    with pytest.raises(DomainError) as error:
        service.accept_proposal(
            work["id"], swept["proposal_id"], {"expected_version": changed["work"]["version"]}
        )
    assert error.value.code in {"proposal_not_pending", "proposal_superseded"}
    assert service.get_work(work["id"])["memories"] == []
