import json
import sqlite3

from audit_spine_face_labels import audit


def test_audit_requires_every_binding_and_rejects_unknown_face_ids(tmp_path):
    head = tmp_path / "head.png"
    head.write_bytes(b"preview")
    plan = {
        "targets": [{
            "source_kind": "official_base",
            "face_ids": ["00", "01"],
            "identity_bindings": [
                {"identifier": "a", "outfit_key": "outfit", "spine_signature": "sig", "identity_status": "mapped"},
                {"identifier": "b", "outfit_key": "outfit", "spine_signature": "sig", "identity_status": "mapped"},
            ],
        }]
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    db = tmp_path / "labels.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE face_visual_label(
          ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT,
          model TEXT, primary_emotion TEXT, confidence REAL,
          description_cn TEXT, semantic_json TEXT, head_path TEXT
        )
        """
    )
    semantic = json.dumps({
        "emotion_family": "neutral",
        "expression_class": "base",
        "hold_policy": "hold",
        "beat_fit": ["dialogue"],
    })
    for ident in ("a", "b"):
        for face_id in ("00", "01"):
            con.execute(
                "INSERT INTO face_visual_label VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ident, "sig", "outfit", face_id, "current", "平静", 0.9,
                 "适合平静对话", semantic, str(head)),
            )
    con.commit()
    con.close()

    complete = audit(plan_path, db, "current")

    assert complete["status"] == "ready"
    assert complete["expected_identity_face_rows"] == 4
    assert complete["complete_target_count"] == 1

    con = sqlite3.connect(db)
    con.execute(
        "UPDATE face_visual_label SET primary_emotion=?, confidence=0 "
        "WHERE ident='a' AND face_id='00'",
        ("无法识别",),
    )
    con.commit()
    con.close()

    unusable = audit(plan_path, db, "current")
    assert unusable["status"] == "incomplete"
    assert unusable["invalid_row_count"] == 1
    assert unusable["invalid_rows_sample"][0]["error"] == "unusable_visual_label"

    con = sqlite3.connect(db)
    con.execute(
        "UPDATE face_visual_label SET primary_emotion=?, confidence=0.9 "
        "WHERE ident='a' AND face_id='00'",
        ("平静",),
    )
    con.execute(
        "INSERT INTO face_visual_label VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("a", "sig", "outfit", "99", "current", "平静", 0.9,
         "计划外表情", semantic, str(head)),
    )
    con.commit()
    con.close()

    invalid = audit(plan_path, db, "current")
    assert invalid["status"] == "incomplete"
    assert invalid["unexpected_row_count"] == 1


def test_audit_applies_two_stage_validation_to_v4(tmp_path):
    head = tmp_path / "head.png"
    head.write_bytes(b"preview")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "targets": [{
            "source_kind": "official_base",
            "face_ids": ["00"],
            "identity_bindings": [{
                "identifier": "a",
                "outfit_key": "outfit",
                "spine_signature": "sig",
                "identity_status": "mapped",
            }],
        }],
    }), encoding="utf-8")
    db = tmp_path / "labels.db"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE face_visual_label(
          ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT,
          model TEXT, primary_emotion TEXT, confidence REAL,
          description_cn TEXT, semantic_json TEXT, head_path TEXT,
          observation_json TEXT, backend_json TEXT
        )
        """
    )
    semantic = json.dumps({
        "emotion_family": "neutral",
        "intensity": 0,
        "expression_class": "base",
        "hold_policy": "hold",
        "beat_fit": ["dialogue"],
        "delivery_fit": ["neutral"],
        "usage_frequency": "default",
        "semantic_confidence": 0.9,
    })
    con.execute(
        "INSERT INTO face_visual_label VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "a", "sig", "outfit", "00",
            "gemini-3.7-flash:semantic-profile-v4", "平静", 0.9,
            "适合平静对话", semantic, str(head), "{}",
            json.dumps({"pipeline": "observation-backend-v4"}),
        ),
    )
    con.commit()
    con.close()

    report = audit(plan_path, db, "gemini-3.7-flash:semantic-profile-v4")

    assert report["status"] == "incomplete"
    errors = {item["error"] for item in report["invalid_rows_sample"]}
    assert "incomplete_visual_facts" in errors
    assert report["invalid_key_count"] == 1
    assert report["invalid_error_counts"]["incomplete_visual_facts"] == 1
    assert report["vision_item_invalid_count"] == 1
    assert report["unexpected_backend_hard_block_count"] == 1
