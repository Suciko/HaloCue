import json

from PIL import Image

import assetdb
import prompt
from asset_catalog import _face_capabilities
from face_semantics import CONTROLLED_BEAT_FIT
from spine_face_labeler import (
    VISION_SCHEMA,
    _valid_vision_item,
    label_face_images,
    list_visual_face_labels,
    persist_visual_face_labels,
)
from spine_face_renderer import RenderedFace


def _label(face_id, emotion, *, beat_fit=None):
    value = {
        "face_id": face_id,
        "primary_emotion": emotion,
        "usage_hint_cn": f"适合{emotion}地回应",
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


def test_beat_fit_is_a_closed_vocabulary():
    required = set(VISION_SCHEMA["properties"]["items"]["items"]["required"])
    assert "reaction" in CONTROLLED_BEAT_FIT
    assert _valid_vision_item(_label("00", "平静", beat_fit=["reaction"]), required)
    assert not _valid_vision_item(_label("00", "平静", beat_fit=["积极回应"]), required)


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
            "avoid_when_cn": "真正暴怒或强烈反击",
            "semantic_level": "rich",
        },
        {"id": "99", "semantic_level": "unknown"},
    ]}}

    text = prompt.build_resources(idx, cast, ["凯伊"], faces)

    assert "03=委屈｜被误解后低声解释或等待安慰" in text
    assert "sadness_hurt,I2,accent,reaction|comfort,short" in text
    assert "避免：真正暴怒或强烈反击" in text
    assert "99" not in text
