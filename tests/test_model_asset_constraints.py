import prompt
from annotate import SCHEMA


def test_prompt_exposes_chinese_labels_but_requires_real_asset_keys():
    index = {
        "bg": {"custom-night": 123},
        "bg_label": {
            "custom-night": {
                "label": "夜晚办公室",
                "place": "室内",
                "time": "夜晚",
                "mood": "安静",
                "tags": "办公室,夜景",
            }
        },
        "sounds": ["custom-bell"],
        "sound_label": {
            "custom-bell": {"label": "门铃声", "tags": "门口,提示"}
        },
        "enums": {"emoticon": {}, "action": {}},
    }

    text = prompt.build_resources(index, {}, [], {})

    assert "custom-bell=门铃声" in text
    assert "custom-night=夜晚办公室" in text
    assert "等号左侧的真实标识" in text


def test_scene_prompt_uses_compact_reuse_semantics_not_human_search_terms():
    index = {
        "bg": {"BG_TrinityHall": 1},
        "bg_label": {"BG_TrinityHall": {
            "label": "哥特式礼堂",
            "main_category_cn": "校园",
            "subcategory": "礼堂",
            "place": "学院礼堂",
            "affiliation_names_cn": ["崔尼蒂"],
            "reuse_scope_cn": "有限跨阵营复用",
            "compatible_affiliation_names_cn": ["阿里乌斯"],
            "usage_hint_cn": "适合庄重集会",
            "avoid_when_cn": "不适合现代科技场景",
            "search_terms_cn": ["这个词只给人类检索"],
        }},
        "scene_labels": {"background": {"BG_TrinityHall": {
            "visual_kind": "background", "dialogue_suitable": True,
            "status": "ready",
        }}},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    text = prompt.build_resources(index, {}, [], {})

    assert "归属:崔尼蒂" in text
    assert "复用:有限跨阵营复用(阿里乌斯)" in text
    assert "适合庄重集会" in text
    assert "这个词只给人类检索" not in text


def test_prompt_describes_combinable_character_effects():
    index = {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}}

    text = prompt.build_resources(index, {}, [], {})

    assert "通讯" in text
    assert "黑屏剪影" in text
    assert "可叠加" in text


