import json
from pathlib import Path

from PIL import Image

import assetdb
from scene_asset_labeler import (
    SceneVisionInput,
    generator_background_keys,
    label_scene_images,
    normalize_scene_labels,
    persist_scene_label,
)


def _image(path: Path, color=(90, 120, 150)) -> Path:
    Image.new("RGB", (80, 45), color).save(path)
    return path


def _target(path: Path, *, item_id="S1", key="BG_Test") -> SceneVisionInput:
    return SceneVisionInput(
        item_id=item_id,
        asset_key=key,
        resource_channel="background",
        image_path=path,
        source_kind="extra_pack",
        content_sha256="digest",
        source_category="AA/bgs/未分类",
        original_filename=path.name,
    )


def _labels(**changes):
    value = {
        "visual_kind": "background",
        "label": "清晨教室",
        "description": "空教室中有成排课桌和晨光",
        "main_category": "campus",
        "subcategory": "教室",
        "place": "学校教室",
        "indoor_outdoor": "indoor",
        "time": "dawn",
        "weather": "",
        "season": "",
        "mood": "安静",
        "staging_capacity": "group",
        "has_fixed_characters": False,
        "visible_character_count": 0,
        "dialogue_suitable": True,
        "usage_hint_cn": "适合上课前或安静交谈",
        "avoid_when_cn": "不适合室外场景",
        "narrative_action_cn": "",
        "character_description_cn": "",
        "shot_type": "wide",
        "display_policy": "hold",
        "tags": ["教室", "课桌", "晨光"],
        "search_terms_cn": ["课室", "上课地点", "空教室"],
        "setting_scope": "generic",
        "affiliation_keys": [],
        "affiliation_evidence": ["visual_architecture"],
        "affiliation_hint_cn": "没有可确认的专属校徽或建筑特征",
        "affiliation_confidence": 0,
        "reuse_scope": "generic",
        "compatible_affiliation_keys": [],
        "reuse_hint_cn": "没有阻碍跨场景使用的专属标识",
        "confidence": 0.94,
    }
    value.update(changes)
    return value


def test_normalize_scene_labels_keeps_ai_subcategory_but_blocks_cg_as_dialogue_bg():
    labels = normalize_scene_labels(_labels(
        visual_kind="cg",
        subcategory="两人争执特写",
        staging_capacity="pair",
        dialogue_suitable=True,
        setting_scope="unknown",
        reuse_scope="unknown",
        tags=["争执", "特写", "争执"],
    ))

    assert labels["visual_kind"] == "cg"
    assert labels["subcategory"] == "两人争执特写"
    assert labels["dialogue_suitable"] is False
    assert labels["staging_capacity"] == "none"
    assert labels["setting_scope"] == "not_applicable"
    assert labels["reuse_scope"] == "not_applicable"
    assert labels["category_path_cn"] == "非地点资源 / 校园 / 两人争执特写"
    assert labels["tags"] == ["争执", "特写"]


def test_scene_affiliation_scope_requires_consistent_keys_and_evidence(tmp_path):
    target = _target(_image(tmp_path / "schale.png"), key="BG_SchaleOffice")

    class Provider:
        def complete_json_vision(self, system, images, user, schema):
            return {"items": [{
                "item_id": target.item_id,
                **_labels(
                    setting_scope="specific",
                    affiliation_keys=["schale"],
                    affiliation_evidence=["asset_key", "visual_architecture"],
                    affiliation_hint_cn="资源名与画面均指向夏莱办公室",
                    affiliation_confidence=0.96,
                    reuse_scope="generic",
                    compatible_affiliation_keys=[],
                    reuse_hint_cn="画面没有夏莱文字或专属标志，可作为通用办公室",
                ),
            }]}

    labels = label_scene_images(Provider(), [target])[0]

    assert labels["setting_scope"] == "specific"
    assert labels["affiliation_keys"] == ["schale"]
    assert labels["affiliation_names_cn"] == ["夏莱"]
    assert labels["affiliation_confidence"] == 0.96
    assert labels["reuse_scope"] == "generic"
    assert labels["category_path_cn"] == "夏莱 / 校园 / 教室"


def test_scene_affiliation_strips_asset_key_evidence_without_real_token(tmp_path):
    target = _target(
        _image(tmp_path / "corridor.png"), key="bg_abandonedcorridor"
    )

    class Provider:
        def complete_json_vision(self, system, images, user, schema):
            return {"items": [{
                "item_id": target.item_id,
                **_labels(
                    setting_scope="specific",
                    affiliation_keys=["arius"],
                    affiliation_evidence=["asset_key", "visual_architecture"],
                    affiliation_hint_cn="废弃哥特回廊",
                    affiliation_confidence=0.88,
                    reuse_scope="cross_affiliation",
                    compatible_affiliation_keys=["trinity"],
                    reuse_hint_cn="也可用于崔尼蒂遗迹",
                ),
            }]}

    labels = label_scene_images(Provider(), [target], retries=1)[0]

    assert labels["affiliation_evidence"] == ["visual_architecture"]


def test_scene_batch_retries_until_every_expected_item_id_is_returned(tmp_path):
    first = _target(_image(tmp_path / "a.png"), item_id="S1", key="BG_A")
    second = _target(_image(tmp_path / "b.png"), item_id="S2", key="BG_B")

    class Provider:
        def __init__(self):
            self.calls = 0

        def complete_json_vision(self, system, images, user, schema):
            self.calls += 1
            ids = ["S1"] if self.calls == 1 else ["S1", "S2"]
            return {"items": [{"item_id": item_id, **_labels()} for item_id in ids]}

    provider = Provider()
    result = label_scene_images(provider, [first, second], retries=2)

    assert provider.calls == 2
    assert [row["item_id"] for row in result] == ["S1", "S2"]


