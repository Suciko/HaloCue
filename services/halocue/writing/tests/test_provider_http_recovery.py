import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.service import WritingService


class _ProviderFixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        state = self.server.fixture_state
        state["requests"] += 1
        remaining = list(state["statuses"])
        status = remaining.pop(0) if remaining else 200
        state["statuses"] = remaining
        if status != 200:
            body = json.dumps(
                {"error": {"message": f"fixture status {status}", "type": "fixture_error"}}
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(
            {
                "id": "fixture-completion",
                "choices": [{"message": {"content": "旁白: 走廊的灯亮起。\n"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 6},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@pytest.fixture
def provider_fixture():
    state = {"statuses": [], "requests": 0}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderFixtureHandler)
    server.fixture_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _provider(server, service):
    return LLMWritingProvider(
        {
            "provider": "openai",
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "model": "fixture-model",
            "api_key": "fixture-key",
            "max_tokens": 256,
            "timeout": 3,
        },
        service.ba_prompt_assembler,
    )


def _ready_scene(service):
    work = service.create_work({"title": "HTTP Provider 恢复夹具"})
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "凯伊在活动室确认提示灯来源。",
            "mode": "bond_short",
            "characters": ["爱丽丝", "凯伊"],
        },
    )
    blueprint = service.generate_blueprint(work["id"], {"expected_version": brief["work"]["version"]})
    chapter = service.create_chapter(
        work["id"], {"expected_version": blueprint["work"]["version"], "title": "第一章"}
    )
    scene = service.create_scene(
        work["id"], chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "提示灯",
            "location": "活动室",
            "goal": "确认提示灯来源",
        },
    )
    generated = service.generate_scene_candidate(
        work["id"], scene["scene_id"], {"expected_version": scene["work"]["version"]}
    )
    rejected = service.reject_proposal(
        work["id"], generated["proposal_id"],
        {"expected_version": generated["work"]["version"], "note": "准备 HTTP Provider 恢复测试"},
    )
    first = service.save_character_card(
        work["id"],
        {
            "expected_version": rejected["work"]["version"],
            "card_id": "character-aris",
            "name": "爱丽丝",
            "source_refs": ["测试确认"],
            "voice_anchors": ["先确认眼前的情况。"],
            "trust_status": "confirmed",
        },
    )
    second = service.save_character_card(
        work["id"],
        {
            "expected_version": first["work"]["version"],
            "card_id": "character-kei",
            "name": "凯伊",
            "source_refs": ["测试确认"],
            "voice_anchors": ["我先核对数据。"],
            "trust_status": "confirmed",
        },
    )
    configured = service.configure_scene_context(
        work["id"], scene["scene_id"],
        {
            "expected_version": second["work"]["version"],
            "character_card_ids": ["character-aris", "character-kei"],
            "world_item_ids": [],
            "reference_file_ids": [],
        },
    )
    return work["id"], scene["scene_id"], configured["work"]


@pytest.mark.parametrize("transient_status", [429, 504])
def test_openai_compatible_provider_retries_transient_http_status_and_keeps_usage(
    tmp_path, provider_fixture, monkeypatch, transient_status
):
    server, state = provider_fixture
    state["statuses"] = [transient_status, 200]
    monkeypatch.setattr("halocue_writing.providers.time.sleep", lambda _seconds: None)
    service = WritingService(tmp_path)
    provider = _provider(server, service)

    result = provider.generate_scene(
        {
            "rules": {"mode_key": "bond_short"},
            "brief": {"mode": "bond_short"},
            "scene_contract": {"has_sensei": False},
            "scene_writing_pack": {"schema_version": "scene-writing-pack/1.0", "digest": "sha256:fixture"},
        }
    )

    assert result == "旁白: 走廊的灯亮起。\n"
    assert state["requests"] == 2
    assert provider.last_usage() == {
        "schema_version": "provider-usage/1.0",
        "input_tokens_semantics": "total_including_cache",
        "input_tokens": 17,
        "output_tokens": 6,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "estimated_cost": None,
        "usage_status": "reported",
        "cache_status": "unknown",
    }


@pytest.mark.parametrize("terminal_status,expected_kind", [(429, "provider_rate_limited"), (504, "provider_timeout")])
def test_openai_compatible_provider_terminal_http_status_preserves_recovery_details(
    tmp_path, provider_fixture, monkeypatch, terminal_status, expected_kind
):
    server, state = provider_fixture
    state["statuses"] = [terminal_status, terminal_status, terminal_status]
    monkeypatch.setattr("halocue_writing.providers.time.sleep", lambda _seconds: None)
    service = WritingService(tmp_path)
    provider = _provider(server, service)

    with pytest.raises(DomainError) as raised:
        provider.generate_scene(
            {
                "rules": {"mode_key": "bond_short"},
                "brief": {"mode": "bond_short"},
                "scene_contract": {"has_sensei": False},
                "scene_writing_pack": {"schema_version": "scene-writing-pack/1.0", "digest": "sha256:fixture"},
            }
        )

    error = raised.value
    assert error.code == "writing_provider_failed"
    assert error.details.get("failure_kind") == expected_kind
    assert error.details.get("http_status") == terminal_status
    assert state["requests"] == 3


def test_http_provider_failure_becomes_durable_agent_failure_and_explicit_retry(
    tmp_path, provider_fixture, monkeypatch
):
    server, state = provider_fixture
    monkeypatch.setattr("halocue_writing.providers.time.sleep", lambda _seconds: None)
    service = WritingService(tmp_path)
    work_id, scene_id, ready = _ready_scene(service)
    state["statuses"] = [429, 429, 429]
    service.provider = _provider(server, service)

    with pytest.raises(DomainError) as raised:
        service.run_scene_agent(
            work_id,
            scene_id,
            {"expected_version": ready["version"], "instruction": "起草本场"},
        )

    failure = raised.value
    assert failure.code == "agent_failed"
    failed_run_id = failure.details["agent_run_id"]
    restored = WritingService(tmp_path).get_work(work_id)
    failed_run = next(item for item in restored["agent_runs"] if item["id"] == failed_run_id)
    assert failed_run["status"] == "failed"
    assert failed_run["failure"]["failure_kind"] == "provider_rate_limited"
    assert failed_run["failure"]["details"]["http_status"] == 429
    failed_items = [
        item for run in restored["runs"] for item in run["work_items"]
        if item["acceptance"].get("agent_run_id") == failed_run_id
    ]
    assert len(failed_items) == 1
    assert failed_items[0]["status"] == "failed"
    assert failed_items[0]["attempts"][0]["status"] == "failed"
    assert not any(proposal["status"] == "pending" for proposal in restored["proposals"])

    state["statuses"] = [200]
    retried = service.retry_agent_run(
        work_id,
        failed_run_id,
        {"expected_version": restored["version"]},
    )
    assert retried["retried_from_agent_run_id"] == failed_run_id
    assert retried["proposal_id"]
    retry_run = next(item for item in retried["work"]["agent_runs"] if item["id"] == retried["agent_run_id"])
    assert retry_run["status"] == "waiting_user"
    scene = next(
        item for chapter in retried["work"]["chapters"] for item in chapter["scenes"] if item["id"] == scene_id
    )
    assert scene["current_revision_id"] is None
