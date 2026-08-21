import json

import assetdb
from face_label_backend import normalize_visual_facts, resolve_backend_label
from PIL import Image
from spine_face_labeler import (
    label_face_images, list_visual_face_labels, persist_visual_face_labels,
    update_visual_face_label,
)
from spine_face_renderer import RenderedFace


def _label(face_id="05"):
    return {
        "face_id": face_id,
        "primary_emotion": "平静好奇",
        "usage_hint_cn": "发现异常后观察并追问",
        "eyes": "睁眼",
        "brows": "自然上扬",
        "mouth": "微张",
        "blush": False,
        "tears": False,
        "confidence": 0.92,
        "emotion_family": "neutral",
        "intensity": 1,
        "expression_class": "accent",
        "beat_fit": ["question", "reaction"],
        "hold_policy": "short",
        "delivery_fit": ["silent_reaction", "normal_speech"],
        "usage_frequency": "common",
        "semantic_confidence": 0.9,
        "semantic_tags": ["curious", "focused"],
        "avoid_when_cn": "强烈喊叫",
        "visual_facts": {
            "eye_openness": "open", "gaze": "forward", "iris_color": "cyan",
            "eye_effect": "normal", "brow_shape": "raised",
            "mouth_openness": "slightly_open", "mouth_shape": "neutral",
            "blush_level": "none", "tears_level": "none", "sweat_level": "none",
            "face_shadow": "none", "visual_tags": [], "visual_confidence": 0.92,
            "review_note_cn": "",
        },
    }


def test_backend_preserves_observation_and_aggregates_official_evidence():
    result = resolve_backend_label(_label(), [{
        "silent": True, "closeup": True, "emoticons": ["?"], "actions": ["stiff"],
    }])
    assert result["pipeline"].endswith("v4")
    assert result["selection_ready"] is True
    assert result["official_evidence"] == {
        "examples": 1, "silent_examples": 1, "closeup_examples": 1,
        "emoticons": ["?"], "actions": ["stiff"],
    }
    assert result["selection_profile"]["delivery_fit"] == [
        "silent_reaction", "normal_speech",
    ]


def test_backend_flags_candidate_visual_conflict_without_rewriting_it():
    item = _label()
    item["visual_facts"] = {
        **item["visual_facts"], "eye_openness": "closed", "iris_color": "not_visible",
    }
    item["usage_hint_cn"] = "睁眼确认结果"
    result = resolve_backend_label(item)
    assert "candidate_conflicts_with_eyes" in result["review_flags"]
    assert result["selection_ready"] is False


def test_backend_does_not_offer_low_confidence_visual_or_semantic_label():
    visual = _label()
    visual["visual_facts"] = {**visual["visual_facts"], "visual_confidence": 0.42}
    semantic = _label()
    semantic["semantic_confidence"] = 0.42

    visual_result = resolve_backend_label(visual)
    semantic_result = resolve_backend_label(semantic)

    assert "visual_facts_low_confidence" in visual_result["review_flags"]
    assert "semantic_low_confidence" in semantic_result["review_flags"]
    assert visual_result["selection_ready"] is False
    assert semantic_result["selection_ready"] is False


def test_backend_blocks_special_visual_marked_as_ordinary_common_face():
    item = _label("04")
    item["visual_facts"] = {
        **item["visual_facts"],
        "eye_effect": "blank",
        "sweat_level": "multiple",
        "face_shadow": "upper",
    }
    item["expression_class"] = "accent"
    item["usage_frequency"] = "common"

    result = resolve_backend_label(item)

    assert "special_visual_requires_special_class" in result["hard_blocks"]
    assert result["selection_ready"] is False


def test_backend_requires_special_faces_to_be_conditional_or_rare():
    item = _label("04")
    item["expression_class"] = "special"
    item["usage_frequency"] = "common"
    result = resolve_backend_label(item)
    assert "special_class_frequency_too_common" in result["hard_blocks"]
    assert result["selection_ready"] is False


def test_backend_owns_normal_aris_persona_isolation():
    blocked = resolve_backend_label(_label("14"), ident="아리스N", face_id="14")
    allowed = resolve_backend_label(_label("13"), ident="아리스N", face_id="13")
    assert blocked["persona_scope"] == "normal_aris"
    assert "persona_scope_blocked" in blocked["hard_blocks"]
    assert blocked["selection_ready"] is False
    assert allowed["selection_ready"] is True


