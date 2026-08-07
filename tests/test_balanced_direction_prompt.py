from annotate import SCHEMA, build_batch_context
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
