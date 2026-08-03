from pathlib import Path

from PIL import Image
import pytest

import assetdb
import llm
from asset_catalog import _face_capabilities
from spine_face_labeler import (
    _SYSTEM,
    label_face_images,
    list_visual_face_labels,
    persist_visual_face_labels,
    update_visual_face_label,
)
from spine_face_renderer import RenderedFace


class FakeVisionProvider:
    model = "gemini-3.6-flash"

    def __init__(self):
        self.calls = []

    def complete_json_vision(self, system, images, user, schema):
        self.calls.append((system, images, user, schema))
        return {
            "items": [
                {
                    "face_id": tag,
                    "primary_emotion": "轻微微笑" if tag == "05" else "惊讶",
                    "secondary_emotions": ["温和"] if tag == "05" else ["意外"],
                    "valence": "positive" if tag == "05" else "neutral",
                    "arousal": "low" if tag == "05" else "high",
                    "eyes": "自然睁眼",
                    "brows": "放松",
                    "mouth": "嘴角轻微上扬" if tag == "05" else "张嘴",
                    "blush": False,
                    "tears": False,
                    "confidence": 0.91,
                    "description_cn": "温和、克制的轻微微笑",
                }
                for tag, _ in images
            ]
        }


def _face(tmp_path: Path, face_id: str, color: tuple[int, int, int]) -> RenderedFace:
    portrait = tmp_path / f"{face_id}-portrait.png"
    head = tmp_path / f"{face_id}-head.png"
    Image.new("RGBA", (256, 256), (*color, 255)).save(portrait)
    Image.new("RGBA", (256, 256), (*color, 255)).save(head)
    return RenderedFace(face_id=face_id, portrait_path=portrait, head_path=head)


def test_visual_labeler_sends_jpeg_images_and_keeps_exact_face_ids(tmp_path):
    provider = FakeVisionProvider()
    faces = [_face(tmp_path, "05", (220, 80, 120)), _face(tmp_path, "12", (80, 120, 220))]

    labels = label_face_images(provider, faces, batch_size=8)

    assert [label["face_id"] for label in labels] == ["05", "12"]
    assert labels[0]["primary_emotion"] == "轻微微笑"
    sent = provider.calls[0][1]
    assert [tag for tag, _ in sent] == ["05", "12"]
    assert all(blob.startswith(b"\xff\xd8") for _, blob in sent)
    assert "只根据图中实际可见" in _SYSTEM
    assert "涓" not in _SYSTEM


def test_visual_labeler_retries_empty_compatible_endpoint_response(tmp_path):
    class FlakyProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            if len(self.calls) == 1:
                raise llm.LLMError("vision endpoint returned empty text")
            return {
                "items": [
                    {
                        "face_id": tag,
                        "primary_emotion": "平静",
                        "secondary_emotions": [],
                        "valence": "neutral",
                        "arousal": "low",
                        "eyes": "自然睁眼",
                        "brows": "自然",
                        "mouth": "闭嘴",
                        "blush": False,
                        "tears": False,
                        "confidence": 0.9,
                        "description_cn": "平静地注视前方",
                    }
                    for tag, _ in images
                ]
            }

    provider = FlakyProvider()
    labels = label_face_images(
        provider,
        [_face(tmp_path, "00", (220, 220, 220))],
        max_attempts=2,
    )

    assert labels[0]["primary_emotion"] == "平静"
    assert len(provider.calls) == 2
    assert '根键必须是 "items"' in provider.calls[1][2]


def test_visual_labeler_rejects_incomplete_direct_object_after_retries(tmp_path):
    class IgnoringSchemaProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            return {
                "face_id": "00",
                "primary_emotion": "平静",
            }

    provider = IgnoringSchemaProvider()

    with pytest.raises(ValueError, match="视觉模型连续"):
        label_face_images(
            provider,
            [_face(tmp_path, "00", (220, 220, 220))],
            max_attempts=2,
        )

    assert len(provider.calls) == 2


