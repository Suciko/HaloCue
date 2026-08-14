import io
import json
from pathlib import Path

from PIL import Image
import pytest

import assetdb
import llm
import spine_face_labeler
from asset_catalog import _face_capabilities
from spine_face_labeler import (
    _SYSTEM,
    VISION_SCHEMA,
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


def _compact_label(
    face_id: str,
    *,
    emotion: str = "平静",
    usage: str = "普通交谈或安静倾听",
    confidence: float = 0.9,
):
    return {
        "face_id": face_id,
        "primary_emotion": emotion,
        "usage_hint_cn": usage,
        "confidence": confidence,
    }


def test_visual_schema_accepts_selection_semantics_without_face_components(tmp_path):
    item_schema = VISION_SCHEMA["properties"]["items"]["items"]
    assert set(item_schema["required"]) == {
        "face_id", "primary_emotion", "usage_hint_cn", "confidence",
    }
    assert not {
        "eyes", "brows", "mouth", "blush", "tears",
    }.intersection(item_schema["properties"])

    class CompactProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            ids = images[0][0].split(":", 1)[1].split(",")
            return {"items": [_compact_label(face_id) for face_id in ids]}

    provider = CompactProvider()
    labels = label_face_images(
        provider,
        [_face(tmp_path, "00", (220, 220, 220))],
        max_attempts=1,
    )

    assert labels[0]["usage_hint_cn"] == "普通交谈或安静倾听"
    assert "不得用是否脸红、是否流泪等视觉现象决定是否使用" in provider.calls[0][0]


def test_rich_semantics_round_trip_and_legacy_level(tmp_path):
    item_schema = VISION_SCHEMA["properties"]["items"]["items"]
    assert item_schema["properties"]["intensity"]["minimum"] == 0
    assert item_schema["properties"]["intensity"]["maximum"] == 3
    assert "emotion_family" in item_schema["properties"]
    assert "avoid_when_cn" in item_schema["properties"]

    con = assetdb.connect(tmp_path / "assets.db")
    persist_visual_face_labels(
        con,
        ident="hero",
        spine_signature="sig",
        outfit_key="outfit",
        model="vision-rich",
        labels=[{
            **_compact_label("17", emotion="慌乱尴尬"),
            "emotion_family": "embarrassment",
            "intensity": 2,
            "expression_class": "accent",
            "beat_fit": ["reaction", "denial"],
            "hold_policy": "short",
            "special_tags": [],
            "avoid_when_cn": "不适合真正发火",
        }],
    )
    rich = list_visual_face_labels(
        con, ident="hero", spine_signature="sig", outfit_key="outfit"
    )[0]
    assert rich["effective"]["semantic_level"] == "rich"
    assert rich["effective"]["intensity"] == 2
    assert rich["effective"]["beat_fit"] == ["reaction", "denial"]
    assert rich["effective"]["avoid_when_cn"] == "不适合真正发火"

    persist_visual_face_labels(
        con,
        ident="legacy",
        spine_signature="sig",
        outfit_key="outfit",
        model="vision-legacy",
        labels=[_compact_label("00")],
    )
    legacy = list_visual_face_labels(
        con, ident="legacy", spine_signature="sig", outfit_key="outfit"
    )[0]
    assert legacy["effective"]["semantic_level"] == "basic"


def test_legacy_provider_fields_remain_available_for_evidence_diagnostics(tmp_path):
    provider = FakeVisionProvider()
    labels = label_face_images(
        provider,
        [_face(tmp_path, "00", (220, 220, 220))],
        max_attempts=1,
    )

    con = assetdb.connect(tmp_path / "assets.db")
    persist_visual_face_labels(
        con,
        ident="generic-character",
        spine_signature="generic-skeleton",
        outfit_key="generic-outfit",
        model="legacy-model",
        labels=labels,
    )
    raw = con.execute(
        "SELECT raw FROM face_evidence WHERE source='vision:legacy-model'"
    ).fetchone()[0]

    assert json.loads(raw)["eyes"] == "自然睁眼"


def test_visual_labeler_allows_duplicate_selection_semantics(tmp_path):
    class DuplicateSemanticsProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            ids = images[0][0].split(":", 1)[1].split(",")
            return {"items": [_compact_label(face_id) for face_id in ids]}

    labels = label_face_images(
        DuplicateSemanticsProvider(),
        [
            _face(tmp_path, "00", (220, 220, 220)),
            _face(tmp_path, "01", (220, 220, 220)),
        ],
        max_attempts=1,
    )

    assert [item["primary_emotion"] for item in labels] == ["平静", "平静"]
    assert [item["usage_hint_cn"] for item in labels] == [
        "普通交谈或安静倾听", "普通交谈或安静倾听",
    ]


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
    assert "只判断整体情绪、态度和适用的台词语境" in _SYSTEM
    assert "涓" not in _SYSTEM


def test_vision_sheet_has_stable_three_by_three_dimensions(tmp_path):
    faces = [_face(tmp_path, f"{index:02d}", (index * 20, 80, 120)) for index in range(4)]

    blob, face_ids = make_vision_sheet(faces, cell_size=160, columns=3)
    image = Image.open(io.BytesIO(blob))

    assert face_ids == ["00", "01", "02", "03"]
    assert image.size == (480, 480)
    assert image.format == "JPEG"


def test_visual_labeler_defaults_to_four_face_comparison(tmp_path):
    provider = FakeVisionProvider()
    faces = [_face(tmp_path, f"{index:02d}", (index * 30, 80, 120)) for index in range(5)]
    label_face_images(provider, faces, max_attempts=1)
    assert len(provider.calls) == 2
    labels = sorted(call[1][0][0] for call in provider.calls)
    assert labels[0].endswith("00,01,02,03")
    assert labels[1].endswith("04")


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
                incomplete.pop("description_cn")
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


@pytest.mark.parametrize(("field", "invalid"), [
    ("confidence", "not-a-number"),
    ("confidence", 1.5),
    ("primary_emotion", 123),
    ("usage_hint_cn", 123),
])
def test_visual_labeler_reviews_batch_items_with_invalid_schema_values(
    tmp_path, field, invalid,
):
    class InvalidFieldProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            ids = images[0][0].split(":", 1)[1].split(",")
            if len(ids) == 1:
                return {"items": [_vision_label(ids[0], emotion="reviewed")]}
            invalid_item = _compact_label("00", emotion="invalid batch item")
            invalid_item[field] = invalid
            return {"items": [invalid_item, _compact_label("01", emotion="valid")]}

    provider = InvalidFieldProvider()
    labels = label_face_images(
        provider,
        [_face(tmp_path, "00", (180, 100, 120)), _face(tmp_path, "01", (80, 120, 180))],
        max_attempts=1,
    )

    assert len(provider.calls) == 2
    assert [item["primary_emotion"] for item in labels] == ["reviewed", "valid"]


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


def test_visual_labeler_reviews_usage_hint_that_describes_face_parts(tmp_path):
    class VisualDescriptionProvider(FakeVisionProvider):
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, images, user, schema))
            face_id = images[0][0].split(":", 1)[1].split(",")[0]
            if len(self.calls) == 1:
                return {"items": [_compact_label(
                    face_id, usage="眉毛下垂、眼睛含泪，嘴角向下"
                )]}
            return {"items": [_compact_label(
                face_id, usage="适合受到打击后低声回应或寻求安慰"
            )]}

    provider = VisualDescriptionProvider()
    labels = label_face_images(
        provider,
        [_face(tmp_path, "07", (120, 160, 200))],
        max_attempts=1,
    )

    assert len(provider.calls) == 2
    assert labels[0]["usage_hint_cn"] == "适合受到打击后低声回应或寻求安慰"


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


