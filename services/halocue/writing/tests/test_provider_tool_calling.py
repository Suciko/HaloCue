import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import urllib.error

import pytest

from halocue_writing.errors import DomainError
from halocue_writing.ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.repository import Repository, canonical_json, sha256_text


_PROMPT_DATA = tempfile.TemporaryDirectory()
_PROMPT_REGISTRY = BaWritingSkillRegistry()
_PROMPT_REGISTRY.materialize(Repository(Path(_PROMPT_DATA.name)))
PROMPT_ASSEMBLER = BaWritingPromptAssembler(_PROMPT_REGISTRY)


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def provider(protocol: str, base_url: str) -> LLMWritingProvider:
    return LLMWritingProvider({
        "provider": protocol,
        "base_url": base_url,
        "model": "contract-test-model",
        "api_key": "test-key",
        "max_tokens": 2048,
    }, PROMPT_ASSEMBLER)


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (socket.timeout("timed out"), "provider_timeout"),
        (urllib.error.HTTPError("https://llm.example/v1", 429, "rate limited", {}, io.BytesIO()), "provider_rate_limited"),
    ],
)
def test_provider_failure_exposes_public_retry_classification(exc, kind):
    with pytest.raises(DomainError) as captured:
        provider("openai", "https://llm.example/v1")._provider_failure("作品讨论", exc)

    assert captured.value.code == "writing_provider_failed"
    assert captured.value.details["failure_kind"] == kind


def test_invalid_provider_request_preserves_bounded_provider_diagnostic():
    body = json.dumps({
        "error": {"message": "Invalid model: contract-test-model", "type": "invalid_request_error"}
    }).encode("utf-8")
    error = urllib.error.HTTPError(
        "https://llm.example/v1", 400, "bad request", {}, io.BytesIO(body)
    )

    with pytest.raises(DomainError) as captured:
        provider("openai", "https://llm.example/v1")._provider_failure("场景起草", error)

    assert captured.value.details["failure_kind"] == "provider_invalid_request"
    assert captured.value.details["http_status"] == 400
    assert captured.value.details["provider_message"] == "Invalid model: contract-test-model"
    assert len(captured.value.details["provider_response"]) <= 2048


def scene_context(**overrides) -> dict:
    context = {
        "rules": {"mode_key": "bond_short"},
        "brief": {"mode": "bond_short", "has_sensei": False},
        "scene_contract": {"goal": "确认提示灯来源"},
        "runtime_character_cards": [],
    }
    context.update(overrides)
    pack = {
        "schema_version": "scene-writing-pack/1.0",
        "scene_id": "scene-test",
        "mode_key": context["rules"]["mode_key"],
        "has_sensei": bool(context["scene_contract"].get("has_sensei", context["brief"].get("has_sensei"))),
        "scene_contract": context["scene_contract"],
        "brief": context["brief"],
        "runtime_character_cards": context["runtime_character_cards"],
        "source_revision_ids": [],
    }
    pack["digest"] = sha256_text(canonical_json(pack))
    context["scene_writing_pack"] = pack
    return context


def work_review_pack(workflow: str = "continuity.review") -> dict:
    pack = {
        "schema_version": "work-review-pack/1.0",
        "workflow": workflow,
        "work_id": "work-review",
        "mode_key": "bond_short",
        "has_sensei": False,
        "brief": {"mode": "bond_short"},
        "scenes": [{
            "scene_id": "scene-1",
            "revision_id": "revision-1",
            "revision_hash": "sha256:revision-1",
            "text_excerpt": "旁白: 灯亮了。",
        }],
        "dependency_refs": [],
        "writing_pack_version": "ba-writing.productized/1.1.0",
    }
    pack["digest"] = sha256_text(canonical_json(pack))
    return pack