def test_visual_labels_are_scoped_to_exact_skeleton_and_preferred_over_name_parser(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.replace_semantic_face_evidence(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
        combinations={
            "05": {
                "raw_parts": ["default"],
                "labels": ["default"],
                "special": False,
            }
        },
    )
    labels = [{
        "face_id": "05",
        "primary_emotion": "轻微微笑",
        "secondary_emotions": ["温和"],
        "valence": "positive",
        "arousal": "low",
        "eyes": "自然睁眼",
        "brows": "放松",
        "mouth": "嘴角轻微上扬",
        "blush": False,
        "tears": False,
        "confidence": 0.91,
        "description_cn": "温和、克制的轻微微笑",
        "head_path": str(tmp_path / "05.png"),
    }]

    persist_visual_face_labels(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
        model="gemini-3.6-flash",
        labels=labels,
    )
    capabilities = _face_capabilities(con)
    face = capabilities["626652156"][0]["faces"][0]

    row = con.execute(
        """
        SELECT primary_emotion,confidence,reviewed
        FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
        """,
        ("626652156", "date-sha", "Kei_Date_Outfit", "05"),
    ).fetchone()
    assert tuple(row) == ("轻微微笑", 0.91, 0)
    assert face["cn"] == "轻微微笑"
    assert face["semantic_cn"] == "轻微微笑"
    assert face["sources"] == ["vision:gemini-3.6-flash", "spine_semantic"]


def test_manual_visual_label_override_survives_ai_rerun(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    first = [{
        "face_id": "05",
        "primary_emotion": "轻微微笑",
        "secondary_emotions": ["温和"],
        "valence": "positive",
        "arousal": "low",
        "eyes": "自然睁眼",
        "brows": "放松",
        "mouth": "嘴角轻微上扬",
        "blush": False,
        "tears": False,
        "confidence": 0.91,
        "description_cn": "温和、克制的轻微微笑",
        "head_path": str(tmp_path / "05.png"),
    }]
    saved = persist_visual_face_labels(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
        model="gemini-3.6-flash",
        labels=first,
    )
    assert saved["saved_count"] == 1
    original = list_visual_face_labels(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
    )[0]

    edited = update_visual_face_label(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
        face_id="05",
        patch={"primary_emotion": "克制地生气", "brows": "眉头紧锁"},
        expected_version=original["version"],
    )
    assert edited["effective"]["primary_emotion"] == "克制地生气"
    assert edited["manual"] == {
        "primary_emotion": "克制地生气",
        "brows": "眉头紧锁",
    }

    rerun = [dict(first[0], primary_emotion="明显开心", brows="眉毛上扬")]
    persist_visual_face_labels(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
        model="gemini-3.6-flash",
        labels=rerun,
    )
    current = list_visual_face_labels(
        con,
        ident="626652156",
        spine_signature="date-sha",
        outfit_key="Kei_Date_Outfit",
    )[0]

    assert current["ai"]["primary_emotion"] == "明显开心"
    assert current["effective"]["primary_emotion"] == "克制地生气"
    assert current["effective"]["brows"] == "眉头紧锁"
    assert current["reviewed"] is True
    assert current["version"] > edited["version"]


def test_manual_visual_label_update_rejects_stale_version_and_unknown_fields(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    persist_visual_face_labels(
        con,
        ident="1516544",
        spine_signature="base-sha",
        outfit_key="default",
        model="gemini-3.6-flash",
        labels=[{
            "face_id": "00", "primary_emotion": "平静",
            "secondary_emotions": [], "valence": "neutral", "arousal": "low",
            "eyes": "自然睁眼", "brows": "自然", "mouth": "闭嘴",
            "blush": False, "tears": False, "confidence": 0.9,
            "description_cn": "平静地注视前方", "head_path": str(tmp_path / "00.png"),
        }],
    )
    row = list_visual_face_labels(
        con,
        ident="1516544",
        spine_signature="base-sha",
        outfit_key="default",
    )[0]
    update_visual_face_label(
        con,
        ident="1516544",
        spine_signature="base-sha",
        outfit_key="default",
        face_id="00",
        patch={"mouth": "轻微张嘴"},
        expected_version=row["version"],
    )

    with pytest.raises(ValueError, match="版本"):
        update_visual_face_label(
            con,
            ident="1516544",
            spine_signature="base-sha",
            outfit_key="default",
            face_id="00",
            patch={"eyes": "闭眼"},
            expected_version=row["version"],
        )
    with pytest.raises(ValueError, match="字段"):
        update_visual_face_label(
            con,
            ident="1516544",
            spine_signature="base-sha",
            outfit_key="default",
            face_id="00",
            patch={"head_path": "C:/private.png"},
            expected_version=row["version"] + 1,
        )
