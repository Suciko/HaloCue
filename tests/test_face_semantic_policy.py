import json

from PIL import Image

import assetdb
import prompt
from asset_catalog import _face_capabilities
from face_semantics import CONTROLLED_BEAT_FIT, CONTROLLED_DELIVERY_FIT
from spine_face_labeler import (
    VISION_SCHEMA,
    _valid_vision_item,
    label_face_images,
    list_visual_face_labels,
    persist_visual_face_labels,
    update_visual_face_label,
)
from spine_face_renderer import RenderedFace


def _label(face_id, emotion, *, beat_fit=None):
    value = {
        "face_id": face_id,
        "primary_emotion": emotion,
        "usage_hint_cn": f"适合{emotion}地回应",
        "eyes": "睁眼",
        "brows": "自然",
        "mouth": "闭嘴",
        "blush": False,
        "tears": False,
        "confidence": 0.9,
    }
    if beat_fit is not None:
        value["beat_fit"] = beat_fit
    return value


def _face(tmp_path, face_id):
    path = tmp_path / f"{face_id}.png"
    Image.new("RGBA", (64, 64), (220, 180, 160, 255)).save(path)
    return RenderedFace(face_id, path, path)


def test_effective_visual_label_prefers_manual_then_configured_model(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "kei", "spine_signature": "sig", "outfit_key": "outfit"}
    persist_visual_face_labels(
        con, **scope, model="gemini-3.6-flash", labels=[_label("08", "惊奇")]
    )
    persist_visual_face_labels(
        con, **scope, model="gemini-3.7-flash", labels=[_label("08", "平静")]
    )
    assetdb.set_active_face_label_model(con, "gemini-3.7-flash")

    assert list_visual_face_labels(con, **scope)[0]["effective"]["primary_emotion"] == "平静"
    assert _face_capabilities(con)["kei"][0]["faces"][0]["semantic_cn"].startswith("平静")

    con.execute(
        "UPDATE face_visual_label SET manual_json=? WHERE ident='kei' AND model='gemini-3.6-flash'",
        (json.dumps({"primary_emotion": "人工确认"}, ensure_ascii=False),),
    )
    con.commit()
    assert list_visual_face_labels(con, **scope)[0]["effective"]["primary_emotion"] == "人工确认"


def test_persona_blocked_active_face_model_does_not_fallback(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "aris", "spine_signature": "sig", "outfit_key": "normal"}
    persist_visual_face_labels(
        con, **scope, model="reviewed-v3", labels=[_label("05", "坚定微笑")]
    )
    persist_visual_face_labels(
        con, **scope, model="pending-v4", labels=[_label("05", "模糊候选")]
    )
    con.execute(
        "UPDATE face_visual_label SET backend_json=? WHERE ident=? AND model=?",
        (
            json.dumps({
                "selection_ready": False,
                "review_required": True,
                "review_flags": ["persona_scope_blocked"],
                "hard_blocks": ["persona_scope_blocked"],
            }, ensure_ascii=False),
            "aris",
            "pending-v4",
        ),
    )
    con.commit()
    assetdb.set_active_face_label_model(con, "pending-v4")

    record = list_visual_face_labels(con, **scope)[0]
    face = _face_capabilities(con)["aris"][0]["faces"][0]

    assert record["model"] == "pending-v4"
    assert record["effective"]["primary_emotion"] == "模糊候选"
    assert face["backend_selection_ready"] is False


def test_incomplete_active_face_model_falls_back_to_reviewed_label(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "aris", "spine_signature": "sig", "outfit_key": "normal"}
    persist_visual_face_labels(
        con, **scope, model="reviewed-v3", labels=[_label("05", "坚定微笑")]
    )
    persist_visual_face_labels(
        con, **scope, model="pending-v4", labels=[_label("05", "视觉事实未完成")]
    )
    con.execute(
        "UPDATE face_visual_label SET backend_json=? WHERE ident=? AND model=?",
        (
            json.dumps({
                "selection_ready": False,
                "review_required": True,
                "review_flags": ["visual_facts_incomplete"],
                "hard_blocks": ["visual_facts_incomplete"],
            }, ensure_ascii=False),
            "aris",
            "pending-v4",
        ),
    )
    con.commit()
    assetdb.set_active_face_label_model(con, "pending-v4")

    record = list_visual_face_labels(con, **scope)[0]
    face = _face_capabilities(con)["aris"][0]["faces"][0]

    assert record["model"] == "reviewed-v3"
    assert record["effective"]["primary_emotion"] == "坚定微笑"
    assert face["backend_selection_ready"] is True


