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
