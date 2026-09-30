"""Frozen annotation visibility, with synthetic data and no writes to user runs."""

import copy

from halocue_production.legacy_adapter import Legacy093Adapter


def adapter_with(resources):
    import annotate

    adapter = object.__new__(Legacy093Adapter)
    adapter._modules = {"annotate": annotate}
    adapter._draft_resources = lambda token: copy.deepcopy(resources)
    adapter._task_custom_assets = lambda token: []
    adapter._preview_available = lambda *args: False

    class Names:
        def resolve(self, value):
            return {"aliases": []}

    adapter.name_baseline = Names()
    return adapter


def resources_with_faces():
    return {
        "characters": [
            {
                "identifier": "actor",
                "name": "角色",
                "outfit_key": "school",
                "spine_signature": "sig",
                "faces": [{"id": "00", "label": "平静"}, {"id": "01", "label": ""}],
            }
        ],
        "face_capabilities": {
            "actor": [
                {
                    "outfit_key": "school",
                    "spine_signature": "sig",
                    "faces": [
                        {
                            "id": "01",
                            "semantic_cn": "害羞",
                            "usage_hint_cn": "掩饰关心",
                            "beat_fit": ["hesitation"],
                            "hold_policy": "short",
                            "avoid_when_cn": "严肃宣誓",
                            "intensity": 0,
                            "private_path": "never expose",
                        },
                        {"id": "99", "semantic_cn": "不应增加编号"},
                    ],
                },
                {
                    "outfit_key": "swim",
                    "spine_signature": "other",
                    "faces": [{"id": "01", "semantic_cn": "错误服装"}],
                },
            ]
        },
    }


def test_frozen_face_annotations_are_scoped_and_do_not_expand_ids():
    source = resources_with_faces()
    original = copy.deepcopy(source)
    result = adapter_with(source).draft_character_detail("token", "actor")
    faces = result["character"]["faces"]
    assert [face["id"] for face in faces] == ["00", "01"]
    assert faces[1]["usage_hint_cn"] == "掩饰关心"
    assert faces[1]["intensity"] == 0
    assert "private_path" not in faces[1]
    assert source == original


def test_unscoped_character_does_not_borrow_another_outfits_labels():
    source = resources_with_faces()
    source["characters"][0].pop("outfit_key")
    source["characters"][0].pop("spine_signature")
    faces = adapter_with(source).draft_character_detail("token", "actor")["character"]["faces"]
    assert "semantic_cn" not in faces[1]


def test_direct_face_annotation_wins_and_old_faces_still_work():
    source = resources_with_faces()
    source["characters"][0]["faces"][1]["usage_hint_cn"] = "作者修正"
    source["characters"][0]["faces"].append("02")
    faces = adapter_with(source).draft_character_detail("token", "actor")["character"]["faces"]
    assert faces[1]["usage_hint_cn"] == "作者修正"
    assert faces[2] == {"id": "02", "raw": "02", "label": "02"}


def test_background_usage_survives_api_and_searches_positive_alias_only():
    source = {
        "bg": {"BG_Test": 1},
        "bg_label": {"BG_Test": {"label": "社团室", "place": "室内"}},
        "scene_labels": {
            "background": {
                "BG_Test": {
                    "label": "",
                    "usage_hint_cn": "整理资料",
                    "avoid_when_cn": "战斗爆炸",
                    "search_terms_cn": ["游戏开发"],
                    "has_fixed_characters": True,
                    "dialogue_suitable": False,
                }
            }
        },
    }
    adapter = adapter_with(source)
    result = adapter.list_draft_resources("token", "backgrounds", query="游戏开发")
    assert result["total"] == 1
    row = result["items"][0]
    assert row["name"] == "社团室"
    assert row["avoid_when"] == "战斗爆炸"
    assert row["has_fixed_characters"] is True
    assert row["dialogue_suitable"] is False
    assert adapter.list_draft_resources("token", "backgrounds", query="战斗爆炸")["total"] == 0


def test_legacy_numeric_string_intensity_is_normalized():
    for value, expected in [("2", 2), (0.0, 0), (True, None), ("high", None), (5, None)]:
        source = resources_with_faces()
        source["characters"][0]["faces"][1]["intensity"] = value
        face = adapter_with(source).draft_character_detail("token", "actor")["character"]["faces"][
            1
        ]
        assert face.get("intensity") == expected


def test_new_task_keeps_rich_index_when_database_is_sparse(settings, tmp_path):
    import json
    from dataclasses import replace
    import assetdb
    from tests.test_frozen_face_annotation_pipeline import index_fixture
    from halocue_production.service import ProductionService

    index = tmp_path / "rich-index.json"
    index.write_text(json.dumps(index_fixture(), ensure_ascii=False), encoding="utf-8")
    legacy = tmp_path / "sparse-db"
    legacy.mkdir()
    connection = assetdb.connect(legacy / "aa_assets.db")
    connection.execute(
        "INSERT INTO face_evidence (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count) VALUES (?,?,?,?,?,?,?,?,?)",
        ("actor", "", "", "01", "atlas_candidate", "01", "normal", "", 0),
    )
    connection.commit()
    connection.close()
    service = ProductionService(replace(settings, legacy_root=legacy, resource_index=index))
    try:
        created = service.create_run(
            {
                "project": "Rich frozen pipeline",
                "source": {"kind": "inline", "text": "Actor: Hello.\n"},
            }
        )
        token = created["run"]["draft_token"]
        frozen = service.adapter._draft_resources(token)
        annotate = service.adapter._modules["annotate"]
        cast = {"Actor": {"id": "actor", "portrait": True}}
        assert "日常倾听" in annotate.build_static(frozen, cast, ["Actor"])
        assert annotate.annotation_constraints(frozen, cast)["faces_by_id"]["actor"] == {"01", "04"}
        character = service.adapter.draft_character_detail(token, "actor")["character"]
        assert (
            next(face for face in character["faces"] if face["id"] == "04")["usage_hint_cn"]
            == "突发意外"
        )
        assert "99" not in {face["id"] for face in character["faces"]}
    finally:
        service.jobs.close()
