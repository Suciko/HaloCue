import io
import json
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
    make_vision_sheet,
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
        ids = images[0][0].split(":", 1)[1].split(",")
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
                for tag in ids
            ]
        }


def _face(tmp_path: Path, face_id: str, color: tuple[int, int, int]) -> RenderedFace:
    portrait = tmp_path / f"{face_id}-portrait.png"
    head = tmp_path / f"{face_id}-head.png"
    Image.new("RGBA", (256, 256), (*color, 255)).save(portrait)
    Image.new("RGBA", (256, 256), (*color, 255)).save(head)
    return RenderedFace(face_id=face_id, portrait_path=portrait, head_path=head)


def _vision_label(face_id: str, *, emotion: str = "平静", confidence: float = 0.9):
    return {
        "face_id": face_id,
        "primary_emotion": emotion,
        "secondary_emotions": [],
        "valence": "neutral",
        "arousal": "low",
        "eyes": "自然睁眼",
        "brows": "自然",
        "mouth": "闭嘴",
        "blush": False,
        "tears": False,
        "confidence": confidence,
        "description_cn": emotion,
    }


def test_visual_labeler_sends_one_numbered_sheet_and_keeps_exact_face_ids(tmp_path):
    provider = FakeVisionProvider()
    faces = [_face(tmp_path, "05", (220, 80, 120)), _face(tmp_path, "12", (80, 120, 220))]

    labels = label_face_images(provider, faces, batch_size=9)

    assert [label["face_id"] for label in labels] == ["05", "12"]
    assert labels[0]["primary_emotion"] == "轻微微笑"
    sent = provider.calls[0][1]
    assert len(sent) == 1
    assert sent[0][0] == "编号九宫格:05,12"
    assert sent[0][1].startswith(b"\xff\xd8")
    assert "只根据图中实际可见" in _SYSTEM
    assert "涓" not in _SYSTEM


def test_vision_sheet_has_stable_three_by_three_dimensions(tmp_path):
    faces = [_face(tmp_path, f"{index:02d}", (index * 20, 80, 120)) for index in range(4)]

    blob, face_ids = make_vision_sheet(faces, cell_size=160, columns=3)
    image = Image.open(io.BytesIO(blob))

    assert face_ids == ["00", "01", "02", "03"]
    assert image.size == (480, 480)
    assert image.format == "JPEG"


@pytest.mark.parametrize(("count", "expected_calls"), [(1, 1), (9, 1), (10, 2)])
def test_visual_labeler_batches_at_nine_faces(tmp_path, count, expected_calls):
    provider = FakeVisionProvider()
    faces = [
        _face(tmp_path, f"{index:02d}", ((index * 19) % 255, 100, 160))
        for index in range(count)
    ]

    labels = label_face_images(provider, faces, batch_size=9, batch_workers=2)

    assert len(provider.calls) == expected_calls
    assert all(len(call[1]) == 1 for call in provider.calls)
    assert [item["face_id"] for item in labels] == [f"{index:02d}" for index in range(count)]


def test_visual_labeler_reviews_only_low_confidence_face(tmp_path):
    class LowConfidenceProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            response = super().complete_json_vision(system, images, user, schema)
            ids = images[0][0].split(":", 1)[1].split(",")
            for item in response["items"]:
                item["confidence"] = 0.42 if len(ids) > 1 and item["face_id"] == "01" else 0.94
            return response

    provider = LowConfidenceProvider()
    faces = [_face(tmp_path, f"{index:02d}", (180, 80 + index * 20, 120)) for index in range(3)]

    labels = label_face_images(
        provider,
        faces,
        batch_size=9,
        batch_workers=2,
        confidence_threshold=0.6,
    )

    assert [call[1][0][0] for call in provider.calls] == [
        "编号九宫格:00,01,02",
        "编号九宫格:01",
    ]
    assert [item["confidence"] for item in labels] == [0.94, 0.94, 0.94]


def test_visual_labeler_retries_empty_compatible_endpoint_response(tmp_path):
    class FlakyProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            if len(self.calls) == 1:
                raise llm.LLMError("vision endpoint returned empty text")
            ids = images[0][0].split(":", 1)[1].split(",")
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
                    for tag in ids
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

    labels = label_face_images(
        provider,
        [_face(tmp_path, "00", (220, 220, 220))],
        max_attempts=2,
    )

    assert len(provider.calls) == 2
    assert labels == [{
        "face_id": "00",
        "head_path": str(tmp_path / "00-head.png"),
        "failed": True,
        "error": "vision_label_failed",
    }]