def test_refresh_visual_face_preview_paths_updates_every_model_without_labels(
    tmp_path,
):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {
        "ident": "626652156",
        "spine_signature": "date-sha",
        "outfit_key": "Kei_Date_Outfit",
    }
    old_head = tmp_path / "heads-v4" / "37.png"
    new_head = tmp_path / "heads-v7" / "37.png"
    portrait = tmp_path / "portraits-v7" / "37.png"
    for path in (old_head, new_head, portrait):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (64, 64), "white").save(path)
    for model, emotion in (("model-a", "抓狂"), ("model-b", "生闷气")):
        persist_visual_face_labels(
            con,
            **scope,
            model=model,
            labels=[{
                **_compact_label("37", emotion=emotion),
                "head_path": str(old_head),
            }],
        )
    con.execute(
        """
        UPDATE face_visual_label
        SET manual_json='{"primary_emotion":"人工抓狂"}', reviewed=1
        WHERE model='model-a'
        """
    )
    con.commit()
    before = {
        row["model"]: dict(row)
        for row in con.execute(
            "SELECT * FROM face_visual_label ORDER BY model"
        )
    }

    changed = spine_face_labeler.refresh_visual_face_preview_paths(
        con,
        **scope,
        faces=[RenderedFace("37", portrait, new_head)],
    )
    unchanged = spine_face_labeler.refresh_visual_face_preview_paths(
        con,
        **scope,
        faces=[RenderedFace("37", portrait, new_head)],
    )

    after = {
        row["model"]: dict(row)
        for row in con.execute(
            "SELECT * FROM face_visual_label ORDER BY model"
        )
    }
    assert changed == 2
    assert unchanged == 0
    for model in ("model-a", "model-b"):
        assert after[model]["head_path"] == str(new_head)
        assert after[model]["version"] == before[model]["version"] + 1
        for field in (
            "primary_emotion", "description_cn", "confidence",
            "manual_json", "reviewed",
        ):
            assert after[model][field] == before[model][field]


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
    expected_semantics = "轻微微笑｜温和、克制的轻微微笑"
    assert face["cn"] == expected_semantics
    assert face["semantic_cn"] == expected_semantics
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


