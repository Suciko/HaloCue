"""Rich frozen labels must survive a smaller local database and reach the model."""

import copy
import assetdb
from asset_catalog import merge_model_constraints
from annotate import annotation_constraints, build_static


def index_fixture():
    return {
        "bg": {},
        "sounds": [],
        "enums": {"emoticon": {}, "action": {}},
        "characters": [
            {
                "identifier": "actor",
                "name": "Actor",
                "outfit_key": "school",
                "faces": [
                    {"id": "01", "raw": "01", "label": "normal"},
                    {"id": "04", "raw": "04", "label": "surprise"},
                ],
            }
        ],
        "face_capabilities": {
            "actor": [
                {
                    "spine_signature": "",
                    "outfit_key": "",
                    "faces": [
                        {"id": "01", "raw": "01", "label": "normal", "sources": ["atlas_candidate"]}
                    ],
                },
                {
                    "spine_signature": "sig-school",
                    "outfit_key": "school",
                    "faces": [
                        {
                            "id": "01",
                            "raw": "01",
                            "label": "平静",
                            "semantic_cn": "平静",
                            "usage_hint_cn": "日常倾听",
                            "hold_policy": "hold",
                            "avoid_when_cn": "激烈爆发",
                            "sources": ["vision:fixture"],
                        },
                        {
                            "id": "04",
                            "raw": "04",
                            "label": "慌张",
                            "usage_hint_cn": "突发意外",
                            "hold_policy": "short",
                            "sources": ["vision:fixture"],
                        },
                        {
                            "id": "99",
                            "raw": "99",
                            "label": "未经登记",
                            "sources": ["vision:fixture"],
                        },
                    ],
                },
                {
                    "spine_signature": "sig-winter",
                    "outfit_key": "winter",
                    "faces": [
                        {
                            "id": "04",
                            "raw": "04",
                            "label": "错误冬装标签",
                            "sources": ["vision:fixture"],
                        }
                    ],
                },
            ]
        },
    }


def test_smaller_database_does_not_replace_rich_index_variants(tmp_path):
    index = index_fixture()
    before = copy.deepcopy(index)
    con = assetdb.connect(tmp_path / "assets.db")
    try:
        con.execute(
            "INSERT INTO face_evidence (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count) VALUES (?,?,?,?,?,?,?,?,?)",
            ("actor", "", "", "01", "atlas_candidate", "01", "normal", "", 0),
        )
        con.commit()
        merged = merge_model_constraints(index, con, scope="test")
        variants = merged["face_capabilities"]["actor"]
        assert len(variants) == 3
        assert (
            next(v for v in variants if v["outfit_key"] == "school")["faces"][0]["usage_hint_cn"]
            == "日常倾听"
        )
        assert index == before
        assert "99" not in {face["id"] for face in merged["characters"][0]["faces"]}
        assert "未经登记" not in build_static(
            merged, {"Actor": {"id": "actor", "portrait": True}}, ["Actor"]
        )
    finally:
        con.close()


def test_prompt_and_allowlist_use_same_registered_outfit_and_face_ids():
    index = index_fixture()
    cast = {"Actor": {"id": "actor", "portrait": True}}
    text = build_static(index, cast, ["Actor"])
    assert "日常倾听" in text and "突发意外" in text and "不适用=激烈爆发" in text
    assert "错误冬装标签" not in text and "未经登记" not in text
    constraints = annotation_constraints(index, cast)
    assert constraints["faces_by_id"]["actor"] == {"01", "04"}
    assert constraints["face_evidence_by_id"]["actor"]["04"] == "visual_confirmed"


def test_explicit_missing_outfit_never_falls_back_to_frozen_default():
    index = index_fixture()
    cast = {"Actor": {"id": "actor", "portrait": True, "outfit_key": "missing"}}
    assert annotation_constraints(index, cast)["faces_by_id"]["actor"] == set()
    assert "突发意外" not in build_static(index, cast, ["Actor"])


def test_ambiguous_selected_outfit_is_not_merged_between_skeletons():
    index = index_fixture()
    index["face_capabilities"]["actor"].append(
        {
            "spine_signature": "school-v2",
            "outfit_key": "school",
            "faces": [{"id": "04", "label": "另一个骨骼", "sources": ["vision:fixture"]}],
        }
    )
    cast = {"Actor": {"id": "actor", "portrait": True}}
    assert annotation_constraints(index, cast)["faces_by_id"]["actor"] == set()
    assert "另一个骨骼" not in build_static(index, cast, ["Actor"])


def test_same_variant_weak_rows_cannot_erase_rich_semantics():
    from asset_catalog import _merge_face_variants

    original = [
        {
            "spine_signature": "sig",
            "outfit_key": "school",
            "faces": [
                {
                    "id": "01",
                    "raw": "01",
                    "semantic_cn": "温和",
                    "usage_hint_cn": "日常倾听",
                    "semantic_level": "rich",
                    "sources": ["vision:fixture"],
                }
            ],
        }
    ]
    sparse = [
        {
            "spine_signature": "sig",
            "outfit_key": "school",
            "faces": [
                {
                    "id": "01",
                    "raw": "01",
                    "label": "normal",
                    "semantic_cn": "",
                    "semantic_level": "basic",
                    "sources": ["aap_observed"],
                }
            ],
        }
    ]
    before = copy.deepcopy(original)
    merged = _merge_face_variants(original, sparse)
    face = merged[0]["faces"][0]
    assert face["semantic_cn"] == "温和"
    assert face["usage_hint_cn"] == "日常倾听"
    assert face["semantic_level"] == "rich"
    assert face["visual_evidence"] == "visual_confirmed"
    assert set(face["sources"]) == {"vision:fixture", "aap_observed"}
    assert original == before
