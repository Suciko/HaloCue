import pytest

from annotate import (
    annotation_constraints, annotation_rows, build_static, filter_annotation_row,
    annotation_directives, apply_annotation_response_row, load_custom_faces,
    normalize_bgfx_lifetime, apply_speaker_turn_face_activation,
)
from llm import LLMError


def test_filter_rejects_unknown_assets_and_portrait_effects_for_narrator():
    constraints = annotation_constraints(
        {
            "bg": {"BG_River": 1},
            "sounds": ["SE_Wave"],
            "enums": {
                "emoticon": {"1": {"sym": "[再见]", "cn": "Chat"}},
                "action": {"6": {"verb": "jump", "cn": "跳跃"}},
            },
        },
        {"旁白": {"narrator": True, "portrait": False}},
    )

    clean, dropped = filter_annotation_row(
        {"face": "99", "emo": "Chat", "act": "jump", "fx": "特写", "se": "bad", "bg": "bad"},
        {"who": "旁白", "kind": "line"},
        {"narrator": True, "portrait": False},
        constraints,
    )

    assert clean == {}
    assert dropped == [
        "旁白无立绘，不能使用 face",
        "旁白无立绘，不能使用 emo",
        "旁白无立绘，不能使用 act",
        "旁白无立绘，不能使用 fx",
        "未知音效 bad",
        "未知背景 bad",
    ]


def test_official_named_faces_are_basic_candidates_but_unknown_faces_are_not_suggested():
    idx = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{"identifier": "official", "faces": []}],
        "face_capabilities": {"official": [{
            "spine_signature": "official-sha", "outfit_key": "default",
            "faces": [
                {"id": "00", "raw": "default", "label": "default", "cn": "默认", "sources": ["atlas_candidate"]},
                {"id": "03", "raw": "smile", "label": "smile", "cn": "微笑", "sources": ["atlas_candidate"]},
                {"id": "17", "raw": "17", "label": "", "cn": "", "sources": ["atlas_candidate"]},
            ],
        }]},
    }
    cast = {"官方": {"id": "official", "portrait": True, "spine_signature": "official-sha", "outfit_key": "default"}}

    constraints = annotation_constraints(idx, cast)
    assert constraints["faces_by_id"]["official"] == {"00", "03", "17"}
    prompt = build_static(idx, cast, ["官方"])
    assert "00=默认" in prompt
    assert "03=微笑" in prompt
    assert "17=" not in prompt


def test_official_spine_path_selects_one_exact_visual_label_variant():
    idx = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{
            "identifier": "juri-work",
            "spine": r"characters\CH0286_spr\CH0286_spr",
            "faces": [],
        }],
        "face_capabilities": {"juri-work": [{
            "spine_signature": "sig-juri-work",
            "outfit_key": "CH0286_spr",
            "faces": [{
                "id": "03",
                "semantic_cn": "得意微笑｜计划顺利时轻快回应",
                "semantic_level": "rich",
                "sources": ["vision:model"],
            }],
        }]},
    }
    cast = {"朱莉": {"id": "juri-work", "portrait": True}}

    constraints = annotation_constraints(idx, cast)
    static = build_static(idx, cast, ["朱莉"])

    assert constraints["faces_by_id"]["juri-work"] == {"03"}
    assert "03=得意微笑｜计划顺利时轻快回应" in static


def test_legacy_character_face_catalog_remains_model_safe_without_capabilities():
    constraints = annotation_constraints(
        {
            "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
            "characters": [{
                "identifier": "kai",
                "faces": [{"id": "00", "raw": "00", "label": "", "cn": ""}],
            }],
            "faces_used": {"kai": [{"id": "99", "raw": "99", "label": ""}]},
        },
        {"Kai": {"id": "kai", "portrait": True}},
    )

    assert constraints["faces_by_id"]["kai"] == {"00"}
    assert constraints["face_evidence_by_id"]["kai"] == {"00": "asset_semantic"}


