"""Public prompt profile contracts; fixtures contain synthetic resources only."""

import hashlib
import json
from pathlib import Path

import pytest

import prompt
from director_state import (
    BEAT_REASONS,
    CONTINUITY_STATES,
    DIRECTION_REASONS,
    FOCUS_KINDS,
    RELATION_DISTANCES,
    SCENE_FUNCTIONS,
    SCENE_TYPES,
)


FIXTURE = Path(__file__).parent / "fixtures" / "direction_profiles" / "standard_prompt.json"


def test_original_prompt_matches_fixed_synthetic_input_and_output():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert prompt.build_system(**fixture["input"]) == fixture["standard_system"]
    for story_type, expected_hash in fixture["standard_rules_sha256"].items():
        assert (
            hashlib.sha256(prompt.build_rules(story_type).encode("utf-8")).hexdigest()
            == expected_hash
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "standard"), ("standard", "standard"), ("conservative", "conservative")],
)
def test_profile_accepts_only_supported_names_and_defaults_legacy_requests(value, expected):
    from direction_profiles import normalize_direction_profile

    assert normalize_direction_profile(value) == expected


@pytest.mark.parametrize(
    "value", ["", " ", "STANDARD", "standard ", "unknown", 0, 1, True, False, [], {}]
)
def test_profile_rejects_invalid_values_with_a_stable_error(value):
    from direction_profiles import normalize_direction_profile

    with pytest.raises(ValueError) as error:
        normalize_direction_profile(value)

    assert error.value.code == "invalid_direction_profile"


def test_explicit_standard_keeps_original_system_and_versioned_rules_identity():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert (
        prompt.build_system(**fixture["input"], direction_profile="standard")
        == fixture["standard_system"]
    )
    for story_type, expected_hash in fixture["standard_rules_sha256"].items():
        assert prompt.profile_snapshot("standard", story_type=story_type) == {
            "id": "standard",
            "version": "1.0",
            "rules_sha256": expected_hash,
        }
        assert prompt.build_rules(story_type, direction_profile="standard") == prompt.build_rules(
            story_type
        )


def test_conservative_system_uses_continuity_labels_and_available_backgrounds():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    text = prompt.build_system(**fixture["input"], direction_profile="conservative")

    for instruction in (
        "简洁（保守）",
        "原文一个字都不改",
        "authored=...",
        "当前角色和当前服装",
        "不重新打标、不调用识图模型",
        "没有新证据就 hold",
        "五个可见立绘站位",
        "槽 0 不是第六个立绘位",
        "优先保持已有站位和可见名单",
        "匹配度最高的有效背景",
        "不生成 bg_request，不调用图片模型",
        "资源确实缺失、损坏或非法",
        "se / bg / bgfx / trans / place",
    ):
        assert instruction in text
    for obsolete_instruction in (
        "一次表情拍通常覆盖该角色 1～2 次发言",
        "00 默认  01 平常",
        "若资源表没有准确背景，bg 留空",
        "默认用单人或双人",
        "face=05 fx=特写 bgfx=集中线",
        "只能标 se / wait / bg",
    ):
        assert obsolete_instruction not in text
    assert "03=平静｜认真倾听" in text
    assert "07=微笑｜安心回应" in text
    assert "未选服装专用标签" not in text
    assert "未出场角色专用标签" not in text
    assert len(text) < len(fixture["standard_system"])


def test_conservative_prompt_preserves_validated_protocol_nesting_and_enums():
    rules = prompt.build_rules(direction_profile="conservative")

    for field, values in (
        ("scene_type", SCENE_TYPES),
        ("scene_function", SCENE_FUNCTIONS),
        ("focus_kind", FOCUS_KINDS),
        ("relation_distance", RELATION_DISTANCES),
        ("direction.reason", DIRECTION_REASONS),
        ("beat.reason", BEAT_REASONS),
    ):
        assert f"{field} 只使用：" + " / ".join(values) in rules
    assert "分层使用：" + " / ".join(CONTINUITY_STATES) in rules
    assert "是行级演出字段，与 i 同级，不能放进 d/direction" in rules
    assert "必须放在 d/direction 内，不能与 i 平级" in rules
    assert "wait_ms 只属于 beat" in rules
    assert "每条记忆必须引用本轮可见的 source_id" in rules
    assert "紧凑协议只返回真正发生变化的行" in rules


@pytest.mark.parametrize("story_type", ["auto", "main", "event", "bond"])
def test_profile_snapshot_identifies_the_selected_rules_without_shared_mutable_state(story_type):
    conservative = prompt.profile_snapshot("conservative", story_type=story_type)
    rules = prompt.build_rules(story_type, direction_profile="conservative")

    assert conservative == {
        "id": "conservative",
        "version": "1.0",
        "rules_sha256": hashlib.sha256(rules.encode("utf-8")).hexdigest(),
    }
    assert (
        conservative["rules_sha256"]
        != prompt.profile_snapshot("standard", story_type=story_type)["rules_sha256"]
    )
    conservative["id"] = "changed-by-caller"
    assert prompt.profile_snapshot("conservative", story_type=story_type)["id"] == "conservative"


def test_invalid_profile_cannot_reach_any_prompt_assembly_entry():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value = "unknown-private-setting"

    for build in (prompt.build_rules, prompt.profile_snapshot):
        with pytest.raises(ValueError) as error:
            build(direction_profile=value)
        assert error.value.code == "invalid_direction_profile"
        assert value not in str(error.value)
    for build in (prompt.build_resources, prompt.build_system):
        with pytest.raises(ValueError) as error:
            build(**fixture["input"], direction_profile=value)
        assert error.value.code == "invalid_direction_profile"
        assert value not in str(error.value)
