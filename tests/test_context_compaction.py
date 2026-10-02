import copy
import json

import pytest

from model_capabilities import compact_request_context, context_compaction_threshold, completion_parameters, ModelCapabilityError


def test_shared_budget_reserves_output_and_uses_256k_ceiling():
    assert context_compaction_threshold({"model": "private"}) == 256000
    assert context_compaction_threshold({"model": "private", "context_window": 32000, "max_tokens": 4096}) < 32000 - 4096


def test_pressure_packs_json_without_losing_prose_constraints_or_stable_prefix():
    blocks = [{"id": "b", "type": "narration", "text": "雨还没停。" * 200}]
    value = {"manuscript": {"blocks": blocks, "text": "旁白: " + blocks[0]["text"] + "\n"},
             "instruction": "不要改变结局。", "pending_id": "p1", "revision_id": "r1"}
    prefix = {"role": "system", "content": "规则始终稳定。"}
    payload = {"messages": [prefix, {"role": "user", "content": "作品上下文: " + json.dumps(value, ensure_ascii=False)}]}
    original = copy.deepcopy(payload)
    packed, report = compact_request_context({"model": "private", "context_compaction_tokens": 1024}, payload)
    assert payload == original
    assert packed["messages"][0] == prefix
    decoded = json.loads(packed["messages"][1]["content"].split(": ", 1)[1])
    assert decoded["manuscript"]["blocks"] == blocks
    assert "text" not in decoded["manuscript"]
    assert decoded["instruction"] == value["instruction"]
    assert decoded["pending_id"] == "p1" and decoded["revision_id"] == "r1"
    assert report["triggered"] and report["estimated_after_tokens"] < report["estimated_before_tokens"]


def test_free_prose_and_native_tool_exchange_are_never_truncated():
    payload = {"messages": [{"role": "user", "content": "保留全部原文。" * 1000},
                             {"role": "assistant", "tool_calls": [{"id": "t1"}]},
                             {"role": "tool", "tool_call_id": "t1", "content": "原始工具结果"}]}
    packed, report = compact_request_context({"model": "private", "context_compaction_tokens": 1024}, payload)
    assert packed == payload
    assert report["protected_context_exceeds_target"]
    with pytest.raises(ModelCapabilityError):
        completion_parameters({"model": "private", "context_window": 3000}, packed)