def test_filter_accepts_only_variant_verified_face_id():
    constraints = annotation_constraints(
        {
            "bg": {},
            "sounds": [],
            "enums": {"emoticon": {}, "action": {}},
            "face_capabilities": {
                "626652156": [{
                    "spine_signature": "date",
                    "outfit_key": "date",
                    "faces": [
                        {"id": "00", "sources": ["aa_verified"]},
                        {"id": "01", "sources": ["atlas_candidate"]},
                    ],
                }]
            },
        },
        {"凯伊": {
            "id": "626652156", "portrait": True,
            "spine_signature": "date", "outfit_key": "date",
        }},
    )

    clean, dropped = filter_annotation_row(
        {"face": "01"},
        {"who": "凯伊", "kind": "line"},
        {"id": "626652156", "portrait": True,
         "spine_signature": "date", "outfit_key": "date"},
        constraints,
    )

    assert clean == {}
    assert dropped == ["凯伊 没有已验证表情 01"]


def test_context_inferred_face_is_not_auto_selectable_and_is_reviewable():
    constraints = {
        "faces_by_id": {"kai": {"07"}},
        "face_evidence_by_id": {"kai": {"07": "context_inferred"}},
        "sym2cn": {}, "ok_emo": set(), "ok_act": set(),
        "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
        "confirmed_bg": set(), "ok_shot": {"Kai"},
    }
    character = {
        "id": "kai", "portrait": True,
        "spine_signature": "sig-winter", "outfit_key": "winter",
    }

    clean, dropped, details = filter_annotation_row(
        {"face": "07"}, {"who": "Kai"}, character,
        constraints, include_details=True,
    )

    assert clean == {}
    assert dropped == ["Kai 的表情 07 只有上下文证据，需要人工审阅"]
    assert details == [{
        "code": "face_inferred_only",
        "field": "face",
        "value": "07",
        "reason": "Kai 的表情 07 只有上下文证据，需要人工审阅",
        "character": "Kai",
        "character_id": "kai",
        "outfit_key": "winter",
        "spine_signature": "sig-winter",
        "face_id": "07",
        "evidence_level": "context_inferred",
    }]


def test_inferred_face_review_context_reaches_annotation_diagnostics():
    constraints = {
        "faces_by_id": {"kai": {"07"}},
        "face_evidence_by_id": {"kai": {"07": "context_inferred"}},
        "sym2cn": {}, "ok_emo": set(), "ok_act": set(),
        "ok_fx": set(), "ok_se": set(), "ok_bg": set(),
        "confirmed_bg": set(), "ok_shot": {"Kai"},
    }
    item = {"kind": "line", "who": "Kai", "text": "hello", "annotation_id": "line-1"}
    cast = {"Kai": {
        "id": "kai", "portrait": True,
        "spine_signature": "sig-winter", "outfit_key": "winter",
    }}
    diagnostics = []

    apply_annotation_response_row(
        item, {"face": "07"}, cast, constraints, [], [], diagnostics
    )

    diagnostic = diagnostics[0]
    assert diagnostic["code"] == "face_inferred_only"
    assert diagnostic["source_id"] == "line-1"
    assert {
        key: diagnostic[key]
        for key in (
            "character", "character_id", "outfit_key", "spine_signature",
            "face_id", "evidence_level",
        )
    } == {
        "character": "Kai", "character_id": "kai", "outfit_key": "winter",
        "spine_signature": "sig-winter", "face_id": "07",
        "evidence_level": "context_inferred",
    }


def test_build_static_keeps_semantic_hints_separate_from_verified_faces():
    idx = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{
            "identifier": "626652156", "name": "凯伊（约会服）", "faces": [],
            "expression_mode": "semantic_modular",
            "expression_parts": [{"kind": "mouth", "labels": ["微笑", "开心"]}],
        }],
        "face_capabilities": {"626652156": [{
            "spine_signature": "date", "outfit_key": "date", "faces": [],
        }]},
    }
    cast = {"凯伊": {
        "id": "626652156", "portrait": True,
        "spine_signature": "date", "outfit_key": "date",
    }}

    text = build_static(idx, cast, ["凯伊"])

    assert "语义部件：mouth（微笑、开心）" in text
    assert "face 一律留空串" in text


