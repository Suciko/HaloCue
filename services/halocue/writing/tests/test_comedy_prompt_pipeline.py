"""Check shipped rules at the model boundary, not the small synthetic test pack."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from halocue_writing.ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
from halocue_writing.providers import LLMWritingProvider
from halocue_writing.repository import Repository
from halocue_writing.workflow_pack import COMEDY_RULE_SOURCE, PACK_VERSION


@pytest.fixture
def prompt_assembler(tmp_path):
    shipped = Path(__file__).resolve().parents[1] / "skill" / "ba-writing"
    registry = BaWritingSkillRegistry(shipped)
    assert registry.materialize(Repository(tmp_path / "data"))["status"] == "ready"
    return BaWritingPromptAssembler(registry)


@pytest.mark.parametrize(
    "stage", ["discussion", "blueprint", "structure", "chapter", "draft", "rewrite", "review"]
)
@pytest.mark.parametrize(
    "direction", ["短篇整活：节能借口逐步翻车，最后回收", "认真剧情：保留克制，不要添加笑话"]
)
def test_shipped_stage_rules_reach_provider_and_keep_author_direction(
    prompt_assembler, monkeypatch, stage, direction
):
    provider = LLMWritingProvider({"provider": "openai", "model": "fixture"}, prompt_assembler)
    captured = []
    output = (
        "角色甲: 这是测试返回，不是质量评测。"
        if stage in {"draft", "rewrite"}
        else json.dumps({"text": "测试", "findings": []})
    )

    def call(system, user, **kwargs):
        captured.append((system, user))
        return SimpleNamespace(text=output, tool_calls=())

    monkeypatch.setattr(provider, "_call_llm", call)
    context = {
        "idea": direction,
        "brief": {"mode": "long_comedy", "idea": direction},
        "scene_contract": {"goal": direction},
        "scene_writing_pack": {
            "schema_version": "scene-writing-pack/1.0",
            "digest": "sha256:synthetic-scene",
            "author_instruction": direction,
        },
    }
    before = copy.deepcopy(context)
    messages = [{"role": "user", "text": direction}]
    if stage == "discussion":
        provider.discuss_work(messages, context)
    elif stage == "blueprint":
        provider.generate_blueprint(context)
    elif stage == "structure":
        provider.generate_structure_plan(messages, context)
    elif stage == "chapter":
        provider.generate_chapter_plan(messages, context)
    elif stage == "draft":
        provider.generate_scene(context)
    elif stage == "rewrite":
        provider.rewrite_scene(context, "角色甲: 原稿。", direction)
    else:
        provider.review_scene(context, "角色甲: 原稿。")
    assert context == before
    assert len(captured) == 1
    system, user = captured[0]
    assert "# 二创喜剧与传播" in system
    assert "回收同一个梗时改变处境" in system
    assert "不强塞笑话" in system
    assert direction in user
    if stage == "discussion":
        assert "梗和尺度要传给大纲与正文" in system
        assert "# Writer" not in system
    elif stage in {"structure", "chapter", "blueprint"}:
        assert "不规定行动数量" in system
    elif stage == "review":
        assert "不因词面命中就退回" in system
    else:
        assert "约定的笑点回收也是必要兑现" in system
        assert "不要补主题回扣" not in system


def test_edit_and_release_review_share_rules_but_memory_does_not_create_jokes(prompt_assembler):
    for task, output in [
        ("scene.draft.rewrite", "edit_patch"),
        ("release.review", "review_findings"),
    ]:
        assembled = prompt_assembler.assemble(task, output_mode=output)
        assert assembled["status"] == "ready"
        assert assembled["pack_version"] == PACK_VERSION
        assert COMEDY_RULE_SOURCE in assembled["source_files"]
    memory = prompt_assembler.assemble("memory.sweep")
    assert COMEDY_RULE_SOURCE not in memory["source_files"]


def test_missing_comedy_source_cannot_silently_use_partial_stage_rules(prompt_assembler, tmp_path):
    root = tmp_path / "incomplete"
    root.mkdir()
    (root / "SKILL.md").write_text("# Synthetic", encoding="utf-8")
    discussion = root / "knowledge" / "创作讨论.md"
    discussion.parent.mkdir()
    discussion.write_text("# Synthetic discussion", encoding="utf-8")
    missing = BaWritingPromptAssembler(BaWritingSkillRegistry(root)).assemble(
        "brief.build", output_mode="discussion_json"
    )
    assert missing["status"] == "unavailable"
    assert missing["missing_files"] == [COMEDY_RULE_SOURCE]