def test_review_required_face_remains_selectable_but_is_marked_for_downgrade(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "aris", "spine_signature": "sig", "outfit_key": "normal"}
    persist_visual_face_labels(
        con, **scope, model="pending-v4", labels=[_label("05", "模糊候选")]
    )
    con.execute(
        "UPDATE face_visual_label SET backend_json=? WHERE ident=? AND model=?",
        (
            json.dumps({
                "selection_ready": True,
                "review_required": True,
                "review_flags": ["semantic_low_confidence"],
            }, ensure_ascii=False),
            "aris",
            "pending-v4",
        ),
    )
    con.commit()
    assetdb.set_active_face_label_model(con, "pending-v4")

    face = _face_capabilities(con)["aris"][0]["faces"][0]

    assert face["backend_selection_ready"] is True
    assert face["backend_review_required"] is True


def test_runtime_face_capabilities_include_rich_manual_overrides(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "aris", "spine_signature": "sig", "outfit_key": "normal"}
    persist_visual_face_labels(
        con, **scope, model="vision-model", labels=[_label("02", "平静认真")]
    )

    update_visual_face_label(
        con,
        **scope,
        face_id="02",
        expected_version=1,
        patch={
            "primary_emotion": "无神平淡",
            "usage_hint_cn": "仅适合明确的失神状态。",
            "beat_fit": ["idle"],
            "avoid_when_cn": "普通对话和正式报告不要使用。",
        },
    )

    face = _face_capabilities(con)["aris"][0]["faces"][0]
    assert face["semantic_cn"].startswith("无神平淡")
    assert face["beat_fit"] == ["idle"]
    assert face["avoid_when_cn"] == "普通对话和正式报告不要使用。"


def test_runtime_face_capabilities_keep_objective_closed_eye_trait(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "midori", "spine_signature": "sig", "outfit_key": "normal"}
    persist_visual_face_labels(
        con,
        **scope,
        model="vision-model",
        labels=[{
            **_label("99", "闭目沉思", beat_fit=["idle", "transition"]),
            "eyes": "闭眼",
            "brows": "放松",
            "mouth": "闭嘴微笑",
            "blush": False,
            "tears": False,
        }],
    )

    face = _face_capabilities(con)["midori"][0]["faces"][0]

    assert face["eyes"] == "闭眼"
    assert face["brows"] == "放松"
    assert face["mouth"] == "闭嘴微笑"
    assert "闭眼" in prompt._face_option(face)
    assert "闭嘴微笑" in prompt._face_option(face)