def test_backend_calibrates_nonlexical_official_face_without_losing_ai_candidate():
    item = _label("02")
    item["delivery_fit"] = ["normal_speech", "listening"]
    item["usage_frequency"] = "default"
    result = resolve_backend_label(item, official_profile={
        "total_count": 10,
        "lexical_dialogue_count": 0,
        "nonlexical_dialogue_count": 5,
        "no_dialogue_count": 5,
    })
    assert item["delivery_fit"] == ["normal_speech", "listening"]
    assert result["selection_profile"]["delivery_fit"] == [
        "listening", "silent_reaction",
    ]
    assert result["selection_profile"]["usage_frequency"] == "conditional"
    assert result["evidence_adjustments"] == ["official_nonlexical_usage_profile"]


def test_backend_rejects_sleep_only_semantics_for_frequently_spoken_face():
    item = _label("99")
    item["primary_emotion"] = "安详沉睡"
    item["usage_hint_cn"] = "适合平静入眠、彻底放下防备或静谧转场"
    item["delivery_fit"] = ["normal_speech", "soft_speech", "silent_reaction"]

    result = resolve_backend_label(item, official_profile={
        "total_count": 275,
        "lexical_dialogue_count": 268,
        "nonlexical_dialogue_count": 3,
        "no_dialogue_count": 4,
    })

    assert "candidate_conflicts_with_official_speech" in result["review_flags"]
    assert result["selection_ready"] is False


def test_backend_accepts_explicitly_negated_sleep_word_for_spoken_closed_eye_face():
    item = _label("99")
    item["primary_emotion"] = "闭目从容"
    item["usage_hint_cn"] = "适合平静说明和温和回应，不等同于沉睡"
    item["delivery_fit"] = ["normal_speech", "soft_speech", "listening"]

    result = resolve_backend_label(item, official_profile={
        "total_count": 275,
        "lexical_dialogue_count": 268,
        "nonlexical_dialogue_count": 3,
        "no_dialogue_count": 4,
    })

    assert "candidate_conflicts_with_official_speech" not in result["review_flags"]
    assert result["selection_ready"] is True


def test_backend_still_rejects_positive_sleep_claim_after_a_negated_one():
    item = _label("99")
    item["primary_emotion"] = "不是沉睡"
    item["usage_hint_cn"] = "适合安静入眠"

    result = resolve_backend_label(item, official_profile={
        "total_count": 20,
        "lexical_dialogue_count": 18,
        "nonlexical_dialogue_count": 1,
        "no_dialogue_count": 1,
    })

    assert "candidate_conflicts_with_official_speech" in result["hard_blocks"]


def test_observation_and_backend_are_persisted_separately(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    persist_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        model="face-label-v2", labels=[_label()],
    )
    row = con.execute(
        "SELECT observation_json,backend_json FROM face_visual_label"
    ).fetchone()
    assert json.loads(row["observation_json"])["eye_openness"] == "open"
    assert json.loads(row["backend_json"])["pipeline"].endswith("v4")
    record = list_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school"
    )[0]
    assert record["observation"]["mouth_openness"] == "slightly_open"
    assert record["backend"]["semantic_source"] == "ai_candidate_validated_by_backend"


def test_manual_semantic_fix_recomputes_backend_selection(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    item = _label("99")
    item["visual_facts"] = {
        **item["visual_facts"], "eye_openness": "closed",
        "iris_color": "not_visible",
    }
    item["usage_hint_cn"] = "适合睁眼确认结果"
    persist_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        model="face-label-v3", labels=[item],
    )
    before = list_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school"
    )[0]
    assert before["backend"]["selection_ready"] is False
    after = update_visual_face_label(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        face_id="99", patch={"usage_hint_cn": "适合闭目平静回应"},
        expected_version=before["version"],
    )
    assert after["backend"]["selection_ready"] is True