def test_visual_labeler_preserves_valid_batch_items_and_falls_back_per_bad_face(
    tmp_path,
):
    class PartialBatchProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            ids = images[0][0].split(":", 1)[1].split(",")
            if len(ids) > 1:
                incomplete = _vision_label("02")
                incomplete.pop("mouth")
                return {"items": [
                    _vision_label("00", emotion="合法批次结果"),
                    _vision_label("01"),
                    _vision_label("01", emotion="重复结果"),
                    incomplete,
                ]}
            if ids == ["01"]:
                return {"items": [_vision_label("01", emotion="单图恢复")]}
            if ids == ["03"]:
                return {"items": [_vision_label("03", emotion="缺失项恢复")]}
            raise llm.LLMError("single-face endpoint failed")

    provider = PartialBatchProvider()
    faces = [
        _face(tmp_path, f"{index:02d}", (180, 80 + index * 20, 120))
        for index in range(4)
    ]

    labels = label_face_images(provider, faces, max_attempts=2)

    assert [call[1][0][0] for call in provider.calls] == [
        "编号九宫格:00,01,02,03",
        "编号九宫格:01",
        "编号九宫格:02",
        "编号九宫格:02",
        "编号九宫格:03",
    ]
    assert labels[0]["primary_emotion"] == "合法批次结果"
    assert labels[1]["primary_emotion"] == "单图恢复"
    assert labels[2] == {
        "face_id": "02",
        "head_path": str(tmp_path / "02-head.png"),
        "failed": True,
        "error": "vision_label_failed",
    }
    assert labels[3]["primary_emotion"] == "缺失项恢复"

    con = assetdb.connect(tmp_path / "assets.db")
    result = persist_visual_face_labels(
        con,
        ident="generic-character",
        spine_signature="generic-skeleton",
        outfit_key="generic-outfit",
        model="vision-model",
        labels=labels,
    )

    assert result["saved_count"] == 3
    assert result["failed_count"] == 1
    assert result["failures"] == [{
        "face_id": "02", "error": "vision_label_failed",
    }]
    evidence = con.execute(
        """
        SELECT face_id,label,raw FROM face_evidence
        WHERE ident='generic-character' AND source='vision:vision-model'
        ORDER BY face_id
        """
    ).fetchall()
    assert [(row["face_id"], row["label"]) for row in evidence] == [
        ("00", "合法批次结果"), ("01", "单图恢复"),
        ("03", "缺失项恢复"),
    ]


def test_visual_labeler_keeps_valid_low_confidence_result_when_review_fails(tmp_path):
    class FailedReviewProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            ids = images[0][0].split(":", 1)[1].split(",")
            if len(ids) == 1:
                raise llm.LLMError("review failed")
            self.calls.append((system, images, user, schema))
            return {"items": [
                _vision_label(face_id, emotion="可用结果", confidence=0.4)
                for face_id in ids
            ]}

    provider = FailedReviewProvider()
    faces = [
        _face(tmp_path, f"{index:02d}", (180, 100, 120))
        for index in range(2)
    ]

    labels = label_face_images(provider, faces, max_attempts=1)

    assert [item["primary_emotion"] for item in labels] == ["可用结果", "可用结果"]
    assert all(not item.get("failed") for item in labels)


def test_failed_rerun_preserves_last_saved_label_and_effective_evidence(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {
        "ident": "generic-character",
        "spine_signature": "generic-skeleton",
        "outfit_key": "generic-outfit",
        "model": "vision-model",
    }
    label = _vision_label("face-x", emotion="上次成功结果")
    persist_visual_face_labels(con, **scope, labels=[label])

    result = persist_visual_face_labels(con, **scope, labels=[{
        "face_id": "face-x",
        "failed": True,
        "error": "vision_label_failed",
    }])

    assert result["saved_count"] == 0
    assert result["failed_count"] == 1
    assert list_visual_face_labels(con, **{key: scope[key] for key in (
        "ident", "spine_signature", "outfit_key",
    )})[0]["effective"]["primary_emotion"] == "上次成功结果"
    evidence = con.execute(
        """
        SELECT label,label_cn FROM face_evidence
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id='face-x'
          AND source='vision:vision-model'
        """,
        (scope["ident"], scope["spine_signature"], scope["outfit_key"]),
    ).fetchone()
    assert tuple(evidence) == ("上次成功结果", "上次成功结果")


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


def test_manual_visual_label_override_survives_different_model_rerun_and_syncs_evidence(
    tmp_path,
):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {
        "ident": "generic-character",
        "spine_signature": "generic-skeleton",
        "outfit_key": "generic-outfit",
    }
    first = _vision_label("face-x", emotion="模型 A 判断")
    first["head_path"] = str(tmp_path / "face-x.png")
    persist_visual_face_labels(con, **scope, model="model-a", labels=[first])
    original = list_visual_face_labels(con, **scope)[0]
    update_visual_face_label(
        con,
        **scope,
        face_id="face-x",
        patch={"primary_emotion": "人工确认", "brows": "眉头紧锁"},
        expected_version=original["version"],
    )

    second = _vision_label("face-x", emotion="模型 B 判断")
    second["brows"] = "眉毛上扬"
    second["head_path"] = str(tmp_path / "face-x-new.png")
    persist_visual_face_labels(con, **scope, model="model-b", labels=[second])

    current = list_visual_face_labels(con, **scope)[0]
    assert current["model"] == "model-b"
    assert current["ai"]["primary_emotion"] == "模型 B 判断"
    assert current["effective"]["primary_emotion"] == "人工确认"
    assert current["effective"]["brows"] == "眉头紧锁"
    assert current["reviewed"] is True
    rows = con.execute(
        """
        SELECT model,manual_json FROM face_visual_label
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
        ORDER BY model
        """,
        (*scope.values(), "face-x"),
    ).fetchall()
    assert [row["model"] for row in rows] == ["model-a", "model-b"]
    assert all(
        json.loads(row["manual_json"])["primary_emotion"] == "人工确认"
        for row in rows
    )
    evidence = con.execute(
        """
        SELECT source,label,label_cn FROM face_evidence
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id=?
          AND source LIKE 'vision:%'
        ORDER BY source
        """,
        (*scope.values(), "face-x"),
    ).fetchall()
    assert [tuple(row) for row in evidence] == [
        ("vision:model-a", "人工确认", "人工确认"),
        ("vision:model-b", "人工确认", "人工确认"),
    ]


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
