import json
from pathlib import Path

import tables
from annotate import (
    build_batch_context,
    build_face_usage_summary,
    build_static,
    normalize_contextual_sounds,
    normalize_emoticon_density,
)
from direction_rules import infer_direction_cues, normalize_direction_density
from camera import plan_camera
from dialogue_pacing import split_strong_dialogue_items
from performance_rules import enforce_focusline_shots, enforce_persistent_closeups
from script2aap import build, load_cast
from prompt import build_rules


ROOT = Path(__file__).resolve().parents[1]


def test_semantic_direction_cues_cover_comedy_reaction_examples():
    assert infer_direction_cues("所以我才想问，你为什么已经到了！？")["emo"] == "惊叹"
    assert infer_direction_cues("被天气、路线、店铺营业时间……淘汰了。") ["emo"] == "冒烟"
    assert infer_direction_cues("当然吃！不然不是浪费吗！只是……")["act"] == "jump"


def test_hophop_is_preserved_for_an_escalating_steam_sequence():
    items = [
        {"kind": "line", "who": "凯伊", "emo": "冒烟"},
        {"kind": "line", "who": "凯伊", "emo": "冒烟", "act": "hophop"},
    ]

    normalize_direction_density(items)

    assert items[1]["emo"] == "冒烟"
    assert items[1]["act"] == "hophop"


def test_adjacent_distinct_comedy_emoticons_are_preserved():
    items = [
        {"kind": "line", "who": "凯伊", "emo": "惊叹"},
        {"kind": "line", "who": "凯伊", "emo": "冒烟"},
    ]

    normalize_direction_density(items)

    assert items[0]["emo"] == "惊叹"
    assert items[1]["emo"] == "冒烟"


def _script(names, *, bg_effect=0, shapes=None, speaker_slot=0):
    shapes = shapes or {}
    chars = []
    for slot in range(6):
        name = names.get(slot, "")
        chars.append({
            "name": name,
            "shapeOverride": shapes.get(slot, 0),
        })
    return {
        "bgEffect": bg_effect,
        "characters": {"$values": chars},
        "speakerSlotNum": speaker_slot,
    }


def test_focusline_is_removed_from_a_side_closeup_without_mutating_the_cast():
    script = _script(
        {1: "kei", 3: "momoi"},
        bg_effect=tables.BGEFFECT["BG_FocusLine"],
        shapes={1: 4},
        speaker_slot=1,
    )

    enforce_focusline_shots([script])

    assert script["bgEffect"] == 0
    assert script["characters"]["$values"][1]["name"] == "kei"
    assert script["characters"]["$values"][1]["shapeOverride"] == 4
    assert script["characters"]["$values"][3]["name"] == "momoi"


def test_focusline_is_removed_when_the_center_character_is_not_already_closeup():
    script = _script(
        {3: "kei"},
        bg_effect=tables.BGEFFECT["BG_FocusLine"],
        shapes={3: 1},
    )

    enforce_focusline_shots([script])

    assert script["bgEffect"] == 0
    assert script["characters"]["$values"][3]["shapeOverride"] == 1


def test_focusline_is_kept_only_for_an_existing_centered_solo_closeup():
    script = _script(
        {3: "kei"},
        bg_effect=tables.BGEFFECT["BG_FocusLine"],
        shapes={3: 5},
        speaker_slot=3,
    )

    enforce_focusline_shots([script])

    assert script["bgEffect"] == tables.BGEFFECT["BG_FocusLine"]
    assert script["characters"]["$values"][3]["shapeOverride"] == 5


def test_closeup_persists_until_the_focal_character_leaves_the_shot():
    scripts = [
        _script({2: "kei"}, shapes={2: 4}, speaker_slot=2),
        _script({2: "kei"}, speaker_slot=2),
        _script({2: "kei", 4: "momoi"}, speaker_slot=4),
        _script({4: "momoi"}, speaker_slot=4),
        _script({2: "kei"}, speaker_slot=2),
    ]

    enforce_persistent_closeups(scripts)

    assert [row["characters"]["$values"][2]["shapeOverride"] for row in scripts[:3]] == [4, 4, 4]
    assert scripts[3]["characters"]["$values"][4]["shapeOverride"] == 0
    assert scripts[4]["characters"]["$values"][2]["shapeOverride"] == 0