def test_usage_hint_is_persisted_edited_and_synced_to_face_evidence(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {
        "ident": "generic-character",
        "spine_signature": "generic-skeleton",
        "outfit_key": "generic-outfit",
    }
    label = _compact_label(
        "00", emotion="平静", usage="普通交谈或安静倾听",
    )
    label["head_path"] = str(tmp_path / "00.png")
    persist_visual_face_labels(
        con, **scope, model="vision-model", labels=[label],
    )

    record = list_visual_face_labels(con, **scope)[0]
    assert record["effective"]["usage_hint_cn"] == "普通交谈或安静倾听"
    assert record["effective"]["description_cn"] == "普通交谈或安静倾听"

    saved = update_visual_face_label(
        con,
        **scope,
        face_id="00",
        patch={"usage_hint_cn": "压低情绪回应，不急于表态"},
        expected_version=record["version"],
    )

    assert saved["manual"]["usage_hint_cn"] == "压低情绪回应，不急于表态"
    assert saved["effective"]["description_cn"] == "压低情绪回应，不急于表态"
    evidence = con.execute(
        """
        SELECT label,label_cn FROM face_evidence
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id='00'
          AND source='vision:vision-model'
        """,
        tuple(scope.values()),
    ).fetchone()
    assert tuple(evidence) == (
        "平静｜压低情绪回应，不急于表态",
        "平静｜压低情绪回应，不急于表态",
    )


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
        ("vision:model-a", "人工确认｜模型 A 判断", "人工确认｜模型 A 判断"),
        ("vision:model-b", "人工确认｜模型 B 判断", "人工确认｜模型 B 判断"),
    ]


def test_manual_patch_and_restore_keep_each_models_ai_usage_in_its_evidence(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {
        "ident": "generic-character",
        "spine_signature": "generic-skeleton",
        "outfit_key": "generic-outfit",
    }
    for model, emotion, usage in (
        ("model-a", "emotion-a", "usage-a"),
        ("model-b", "emotion-b", "usage-b"),
    ):
        label = _compact_label("00", emotion=emotion, usage=usage)
        label["head_path"] = str(tmp_path / f"{model}.png")
        persist_visual_face_labels(con, **scope, model=model, labels=[label])

    current = list_visual_face_labels(con, **scope)[0]
    saved = update_visual_face_label(
        con,
        **scope,
        face_id="00",
        patch={"primary_emotion": "manual"},
        expected_version=current["version"],
    )
    rows = con.execute(
        """
        SELECT source,label_cn FROM face_evidence
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id='00'
          AND source LIKE 'vision:%'
        ORDER BY source
        """,
        tuple(scope.values()),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("vision:model-a", "manual｜usage-a"),
        ("vision:model-b", "manual｜usage-b"),
    ]

    update_visual_face_label(
        con,
        **scope,
        face_id="00",
        patch={"primary_emotion": None},
        expected_version=saved["version"],
    )
    rows = con.execute(
        """
        SELECT source,label_cn FROM face_evidence
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND face_id='00'
          AND source LIKE 'vision:%'
        ORDER BY source
        """,
        tuple(scope.values()),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("vision:model-a", "emotion-a｜usage-a"),
        ("vision:model-b", "emotion-b｜usage-b"),
    ]


def test_manual_usage_hint_can_be_empty_and_restored_to_ai(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = {
        "ident": "generic-character",
        "spine_signature": "generic-skeleton",
        "outfit_key": "generic-outfit",
    }
    label = _compact_label("00", emotion="calm", usage="quiet replies")
    label["head_path"] = str(tmp_path / "00.png")
    persist_visual_face_labels(con, **scope, model="model-a", labels=[label])

    current = list_visual_face_labels(con, **scope)[0]
    cleared = update_visual_face_label(
        con,
        **scope,
        face_id="00",
        patch={"usage_hint_cn": ""},
        expected_version=current["version"],
    )
    assert cleared["manual"]["usage_hint_cn"] == ""
    assert cleared["effective"]["usage_hint_cn"] == ""
    assert con.execute(
        "SELECT label_cn FROM face_evidence WHERE source='vision:model-a'"
    ).fetchone()[0] == "calm"

    restored = update_visual_face_label(
        con,
        **scope,
        face_id="00",
        patch={"usage_hint_cn": None},
        expected_version=cleared["version"],
    )
    assert "usage_hint_cn" not in restored["manual"]
    assert restored["effective"]["usage_hint_cn"] == "quiet replies"


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