@pytest.mark.parametrize(
    ("protocol", "mode", "expected_instruction"),
    [
        ("openai", "creative", "先比较多个可行方向"),
        ("anthropic", "strict", "优先核对来源、既有事实、人物约束和冲突"),
    ],
)
def test_reasoning_mode_changes_runtime_prompt_without_requesting_hidden_chain(
    monkeypatch, protocol, mode, expected_instruction,
):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        if protocol == "anthropic":
            return FakeHTTPResponse({
                "usage": {"input_tokens": 10, "output_tokens": 4},
                "content": [{"type": "text", "text": json.dumps({
                    "text": "已完成约束核对。",
                    "questions": [],
                    "reasoning_summary": "当前结论只采用已确认事实。",
                    "ready_for_proposal": False,
                }, ensure_ascii=False)}],
            })
        return FakeHTTPResponse({
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            "choices": [{"message": {"content": json.dumps({
                "text": "给出两个方向后选定其一。",
                "questions": [],
                "reasoning_summary": "所选方向兼顾人物约束和表现力。",
                "ready_for_proposal": False,
            }, ensure_ascii=False)}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = LLMWritingProvider({
        "provider": protocol,
        "base_url": "https://api.anthropic.com/v1" if protocol == "anthropic" else "https://llm.example/v1",
        "model": "reasoning-mode-test",
        "api_key": "test",
        "reasoning_mode": mode,
    }, PROMPT_ASSEMBLER)
    result = current_provider.discuss_work([], {"work_id": "reasoning-mode"})

    system_prompt = (
        captured["body"]["system"][0]["text"]
        if protocol == "anthropic"
        else captured["body"]["messages"][0]["content"]
    )
    assert expected_instruction in system_prompt
    assert "不要输出、转述或要求展示隐藏思维链" in system_prompt
    assert result["reasoning_summary"]
    assert "reasoning_content" not in result


def test_unknown_reasoning_mode_falls_back_to_balanced_prompt(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "choices": [{"message": {"content": json.dumps({
                "text": "ok",
                "questions": [],
                "reasoning_summary": "摘要",
                "ready_for_proposal": False,
            }, ensure_ascii=False)}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = LLMWritingProvider({
        "provider": "openai",
        "base_url": "https://llm.example/v1",
        "model": "fallback-test",
        "api_key": "test",
        "reasoning_mode": "unsupported",
    }, PROMPT_ASSEMBLER)
    current_provider.discuss_work([], {})

    assert current_provider.reasoning_mode == "balanced"
    assert "创意推进、事实约束和回答篇幅之间保持平衡" in captured["body"]["messages"][0]["content"]


def test_transient_provider_failure_retries_then_returns_real_result(monkeypatch):
    calls = []
    delays = []

    def flaky_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) < 3:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                io.BytesIO(b"{}"),
            )
        return FakeHTTPResponse({
            "choices": [{"message": {"content": json.dumps({
                "text": "已恢复并完成本轮讨论。",
                "questions": [],
                "reasoning_summary": "沿用固定输入继续处理。",
                "ready_for_proposal": False,
            }, ensure_ascii=False)}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("halocue_writing.providers.time.sleep", delays.append)

    result = provider("openai", "https://llm.example/v1").discuss_work([], {})

    assert result["text"] == "已恢复并完成本轮讨论。"
    assert len(calls) == 3
    assert delays == [0.0, 0.0]


def test_authentication_failure_is_not_retried(monkeypatch):
    calls = []

    def unauthorized(request, timeout):
        calls.append((request.full_url, timeout))
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b"{}"),
        )

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", unauthorized)
    monkeypatch.setattr(
        "halocue_writing.providers.time.sleep",
        lambda _delay: pytest.fail("401 不应触发重试等待"),
    )

    with pytest.raises(DomainError) as rejected:
        provider("openai", "https://llm.example/v1").discuss_work([], {})

    assert rejected.value.code == "writing_provider_failed"
    assert len(calls) == 1


def test_scene_generation_uses_compiled_single_mode_skill_prompt(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "choices": [{"message": {"content": "旁白: 活动室里只剩提示灯。\n爱丽丝: 先确认目标。"}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("openai", "https://llm.example/v1")
    result = current_provider.generate_scene(scene_context())

    system_prompt = captured["body"]["messages"][0]["content"]
    user_prompt = captured["body"]["messages"][1]["content"]
    assert "羁绊短场景" in system_prompt
    assert "主线与战斗优先保证因果" not in system_prompt
    assert "只生成一个候选" in system_prompt
    assert "scene-writing-pack/1.0" in user_prompt
    assert '"readiness"' not in user_prompt
    assert result.startswith("旁白:")


def test_scene_review_uses_stage_skill_and_returns_structured_findings(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "choices": [{"message": {"content": json.dumps({
                "findings": [{
                    "kind": "ooc",
                    "severity": "warning",
                    "message": "角色在证据不足时直接下结论。",
                    "evidence": {"speaker": "爱丽丝", "line": 2},
                }]
            }, ensure_ascii=False)}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("openai", "https://llm.example/v1")
    findings = current_provider.review_scene(scene_context(
        runtime_character_cards=[{"name": "爱丽丝", "ooc_constraints": ["不无证据断言。"]}],
    ), "旁白: 提示灯亮起。\n爱丽丝: 一定是敌人做的。\n")

    system_prompt = captured["body"]["messages"][0]["content"]
    assert "`scene.review`" in system_prompt
    assert "只返回 JSON 对象" in system_prompt
    assert findings == [{
        "kind": "ooc",
        "severity": "warning",
        "message": "角色在证据不足时直接下结论。",
        "evidence": {"speaker": "爱丽丝", "line": 2},
    }]


@pytest.mark.parametrize("workflow", ["continuity.review", "release.review"])
def test_work_review_uses_stage_skill_and_returns_revision_scoped_findings(monkeypatch, workflow):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "choices": [{"message": {"content": json.dumps({
                "findings": [{
                    "scene_id": "scene-1",
                    "revision_id": "revision-1",
                    "kind": "continuity" if workflow == "continuity.review" else "release_quality",
                    "severity": "warning",
                    "message": "需要人工确认。",
                    "evidence": {"line": 1},
                }]
            }, ensure_ascii=False)}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("openai", "https://llm.example/v1")
    pack = work_review_pack(workflow)
    findings = (
        current_provider.review_continuity(pack)
        if workflow == "continuity.review"
        else current_provider.review_release(pack)
    )

    system_prompt = captured["body"]["messages"][0]["content"]
    user_prompt = captured["body"]["messages"][1]["content"]
    assert f"`{workflow}`" in system_prompt
    assert "只读审查 Agent" in system_prompt
    assert "work-review-pack/1.0" in user_prompt
    assert findings[0]["revision_id"] == "revision-1"


def test_work_review_rejects_finding_without_revision_scope(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeHTTPResponse({
            "choices": [{"message": {"content": json.dumps({
                "findings": [{
                    "kind": "continuity",
                    "severity": "warning",
                    "message": "缺少固定修订。",
                    "evidence": {},
                }]
            }, ensure_ascii=False)}}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(DomainError) as error:
        provider("openai", "https://llm.example/v1").review_continuity(work_review_pack())
    assert error.value.code == "provider_output_invalid"


def test_openai_compatible_discussion_sends_registry_functions_and_normalizes_calls(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "usage": {"prompt_tokens": 200, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 80}},
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "text": "我先读取已有资料，再讨论新角色。",
                        "questions": [],
                        "reasoning_summary": "先核对正式资料，避免重复人物卡。",
                        "ready_for_proposal": False,
                    }, ensure_ascii=False),
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "search_character_cards", "arguments": '{"query":"凯伊"}'},
                        },
                        {
                            "id": "call-2",
                            "type": "function",
                            "function": {"name": "read_work_context", "arguments": {}},
                        },
                    ],
                }
            }]
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("openai", "https://llm.example/v1")
    result = current_provider.discuss_work([], {"work_id": "work-1"})

    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["body"]["tool_choice"] == "auto"
    functions = {item["function"]["name"]: item["function"] for item in captured["body"]["tools"]}
    assert "read_work_context" in functions
    assert "draft_character_card" in functions
    assert functions["search_character_cards"]["parameters"]["properties"]["query"]["type"] == "string"
    assert result["tool_calls"] == [
        {"id": "call-1", "tool": "search_character_cards", "arguments": {"query": "凯伊"}},
        {"id": "call-2", "tool": "read_work_context", "arguments": {}},
    ]
    assert all("status" not in item for item in result["tool_calls"])
    assert current_provider.last_usage()["cache_read_tokens"] == 80
    assert current_provider.last_usage()["input_tokens"] == 200
    assert current_provider.last_usage()["input_tokens_semantics"] == "total_including_cache"


def test_discussion_keeps_public_prose_when_gateway_ignores_json_contract(monkeypatch):
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse({
            "choices": [{"message": {
                "content": "先确认这一场的目标，再决定角色关系如何推进。",
                "reasoning_content": "不得展示的内部推理",
            }}],
        }),
    )

    result = provider("openai", "https://llm.example/v1").discuss_work([], {"work_id": "work-prose"})

    assert result["text"] == "先确认这一场的目标，再决定角色关系如何推进。"
    assert result["questions"] == []
    assert result["ready_for_proposal"] is False
    assert "reasoning_content" not in result


def test_gemini_three_uses_completion_budget_parameter(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({"choices": [{"message": {
            "content": '{"text":"ok","questions":[],"reasoning_summary":"ok","ready_for_proposal":false}'
        }}]})

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = LLMWritingProvider({
        "provider": "openai",
        "base_url": "https://llm.example/v1",
        "model": "gemini-3-flash",
        "api_key": "test-key",
        "max_tokens": 65536,
    }, PROMPT_ASSEMBLER)
    current_provider.discuss_work([], {"work_id": "work-gemini"})

    assert captured["body"]["max_completion_tokens"] == 65536
    assert "max_tokens" not in captured["body"]


def test_anthropic_discussion_sends_native_tools_and_parses_tool_use(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 90, "output_tokens": 20, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 12},
            "content": [
                {"type": "thinking", "thinking": "需要先查证现有事实。"},
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "search_work_canon",
                    "input": {"query": "老师是否在场"},
                },
            ],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("anthropic", "https://api.anthropic.com")
    result = current_provider.discuss_work([], {"work_id": "work-1"})

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["body"]["tool_choice"] == {"type": "auto"}
    assert captured["body"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    tools = {item["name"]: item for item in captured["body"]["tools"]}
    assert "search_work_canon" in tools
    assert tools["search_work_canon"]["input_schema"]["type"] == "object"
    assert result["tool_calls"] == [{
        "id": "toolu-1",
        "tool": "search_work_canon",
        "arguments": {"query": "老师是否在场"},
    }]
    assert "实际执行结果为准" in result["text"]
    assert "reasoning_content" not in result
    assert "status" not in result["tool_calls"][0]
    assert current_provider.last_usage()["cache_read_tokens"] == 40
    assert current_provider.last_usage()["cache_write_tokens"] == 12
    assert current_provider.last_usage()["input_tokens"] == 142


def test_malformed_tool_arguments_fail_instead_of_becoming_empty_success(monkeypatch):
    def fake_urlopen(_request, timeout):
        return FakeHTTPResponse({
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-bad",
                        "type": "function",
                        "function": {"name": "draft_canon_fact", "arguments": "not-json"},
                    }],
                }
            }]
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(DomainError) as captured:
        provider("openai", "https://llm.example/v1").discuss_work([], {})

    assert captured.value.code == "writing_provider_failed"
    assert captured.value.details["operation"] == "作品讨论"
    assert "JSON" in captured.value.details["reason"]


def test_tool_call_without_protocol_id_fails_before_dispatch(monkeypatch):
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse({
            "choices": [{"message": {
                "content": None,
                "tool_calls": [{
                    "type": "function",
                    "function": {"name": "read_work_context", "arguments": "{}"},
                }],
            }}],
        }),
    )
    with pytest.raises(DomainError) as captured:
        provider("openai", "https://llm.example/v1").discuss_work([], {})

    assert captured.value.code == "writing_provider_failed"
    assert "调用 ID" in captured.value.details["reason"]


def test_openai_tool_followup_uses_native_tool_message_and_original_call_id(monkeypatch):
    bodies = []

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data.decode("utf-8")))
        if len(bodies) == 1:
            return FakeHTTPResponse({
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
                "choices": [{"message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call-native-1",
                        "type": "function",
                        "function": {"name": "read_work_context", "arguments": "{}"},
                    }],
                }}],
            })
        return FakeHTTPResponse({
            "usage": {"prompt_tokens": 30, "completion_tokens": 8},
            "choices": [{"message": {
                "role": "assistant",
                "content": json.dumps({
                    "text": "工具结果已经纳入最终判断。",
                    "questions": [],
                    "reasoning_summary": "正式上下文为空。",
                    "ready_for_proposal": False,
                }, ensure_ascii=False),
            }}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("openai", "https://llm.example/v1")
    first = current_provider.discuss_work([], {"work_id": "work-native"})
    result = current_provider.discuss_work([], {
        "work_id": "work-native",
        "tool_followup": True,
        "tool_results": [{
            "tool": "read_work_context",
            "status": "succeeded",
            "output": {"artifacts": []},
            "error": None,
        }],
    })

    assert first["tool_calls"][0]["id"] == "call-native-1"
    assert result["text"] == "工具结果已经纳入最终判断。"
    followup = bodies[1]
    assert followup["tools"]
    assert followup["tool_choice"] == "none"
    assert [item["role"] for item in followup["messages"]] == ["system", "user", "assistant", "tool"]
    assert followup["messages"][2]["tool_calls"][0]["id"] == "call-native-1"
    tool_message = followup["messages"][3]
    assert tool_message["tool_call_id"] == "call-native-1"
    assert json.loads(tool_message["content"])["output"] == {"artifacts": []}


def test_anthropic_tool_followup_uses_native_tool_result_and_original_use_id(monkeypatch):
    bodies = []

    def fake_urlopen(request, timeout):
        bodies.append(json.loads(request.data.decode("utf-8")))
        if len(bodies) == 1:
            return FakeHTTPResponse({
                "usage": {"input_tokens": 20, "output_tokens": 5},
                "content": [{
                    "type": "tool_use",
                    "id": "toolu-native-1",
                    "name": "search_work_canon",
                    "input": {"query": "广播"},
                }],
            })
        return FakeHTTPResponse({
            "usage": {"input_tokens": 30, "output_tokens": 8},
            "content": [{"type": "text", "text": json.dumps({
                "text": "已经根据事实检索结果回答。",
                "questions": [],
                "reasoning_summary": "没有找到已确认事实。",
                "ready_for_proposal": False,
            }, ensure_ascii=False)}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("anthropic", "https://api.anthropic.com/v1")
    current_provider.discuss_work([], {"work_id": "work-native"})
    current_provider.discuss_work([], {
        "work_id": "work-native",
        "tool_followup": True,
        "tool_results": [{
            "tool": "search_work_canon",
            "status": "succeeded",
            "output": [],
            "error": None,
        }],
    })

    followup = bodies[1]
    assert followup["tools"]
    assert followup["tool_choice"] == {"type": "none"}
    assert [item["role"] for item in followup["messages"]] == ["user", "assistant", "user"]
    assert followup["messages"][1]["content"][0]["id"] == "toolu-native-1"
    tool_result = followup["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu-native-1"
    assert tool_result["is_error"] is False
    assert json.loads(tool_result["content"])["output"] == []


def test_provider_runtime_state_is_isolated_between_concurrent_threads(monkeypatch):
    read_barrier = threading.Barrier(2)
    done_barrier = threading.Barrier(2)
    observed = {}

    class ConcurrentResponse(FakeHTTPResponse):
        def read(self):
            read_barrier.wait(timeout=5)
            return super().read()

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        marker = "线程甲" if "线程甲" in json.dumps(body, ensure_ascii=False) else "线程乙"
        tokens = 101 if marker == "线程甲" else 202
        return ConcurrentResponse({
            "usage": {"prompt_tokens": tokens, "completion_tokens": 1},
            "choices": [{"message": {
                "content": json.dumps({
                    "text": marker,
                    "questions": [],
                    "reasoning_summary": marker,
                    "ready_for_proposal": False,
                }, ensure_ascii=False),
                "reasoning_content": f"{marker} reasoning",
            }}],
        })

    monkeypatch.setattr("halocue_writing.providers.urllib.request.urlopen", fake_urlopen)
    current_provider = provider("openai", "https://llm.example/v1")

    def run(marker):
        reply = current_provider.discuss_work([], {"work_id": marker})
        done_barrier.wait(timeout=5)
        observed[marker] = (reply, current_provider.last_usage())

    threads = [threading.Thread(target=run, args=(marker,)) for marker in ("线程甲", "线程乙")]
    for item in threads:
        item.start()
    for item in threads:
        item.join(timeout=5)

    assert not any(item.is_alive() for item in threads)
    assert "reasoning_content" not in observed["线程甲"][0]
    assert "reasoning_content" not in observed["线程乙"][0]
    assert observed["线程甲"][1]["input_tokens"] == 101
    assert observed["线程乙"][1]["input_tokens"] == 202


@pytest.mark.parametrize(
    ("protocol", "usage", "expected_input", "expected_cost"),
    [
        (
            "openai",
            {"prompt_tokens": 200, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 80}},
            200,
            0.00228,
        ),
        (
            "anthropic",
            {"input_tokens": 90, "output_tokens": 20, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 12},
            142,
            0.00149,
        ),
    ],
)
def test_usage_contract_counts_cache_once_and_prices_each_bucket(monkeypatch, protocol, usage, expected_input, expected_cost):
    response = (
        {"usage": usage, "content": [{"type": "text", "text": '{"text":"ok","questions":[],"reasoning_summary":"ok","ready_for_proposal":false}'}]}
        if protocol == "anthropic"
        else {"usage": usage, "choices": [{"message": {"content": '{"text":"ok","questions":[],"reasoning_summary":"ok","ready_for_proposal":false}'}}]}
    )
    monkeypatch.setattr(
        "halocue_writing.providers.urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse(response),
    )
    current_provider = LLMWritingProvider({
        "provider": protocol,
        "base_url": "https://api.anthropic.com/v1" if protocol == "anthropic" else "https://llm.example/v1",
        "model": "cost-test",
        "api_key": "test",
        "input_cost_per_million": 10,
        "output_cost_per_million": 20,
    }, PROMPT_ASSEMBLER)
    current_provider.discuss_work([], {"work_id": "cost"})

    snapshot = current_provider.last_usage()
    assert snapshot["schema_version"] == "provider-usage/1.0"
    assert snapshot["input_tokens"] == expected_input
    assert snapshot["estimated_cost"] == pytest.approx(expected_cost)