def test_base_blush_is_not_exposed_as_story_blush(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {"ident": "hero", "spine_signature": "sig", "outfit_key": "normal"}
    label = _label("00", "平静")
    label["visual_facts"] = {
        "eye_openness": "open", "gaze": "forward", "iris_color": "pink",
        "eye_effect": "normal", "brow_shape": "relaxed",
        "mouth_openness": "closed", "mouth_shape": "neutral",
        "blush_level": "base", "tears_level": "none", "sweat_level": "none",
        "face_shadow": "none", "visual_tags": [], "visual_confidence": 0.95,
        "review_note_cn": "",
    }
    label["blush"] = True
    persist_visual_face_labels(con, **scope, model="vision-model", labels=[label])
    face = _face_capabilities(con)["hero"][0]["faces"][0]
    assert face.get("blush") is not True
    assert "脸红" not in prompt._face_option(face)


def test_visual_labels_without_ident_attach_to_one_exact_catalogued_outfit(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO character(ident,name,club,spine,source) VALUES (?,?,?,?,?)",
        (
            "朱莉（打工）",
            "朱莉",
            "",
            r"characters\CH0286_spr\CH0286_spr",
            "official",
        ),
    )
    persist_visual_face_labels(
        con,
        ident="",
        spine_signature="sig-juri-work",
        outfit_key="CH0286_spr",
        model="vision-model",
        labels=[_label("03", "得意微笑")],
    )

    capabilities = _face_capabilities(con)

    assert "03" in {
        face["id"]
        for variant in capabilities["朱莉（打工）"]
        for face in variant["faces"]
    }
    assert capabilities.get("", []) == []


def test_beat_fit_is_a_closed_vocabulary():
    required = set(VISION_SCHEMA["properties"]["items"]["items"]["required"])
    assert "reaction" in CONTROLLED_BEAT_FIT
    assert _valid_vision_item(_label("00", "平静", beat_fit=["reaction"]), required)
    assert not _valid_vision_item(_label("00", "平静", beat_fit=["积极回应"]), required)


def test_delivery_fit_is_a_closed_vocabulary():
    required = set(VISION_SCHEMA["properties"]["items"]["items"]["required"])
    item = _label("00", "平静")
    item["delivery_fit"] = ["listening", "normal_speech"]
    item["usage_frequency"] = "common"
    item["semantic_confidence"] = 0.88
    assert "normal_speech" in CONTROLLED_DELIVERY_FIT
    assert _valid_vision_item(item, required)
    item["delivery_fit"] = ["普通说话"]
    assert not _valid_vision_item(item, required)


def test_character_comparison_memory_reaches_later_batches(tmp_path):
    class Provider:
        model = "test"

        def __init__(self):
            self.calls = []

        def complete_json_vision(self, system, images, user, schema):
            self.calls.append(user)
            ids = images[0][0].split(":", 1)[1].split(",")
            return {"items": [_label(face_id, f"情绪{face_id}") for face_id in ids]}

    provider = Provider()
    label_face_images(
        provider,
        [_face(tmp_path, face_id) for face_id in ("00", "01", "02", "03")],
        batch_size=2,
        comparison_memory=True,
        max_attempts=1,
    )

    assert "CHARACTER_LABEL_CACHE" not in provider.calls[0]
    assert "CHARACTER_LABEL_CACHE" in provider.calls[1]
    assert "FACE 00=情绪00" in provider.calls[1]
    assert "FACE 01=情绪01" in provider.calls[1]


def test_prompt_consumes_full_semantics_and_hides_unlabeled_ids():
    idx = {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}}
    cast = {"凯伊": {"id": "kei", "portrait": True}}
    faces = {"kei": {"faces": [
        {
            "id": "03",
            "semantic_cn": "委屈｜被误解后低声解释或等待安慰",
            "emotion_family": "sadness_hurt",
            "intensity": 2,
            "expression_class": "accent",
            "beat_fit": ["reaction", "comfort"],
            "hold_policy": "short",
            "delivery_fit": ["silent_reaction", "soft_speech"],
            "usage_frequency": "conditional",
            "avoid_when_cn": "真正暴怒或强烈反击",
            "semantic_level": "rich",
        },
        {
            "id": "07",
            "semantic_cn": "无法识别｜渲染结果不足以判断",
            "confidence": 0,
            "active_label_model": "vision-current",
            "semantic_level": "rich",
        },
        {"id": "99", "semantic_level": "unknown"},
    ]}}

    text = prompt.build_resources(idx, cast, ["凯伊"], faces)

    assert "03=委屈｜被误解后低声解释或等待安慰" in text
    assert "[I2,accent,short]" in text
    assert "[D:silent_reaction|soft_speech]" in text
    assert "[F:conditional]" in text
    assert "sadness_hurt" not in text
    assert "reaction|comfort" not in text
    assert "避免：真正暴怒或强烈反击" in text
    assert "99" not in text
    assert "07" not in text
