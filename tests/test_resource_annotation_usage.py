"""Synthetic annotation fixtures; no local assets or model calls."""

import copy

import pytest

import prompt
from resource_retrieval import build_resource_candidate_index, rank_background_candidates


def annotated_index():
    return {
        "bg": {"BG_A": 99, "BG_B": 1},
        "sounds": [],
        "bg_label": {"BG_B": {"label": "安静房间", "place": "社团室"}},
        "scene_labels": {
            "background": {
                "BG_B": {
                    "label": "",
                    "weather": "雨天",
                    "indoor_outdoor": "室内",
                    "search_terms_cn": ["游戏开发"],
                    "usage_hint_cn": "整理资料",
                    "avoid_when_cn": "战斗爆炸",
                    "has_fixed_characters": True,
                    "dialogue_suitable": False,
                }
            }
        },
        "enums": {"emoticon": {}, "action": {}},
    }


def test_scene_annotation_is_used_for_retrieval_without_mutation():
    index = annotated_index()
    before = copy.deepcopy(index)
    candidate, _ = build_resource_candidate_index(index, "游戏开发", background_limit=1)
    assert list(candidate["bg"]) == ["BG_B"]
    assert candidate["bg_label"]["BG_B"]["place"] == "社团室"
    assert candidate["bg_label"]["BG_B"]["label"] == "安静房间"
    assert index == before


def test_negative_usage_is_not_a_positive_retrieval_match():
    assert all(score == 0 for score, _ in rank_background_candidates(annotated_index(), "战斗爆炸"))
    assert rank_background_candidates(annotated_index(), "雨天")[0][1] == "BG_B"


@pytest.mark.parametrize("profile", ["standard", "conservative"])
def test_prompt_preserves_rich_usage_in_both_modes(profile):
    faces = {
        "actor": [
            {
                "id": "03",
                "cn": "害羞",
                "emotion_family": "joy",
                "intensity": 1,
                "semantic_level": "rich",
                "expression_class": "accent",
                "usage_hint_cn": "掩饰关心",
                "beat_fit": ["hesitation"],
                "hold_policy": "short",
                "avoid_when_cn": "严肃宣誓",
            }
        ]
    }
    text = prompt.build_resources(
        annotated_index(),
        {"角色": {"id": "actor", "portrait": True}},
        ["角色"],
        faces,
        direction_profile=profile,
    )
    for phrase in (
        "03=害羞",
        "适用语境=掩饰关心",
        "适合节拍=hesitation",
        "持续方式=short",
        "不适用=严肃宣誓",
        "不适用=战斗爆炸",
        "画面带固定人物",
        "不适合普通对话",
        "不得为迁就素材改写正文",
    ):
        assert phrase in text
    assert "不是指令" in text


def test_annotation_prompt_bounds_text_and_handles_old_faces():
    assert len(prompt._annotation_text("a" * 10000)) == 180
    assert "\n" not in prompt._annotation_text("a\nb")
    text = prompt.build_resources(
        annotated_index(),
        {"角色": {"id": "actor", "portrait": True}},
        ["角色"],
        {"actor": [{"id": "00", "label": "平静"}]},
    )
    assert "00=平静" in text


def test_database_face_usage_reaches_capabilities(tmp_path):
    import json
    import assetdb
    from asset_catalog import _face_capabilities

    con = assetdb.connect(tmp_path / "assets.db")
    try:
        rich = {"usage_hint_cn": "掩饰关心", "hold_policy": "short", "avoid_when_cn": "宣誓"}
        con.execute(
            "INSERT INTO face_evidence (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count) VALUES (?,?,?,?,?,?,?,?,?)",
            ("actor", "sig", "school", "01", "vision:synthetic", json.dumps(rich), "", "害羞", 0),
        )
        con.commit()
        face = _face_capabilities(con)["actor"][0]["faces"][0]
        assert face["usage_hint_cn"] == "掩饰关心"
        assert face["avoid_when_cn"] == "宣誓"
    finally:
        con.close()
