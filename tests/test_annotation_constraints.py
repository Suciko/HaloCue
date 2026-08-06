import pytest

from annotate import (
    annotation_constraints, annotation_rows, build_static, filter_annotation_row,
    annotation_directives, load_custom_faces, normalize_bgfx_lifetime,
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


def test_annotation_rows_accepts_the_schema_lines_object_or_equivalent_list():
    rows = [{"i": 0, "face": ""}]

    assert annotation_rows({"lines": rows}) == rows
    assert annotation_rows(rows) == rows


def test_annotation_rows_rejects_an_invalid_top_level_response():
    with pytest.raises(LLMError, match="顶层"):
        annotation_rows({"items": []})