def test_semantic_modes_round_trip_and_manual_override_recompute_backend(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    item = _label("05")
    item["semantic_modes"] = [{
        "label_cn": "认真说明", "beat_fit": ["exposition"],
        "delivery_fit": ["normal_speech"], "intensity": 1,
        "semantic_tags": ["serious"], "avoid_when_cn": "激烈喊叫",
    }]
    persist_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        model="face-label-v4", labels=[item],
    )
    before = list_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school",
    )[0]
    assert before["effective"]["semantic_modes"][0]["label_cn"] == "认真说明"
    assert before["backend"]["selection_profile"]["semantic_modes"][0]["label_cn"] == "认真说明"

    replacement = [{
        "label_cn": "克制生气", "beat_fit": ["conflict"],
        "delivery_fit": ["emphatic_speech"], "intensity": 2,
        "semantic_tags": ["angry", "serious"], "avoid_when_cn": "轻松闲聊",
    }]
    after = update_visual_face_label(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        face_id="05", patch={"semantic_modes": replacement},
        expected_version=before["version"],
    )

    assert after["effective"]["semantic_modes"] == replacement
    assert after["backend"]["selection_profile"]["semantic_modes"] == replacement


def test_partial_manual_visual_fix_recomputes_backend_from_merged_observation(
    tmp_path,
):
    con = assetdb.connect(tmp_path / "assets.db")
    item = _label("99")
    item["visual_facts"] = {
        **item["visual_facts"],
        "mouth_openness": "occluded",
        "mouth_shape": "occluded",
    }
    persist_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        model="face-label-v3", labels=[item],
    )
    before = list_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="school"
    )[0]
    assert before["backend"]["review_required"] is True

    after = update_visual_face_label(
        con, ident="hero", spine_signature="sig", outfit_key="school",
        face_id="99",
        patch={"visual_facts": {
            "mouth_openness": "closed",
            "mouth_shape": "downturned",
        }},
        expected_version=before["version"],
    )

    assert after["observation"]["mouth_openness"] == "occluded"
    assert after["effective_observation"]["mouth_openness"] == "closed"
    assert after["effective_observation"]["eye_openness"] == "open"
    assert after["backend"]["review_required"] is False
    assert after["backend"]["review_flags"] == []


def test_legacy_top_level_fields_still_become_visual_facts():
    facts = normalize_visual_facts({
        "eyes": "闭眼", "brows": "放松", "mouth": "闭嘴",
        "blush": False, "tears": False, "confidence": 0.8,
    })
    assert facts["eye_openness"] == "closed"
    assert facts["blush_level"] == "none"


def test_production_relabel_requires_structured_visual_facts(tmp_path):
    head = tmp_path / "05.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(head)

    class LegacyProvider:
        def complete_json_vision(self, system, images, user, schema):
            return {"items": [_label() | {"visual_facts": None}]}

    labels = label_face_images(
        LegacyProvider(),
        [RenderedFace(face_id="05", portrait_path=head, head_path=head)],
        require_visual_facts=True,
        require_semantic_profile=True,
        max_attempts=1,
    )
    assert labels[0]["failed"] is True


def test_production_relabel_rejects_missing_semantic_profile(tmp_path):
    head = tmp_path / "05.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(head)

    class ObjectiveOnlyProvider:
        def complete_json_vision(self, system, images, user, schema):
            item = _label()
            for field in (
                "delivery_fit", "usage_frequency", "semantic_confidence",
            ):
                item.pop(field)
            return {"items": [item]}

    labels = label_face_images(
        ObjectiveOnlyProvider(),
        [RenderedFace(face_id="05", portrait_path=head, head_path=head)],
        require_visual_facts=True,
        require_semantic_profile=True,
        max_attempts=1,
    )
    assert labels[0]["failed"] is True


def test_v4_production_relabel_requires_alternate_semantic_modes(tmp_path):
    head = tmp_path / "05.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(head)

    class MissingModesProvider:
        def complete_json_vision(self, system, images, user, schema):
            return {"items": [_label()]}

    labels = label_face_images(
        MissingModesProvider(),
        [RenderedFace(face_id="05", portrait_path=head, head_path=head)],
        require_visual_facts=True,
        require_semantic_profile=True,
        require_semantic_modes=True,
        max_attempts=1,
    )
    assert labels[0]["failed"] is True
