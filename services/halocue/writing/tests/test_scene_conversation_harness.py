import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from halocue_writing.app import make_handler
from halocue_writing.errors import DomainError, NotFound
from halocue_writing.providers import FakeWritingProvider
from halocue_writing.service import WritingService


class CapturingProvider(FakeWritingProvider):
    def __init__(self):
        self.discussion_contexts = []
        self.scene_contexts = []

    def discuss_work(self, messages: list[dict], work_context: dict) -> dict:
        self.discussion_contexts.append(work_context)
        return super().discuss_work(messages, work_context)

    def generate_scene(self, context: dict) -> str:
        self.scene_contexts.append(context)
        return super().generate_scene(context)


def create_ready_scene(service: WritingService, *, title: str = "提示灯") -> tuple[str, str, dict]:
    work = service.create_work({"title": f"{title}测试"})
    card = service.save_character_card(
        work["id"],
        {
            "expected_version": work["version"],
            "card_id": "alice-card",
            "name": "爱丽丝",
            "source_type": "custom",
            "trust_status": "confirmed",
            "source_refs": ["用户确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "ooc_constraints": ["不替别人猜测动机"],
        },
    )
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": card["work"]["version"],
            "idea": "爱丽丝发现活动室里的旧终端在深夜亮起。",
            "mode": "bond_short",
            "characters": ["爱丽丝"],
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"],
        {"expected_version": blueprint["work"]["version"], "title": "夜间调查"},
    )
    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": title,
            "location": "游戏开发部活动室",
            "goal": "确认提示灯为何亮起",
            "stop_boundary": "确认终端会回应口令后停止",
        },
    )
    return work["id"], scene["scene_id"], scene["work"]


def create_scene_thread(service: WritingService, work_id: str, scene_id: str, work: dict) -> tuple[dict, dict]:
    created = service.create_conversation_thread(
        work_id,
        {
            "expected_version": work["version"],
            "scope_type": "scene",
            "scope_id": scene_id,
            "title": "本场写作讨论",
        },
    )
    thread = next(
        item for item in created["work"]["conversation_threads"]
        if item["id"] == created["thread_id"]
    )
    return created["work"], thread


def request_json(url: str, body: dict):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_scene_thread_scope_is_persisted_and_rejects_cross_work_or_cross_scene(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service, title="第一场")
    other_work_id, other_scene_id, _other_work = create_ready_scene(service, title="外部场景")

    with pytest.raises(NotFound) as foreign:
        service.create_conversation_thread(
            work_id,
            {
                "expected_version": work["version"],
                "scope_type": "scene",
                "scope_id": other_scene_id,
            },
        )
    assert foreign.value.code == "not_found"

    current, thread = create_scene_thread(service, work_id, scene_id, work)
    with pytest.raises(DomainError) as escaped:
        service.post_conversation_message(
            work_id,
            thread["id"],
            {
                "expected_thread_version": thread["version"],
                "text": "切换到另一场继续写。",
                "task_scope": {"surface": "scene", "scene_id": other_scene_id},
            },
        )
    assert escaped.value.code == "invalid_thread_scope"

    restored = WritingService(tmp_path).get_work(work_id)
    restored_thread = next(item for item in restored["conversation_threads"] if item["id"] == thread["id"])
    assert restored_thread["scope_type"] == "scene"
    assert restored_thread["scope_id"] == scene_id
    assert restored_thread["version"] == thread["version"]
    assert other_work_id != work_id


