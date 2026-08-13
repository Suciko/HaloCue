from annotate import SCHEMA, build_batch_context
import prompt
from director_state import (
    BEAT_REASONS,
    DIRECTION_REASONS,
    RELATION_DISTANCES,
    SCENE_FUNCTIONS,
)
from prompt import build_rules


def test_prompt_coordinates_direction_dimensions_and_explains_boundaries():
    rules = build_rules()

    for phrase in (
        "先判断这一句的情绪阶段、身体反应和镜头重点",
        "Dot / 沉默",
        "Exclaim / 惊叹",
        "Steam / 冒烟",
        "动作 act 是原地身体反应",
        "走位 move 是人物真实位置变化",
        "普通感叹号不能单独触发 jump",
    ):
        assert phrase in rules


def test_prompt_allows_semantic_comedy_reaction_chains_without_blanket_caps():
    rules = build_rules()

    assert "一段 10 行最多 2-3 个" not in rules
    assert "任意两句相邻对白绝不连续使用气泡" not in rules
    assert "喜剧连击" in rules
    assert "连续使用气泡" in rules
    assert "持续而外显的兴奋或愤怒爆发" in rules
    assert "结巴、掩饰、反讽" in rules
    assert "！？" in rules


def test_prompt_reserves_wait_for_schema_backed_dialogue_free_beats():
    rules = build_rules()

    assert "Schema 包含 beats" in rules
    assert "独立无台词反应" in rules
    assert "普通对白" in rules
    assert "wait_ms" in rules


def test_prompt_uses_official_style_dialogue_actions_as_character_performance():
    rules = build_rules("bond")

    assert "不要求原文先写出“跳了一下”" in rules
    assert "强烈反驳" in rules
    assert "突然自信" in rules
    assert "卡壳、紧张、羞涩" in rules
    assert "台词本身就是身体反应的证据" in rules
    assert "physical_reaction" in rules


def test_batch_context_includes_recent_emoticon_and_action_choices():
    items = [
        {
            "kind": "line",
            "who": "凯伊",
            "text": "不行。",
            "face": "05",
            "emo": "冒烟",
            "act": "jump",
        }
    ]

    context = build_batch_context(items, [0])

    assert "face=05" in context
    assert "emo=冒烟" in context
    assert "act=jump" in context


def test_annotation_schema_uses_the_real_direction_contract():
    fields = SCHEMA["properties"]["lines"]["items"]["properties"]

    assert "瞬时心理反应" in fields["emo"]["description"]
    assert "原地身体反应" in fields["act"]["description"]
    assert "真实位置变化" in fields["move"]["description"]
    assert "通讯 / 黑屏剪影 / 特写" in fields["fx"]["description"]


def test_prompt_limits_long_term_memory_to_evidence_backed_events():
    rules = build_rules()
    assert "memory_events" in rules
    assert "原样摘录" in rules
    assert "不能把猜测升级为事实" in rules
    assert "普通表情变化" in rules


def test_prompt_contains_story_modes_scene_functions_and_continuity():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    text = prompt.build_system(idx, {}, [], {}, story_type="event")

    assert "main / event / bond" in text
    assert "喜剧升级" in text and "情绪转折" in text
    assert "listener" in text and "offscreen_space" in text
    assert "start / hold / escalate / end" in text
    assert "不要按固定次数、比例或每 N 行配额" in text
    assert "每次有立绘角色发言" in text
    assert "一次表情拍通常覆盖该角色 1～2 次发言" in text
    assert "同一 face 不重复输出" in text
    assert "authored=..." in text


def test_prompt_forbids_mechanical_face_rotation_and_dialogue_rewrite():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    text = prompt.build_system(idx, {}, [], {}, story_type="bond")

    assert "不要为了画面变化而换 face" in text
    assert "一个字都不改" in text
    assert "优先选择一个与上一句不同" not in text


def test_each_story_mode_receives_a_distinct_directing_priority():
    idx = {"enums": {"emoticon": {}, "action": {}}, "sounds": [], "bg": {}}
    main = prompt.build_system(idx, {}, [], {}, story_type="main")
    event = prompt.build_system(idx, {}, [], {}, story_type="event")
    bond = prompt.build_system(idx, {}, [], {}, story_type="bond")

    assert "画外动作" in main
    assert "群体同步" in event
    assert "关系距离" in bond
    assert len({main, event, bond}) == 3


def test_prompt_defines_scene_sequences_emotion_chains_and_reason_contract():
    rules = build_rules("bond")

    for scene_function in (
        "建立场景", "日常对话", "喜剧升级", "情绪转折", "信息揭示",
        "做出决定", "动作事件", "转场", "余波",
    ):
        assert scene_function in rules
    assert rules.count("触发：") >= 9
    assert rules.count("序列：") >= 9
    assert rules.count("禁用：") >= 9
    assert rules.count("退出：") >= 9
    assert "平静 → 注意 → 疑惑 → 确认 → 释然" in rules
    assert "direction.reason" in rules
    assert "短枚举值" in rules


def test_prompt_director_values_match_the_validated_protocol_enums():
    rules = build_rules("main")

    assert "scene_function 只使用：" + " / ".join(SCENE_FUNCTIONS) in rules
    assert "relation_distance 只使用：" + " / ".join(RELATION_DISTANCES) in rules
    assert "direction.reason 只使用：" + " / ".join(DIRECTION_REASONS) in rules
    assert "beat.reason 只使用：" + " / ".join(BEAT_REASONS) in rules
    assert "confrontational" not in rules