def test_automatic_scene_label_does_not_overwrite_manual_lock(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    target = _target(_image(tmp_path / "bg.png"))
    con.execute(
        """
        INSERT INTO scene_visual_label
          (resource_channel,asset_key,content_sha256,source_kind,model,
           visual_kind,label_json,confidence,status,manual_json)
        VALUES ('background','BG_Test','digest','extra_pack','manual',
                'background',?,1,'manual_locked',?)
        """,
        (
            json.dumps(_labels(label="人工教室"), ensure_ascii=False),
            json.dumps({"label": "人工教室"}, ensure_ascii=False),
        ),
    )
    con.commit()

    saved = persist_scene_label(
        con, target=target, model="gemini-current", labels=_labels(label="模型教室")
    )
    rows = con.execute(
        "SELECT model,label_json,status FROM scene_visual_label"
    ).fetchall()

    assert saved is False
    assert len(rows) == 1
    assert rows[0]["model"] == "manual"
    assert rows[0]["status"] == "manual_locked"
    assert json.loads(rows[0]["label_json"])["label"] == "人工教室"


def test_effective_scene_label_prefers_active_model_then_extra_pack(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    for model, source, label in (
        ("old", "extra_pack", "旧额外包"),
        ("current", "official_base", "当前基础包"),
        ("current", "extra_pack", "当前额外包"),
    ):
        con.execute(
            """
            INSERT INTO scene_visual_label
              (resource_channel,asset_key,content_sha256,source_kind,model,
               visual_kind,label_json,confidence,status)
            VALUES ('background','BG_Test',?,?,?,'background',?,.9,'ready')
            """,
            (label, source, model, json.dumps(_labels(label=label), ensure_ascii=False)),
        )
    con.commit()
    assetdb.set_active_scene_label_model(con, "current")

    row = assetdb.effective_scene_label_rows(con)[0]

    assert row["model"] == "current"
    assert row["source_kind"] == "extra_pack"
    assert json.loads(row["label_json"])["label"] == "当前额外包"


def test_generator_background_keys_exclude_ready_cg_but_keep_legacy_fallback():
    index = {
        "bg": {"BG_Room": 1, "BG_CG": 2, "BG_Legacy": 3},
        "scene_labels": {"background": {
            "BG_Room": {
                "visual_kind": "background", "dialogue_suitable": True,
                "status": "ready",
            },
            "BG_CG": {
                "visual_kind": "cg", "dialogue_suitable": False,
                "status": "ready",
            },
        }},
    }

    assert generator_background_keys(index) == {"BG_Room", "BG_Legacy"}


def test_unified_scene_query_searches_categories_and_filters_generator_backgrounds(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    room = _target(_image(tmp_path / "room.png"), key="BG_Room")
    cg = SceneVisionInput(
        **{
            **room.__dict__,
            "item_id": "S2",
            "asset_key": "BG_CG",
            "content_sha256": "cg-digest",
        }
    )
    persist_scene_label(
        con, target=room, model="current",
        labels=_labels(main_category="campus", subcategory="教室"),
    )
    persist_scene_label(
        con, target=cg, model="current",
        labels=_labels(
            visual_kind="cg", label="争执特写",
            main_category="event", subcategory="争执场面",
            dialogue_suitable=False,
        ),
    )

    searched = assetdb.query_scene_assets(con, query="校园")
    usable = assetdb.query_scene_assets(con, generator_only=True)

    assert [item["asset_key"] for item in searched] == ["BG_Room"]
    assert [item["asset_key"] for item in usable] == ["BG_Room"]

    exported = assetdb.export_json(con, tmp_path / "resources.json")
    assert exported["scene_labels"]["background"]["BG_Room"]["subcategory"] == "教室"
    assert exported["scene_labels"]["background"]["BG_CG"]["visual_kind"] == "cg"


def test_export_json_preserves_legacy_compatibility_fields_and_missing_characters(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO character(ident,name,club,spine,avatar) VALUES(?,?,?,?,?)",
        ("CH_DB", "数据库角色", "", "characters/CH_DB", ""),
    )
    con.commit()
    output = tmp_path / "resources.json"
    output.write_text(json.dumps({
        "_source": "legacy-0.9.2",
        "faces_used": {"CH_OLD": ["00"]},
        "face_capabilities": {"CH_OLD": {"00": ["eye"]}},
        "characters": [
            {
                "identifier": "CH_DB", "spine": "characters/CH_DB",
                "legacy_extra": "keep",
            },
            {
                "identifier": "CH_DB", "spine": "characters/NP_DB",
                "legacy_extra": "keep-variant",
            },
            {"identifier": "CH_OLD", "name": "仅旧索引存在"},
        ],
    }, ensure_ascii=False), encoding="utf-8")

    exported = assetdb.export_json(con, output)

    assert exported["_source"] == "legacy-0.9.2"
    assert exported["faces_used"] == {"CH_OLD": ["00"]}
    assert exported["face_capabilities"]["CH_OLD"]["00"] == ["eye"]
    by_identity = {
        (row["identifier"], row.get("spine")): row
        for row in exported["characters"]
    }
    assert by_identity[("CH_DB", "characters/CH_DB")]["legacy_extra"] == "keep"
    assert by_identity[("CH_DB", "characters/NP_DB")]["legacy_extra"] == "keep-variant"
    assert by_identity[("CH_OLD", None)]["name"] == "仅旧索引存在"
