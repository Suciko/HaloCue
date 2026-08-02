from asset_catalog import export_model_constraints, migrate, upsert_candidate
from asset_models import AssetCandidate
import assetdb


def test_catalog_persists_semantic_face_combinations_but_excludes_special_ids(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    candidate = AssetCandidate(
        kind="character", source_path=tmp_path, stem="date", aa_key="626652156", sha256="digest",
        metadata={
            "spine_signature": "date-sha", "outfit_key": "Kei_Date_Outfit", "faces": [],
            "expression_mode": "semantic_modular",
            "semantic_face_combinations": {
                "00": {"face_id": "00", "raw_parts": ["base"], "labels": ["default"], "special": False},
                "03": {"face_id": "03", "raw_parts": ["surprise-eye"], "labels": ["surprise"], "special": False},
                "99": {"face_id": "99", "raw_parts": ["special"], "labels": [], "special": True},
            },
        },
    )

    upsert_candidate(con, candidate, scope="date-project", status="registered")
    character = export_model_constraints(con, scope="date-project")["characters"][0]
    faces = character["face_capabilities"][0]["faces"]

    assert [face["id"] for face in faces] == ["00", "03"]
    assert faces[1]["cn"] == "surprise"
    assert faces[1]["semantic_cn"] == "surprise"
    assert faces[1]["sources"] == ["spine_semantic"]


def test_observed_special_animation_can_receive_semantics_without_guessing_legality(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    con.execute(
        """
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES ('626652156','date-sha','Kei_Date_Outfit','99',
                'aap_observed','99','','',1)
        """
    )
    candidate = AssetCandidate(
        kind="character",
        source_path=tmp_path,
        stem="date",
        aa_key="626652156",
        sha256="digest",
        metadata={
            "spine_signature": "date-sha",
            "outfit_key": "Kei_Date_Outfit",
            "faces": [],
            "semantic_face_combinations": {
                "99": {
                    "face_id": "99",
                    "raw_parts": ["closed eyes"],
                    "labels": ["闭眼", "平静"],
                    "special": True,
                }
            },
        },
    )

    upsert_candidate(con, candidate, scope="date-project", status="registered")

    rows = con.execute(
        """
        SELECT source,label_cn FROM face_evidence
        WHERE ident='626652156' AND spine_signature='date-sha'
          AND outfit_key='Kei_Date_Outfit' AND face_id='99'
        ORDER BY source
        """
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("aap_observed", ""),
        ("spine_semantic", "闭眼、平静"),
    ]


def test_catalog_prefers_condensed_expression_semantics_over_raw_part_union(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    candidate = AssetCandidate(
        kind="character",
        source_path=tmp_path,
        stem="date",
        aa_key="626652156",
        sha256="digest",
        metadata={
            "spine_signature": "date-sha",
            "outfit_key": "Kei_Date_Outfit",
            "faces": [],
            "semantic_face_combinations": {
                "42": {
                    "face_id": "42",
                    "raw_parts": ["cry-mouth", "wide-eye", "sweat"],
                    "labels": ["哭诉", "紧张", "惊讶", "强烈脸红", "汗"],
                    "primary_emotion": "慌张",
                    "semantic_labels": ["慌张", "害羞", "强烈脸红", "汗"],
                    "special": False,
                }
            },
        },
    )

    upsert_candidate(con, candidate, scope="date-project", status="registered")

    face = export_model_constraints(
        con, scope="date-project"
    )["characters"][0]["face_capabilities"][0]["faces"][0]
    assert face["label"] == "慌张"
    assert face["semantic_cn"] == "慌张、害羞、强烈脸红、汗"