def test_scene_break_clears_previous_cast_before_the_next_speaker():
    shots = plan_camera([
        {"speaker": "momoi", "text": "记下来！"},
        {"speaker": "kei", "text": "不许记。"},
        {"speaker": None, "text": "两人在河堤坐下。", "scene_break": True},
        {"speaker": "kei", "text": "开始总结。"},
    ])

    assert shots[2] == []
    assert shots[3] == ["kei"]


def test_first_portrait_dialogue_fades_even_after_opening_narration():
    events = [
        {
            "k": "line", "who": "旁白", "text": "商店街入口。",
            "face": None, "emo": None, "act": None, "fx": None, "no": 1,
        },
        {
            "k": "line", "who": "凯伊", "text": "你来早了。",
            "face": None, "emo": None, "act": None, "fx": None, "no": 2,
        },
    ]
    cast = {
        "旁白": {"narrator": True},
        "凯伊": {"id": "kei", "portrait": True},
    }
    idx = {
        "bg": {"BG_Black": 0},
        "sounds": [],
        "characters": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    scenes = build(events, {"default_bg": "BG_Black"}, cast, idx, "Demo")
    kei = next(
        character
        for character in scenes[0][1][1]["characters"]["$values"]
        if character["name"] == "kei"
    )

    assert kei["appear"] == 3


def test_strong_emotional_dialogue_splits_at_existing_em_dash_without_rewriting():
    text = (
        "不要念出来！！这是调月莉央擅自加装的多余功能——"
        "你忘掉刚才看到的东西！现在！立刻！"
    )
    items = [{
        "kind": "line", "who": "凯伊", "text": text, "raw": f"凯伊: {text}",
        "face": None, "emo": None, "act": None, "fx": None,
    }]

    result = split_strong_dialogue_items(
        items, {"凯伊": {"portrait": True, "narrator": False}}
    )

    assert [item["text"] for item in result] == [
        "不要念出来！！这是调月莉央擅自加装的多余功能——",
        "你忘掉刚才看到的东西！现在！立刻！",
    ]
    assert "".join(item["text"] for item in result) == text


def test_emoticons_are_never_consecutive_and_shy_has_a_longer_cooldown():
    items = [
        {"kind": "line", "emo": "脸红"},
        {"kind": "line", "emo": "冷汗"},
        {"kind": "line"},
        {"kind": "line", "emo": "脸红"},
        *({"kind": "line"} for _ in range(7)),
        {"kind": "line", "emo": "脸红"},
    ]

    normalize_emoticon_density(items)

    assert items[0]["emo"] == "脸红"
    assert "emo" not in items[1]
    assert "emo" not in items[3]
    assert items[-1]["emo"] == "脸红"


def test_opening_arrival_gets_one_real_footstep_sound_from_the_index():
    items = [
        {
            "kind": "line", "who": "旁白",
            "text": "商店街入口，凯伊已经站在那里等候。",
        },
        {"kind": "line", "who": "老师", "text": "咦，这么早。"},
        {"kind": "line", "who": "凯伊", "text": "你怎么已经来了。"},
    ]

    normalize_contextual_sounds(items, {"sounds": ["SE_FootStep_01"]})

    assert items[1]["se"] == "SE_FootStep_01"
    assert "se" not in items[2]


def test_box_rustle_and_character_reveal_get_registered_contextual_sounds():
    items = [
        {"kind": "line", "who": "旁白", "text": "纸箱里传出压低的说话声。"},
        {"kind": "line", "who": "旁白", "text": "桃井突然从纸箱后探出头。"},
    ]
    idx = {"sounds": ["SE_BoxShake_01", "SE_Appear_01a"]}

    normalize_contextual_sounds(items, idx)

    assert items[0]["se"] == "SE_BoxShake_01"
    assert items[1]["se"] == "SE_Appear_01a"


def test_contextual_sound_fallback_never_overwrites_the_models_registered_choice():
    items = [{
        "kind": "line",
        "who": "旁白",
        "text": "纸箱里传出窸窸窣窣的声音。",
        "se": "SE_Clothes_01",
    }]

    normalize_contextual_sounds(
        items, {"sounds": ["SE_BoxShake_01", "SE_Clothes_01"]}
    )

    assert items[0]["se"] == "SE_Clothes_01"


def test_expression_prompt_prefers_a_suitable_change_and_keeps_only_as_fallback():
    rules = build_rules()

    assert "优先选择一个与上一句不同、又符合当前语义的已标注表情" in rules
    assert "即使相邻台词的情绪接近" in rules
    assert "实在没有其他合适候选时，才保持上一表情" in rules
    assert "不要为了变化而换成明显不合语境的表情" in rules


def test_expression_prompt_treats_usage_context_as_guidance_not_trigger():
    rules = build_rules()

    assert "使用语境是候选提示，不是关键词触发规则" in rules
    assert "不能仅凭脸红、泪水等视觉现象决定表情" in rules
    assert "没有完美差分时" in rules

    idx = {
        "bg": {},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
        "characters": [{
            "identifier": "kei",
            "faces": [],
            "expression_mode": "opaque_custom",
        }],
        "face_capabilities": {
            "kei": [{
                "spine_signature": "sig",
                "outfit_key": "date",
                "faces": [{
                    "id": "37",
                    "semantic_cn": "克制不满｜冷淡反驳、忍着不发作",
                    "sources": ["aa_verified", "vision:model"],
                }],
            }],
        },
    }
    cast = {"凯伊": {
        "id": "kei", "portrait": True,
        "spine_signature": "sig", "outfit_key": "date",
    }}

    text = build_static(idx, cast, ["凯伊"])

    assert "37=克制不满｜冷淡反驳、忍着不发作" in text


def test_custom_expression_table_overrides_official_common_face_numbers():
    rules = build_rules()

    assert "角色资源表中的逐编号语义优先" in rules
    assert "自定义骨骼不一定遵循 00-06 通用含义" in rules


def test_batch_context_exposes_recent_face_choices_and_usage_to_the_model():
    items = [
        {"kind": "line", "who": "桃井", "text": "第一句", "face": "03", "emo": "音符"},
        {"kind": "line", "who": "凯伊", "text": "第二句", "face": "14"},
        {"kind": "line", "who": "桃井", "text": "第三句", "face": "04"},
    ]

    text = build_batch_context(items, [0, 1, 2])

    assert "桃井: 第三句（face=04" in text
    assert "桃井近期 face 使用：03×1、04×1" in text
    assert "桃井本章已用 face：03×1、04×1" in build_face_usage_summary(items, [0, 1, 2])


def test_model_resource_table_hides_verified_but_unlabeled_official_faces():
    idx = {
        "bg": {},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
        "characters": [{"identifier": "momoi", "expression_mode": "opaque_custom"}],
        "face_capabilities": {
            "momoi": [{
                "spine_signature": "",
                "outfit_key": "",
                "faces": [
                    {"id": "03", "label": "smile", "sources": ["aa_verified"]},
                    {"id": "07", "label": "", "sources": ["aa_verified"]},
                ],
            }],
        },
    }
    cast = {"桃井": {"id": "momoi", "portrait": True}}

    text = build_static(idx, cast, ["桃井"])
    resource_line = next(line for line in text.splitlines() if line.startswith("- 桃井"))

    assert "03=smile" in resource_line
    assert "07" not in resource_line


def test_date_outfit_uses_canonical_display_name_and_club_alias(
    synthetic_cast_path,
):
    _, loaded_cast, _ = load_cast(synthetic_cast_path)
    cast = loaded_cast["凯伊"]

    assert cast["name"] == "凯伊"
    assert cast["club"] == "特殊现象调查部"
