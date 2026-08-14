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
        "INSERT INTO face_visual_label VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("a", "sig", "outfit", "99", "current", "平静", 0.9,
         "计划外表情", semantic, str(head)),
    )
    con.commit()
    con.close()

    invalid = audit(plan_path, db, "current")
    assert invalid["status"] == "incomplete"
    assert invalid["unexpected_row_count"] == 1
