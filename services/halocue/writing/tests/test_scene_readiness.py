from halocue_writing.providers import FakeWritingProvider
from halocue_writing.scene_readiness import build_scene_readiness
from halocue_writing.service import WritingService


class RealTestProvider(FakeWritingProvider):
    is_simulation = False


def create_scene(service: WritingService, *, characters: list[str]) -> tuple[str, str, dict]:
    work = service.create_work({"title": "SceneReadiness 测试"})
    brief = service.save_brief(
        work["id"],
        {
            "expected_version": work["version"],
            "idea": "深夜活动室里的旧机器突然启动。",
            "mode": "bond_short",
            "characters": characters,
        },
    )
    blueprint = service.generate_blueprint(
        work["id"], {"expected_version": brief["work"]["version"]}
    )
    chapter = service.create_chapter(
        work["id"],
        {"expected_version": blueprint["work"]["version"], "title": "第一章"},
    )
    scene = service.create_scene(
        work["id"],
        chapter["chapter_id"],
        {
            "expected_version": chapter["work"]["version"],
            "title": "提示灯",
            "location": "游戏开发部活动室",
            "goal": "确认异常来源",
        },
    )
    return work["id"], scene["scene_id"], scene["work"]


def test_readiness_builder_reports_each_blocker_with_stable_schema():
    readiness = build_scene_readiness(
        provider=FakeWritingProvider().descriptor(),
        skill_runtime={"status": "unavailable", "missing_files": ["agents/writer.md"]},
        runtime_character_cards=[],
        missing_runtime_character_cards=[],
        explicit_character_selection=False,
    )

    assert readiness["schema_version"] == "scene-readiness/1.0"
    assert readiness["can_run"] is False
    assert readiness["context_ready"] is True
    assert readiness["provider_ready"] is False
    assert readiness["skill_ready"] is False
    assert readiness["runtime_cards_ready"] is False
    assert [item["code"] for item in readiness["blocking_reasons"]] == [
        "runtime_character_cards_not_ready",
        "ba_writing_skill_not_ready",
        "writing_provider_not_ready",
    ]
    assert readiness["reason"] == "本场没有可用的已确认运行时人物卡。"
    assert "人物卡已就绪" not in readiness["reason"]


def test_assemble_context_zero_cards_never_claims_runtime_cards_are_ready(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, _work = create_scene(service, characters=[])

    readiness = service.assemble_context(work_id, scene_id)["readiness"]

    assert readiness["schema_version"] == "scene-readiness/1.0"
    assert readiness["context_ready"] is True
    assert readiness["skill_ready"] is True
    assert readiness["runtime_cards_ready"] is False
    assert readiness["provider_ready"] is False
    assert readiness["can_run"] is False
    assert readiness["reason"] == "本场没有可用的已确认运行时人物卡。"
    assert readiness["real_ba_writing"] == "blocked"


def test_assemble_context_keeps_legacy_fields_while_exposing_provider_blocker(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_scene(service, characters=["爱丽丝"])
    service.save_character_card(
        work_id,
        {
            "expected_version": work["version"],
            "name": "爱丽丝",
            "voice_anchors": ["先确认眼前的情况。"],
            "ooc_constraints": ["不替其他人猜测动机"],
            "source_refs": ["用户确认"],
        },
    )

    readiness = service.assemble_context(work_id, scene_id)["readiness"]

    assert readiness["runtime_cards_ready"] is True
    assert readiness["skill_ready"] is True
    assert readiness["provider_ready"] is False
    assert readiness["can_run"] is False
    assert [item["code"] for item in readiness["blocking_reasons"]] == [
        "writing_provider_not_ready"
    ]
    assert readiness["fake_provider"] == "ready"
    assert readiness["real_ba_writing"] == "ready_for_provider"
    assert readiness["skill_source"] == "ready"
    assert readiness["missing_runtime_character_cards"] == []


def test_assemble_context_can_run_when_all_readiness_dimensions_are_true(tmp_path):
    service = WritingService(tmp_path)
    work_id, scene_id, work = create_scene(service, characters=["爱丽丝"])
    service.save_character_card(
        work_id,
        {
            "expected_version": work["version"],
            "name": "爱丽丝",
            "voice_anchors": ["先确认眼前的情况。"],
            "ooc_constraints": ["不替其他人猜测动机"],
            "source_refs": ["用户确认"],
        },
    )
    service.provider = RealTestProvider()

    readiness = service.assemble_context(work_id, scene_id)["readiness"]

    assert readiness["schema_version"] == "scene-readiness/1.0"
    assert readiness["can_run"] is True
    assert readiness["context_ready"] is True
    assert readiness["provider_ready"] is True
    assert readiness["skill_ready"] is True
    assert readiness["runtime_cards_ready"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["reason"] == "本场上下文、运行时人物卡、Skill 与真实模型 Provider 均已就绪。"