def test_semantic_modular_character_does_not_offer_historical_numeric_faces():
    idx = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{
            "identifier": "626652156", "faces": [],
            "expression_mode": "semantic_modular",
            "expression_parts": [{"kind": "eyes", "labels": ["驚訝"]}],
        }],
        "face_capabilities": {"626652156": [{
            "spine_signature": "date", "outfit_key": "date",
            "faces": [{"id": "99", "sources": ["aap_observed"]}],
        }]},
    }
    cast = {"凯伊": {
        "id": "626652156", "portrait": True,
        "spine_signature": "date", "outfit_key": "date",
    }}

    constraints = annotation_constraints(idx, cast)

    assert constraints["faces_by_id"]["626652156"] == set()


def test_semantic_atlas_is_not_reported_as_unreadable(tmp_path, capsys):
    atlas = tmp_path / "date.atlas"
    atlas.write_text("date.png\nsize:8,8\neyes_happy\n", encoding="utf-8")
    cast = {"Kei": {"custom": {"src": str(tmp_path), "asset": "date"}}}

    load_custom_faces(cast, tmp_path)

    assert cast["Kei"]["_faces"] == []
    assert "未发现编号表情" in capsys.readouterr().out


def test_custom_semantic_atlas_blocks_historical_numeric_face_ids(tmp_path):
    atlas = tmp_path / "date.atlas"
    atlas.write_text("date.png\nsize:8,8\n眼睛（惊讶）\n", encoding="utf-8")
    cast = {"Kei": {
        "id": "626652156", "portrait": True,
        "spine_signature": "date", "outfit_key": "date",
        "custom": {"src": str(tmp_path), "asset": "date"},
    }}
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [],
        "face_capabilities": {"626652156": [{
            "spine_signature": "date", "outfit_key": "date",
            "faces": [{"id": "05", "sources": ["aap_observed"]}],
        }]},
    }

    load_custom_faces(cast, tmp_path)

    assert annotation_constraints(index, cast)["faces_by_id"]["626652156"] == set()


def test_custom_semantic_atlas_binds_exact_registered_variant_before_filtering(tmp_path):
    """The command-line path must bind the custom asset name to one safe variant."""
    atlas = tmp_path / "Kei_Date_Outfit.atlas"
    atlas.write_text("date.png\nsize:8,8\n眼睛（惊讶）\n", encoding="utf-8")
    cast = {"Kei": {
        "id": "626652156", "portrait": True,
        "custom": {"src": str(tmp_path), "asset": "Kei_Date_Outfit"},
    }}
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [],
        "face_capabilities": {"626652156": [
            {
                "spine_signature": "date-sha", "outfit_key": "Kei_Date_Outfit",
                "faces": [{"id": "03", "sources": ["spine_semantic"]}],
            },
            {
                "spine_signature": "winter-sha", "outfit_key": "Kei_Winter_Outfit",
                "faces": [{"id": "05", "sources": ["spine_semantic"]}],
            },
        ]},
    }

    load_custom_faces(cast, tmp_path, index)

    assert cast["Kei"]["spine_signature"] == "date-sha"
    assert cast["Kei"]["outfit_key"] == "Kei_Date_Outfit"
    assert annotation_constraints(index, cast)["faces_by_id"]["626652156"] == {"03"}


def test_transient_background_effect_resets_but_rain_stays_until_explicit_reset():
    items = [
        {"kind": "line", "bgfx": "集中线"},
        {"kind": "line"},
        {"kind": "line", "bgfx": "雨"},
        {"kind": "line"},
        {"kind": "line", "bgfx": "无"},
    ]

    normalize_bgfx_lifetime(items)

    assert items[1]["bgfx"] == "无"
    assert "bgfx" not in items[3]
    assert items[4]["bgfx"] == "无"


def test_background_effect_continuity_hold_defers_reset_and_end_clears_state():
    items = [
        {
            "kind": "line", "bgfx": "集中线",
            "_director": {"continuity": {"bgfx": "start"}},
        },
        {"kind": "line", "_director": {"continuity": {"bgfx": "hold"}}},
        {"kind": "line", "_director": {"continuity": {"bgfx": "end"}}},
    ]

    normalize_bgfx_lifetime(items)

    assert "bgfx" not in items[1]
    assert items[2]["bgfx"] == "无"


