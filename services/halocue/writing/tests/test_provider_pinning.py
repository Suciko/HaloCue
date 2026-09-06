import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


USAGE_A = {
    "input_tokens": 11,
    "output_tokens": 7,
    "cache_read_tokens": 3,
    "cache_write_tokens": 2,
    "estimated_cost": 0.125,
}


class ReplacementProvider(FakeWritingProvider):
    kind = "provider-b"
    display_name = "Provider B"
    is_simulation = True

    def descriptor(self) -> dict:
        return {**super().descriptor(), "config_digest": "digest-b"}

    def last_usage(self) -> dict:
        return {"input_tokens": 999, "output_tokens": 999}


class SwitchingProvider(FakeWritingProvider):
    kind = "provider-a"
    display_name = "Provider A"
    is_simulation = False

    def __init__(self, service: WritingService):
        self.service = service

    def descriptor(self) -> dict:
        return {**super().descriptor(), "config_digest": "digest-a"}

    def last_usage(self) -> dict:
        return dict(USAGE_A)

    def _switch(self):
        self.service.provider = ReplacementProvider()

    def generate_blueprint(self, brief: dict, analysis_context: dict | None = None) -> dict:
        self._switch()
        return super().generate_blueprint(brief, analysis_context)

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        self._switch()
        return super().discuss_work(messages, work_context)

    def generate_structure_plan(self, messages: list[dict], structure_context: dict) -> dict:
        self._switch()
        return super().generate_structure_plan(messages, structure_context)

    def review_continuity(self, context: dict) -> list[dict]:
        self._switch()
        return super().review_continuity(context)

    def extract_memory_bundle(self, memory_context: dict) -> dict:
        self._switch()
        return super().extract_memory_bundle(memory_context)


class FailingCandidateProvider(FakeWritingProvider):
    is_simulation = True

    def __init__(self, digest: str, fail: bool):
        self.digest = digest
        self.fail = fail

    def descriptor(self) -> dict:
        return {
            **super().descriptor(),
            "is_simulation": True,
            "config_digest": self.digest,
        }

    def generate_scene(self, context: dict, instruction: str = "") -> str:
        if self.fail:
            raise DomainError(
                "writing_provider_failed",
                "模型服务暂时无法完成本场写作。",
                status=504,
                details={"failure_kind": "provider_timeout"},
            )
        return super().generate_scene(context, instruction)


def _proposal(work: dict, proposal_id: str) -> dict:
    return next(item for item in work["proposals"] if item["id"] == proposal_id)


def _work_item(work: dict, item_type: str) -> dict:
    return next(
        item
        for run in work["runs"]
        for item in run["work_items"]
        if item["type"] == item_type
    )


def _saved_scene(service: WritingService) -> tuple[dict, str]:
    work = service.create_work({"title": "Provider 固定测试"})
    created = service.create_scene(
        work["id"],
        work["chapters"][0]["id"],
        {"expected_version": work["version"], "title": "终端亮起", "goal": "确认终端状态"},
    )
    saved = service.save_scene_manuscript(
        work["id"],
        created["scene_id"],
        {
            "expected_version": created["work"]["version"],
            "expected_base_revision_id": None,
            "blocks": [
                {"id": "block-1", "type": "action", "speaker": "", "text": "终端在口令后亮起。"}
            ],
        },
    )
    return saved["work"], created["scene_id"]


def _candidate_scene(service: WritingService) -> tuple[dict, str]:
    work = service.create_work({"title": "Provider 候选重试", "idea": "夜间活动室的提示灯突然亮起。"})
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "夜间活动室的提示灯突然亮起。",
            "mode": "bond_short",
            "characters": ["爱丽丝", "凯伊"],
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"],
        {
            "expected_version": blueprint["work"]["version"],
            "title": "第一章",
        },
    )
    created = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "提示灯",
            "location": "活动室",
            "goal": "确认异常提示灯的来源",
        },
    )
    return created["work"], created["scene_id"]


def _accepted_blueprint(service: WritingService) -> dict:
    work = service.create_work(
        {"title": "Provider 固定结构", "idea": "两位学生在夜间校舍寻找失落的录音。"}
    )
    thread = work["conversation_threads"][0]
    proposed = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {"expected_version": work["version"], "expected_thread_version": thread["version"]},
    )
    return service.accept_proposal(
        work["id"], proposed["proposal_id"], {"expected_version": proposed["work"]["version"]}
    )["work"]