def test_prompt_does_not_expose_visually_confirmed_cg_as_dialogue_background():
    index = {
        "bg": {"BG_Room": 1, "BG_CS_Event": 2},
        "bg_label": {
            "BG_Room": {"label": "普通教室"},
            "BG_CS_Event": {"label": "事件特写"},
        },
        "scene_labels": {"background": {
            "BG_Room": {
                "visual_kind": "background", "dialogue_suitable": True,
                "status": "ready",
            },
            "BG_CS_Event": {
                "visual_kind": "cg", "dialogue_suitable": False,
                "status": "ready",
            },
        }},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    text = prompt.build_resources(index, {}, [], {})

    assert "BG_Room=普通教室" in text
    assert "BG_CS_Event" not in text


def test_prompt_asset_retrieval_keeps_story_evidence_and_drops_unrelated_catalog_rows():
    index = {
        "bg": {
            "BG_GameDevRoom": 1,
            "BG_TrainCabin_Night": 2,
            "BG_UnrelatedBeach": 3,
        },
        "bg_label": {
            "BG_GameDevRoom": {"label": "游戏开发部活动室", "place": "社团室"},
            "BG_TrainCabin_Night": {"label": "夜间列车车厢", "place": "列车客舱"},
            "BG_UnrelatedBeach": {"label": "正午海滩", "place": "沙滩"},
        },
        "sounds": [
            "SE_FootStep_01", "SE_TrainStart_01", "SE_Alarm_01",
        ],
        "enums": {"emoticon": {}, "action": {}},
    }
    source = (
        "@bg BG_GameDevRoom\n"
        "旁白: 桃井绕过桌角，向绿走近一步。\n"
        "@bg BG_TrainCabin_Night\n"
        "旁白: 夜间列车启动。\n"
    )
    plan = [{
        "segment": "列车车厢",
        "needs": [{
            "kind": "background", "status": "builtin",
            "aa_key": "BG_TrainCabin_Night",
        }],
    }]

    selected = prompt.select_prompt_assets(index, source, plan)
    text = prompt.build_resources(selected, {}, [], {})

    assert set(selected["bg"]) == {"BG_GameDevRoom", "BG_TrainCabin_Night"}
    assert "SE_FootStep_01" in selected["sounds"]
    assert "SE_TrainStart_01" in selected["sounds"]
    assert "SE_Alarm_01" not in selected["sounds"]
    assert "BG_UnrelatedBeach" not in text


def test_prompt_asset_retrieval_uses_cast_affiliation_as_scene_context():
    index = {
        "bg": {
            "BG_GameDevRoom": 1,
            "BG_SpaceshipBridge": 2,
            "BG_UnrelatedBeach": 3,
            "BG_GameDevExpo": 4,
            "BG_GameDevRoomNight": 5,
        },
        "bg_label": {
            "BG_GameDevRoom": {
                "label": "游戏开发部活动室",
                "place": "游戏开发部社团室",
            },
            "BG_SpaceshipBridge": {
                "label": "宇宙战舰舰桥",
                "place": "飞船舰桥",
            },
            "BG_UnrelatedBeach": {"label": "正午海滩", "place": "沙滩"},
            "BG_GameDevExpo": {
                "label": "游戏开发部展会展厅", "subcategory": "展厅", "time": "day",
            },
            "BG_GameDevRoomNight": {
                "label": "游戏开发部活动室（夜间）", "subcategory": "活动室", "time": "night",
            },
        },
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
    }

    selected = prompt.select_prompt_assets(
        index,
        "爱丽丝: 宇宙战舰真是浪漫！",
        context_text="游戏开发部",
    )

    assert "BG_GameDevRoom" in selected["bg"]
    assert "BG_SpaceshipBridge" in selected["bg"]
    assert "BG_UnrelatedBeach" not in selected["bg"]
    assert list(selected["bg"]).index("BG_GameDevRoom") < list(selected["bg"]).index(
        "BG_SpaceshipBridge"
    )
    assert next(iter(selected["bg"])) == "BG_GameDevRoom"


def test_model_schema_cannot_write_additional_prompt():
    fields = SCHEMA["properties"]["lines"]["items"]["properties"]

    assert "additionalPrompt" not in fields
    assert "wait" not in fields
    assert fields["bg_request"]["type"] == "string"
    assert fields["shot"]["type"] == "string"
    assert SCHEMA["properties"]["lines"]["items"]["additionalProperties"] is False


def test_prompt_describes_semantic_parts_without_offering_them_as_face_ids():
    index = {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}}
    cast = {"凯伊": {"id": "626652156", "portrait": True}}

    text = prompt.build_resources(index, cast, ["凯伊"], {
        "626652156": {
            "faces": [],
            "expression_mode": "semantic_modular",
            "expression_parts": [{"kind": "eyes", "labels": ["惊讶", "好奇"]}],
        }
    })

    assert "语义部件：eyes（惊讶、好奇）" in text
    assert "face 一律留空串" in text


def test_dynamic_face_prompt_does_not_expose_real_face_ids():
    index = {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}}
    cast = {"爱丽丝": {"id": "aris", "portrait": True}}
    text = prompt.build_resources(
        index,
        cast,
        ["爱丽丝"],
        {"aris": {"faces": [{
            "id": "05", "semantic_cn": "认真报告",
            "backend_selection_ready": True,
        }]}},
        dynamic_face_shortlists=True,
    )

    assert "05=认真报告" not in text
    assert "禁止自行猜编号" in text
    assert "SILENT_REACTION_SHORTLIST_BY_TARGET" in text

    system = prompt.build_system(
        index,
        cast,
        ["爱丽丝"],
        {"aris": {"faces": [{
            "id": "05", "semantic_cn": "认真报告",
            "backend_selection_ready": True,
        }]}},
        dynamic_face_shortlists=True,
    )
    assert "face=05" not in system
    assert "face=[Emo:严肃制止]" in system
