from pathlib import Path

from halocue_writing.ba_skill_runtime import BaWritingPromptAssembler, BaWritingSkillRegistry
from halocue_writing.repository import Repository
from halocue_writing.workflow_pack import COMMON_RULES, MODE_SOURCES, WORKFLOW_RULE_SOURCES


def _write_skill(root: Path, *, omit: str | None = None, full_pack: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    logical_paths = ["SKILL.md", *COMMON_RULES, MODE_SOURCES["main_battle"], "knowledge/老师在场规则.md"]
    if full_pack:
        logical_paths = [
            path for sources in WORKFLOW_RULE_SOURCES.values() for path in sources
        ] + list(MODE_SOURCES.values()) + ["knowledge/老师在场规则.md"]
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