def test_persistent_weather_hold_does_not_schedule_a_transient_reset():
    items = [
        {
            "kind": "line", "bgfx": "雨",
            "_director": {"continuity": {"bgfx": "start"}},
        },
        {"kind": "line", "_director": {"continuity": {"bgfx": "hold"}}},
        {"kind": "line"},
    ]

    normalize_bgfx_lifetime(items)

    assert "bgfx" not in items[1]
    assert "bgfx" not in items[2]


def test_scene_break_resets_persistent_background_effect_once():
    items = [
        {"kind": "line", "bgfx": "雨"},
        {"kind": "other", "raw": "## 下一场"},
        {"kind": "line"},
        {"kind": "line"},
    ]

    normalize_bgfx_lifetime(items)

    assert items[2]["bgfx"] == "无"
    assert "bgfx" not in items[3]


def test_filter_accepts_combinable_character_effects():
    constraints = annotation_constraints(
        {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {"Kei": {"id": "1", "portrait": True}},
    )

    clean, dropped = filter_annotation_row(
        {"fx": "通讯+特写"}, {"who": "Kei", "kind": "line"},
        {"id": "1", "portrait": True}, constraints,
    )

    assert clean == {"fx": "通讯+特写"}
    assert dropped == []


def test_filter_accepts_shot_only_for_a_registered_portrait_target():
    constraints = annotation_constraints(
        {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {
            "凯伊": {"id": "kei", "portrait": True},
            "旁白": {"narrator": True, "portrait": False},
        },
    )

    clean, dropped = filter_annotation_row(
        {"shot": "凯伊"}, {"who": "旁白", "kind": "line"},
        {"narrator": True, "portrait": False}, constraints,
    )
    invalid, invalid_dropped = filter_annotation_row(
        {"shot": "旁白"}, {"who": "凯伊", "kind": "line"},
        {"id": "kei", "portrait": True}, constraints,
    )

    assert clean == {"shot": "凯伊"}
    assert dropped == []
    assert invalid == {}
    assert invalid_dropped == ["射击目标‘旁白’不是可显示角色"]


def test_filter_drops_camera_focus_mistaken_for_shot_target_without_attack_evidence():
    constraints = annotation_constraints(
        {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {"柚子": {"id": "yuzu", "portrait": True}},
    )

    clean, dropped, details = filter_annotation_row(
        {
            "shot": "柚子",
            "direction": {
                "focus_character": "柚子",
                "visible_characters": ["柚子"],
            },
        },
        {"who": "柚子", "kind": "line", "text": "屏幕上出现了一个陌生账号。"},
        {"id": "yuzu", "portrait": True}, constraints, include_details=True,
    )

    assert "shot" not in clean
    assert any(item["code"] == "shot_camera_subject_confusion" for item in details)
    assert dropped


def test_filter_keeps_explicit_attack_target_even_when_it_is_the_focus():
    constraints = annotation_constraints(
        {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {"柚子": {"id": "yuzu", "portrait": True}},
    )

    clean, dropped = filter_annotation_row(
        {
            "shot": "柚子",
            "direction": {"focus_character": "柚子"},
        },
        {"who": "柚子", "kind": "line", "text": "柚子被击中了！"},
        {"id": "yuzu", "portrait": True}, constraints,
    )

    assert clean == {"shot": "柚子"}
    assert dropped == []


def test_background_generation_request_suppresses_an_unconfirmed_background_swap():
    constraints = annotation_constraints(
        {"bg": {"BG_Campus": 1}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {"凯伊": {"id": "kei", "portrait": True}},
    )

    clean, dropped = filter_annotation_row(
        {
            "bg": "BG_Campus",
            "bg_request": "傍晚的商店街可丽饼摊，暖色霓虹与排队人群，蔚蓝档案剧情背景风格",
        },
        {"who": "凯伊", "kind": "line"}, {"id": "kei", "portrait": True}, constraints,
    )

    assert clean == {
        "bg_request": "傍晚的商店街可丽饼摊，暖色霓虹与排队人群，蔚蓝档案剧情背景风格",
    }
    assert dropped == []
    assert annotation_directives(clean) == [
        "# 待生成自定义背景：傍晚的商店街可丽饼摊，暖色霓虹与排队人群，蔚蓝档案剧情背景风格",
    ]


def test_confirmed_preflight_background_extends_allowlist_and_wins_over_request():
    usage_chain = [{
        "segment": "场景一",
        "needs": [{
            "kind": "background", "status": "registered",
            "aa_key": "BG_HighlanderCentral_Sunset",
        }],
    }]
    constraints = annotation_constraints(
        {"bg": {"BG_TrainStation": 1}, "sounds": [], "enums": {"emoticon": {}, "action": {}}},
        {"凯伊": {"id": "kei", "portrait": True}},
        usage_chain=usage_chain,
    )

    clean, dropped = filter_annotation_row(
        {
            "bg": "BG_HighlanderCentral_Sunset",
            "bg_request": "重新生成一个夕阳列车总站",
        },
        {"who": "凯伊", "kind": "line"},
        {"id": "kei", "portrait": True},
        constraints,
    )

    assert "BG_HighlanderCentral_Sunset" in constraints["ok_bg"]
    assert clean == {"bg": "BG_HighlanderCentral_Sunset"}
    assert dropped == ["已确认背景不再生成背景请求"]


def test_annotation_rows_accepts_the_schema_lines_object_or_equivalent_list():
    rows = [{"i": 0, "face": ""}]

    assert annotation_rows({"lines": rows}) == rows
    assert annotation_rows(rows) == rows


def test_annotation_rows_rejects_an_invalid_top_level_response():
    with pytest.raises(LLMError, match="顶层"):
        annotation_rows({"items": []})


def test_normal_aris_does_not_offer_kei_persona_faces():
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{"identifier": "아리스N", "faces": []}],
        "face_capabilities": {"아리스N": [{
            "spine_signature": "aris", "outfit_key": "CharacterSpine_aris_noweapon",
            "faces": [
                {"id": "01", "sources": ["aap_observed", "vision:test"],
                 "semantic_cn": "平静好奇", "evidence_level": "visual_confirmed"},
                {"id": "14", "sources": ["aap_observed", "vision:test"],
                 "semantic_cn": "无机质失神", "evidence_level": "visual_confirmed"},
            ],
        }]},
    }
    cast = {"爱丽丝": {
        "id": "아리스N", "portrait": True,
        "spine_signature": "aris", "outfit_key": "CharacterSpine_aris_noweapon",
    }}

    constraints = annotation_constraints(index, cast)

    assert constraints["faces_by_id"]["아리스N"] == {"01"}


def test_legacy_normal_aris_catalog_also_blocks_kei_persona_faces():
    index = {
        "bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
        "characters": [{
            "identifier": "아리스N",
            "faces": [{"id": "01"}, {"id": "14"}],
        }],
        "faces_used": {"아리스N": [{"id": "14"}]},
    }

    constraints = annotation_constraints(
        index, {"爱丽丝": {"id": "아리스N", "portrait": True}},
    )

    assert constraints["faces_by_id"]["아리스N"] == {"01"}
    assert [face["id"] for face in constraints["face_records_by_id"]["아리스N"]] == ["01"]


def test_speaker_turn_activation_uses_verified_response_face_once():
    items = [
        {"kind": "line", "who": "绿", "text": "第一句。"},
        {"kind": "line", "who": "桃井", "text": "插话。"},
        {"kind": "line", "who": "绿", "text": "继续说。"},
    ]
    cast = {
        "绿": {"id": "midori", "portrait": True},
        "桃井": {"id": "momoi", "portrait": True},
    }
    constraints = {
        "face_records_by_id": {
            "midori": [{"id": "02", "semantic_cn": "回应", "expression_class": "base"}],
            "momoi": [],
        }
    }
    proposals = []

    changes = apply_speaker_turn_face_activation(items, cast, constraints, proposals)

    assert items[0]["face"] == "02"
    assert "face" not in items[2]
    assert changes == 1
    assert proposals[0]["rule"] == "speaker_turn_face_activation"


def test_filter_accepts_fx_release_as_lifecycle_control():
    constraints = {
        "faces_by_id": {"a": set()}, "sym2cn": {}, "ok_emo": set(),
        "ok_act": set(), "ok_fx": {"特写"}, "ok_se": set(), "ok_bg": set(),
    }

    clean, dropped = filter_annotation_row(
        {"fx": "无"},
        {"who": "A", "kind": "line"},
        {"id": "a", "portrait": True, "narrator": False},
        constraints,
    )

    assert clean == {"fx": "无"}
    assert dropped == []


def test_speaker_turn_activation_uses_semantic_face_for_eager_help_then_report():
    items = [
        {"kind": "line", "who": "爱丽丝", "text": "爱丽丝也可以帮忙，一起检查会更快。",
         "face": "00", "emo": "闪亮", "act": "hophop"},
        {"kind": "line", "who": "桃井", "text": "那就拜托你了。"},
        {"kind": "line", "who": "爱丽丝", "text": "记录要员爱丽丝，报告：没有发现异常。"},
    ]
    cast = {
        "爱丽丝": {"id": "aris", "portrait": True},
        "桃井": {"id": "momoi", "portrait": True},
    }
    constraints = {"face_records_by_id": {
        "aris": [
            {"id": "00", "semantic_cn": "温和微笑", "emotion_family": "joy",
             "expression_class": "base", "beat_fit": ["dialogue"]},
            {"id": "01", "semantic_cn": "平静好奇", "emotion_family": "neutral",
             "expression_class": "base", "beat_fit": ["dialogue"]},
            {"id": "02", "semantic_cn": "无神平淡", "emotion_family": "neutral",
             "expression_class": "base", "beat_fit": ["idle"],
             "avoid_when_cn": "普通对话、正式报告或需要鲜活反应时尽量不要使用"},
            {"id": "03", "semantic_cn": "欣喜开朗", "emotion_family": "joy",
             "expression_class": "accent", "beat_fit": ["reaction"]},
            {"id": "05", "semantic_cn": "严肃专注", "emotion_family": "determination",
             "expression_class": "base", "beat_fit": ["exposition", "tension"],
             "usage_hint_cn": "正式报告、值勤戒备或认真确认时使用"},
        ],
        "momoi": [],
    }}

    apply_speaker_turn_face_activation(items, cast, constraints)

    assert items[0]["face"] == "03"
    assert items[2]["face"] in {"01", "05"}
    assert items[2]["face"] != "02"


def test_explicit_celebration_can_use_a_verified_peak_face():
    items = [{
        "kind": "line", "who": "桃井", "text": "太好了！那我们继续往下检查。",
        "face": "01", "emo": "闪亮", "act": "hophop",
    }]
    cast = {"桃井": {"id": "momoi", "portrait": True}}
    constraints = {"face_records_by_id": {"momoi": [
        {"id": "01", "semantic_cn": "得意自信", "emotion_family": "joy",
         "expression_class": "accent", "beat_fit": ["teasing", "dialogue"]},
        {"id": "03", "semantic_cn": "开怀大笑", "emotion_family": "joy",
         "expression_class": "peak", "beat_fit": ["celebration", "resolution"]},
    ]}}

    apply_speaker_turn_face_activation(items, cast, constraints)

    assert items[0]["face"] == "03"


def test_english_emoticon_alias_is_normalized_to_available_chinese_name():
    item = {"kind": "line", "who": "爱丽丝", "text": "收到。"}
    character = {"id": "aris", "portrait": True}
    constraints = {
        "faces_by_id": {"aris": set()}, "face_evidence_by_id": {"aris": {}},
        "ok_emo": {"反应"}, "sym2cn": {}, "ok_act": set(),
        "ok_se": set(), "ok_bg": set(), "ok_shot": set(), "ok_bgfx": set(),
        "confirmed_bg": set(),
    }

    clean, dropped = filter_annotation_row(
        {"emo": "Reaction"}, item, character, constraints
    )

    assert clean["emo"] == "反应"
    assert dropped == []
