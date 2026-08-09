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


def test_prompt_describes_combinable_character_effects():
    index = {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}}

    text = prompt.build_resources(index, {}, [], {})

    assert "通讯" in text
    assert "黑屏剪影" in text
    assert "可叠加" in text


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
