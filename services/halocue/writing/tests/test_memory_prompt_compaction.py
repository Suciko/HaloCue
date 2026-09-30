import json
from types import SimpleNamespace

from halocue_writing.memory_prompt import compact_memory_prompt_context
from halocue_writing.providers import LLMWritingProvider


def manuscript():
    return {
        "schema_version": "scene-blocks/1.0",
        "blocks": [
            {"id": "block-a", "type": "action", "text": "门开了。"},
            {"id": "block-b", "type": "dialogue", "speaker": "白露", "text": "先进去。"},
        ],
        "text": "门开了。\n白露: 先进去。\n",
    }


def test_compaction_preserves_blocks_and_does_not_mutate_snapshot():
    original = {"manuscript": manuscript(), "source_revision_id": "revision-a"}
    compact = compact_memory_prompt_context(original)
    assert "text" not in compact["manuscript"]
    assert compact["manuscript"]["blocks"] == original["manuscript"]["blocks"]
    assert original["manuscript"]["text"] == "门开了。\n白露: 先进去。\n"
    assert len(json.dumps(compact, ensure_ascii=False)) < len(
        json.dumps(original, ensure_ascii=False)
    )


def test_distinct_or_legacy_manuscript_text_is_kept():
    changed = manuscript()
    changed["text"] = "门悄悄开了。\n白露: 先进去。\n"
    context = {"scenes": [{"manuscript": manuscript()}, {"manuscript": changed}]}
    compact = compact_memory_prompt_context(context)
    assert "text" not in compact["scenes"][0]["manuscript"]
    assert compact["scenes"][1]["manuscript"]["text"] == changed["text"]
    assert context["scenes"][0]["manuscript"]["text"]


def test_real_provider_uses_compact_payload_for_extraction_and_sweep(monkeypatch):
    provider = LLMWritingProvider({"provider": "openai", "model": "test-model"})
    monkeypatch.setattr(provider, "_skill_system_prompt", lambda *args, **kwargs: "规则")
    prompts = []
    system_prompts = []

    def capture(system, user):
        system_prompts.append(system)
        prompts.append(user)
        return SimpleNamespace(text='{"schema_version":"memory-bundle/1.0","items":[]}')

    monkeypatch.setattr(provider, "_call_llm", capture)
    source = manuscript()
    provider.extract_memory_bundle({"manuscript": source})
    provider.sweep_memory_bundle({"scenes": [{"manuscript": source}]})
    provider.extract_memory_bundle(
        {"manuscript": source, "write_boundary": "background_proposal_only"}
    )
    payloads = [json.loads(prompt.split(": ", 1)[1]) for prompt in prompts]
    assert "text" not in payloads[0]["manuscript"]
    assert "text" not in payloads[1]["scenes"][0]["manuscript"]
    assert payloads[0]["manuscript"]["blocks"] == source["blocks"]
    assert payloads[1]["scenes"][0]["manuscript"]["blocks"] == source["blocks"]
    assert "text" not in payloads[2]["manuscript"]
    assert "episode_memory" in system_prompts[0]
    for field in ("episode_memory", "scene_state_snapshot", "open_thread", "decision_record", "target_memory_id", "scope_type", "confidence_status", "source_refs", "source_block_ids"):
        assert field in system_prompts[1]
    assert "与场景记忆提取相同" not in system_prompts[1]
    assert "episode_memory" not in system_prompts[2]
    assert "source_block_ids" in system_prompts[2]
    assert "采纳前不是正式资料" in system_prompts[2]
    assert len(system_prompts[2]) < len(system_prompts[0])
    assert source["text"] == "门开了。\n白露: 先进去。\n"
