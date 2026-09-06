from pathlib import Path

from halocue_writing.ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
from halocue_writing.repository import Repository
from halocue_writing.workflow_pack import (
    COMMON_RULES,
    ENGINE_RULE_SOURCE,
    MODE_SOURCES,
    WORKFLOW_RULE_SOURCES,
)


def _write_skill(root: Path, *, omit: str | None = None, full_pack: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    logical_paths = ["SKILL.md", *COMMON_RULES, MODE_SOURCES["main_battle"], "knowledge/老师在场规则.md"]
    if full_pack:
        logical_paths = [
            path for sources in WORKFLOW_RULE_SOURCES.values() for path in sources
        ] + list(MODE_SOURCES.values()) + ["knowledge/老师在场规则.md", ENGINE_RULE_SOURCE]
    for logical_path in dict.fromkeys(logical_paths):
        if logical_path == omit:
            continue
        path = root / logical_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {logical_path}\n规则来源测试。\n", encoding="utf-8")


def test_registry_compiles_only_the_current_mode_and_records_source_digest(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root)

    runtime = BaWritingSkillRegistry(skill_root).compile("main_battle", has_sensei=True)

    assert runtime["status"] == "ready"
    assert runtime["mode_key"] == "main_battle"
    assert runtime["source_digest"]
    assert [item["path"] for item in runtime["required_files"]] == [
        "SKILL.md",
        *COMMON_RULES,
        MODE_SOURCES["main_battle"],
        "knowledge/老师在场规则.md",
    ]
    assert all(item["status"] == "available" for item in runtime["required_files"])


def test_registry_fails_closed_when_selected_mode_source_is_missing(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root, omit=MODE_SOURCES["main_battle"])

    runtime = BaWritingSkillRegistry(skill_root).compile("main_battle")

    assert runtime["status"] == "unavailable"
    assert runtime["missing_files"] == [MODE_SOURCES["main_battle"]]


def test_materialized_pack_is_immutable_and_prompt_loads_one_mode(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root, full_pack=True)
    repo = Repository(tmp_path / "data")
    registry = BaWritingSkillRegistry(skill_root)

    manifest = registry.materialize(repo)
    assembled = BaWritingPromptAssembler(registry).assemble(
        "scene.draft.generate", mode_key="bond_short", has_sensei=True
    )

    assert manifest["status"] == "ready"
    assert manifest["manifest_uri"].endswith("manifest.json")
    assert repo.read_text(manifest["manifest_uri"])
    assert assembled["status"] == "ready"
    assert MODE_SOURCES["bond_short"] in assembled["source_files"]
    assert MODE_SOURCES["main_battle"] not in assembled["source_files"]
    assert "只生成一个候选" in assembled["system_prompt"]

    original_digest = registry.compile("bond_short", task_id="scene.draft.generate")["source_digest"]
    (skill_root / MODE_SOURCES["bond_short"]).write_text("# 已在外部修改\n", encoding="utf-8")
    pinned = registry.compile("bond_short", task_id="scene.draft.generate")
    assert pinned["source_digest"] == original_digest


def test_default_test_skill_is_complete_without_private_local_files(tmp_path):
    registry = BaWritingSkillRegistry()
    manifest = registry.materialize(Repository(tmp_path / "data"))
    assembled = BaWritingPromptAssembler(registry).assemble(
        "scene.draft.generate", mode_key="bond_short"
    )

    assert manifest["status"] == "ready"
    assert assembled["status"] == "ready"
    assert assembled["missing_files"] == []
    assert "Only for deterministic contract tests." in assembled["system_prompt"]


def test_scene_request_injects_only_matching_conditional_writing_guidance(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root, full_pack=True)
    repo = Repository(tmp_path / "data")
    registry = BaWritingSkillRegistry(skill_root)
    registry.materialize(repo)
    assembler = BaWritingPromptAssembler(registry)
    context = {
        "brief": {"mode": "bond_short"},
        "rules": {"mode_key": "bond_short"},
        "scene_contract": {
            "emotion_delta": "被击中后兴奋失控",
            "ending_payoff": "事后道歉并为失态收场",
            "information_ownership": {"画面": ["提示灯闪烁"]},
            "exchange_chain": [{"trigger": "提示灯闪烁", "responder": "爱丽丝", "change": "停止触碰"}],
            "literary_voice_variant": "literary_voice_v4_5",
            "render_mode": "text_reading",
        },
        "scene_writing_pack": {
            "schema_version": "scene-writing-pack/1.0",
            "digest": "sha256:scene-fixture",
        },
    }

    request = assembler.assemble_scene_request("scene.draft.generate", context)

    assert request["status"] == "ready"
    assert request["output_mode"] == "text_reading"
    assert len(request["conditional_guidance"]) == 6
    assert "短句爆破" in request["system_prompt"]
    assert "道歉只针对一个具体行为" in request["system_prompt"]
    assert "纯听见确认不单独占一轮" in request["system_prompt"]
    assert "official_script" not in request["system_prompt"].split("本场条件化写作规则", 1)[-1]


def test_scene_request_does_not_inject_untriggered_safety_rules(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root, full_pack=True)
    repo = Repository(tmp_path / "data")
    registry = BaWritingSkillRegistry(skill_root)
    registry.materialize(repo)
    request = BaWritingPromptAssembler(registry).assemble_scene_request(
        "scene.draft.generate",
        {
            "brief": {"mode": "bond_short"},
            "scene_contract": {"emotion_delta": "平静转为有限合作"},
            "scene_writing_pack": {
                "schema_version": "scene-writing-pack/1.0",
                "digest": "sha256:scene-fixture",
            },
        },
    )

    assert request["conditional_guidance"] == []
    assert "短句爆破" not in request["system_prompt"]
    assert "道歉只针对一个具体行为" not in request["system_prompt"]


def test_planning_prompts_keep_brief_and_blueprint_out_of_formal_writing(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root, full_pack=True)
    registry = BaWritingSkillRegistry(skill_root)
    registry.materialize(Repository(tmp_path / "data"))
    assembler = BaWritingPromptAssembler(registry)

    brief = assembler.assemble("brief.build", mode_key="bond_short", output_mode="discussion_json")
    blueprint = assembler.assemble("blueprint.generate", mode_key="bond_short", output_mode="story_blueprint_json")

    assert "不写正文" in brief["system_prompt"]
    assert "一次最多提出两个" in brief["system_prompt"]
    assert "只选择一个主写作模式" in brief["system_prompt"]
    assert brief["output_mode"] == "discussion_json"
    assert "只整理 StoryBlueprint 候选" in blueprint["system_prompt"]
    assert "不得把推断升格为事实" in blueprint["system_prompt"]
    assert "Provider、Run、Revision" in blueprint["system_prompt"]


def test_engine_script_requires_skill_contract_and_fails_closed(tmp_path):
    skill_root = tmp_path / "ba-writing"
    _write_skill(skill_root, full_pack=True, omit=ENGINE_RULE_SOURCE)
    repo = Repository(tmp_path / "data")
    registry = BaWritingSkillRegistry(skill_root)
    registry.materialize(repo)
    assembler = BaWritingPromptAssembler(registry)
    context = {
        "brief": {"mode": "bond_short"},
        "scene_contract": {"render_mode": "engine_script"},
        "scene_writing_pack": {
            "schema_version": "scene-writing-pack/1.0",
            "digest": "sha256:scene-fixture",
        },
    }

    request = assembler.assemble_scene_request("scene.draft.generate", context)

    assert request["status"] == "unavailable"
    assert ENGINE_RULE_SOURCE in request["missing_files"]