def test_conversation_blueprint_pins_provider_for_proposal_message_and_result(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work(
        {"title": "Provider 固定蓝图", "idea": "两位学生调查深夜亮起的终端。"}
    )
    thread = work["conversation_threads"][0]
    service.provider = SwitchingProvider(service)

    result = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {"expected_version": work["version"], "expected_thread_version": thread["version"]},
    )

    proposal = _proposal(result["work"], result["proposal_id"])
    message = result["work"]["conversation_threads"][0]["messages"][-1]
    assert service.provider.kind == "provider-b"
    assert result["simulation"] is False
    assert proposal["provider"]["kind"] == "provider-a"
    assert proposal["provider"]["config_digest"] == "digest-a"
    assert message["provider"]["kind"] == "provider-a"


def test_knowledge_proposal_keeps_the_provider_that_created_its_discussion_draft(tmp_path):
    service = WritingService(tmp_path)
    work = service.create_work({"title": "资料来源 Provider 固定"})
    thread = work["conversation_threads"][0]
    service.provider = SwitchingProvider(service)

    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "请建立角色《阿露》的讨论草稿。",
        },
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    proposed = service.propose_conversation_knowledge(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
            "kind": "character_card",
        },
    )

    proposal = _proposal(proposed["work"], proposed["proposal_id"])
    proposal_message = proposed["work"]["conversation_threads"][0]["messages"][-1]
    assert service.provider.kind == "provider-b"
    assert proposed["simulation"] is False
    assert proposal["provider"]["kind"] == "provider-a"
    assert proposal["provider"]["config_digest"] == "digest-a"
    assert proposal_message["provider"]["kind"] == "provider-a"


def test_structure_plan_pins_provider_for_attempt_proposal_usage_and_result(tmp_path):
    service = WritingService(tmp_path)
    work = _accepted_blueprint(service)
    thread = work["conversation_threads"][0]
    discussed = service.post_conversation_message(
        work["id"],
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "第一场先建立日常中的异常。"},
    )
    current_thread = discussed["work"]["conversation_threads"][0]
    service.provider = SwitchingProvider(service)

    result = service.organize_conversation_proposal(
        work["id"],
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
        },
    )

    proposal = _proposal(result["work"], result["proposal_id"])
    item = _work_item(result["work"], "structure.plan")
    message = result["work"]["conversation_threads"][0]["messages"][-1]
    assert result["simulation"] is False
    assert proposal["provider"]["config_digest"] == "digest-a"
    assert item["attempts"][0]["provider"] == "provider-a"
    assert item["acceptance"]["usage"] == USAGE_A
    assert message["provider"]["kind"] == "provider-a"
    assert {key: message[key] for key in USAGE_A} == USAGE_A


def test_work_review_pins_provider_for_attempt_gate_usage_and_result(tmp_path):
    service = WritingService(tmp_path)
    work, _ = _saved_scene(service)
    service.provider = SwitchingProvider(service)

    result = service.review_continuity(
        work["id"], {"expected_version": work["version"]}
    )

    item = _work_item(result["work"], "agent.continuity.review")
    gate = next(item for item in result["work"]["gates"] if item["id"] == result["gate_id"])
    assert result["simulation"] is False
    assert item["attempts"][0]["provider"] == "provider-a"
    assert item["acceptance"]["provider_usage"] == USAGE_A
    assert gate["snapshot"]["provider"]["config_digest"] == "digest-a"
    assert gate["snapshot"]["provider_usage"] == USAGE_A


def test_memory_extract_pins_provider_for_attempt_proposal_usage_and_result(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = _saved_scene(service)
    service.provider = SwitchingProvider(service)

    result = service.generate_memory_proposal(
        work["id"], scene_id, {"expected_version": work["version"]}
    )

    proposal = _proposal(result["work"], result["proposal_id"])
    item = _work_item(result["work"], "memory.extract")
    run = next(
        item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"]
    )
    assert result["simulation"] is False
    assert proposal["provider"]["config_digest"] == "digest-a"
    assert item["attempts"][0]["provider"] == "provider-a"
    assert item["acceptance"]["usage"] == USAGE_A
    assert run["policy"]["usage"] == USAGE_A


def test_scene_retry_rejects_provider_configuration_change(tmp_path):
    service = WritingService(tmp_path)
    work, scene_id = _candidate_scene(service)
    service.provider = FailingCandidateProvider("digest-a", fail=True)

    with pytest.raises(DomainError) as failed:
        service.generate_scene_candidate(
            work["id"], scene_id, {"expected_version": work["version"]}
        )
    assert failed.value.code == "writing_provider_failed"
    failed_work = service.get_work(work["id"])
    failed_run = next(
        run
        for run in failed_work["agent_runs"]
        if run["status"] == "failed" and run["scope_id"] == scene_id
    )

    service.provider = FailingCandidateProvider("digest-b", fail=False)
    with pytest.raises(DomainError) as changed:
        service.retry_agent_run(
            work["id"], failed_run["id"], {"expected_version": failed_work["version"]}
        )
    assert changed.value.code == "provider_config_changed"