def test_scene_conversation_uses_fixed_read_only_context_and_multiturn_fake_reply(tmp_path):
    service = WritingService(tmp_path)
    provider = CapturingProvider()
    service.provider = provider
    work_id, scene_id, work = create_ready_scene(service)
    _current, thread = create_scene_thread(service, work_id, scene_id, work)

    first = service.post_conversation_message(
        work_id,
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "先让爱丽丝怀疑是接触不良，不要立刻解释成敌意。",
        },
    )
    first_thread = next(item for item in first["work"]["conversation_threads"] if item["id"] == thread["id"])
    second = service.post_conversation_message(
        work_id,
        thread["id"],
        {
            "expected_thread_version": first_thread["version"],
            "text": "第二轮再让提示灯回应口令，回应后就停场。",
        },
    )
    current = next(item for item in second["work"]["conversation_threads"] if item["id"] == thread["id"])
    assistant = current["messages"][-1]
    contract = assistant["content"]["task_contract"]
    assert contract["id"] == "scene.draft.generate"
    assert contract["task_scope"] == {
        "surface": "scene",
        "chapter_id": contract["task_scope"]["chapter_id"],
        "chapter_title": "夜间调查",
        "scene_id": scene_id,
        "scene_title": "提示灯",
        "scene_revision_id": None,
    }
    assert "先让爱丽丝怀疑是接触不良" in assistant["content"]["text"]
    assert "第二轮再让提示灯回应口令" in assistant["content"]["text"]

    provider_context = provider.discussion_contexts[-1]["scene_conversation_context"]
    assert provider_context["schema_version"] == "scene-conversation-context/1.0"
    assert provider_context["scene"]["contract"]["goal"] == "确认提示灯为何亮起"
    assert provider_context["current_manuscript"] is None
    assert provider_context["ba_skill"]["status"] == "ready"
    assert provider_context["confirmed_materials"]
    assert provider_context["source_revision_ids"]
    assert "不得写回" in provider_context["write_boundary"]

    run = next(item for item in second["work"]["agent_runs"] if item["id"] == second["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["scene_conversation_context"] == provider_context
    restored = WritingService(tmp_path).get_work(work_id)
    restored_run = next(item for item in restored["agent_runs"] if item["id"] == run["id"])
    assert json.loads(service.repo.read_text(restored_run["input_snapshot_uri"]))["scene_conversation_context"]["scene"]["id"] == scene_id


def test_scene_discussion_only_scope_remains_available_before_runtime_cards_are_ready(tmp_path):
    service = WritingService(tmp_path)
    provider = CapturingProvider()
    service.provider = provider
    work_id, scene_id, work = create_ready_scene(service, title="缺卡讨论")
    _current, thread = create_scene_thread(service, work_id, scene_id, work)

    discussed = service.post_conversation_message(
        work_id,
        thread["id"],
        {
            "expected_thread_version": thread["version"],
            "text": "先讨论需要补齐哪些人物卡，不要生成正文候选。",
            "task_scope": {"surface": "scene", "scene_id": scene_id, "discussion_only": True},
        },
    )
    current = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])
    contract = current["messages"][-1]["content"]["task_contract"]
    assert contract["id"] == "chapter.plan"
    assert contract["task_scope"]["surface"] == "scene"
    assert contract["task_scope"]["scene_id"] == scene_id
    assert "不生成正文候选" in contract["task"]
    assert not any(item["kind"] == "scene_script" and item["status"] == "pending" for item in discussed["work"]["proposals"])


