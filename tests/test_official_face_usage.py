import assetdb
from official_face_examples import load_face_examples
from spine_face_labeler import label_face_images
from PIL import Image
from spine_face_renderer import RenderedFace


def _face(tmp_path, face_id, color):
    head = tmp_path / f"{face_id}.png"
    Image.new("RGBA", (128, 128), (*color, 255)).save(head)
    return RenderedFace(face_id=face_id, portrait_path=head, head_path=head)


def _compact_label(face_id):
    return {
        "face_id": face_id, "primary_emotion": "平静",
        "usage_hint_cn": "普通交谈或安静倾听", "eyes": "睁眼",
        "brows": "自然", "mouth": "闭嘴", "blush": False,
        "tears": False, "confidence": 0.9,
    }


def test_official_usage_is_separate_and_variant_aware(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.replace_face_official_usage(con, [
        {"ident": "hero", "face_id": "05", "record_uid": "role-1",
         "text_cn": "角色级语境", "silent": False},
        {"ident": "hero", "face_id": "05", "record_uid": "role-2",
         "text_cn": "第二条角色级语境", "silent": False},
        {"ident": "hero", "face_id": "05", "record_uid": "variant-1",
         "spine_signature": "sig", "outfit_key": "school",
         "text_cn": "精确变体语境", "silent": True, "actions": ["stiff"]},
    ])
    result = assetdb.official_face_usage(
        con, ident="hero", face_ids=["05"], spine_signature="sig",
        outfit_key="school", representative_limit=3,
    )
    assert [item["text"] for item in result["05"]] == ["精确变体语境"]
    assert con.execute("select count(*) from face_visual_label").fetchone()[0] == 0

    fallback = assetdb.official_face_usage(
        con, ident="hero", face_ids=["05"], representative_limit=1,
    )
    assert len(fallback["05"]) == 1


def test_runtime_loader_reads_sqlite_and_filters_faces(tmp_path):
    db = tmp_path / "assets.db"
    con = assetdb.connect(db)
    assetdb.replace_face_official_usage(con, [{
        "ident": "hero", "face_id": "05", "record_uid": "r1",
        "text_cn": "适合此脸", "emoticons": ["!"],
    }])
    con.close()
    result = load_face_examples(
        {"主角": {"id": "hero", "spine_signature": "", "outfit_key": ""}},
        {"hero": {"faces": [{"id": "05"}, {"id": "06"}]}},
        db_path=db,
    )
    assert set(result["hero"]) == {"05"}
    assert result["hero"]["05"][0]["text"] == "适合此脸"


def test_official_usage_profile_separates_lexical_pause_and_no_dialogue(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.replace_face_official_usage(con, [
        {"ident": "aris", "face_id": "02", "record_uid": "r1", "text_cn": "……"},
        {"ident": "aris", "face_id": "02", "record_uid": "r2", "text_cn": "（咻……）"},
        {"ident": "aris", "face_id": "02", "record_uid": "r3", "silent": True},
        {"ident": "aris", "face_id": "05", "record_uid": "r4", "text_cn": "探索任务开始了！"},
    ])
    profiles = assetdb.official_face_usage_profiles(
        con, ident="aris", face_ids=["02", "05"]
    )
    assert profiles["02"]["lexical_dialogue_count"] == 0
    assert profiles["02"]["nonlexical_dialogue_count"] == 2
    assert profiles["02"]["no_dialogue_count"] == 1
    assert profiles["05"]["lexical_dialogue_count"] == 1


def test_normal_aris_runtime_identity_reads_base_official_face_usage(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.replace_face_official_usage(con, [{
        "ident": "아리스", "face_id": "02", "record_uid": "base-1",
        "text_cn": "平静报告。",
    }])

    examples = assetdb.official_face_usage(
        con, ident="아리스N", face_ids=["02"]
    )
    profiles = assetdb.official_face_usage_profiles(
        con, ident="아리스N", face_ids=["02"]
    )

    assert examples["02"][0]["text"] == "平静报告。"
    assert profiles["02"]["lexical_dialogue_count"] == 1


def test_runtime_identity_usage_merges_with_base_alias_per_face(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    assetdb.replace_face_official_usage(con, [
        {"ident": "아리스", "face_id": "02", "record_uid": "base-1",
         "text_cn": "基础身份语境。"},
        {"ident": "아리스N", "face_id": "02", "record_uid": "runtime-1",
         "text_cn": "运行身份语境。"},
    ])

    examples = assetdb.official_face_usage(
        con, ident="아리스N", face_ids=["02"], representative_limit=3
    )
    profiles = assetdb.official_face_usage_profiles(
        con, ident="아리스N", face_ids=["02"]
    )

    assert {item["text"] for item in examples["02"]} == {
        "运行身份语境。", "基础身份语境。",
    }
    assert profiles["02"]["total_count"] == 2


def test_visual_prompt_keeps_official_context_as_weak_evidence(tmp_path):
    class Provider:
        model = "test"
        def __init__(self):
            self.calls = []
        def complete_json_vision(self, system, images, user, schema):
            self.calls.append((system, user))
            ids = images[0][0].split(":", 1)[1].split(",")
            return {"items": [_compact_label(face_id) for face_id in ids]}

    provider = Provider()
    label_face_images(
        provider,
        [_face(tmp_path, "05", (200, 120, 80))],
        max_attempts=1,
        official_usage={"05": [{"text": "官方语境", "silent": False, "actions": ["jump"]}]},
        official_profiles={"05": {
            "total_count": 8, "lexical_dialogue_count": 7,
            "nonlexical_dialogue_count": 0, "no_dialogue_count": 1,
        }},
    )
    system, user = provider.calls[0]
    assert "OFFICIAL_USAGE_CONTEXT" in user
    assert "官方语境" in user
    assert "OFFICIAL_USAGE_PROFILE" in user
    assert "正常词汇台词=7" in user
    assert "不能据此推断眼睛、眉毛、嘴巴" in user
    assert "官方文本/动作只帮助判断该脸适合的剧情拍点" in system