def test_multiturn_scene_discussion_generates_pending_proposal_and_links_message(tmp_path):
    service = WritingService(tmp_path)
    provider = CapturingProvider()
    service.provider = provider
    work_id, scene_id, work = create_ready_scene(service)
    _current, thread = create_scene_thread(service, work_id, scene_id, work)

    discussed = service.post_conversation_message(
        work_id,
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "开头保持安静，只写提示灯的变化。"},
    )
    current_thread = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])
    discussed = service.post_conversation_message(
        work_id,
        thread["id"],
        {"expected_thread_version": current_thread["version"], "text": "爱丽丝先观察，再说一句短对白。"},
    )
    current_thread = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])

    generated = service.generate_scene_proposal_from_conversation(
        work_id,
        thread["id"],
        {
            "expected_version": discussed["work"]["version"],
            "expected_thread_version": current_thread["version"],
        },
    )

    proposal = next(item for item in generated["work"]["proposals"] if item["id"] == generated["proposal_id"])
    linked_thread = next(item for item in generated["work"]["conversation_threads"] if item["id"] == thread["id"])
    notice = linked_thread["messages"][-1]
    scene = next(
        item for chapter in generated["work"]["chapters"] for item in chapter["scenes"]
        if item["id"] == scene_id
    )
    assert proposal["status"] == "pending"
    assert proposal["scope_type"] == "scene"
    assert proposal["scope_id"] == scene_id
    assert scene["current_revision_id"] is None
    assert notice["proposal_id"] == proposal["id"]
    assert notice["agent_run_id"] == generated["agent_run_id"]
    assert notice["content"]["schema_version"] == "scene-conversation-proposal-link/1.0"
    assert [item["text"] for item in notice["content"]["discussion_constraints"]["messages"]] == [
        "开头保持安静，只写提示灯的变化。",
        "爱丽丝先观察，再说一句短对白。",
    ]

    scene_provider_context = provider.scene_contexts[-1]
    assert "开头保持安静" in scene_provider_context["instruction"]
    assert "爱丽丝先观察" in scene_provider_context["instruction"]
    assert scene_provider_context["discussion_constraints"]["thread_id"] == thread["id"]
    run = next(item for item in generated["work"]["agent_runs"] if item["id"] == generated["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["instruction"] == scene_provider_context["instruction"]
    assert snapshot["discussion_constraints"] == scene_provider_context["discussion_constraints"]

    restored = WritingService(tmp_path).get_work(work_id)
    restored_thread = next(item for item in restored["conversation_threads"] if item["id"] == thread["id"])
    restored_notice = restored_thread["messages"][-1]
    assert restored_notice["proposal_id"] == generated["proposal_id"]
    assert restored_notice["agent_run_id"] == generated["agent_run_id"]


def test_scene_proposal_http_route_uses_rewrite_and_optional_selection(tmp_path):
    service = WritingService(tmp_path / "data")
    work_id, scene_id, work = create_ready_scene(service)
    saved = service.save_scene_manuscript(
        work_id,
        scene_id,
        {
            "expected_version": work["version"],
            "base_revision_id": None,
            "blocks": [
                {"id": "block-1", "type": "dialogue", "speaker": "旁白", "text": "提示灯在黑暗里闪了两次。"},
                {"id": "block-2", "type": "dialogue", "speaker": "爱丽丝", "text": "先别碰它。"},
            ],
        },
    )
    current, thread = create_scene_thread(service, work_id, scene_id, saved["work"])
    discussed = service.post_conversation_message(
        work_id,
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "缩短动作描写，但保留爱丽丝的停顿。"},
    )
    current_thread = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])
    formal = next(
        item for item in discussed["work"]["artifacts"]
        if item["kind"] == "scene_script" and item["scope_id"] == scene_id
    )
    base_revision_id = formal["current_revision_id"]
    base_text = formal["current_revision"]["content"]["text"]
    quote = "先别碰它。"
    start = base_text.index(quote)

    static = Path(__file__).resolve().parents[1] / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, static))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        status, response = request_json(
            f"http://127.0.0.1:{server.server_port}/api/v1/works/{work_id}/threads/{thread['id']}/scene-proposal:generate",
            {
                "expected_version": discussed["work"]["version"],
                "expected_thread_version": current_thread["version"],
                "selection": {"quote": quote, "start": start, "end": start + len(quote)},
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert status == 200, response
    result = response["data"]
    proposal = next(item for item in result["work"]["proposals"] if item["id"] == result["proposal_id"])
    notice = next(item for item in result["work"]["conversation_threads"] if item["id"] == thread["id"])["messages"][-1]
    assert proposal["base_revision_id"] == base_revision_id
    assert proposal["status"] == "pending"
    assert notice["proposal_id"] == proposal["id"]
    run = next(item for item in result["work"]["agent_runs"] if item["id"] == result["agent_run_id"])
    snapshot = json.loads(service.repo.read_text(run["input_snapshot_uri"]))
    assert snapshot["selection"]["quote"] == quote
    assert snapshot["scene_conversation_context"]["current_manuscript"]["revision_id"] == base_revision_id


def test_scene_proposal_generation_requires_both_current_versions(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_ready_scene(service)
    current, thread = create_scene_thread(service, work_id, scene_id, work)
    discussed = service.post_conversation_message(
        work_id,
        thread["id"],
        {"expected_thread_version": thread["version"], "text": "保持短场景。"},
    )
    current_thread = next(item for item in discussed["work"]["conversation_threads"] if item["id"] == thread["id"])

    with pytest.raises(DomainError) as stale_thread:
        service.generate_scene_proposal_from_conversation(
            work_id,
            thread["id"],
            {
                "expected_version": discussed["work"]["version"],
                "expected_thread_version": current_thread["version"] - 1,
            },
        )
    assert stale_thread.value.code == "thread_conflict"

    with pytest.raises(DomainError) as stale_work:
        service.generate_scene_proposal_from_conversation(
            work_id,
            thread["id"],
            {
                "expected_version": discussed["work"]["version"] - 1,
                "expected_thread_version": current_thread["version"],
            },
        )
    assert stale_work.value.code == "revision_conflict"
    assert not service.get_work(work_id)["proposals"]
