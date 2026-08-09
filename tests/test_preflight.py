# -*- coding: utf-8 -*-
import json

import assetdb
import webui
from asset_catalog import list_story_assets, story_asset_preview, upsert_candidate
from asset_models import AssetCandidate


def _candidate(kind, source, stem, key, catalog_source):
    return AssetCandidate(
        kind, source, stem, key, "digest-" + key,
        {"catalog_source": catalog_source},
    )


def test_story_asset_list_only_returns_registered_custom_sources(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    scope = str(tmp_path / "project")
    source = tmp_path / "source.png"
    source.write_bytes(b"preview")
    for key, status, catalog_source in (
        ("custom", "registered", "custom"),
        ("history", "registered", "history_import"),
        ("observed", "registered", "observed"),
        ("verified", "verified", "custom"),
    ):
        upsert_candidate(
            con, _candidate("background", source, key, key, catalog_source),
            scope=scope, status=status, install_path=str(source),
        )

    result = list_story_assets(con, scope=scope)

    assert [row["aa_key"] for row in result["backgrounds"]] == ["custom", "history"]
    assert story_asset_preview(con, scope=scope, kind="background", aa_key="observed") is None
    assert story_asset_preview(con, scope=scope, kind="background", aa_key="verified") is None


def test_preflight_ignores_builtin_refs_and_reports_only_story_custom_assets(tmp_path, monkeypatch):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: None)
    con = assetdb.connect(database)
    con.execute("INSERT INTO bg(name,hash,label) VALUES('BG_Black',1,'黑屏')")
    con.execute("INSERT INTO sound(name,label) VALUES('SE_Click','点击')")
    con.execute(
        "INSERT INTO character(ident,name,club,spine,source) VALUES('hero-id','凯伊','','hero','custom')"
    )
    scope = str(tmp_path / "project")
    source = tmp_path / "asset.bin"
    source.write_bytes(b"custom")
    for kind, key, name in (
        ("character", "hero-id", "凯伊"),
        ("background", "rain", "雨夜"),
        ("sound", "thunder", "雷声"),
    ):
        upsert_candidate(
            con, _candidate(kind, source, name, key, "custom"),
            scope=scope, status="registered", install_path=str(source),
            display_name=name,
        )
    con.close()
    script = tmp_path / "story.txt"
    script.write_text(
        "@bg BG_Black\n@bg rain\n@se SE_Click\n@sound thunder\n@bgm 999\n凯伊: 开始。\n",
        encoding="utf-8",
    )

    result = webui._preflight_result(str(script), scope=scope)

    assert [(row["kind"], row["name"], row["status"]) for row in result["assets"]] == [
        ("background", "rain", "registered"),
        ("sound", "thunder", "registered"),
    ]
    assert result["characters"][0]["custom"] is True
    assert result["character_library"]["total"] == 1
    assert not [issue for issue in result["issues"] if issue["severity"] == "error"]
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_preflight_prefers_the_current_story_custom_outfit_and_keeps_it_from_ai_override(
    tmp_path, monkeypatch
):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.executemany(
        "INSERT INTO character(ident,name,club,spine,source) VALUES(?,?,?,?,?)",
        [
            ("1516544", "凯伊", "特殊现象调查部", "", "observed"),
            ("626652156", "凯伊（约会服）", "约会短篇", "", "custom"),
        ],
    )
    scope = str(tmp_path / "project")
    source = tmp_path / "Kei_Date_Outfit.skel"
    source.write_bytes(b"spine")
    upsert_candidate(
        con,
        _candidate("character", source, "Kei_Date_Outfit", "626652156", "history_import"),
        scope=scope,
        status="registered",
        install_path=str(source),
        display_name="凯伊（约会服）",
    )
    con.close()

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [{
                    "speaker": "凯伊", "kind": "portrait", "id": "1516544",
                    "name": "凯伊", "custom": False, "confidence": 0.99,
                    "reason": "模型选择了普通服装",
                }],
                "assets": [], "usage_chain": [], "issues": [],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("凯伊：今天按约会行程走。\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=scope)

    kei = result["characters"][0]
    assert kei["id"] == "626652156"
    assert kei["name"] == "凯伊"
    assert kei["custom"] is True


def test_preflight_voice_mapping_uses_the_screenplay_speaker_as_display_name(
    tmp_path, monkeypatch
):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("shop-clerk", None, None, "observed"),
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('店员','shop-clerk','voice',9)"
    )
    con.commit()
    con.close()

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [{
                    "speaker": "店员", "kind": "voice", "id": "shop-clerk",
                    "name": "shop-clerk", "custom": False, "confidence": 0.9,
                    "reason": "语音角色",
                }],
                "assets": [], "usage_chain": [], "issues": [],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("店员：欢迎光临。\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["characters"][0]["name"] == "店员"


def test_ai_cannot_mark_a_missing_asset_as_registered(tmp_path, monkeypatch):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.execute(
        "INSERT INTO character(ident,name,club,spine,source) VALUES('hero-id','凯伊','','hero','observed')"
    )
    con.commit()
    con.close()

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [{
                    "speaker": "凯伊", "kind": "portrait", "id": "hero-id", "name": "凯伊",
                    "custom": False, "confidence": 0.9, "reason": "候选匹配",
                }],
                "assets": [{
                    "kind": "background", "name": "不存在", "status": "registered",
                    "location": "任意位置", "reason": "模型误判",
                }],
                "issues": [],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("@bg 不存在\n凯伊: 测试。\n@bad-command value\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["assets"][0]["status"] == "missing"
    assert result["assets"][0]["location"] == "第1行"
    assert {issue["code"] for issue in result["issues"]} >= {
        "missing_custom_asset", "unknown_directive",
    }


def test_nonstandard_script_blocks_when_full_text_ai_review_did_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: None)
    script = tmp_path / "freeform.md"
    script.write_text(
        "雨夜的天台上，凯伊望向远处。\n她说今天也辛苦了。\n",
        encoding="utf-8",
    )

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["analysis"]["format"]["confidence"] == "low"
    assert result["ai_status"] == "not_configured"
    blocking = [item for item in result["issues"] if item["severity"] == "error"]
    assert {item["code"] for item in blocking} == {"nonstandard_format_requires_ai"}
    assert "配置可用模型" in blocking[0]["action"]


def test_ai_can_discover_roles_and_assets_in_nonstandard_full_text(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [{
                    "speaker": "凯伊", "kind": "unset", "id": "", "name": "凯伊",
                    "custom": True, "confidence": 0.72, "reason": "小说正文中的说话角色",
                }],
                "assets": [{
                    "kind": "background", "name": "雨夜天台", "status": "missing",
                    "location": "开场描述", "reason": "正文明确描述场景",
                }, {
                    "kind": "sound", "name": "雨声", "status": "missing",
                    "location": "环境描写", "reason": "正文需要持续雨声",
                }],
                "usage_chain": [],
                "issues": [],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "freeform.md"
    script.write_text(
        "雨夜的天台上，凯伊望向远处。\n她轻声说，今天也辛苦了。\n",
        encoding="utf-8",
    )

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["ai_status"] == "completed"
    assert result["characters"][0]["speaker"] == "凯伊"
    assert result["characters"][0]["detected_by"] == "ai"
    assert {(item["kind"], item["name"]) for item in result["assets"]} == {
        ("background", "雨夜天台"), ("sound", "雨声"),
    }
    codes = {item["code"] for item in result["issues"]}
    assert "nonstandard_format_requires_ai" not in codes
    assert codes >= {"speaker_unmapped", "background_asset_suggestion", "optional_asset_suggestion"}
    assert "missing_custom_asset" not in codes


def test_ai_builds_a_natural_language_scene_usage_chain_and_background_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute("INSERT INTO bg(name,hash,label) VALUES('BG_Classroom',1,'教室')")
    con.execute("INSERT INTO sound(name,label) VALUES('SE_Door','开门声')")
    con.commit()
    con.close()

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [],
                "assets": [],
                "usage_chain": [{
                    "segment": "开场",
                    "location": "教室",
                    "start": "第1行",
                    "end": "第2行",
                    "evidence": "教室里，凯伊推开门。",
                    "needs": [
                        {"kind": "background", "name": "教室", "location": "第1行", "reason": "正文明确场景", "confidence": 0.95},
                        {"kind": "bgm", "name": "轻松日常", "location": "第1行", "reason": "气氛平静", "confidence": 0.62},
                        {"kind": "sound", "name": "开门声", "location": "第2行", "reason": "正文描述动作", "confidence": 0.88},
                    ],
                }, {
                    "segment": "转场",
                    "location": "夜间天台",
                    "start": "第3行",
                    "end": "第4行",
                    "evidence": "夜色中的天台很安静。",
                    "needs": [{"kind": "background", "name": "夜间天台", "location": "第3行", "reason": "官方库没有相近背景", "confidence": 0.91}],
                }],
                "issues": [],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "freeform.md"
    script.write_text(
        "教室里，凯伊推开门。\n夜色中的天台很安静。\n",
        encoding="utf-8",
    )

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["ai_status"] == "completed"
    assert result["usage_chain_status"] == "completed"
    assert [item["segment"] for item in result["usage_chain"]] == ["开场", "转场"]
    needs = [need for item in result["usage_chain"] for need in item["needs"]]
    by_key = {(need["kind"], need["name"]): need for need in needs}
    assert by_key[("background", "教室")]["status"] == "builtin"
    assert by_key[("background", "教室")]["aa_key"] == "BG_Classroom"
    assert by_key[("sound", "开门声")]["status"] == "builtin"
    assert by_key[("bgm", "轻松日常")]["status"] == "unsupported"
    assert by_key[("background", "夜间天台")]["status"] == "missing"
    assert "夜间天台" in by_key[("background", "夜间天台")]["generation_prompt"]
    assert "低噪点" in by_key[("background", "夜间天台")]["generation_prompt"]
    assert "无颗粒" in by_key[("background", "夜间天台")]["generation_prompt"]
    assert "无 JPEG 压缩伪影" in by_key[("background", "夜间天台")]["generation_prompt"]
    assert str(tmp_path) not in by_key[("background", "夜间天台")]["generation_prompt"]


def test_usage_chain_compacts_long_start_and_end_but_keeps_full_evidence(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    evidence = "休息日下午，商店街入口的钟塔下。凯伊催促大家尽快出发。"
    start = "旁白：休息日下午，商店街入口的钟塔下。\n远处传来钟声，来往的人群渐渐多了起来。"
    end = "凯伊：全身上下就嘴巴最灵光……走了！再不出发，才真的要偏离计划了。所有人都跟上。"
    try:
        chain, _refs = webui._normalize_usage_chain([{
            "segment": "场景 1：商店街钟塔集合",
            "location": "商店街入口的钟塔下",
            "start": start,
            "end": end,
            "evidence": evidence,
            "needs": [{
                "kind": "background", "name": "商店街入口钟塔",
                "location": "开场", "reason": "正文明确场景", "confidence": 0.95,
            }],
        }], {"backgrounds": [], "sounds": [], "bgms": []}, con)
    finally:
        con.close()

    assert len(chain[0]["start"]) <= 32
    assert len(chain[0]["end"]) <= 32
    assert chain[0]["start"].endswith("…")
    assert chain[0]["end"].endswith("…")
    assert "\n" not in chain[0]["start"]
    assert chain[0]["evidence"] == evidence


def test_usage_chain_keeps_only_verified_official_background_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "_background_preview_available", lambda _name: False)
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO bg(name,hash,label,tags) VALUES(?,?,?,?)",
        ("BG_ShoppingDistrict", 101, "Shopping District", "shopping,district"),
    )
    con.commit()
    try:
        chain, refs = webui._normalize_usage_chain([{
            "segment": "场景一", "location": "商店街入口钟塔", "start": "开场",
            "end": "集合后", "evidence": "众人在商店街入口的钟塔下集合。",
            "needs": [{
                "kind": "background", "name": "商店街入口钟塔",
                "location": "场景一", "reason": "表现集合地点", "confidence": 0.95,
                "candidates": [{
                    "aa_key": "BG_MadeUpClockTower", "confidence": 0.99,
                    "reason": "模型编造的素材",
                }, {
                    "aa_key": "BG_ShoppingDistrict", "confidence": 0.70,
                    "reason": "已有商店街背景，但没有突出钟塔",
                }],
            }],
        }], {"backgrounds": [], "sounds": [], "bgms": []}, con)
    finally:
        con.close()

    need = chain[0]["needs"][0]
    assert need["status"] == "approximate"
    assert need["candidates"] == [{
        "aa_key": "BG_ShoppingDistrict",
        "label": "Shopping District",
        "source": "official",
        "preview_source": "official",
        "confidence": 0.70,
        "reason": "已有商店街背景，但没有突出钟塔",
        "preview_available": False,
    }]
    assert "商店街入口钟塔" in need["generation_prompt"]
    assert refs[0]["status"] == "approximate"


def test_usage_chain_suggests_catalog_background_when_ai_returns_no_candidate(tmp_path):
    """A missing AI candidate must not hide a close official scene from review."""
    con = assetdb.connect(tmp_path / "assets.db")
    con.executemany(
        "INSERT INTO bg(name,hash,label,time,tags) VALUES(?,?,?,?,?)",
        [
            ("BG_MainOffice_Night", 101, "Main Office", "\u591c\u665a", "main,office"),
            ("BG_CityOffice_Night", 102, "City Office", "\u591c\u665a", "city,office"),
            ("BG_Park_Night", 103, "Park", "\u591c\u665a", "park,outdoor"),
        ],
    )
    con.commit()
    try:
        chain, _refs = webui._normalize_usage_chain([{
            "segment": "\u5f53\u665a", "location": "\u672a\u660e\u786e", "start": "\u7b2c1\u884c", "end": "\u7b2c2\u884c",
            "evidence": "\u8001\u5e08\u6536\u5230\u6d88\u606f\u65f6\u7684\u73af\u5883\uff0c\u65f6\u95f4\u4e3a\u591c\u665a\u3002",
            "needs": [{
                "kind": "background", "name": "\u591c\u665a\u5ba4\u5185", "location": "\u7b2c1\u884c",
                "reason": "\u8001\u5e08\u6536\u5230\u6d88\u606f\u65f6\u7684\u73af\u5883\uff0c\u65f6\u95f4\u4e3a\u591c\u665a\u3002", "confidence": 0.60,
                "candidates": [],
            }],
        }], {"backgrounds": [], "sounds": [], "bgms": []}, con)
    finally:
        con.close()

    need = chain[0]["needs"][0]
    assert need["status"] == "approximate"
    assert need["candidates"][0]["aa_key"] == "BG_MainOffice_Night"
    assert need["candidates"][0]["source"] == "official"


def test_usage_chain_hides_custom_background_workflow_at_or_above_ninety_percent(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        ("BG_ShoppingDistrict", 101, "Shopping District"),
    )
    con.commit()
    try:
        def normalize(confidence):
            chain, _refs = webui._normalize_usage_chain([{
                "segment": "场景一", "location": "商店街", "start": "开场",
                "end": "结束", "evidence": "众人在商店街集合。",
                "needs": [{
                    "kind": "background", "name": "商店街钟塔", "location": "场景一",
                    "reason": "表现集合地点", "confidence": 0.95,
                    "candidates": [{
                        "aa_key": "BG_ShoppingDistrict", "confidence": confidence,
                        "reason": "官方商店街背景没有钟塔细节",
                    }],
                }],
            }], {"backgrounds": [], "sounds": [], "bgms": []}, con)
            return chain[0]["needs"][0]

        assert "generation_prompt" in normalize(0.89)
        assert "generation_prompt" not in normalize(0.90)
    finally:
        con.close()


def test_usage_chain_does_not_hide_missing_background_with_weak_candidate(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        ("BG_ShoppingDistrict", 101, "Shopping District"),
    )
    con.commit()
    try:
        chain, _refs = webui._normalize_usage_chain([{
            "segment": "场景一", "location": "钟塔内部", "start": "开场",
            "end": "结束", "evidence": "众人进入钟塔机械室。",
            "needs": [{
                "kind": "background", "name": "钟塔机械室",
                "location": "场景一", "reason": "剧情依赖内部机械结构", "confidence": 0.95,
                "candidates": [{
                    "aa_key": "BG_ShoppingDistrict", "confidence": 0.59,
                    "reason": "只有室外商店街，差异过大",
                }],
            }],
        }], {"backgrounds": [], "sounds": [], "bgms": []}, con)
    finally:
        con.close()

    need = chain[0]["needs"][0]
    assert need["status"] == "missing"
    assert need["candidates"] == []
    assert "钟塔机械室" in need["generation_prompt"]


def test_preflight_exposes_official_background_catalog_to_model(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO bg(name,hash,label,tags) VALUES(?,?,?,?)",
        ("BG_ShoppingDistrict", 101, "Shopping District", "shopping,district"),
    )
    con.commit()
    con.close()
    captured = {}

    class Provider:
        def complete_json(self, _static, volatile, _user, _schema):
            captured.update(json.loads(volatile))
            return {"characters": [], "assets": [], "usage_chain": [], "issues": []}

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("旁白：商店街入口。\n", encoding="utf-8")

    webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert captured["official_backgrounds"] == [{
        "aa_key": "BG_ShoppingDistrict", "label": "Shopping District",
        "place": "", "time": "", "mood": "", "tags": "shopping,district",
    }]


def test_background_library_collapses_duplicate_variants_before_limit(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.executemany(
        "INSERT INTO bg(name,hash,label,tags) VALUES(?,?,?,?)",
        [
            (f"BG_A_Variant_{index:04d}", index + 1, "Repeated Street", "street")
            for index in range(810)
        ] + [("BG_ShoppingDistrict", 9999, "Shopping District", "shopping,district")],
    )
    con.commit()
    try:
        library = webui._preflight_background_library(con)
    finally:
        con.close()

    assert [item["aa_key"] for item in library] == [
        "BG_A_Variant_0000", "BG_ShoppingDistrict"
    ]


def test_ai_audio_suggestions_are_optional_but_explicit_audio_directives_block(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [], "assets": [], "issues": [],
                "usage_chain": [{
                    "segment": "开场", "location": "商店街", "start": "第1行",
                    "end": "第1行", "evidence": "街上传来人声。",
                    "needs": [{
                        "kind": "sound", "name": "环境人声喧嚣", "location": "开场",
                        "reason": "增强街道氛围", "confidence": 0.75,
                    }, {
                        "kind": "bgm", "name": "轻松日常BGM", "location": "开场",
                        "reason": "增强轻松氛围", "confidence": 0.80,
                    }],
                }],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    ai_script = tmp_path / "ai.txt"
    ai_script.write_text("旁白：街上传来人声。\n", encoding="utf-8")
    explicit_script = tmp_path / "explicit.txt"
    explicit_script.write_text(
        "@sound SE_NotRegistered\n@bgm BGM_NotRegistered\n旁白：街上传来人声。\n",
        encoding="utf-8",
    )

    ai_result = webui._preflight_result(str(ai_script), scope=str(tmp_path / "ai-project"))
    explicit_result = webui._preflight_result(
        str(explicit_script), scope=str(tmp_path / "explicit-project")
    )

    ai_issue = next(item for item in ai_result["issues"] if "环境人声喧嚣" in item["message"])
    bgm_issue = next(item for item in ai_result["issues"] if "轻松日常BGM" in item["message"])
    directive_issue = next(
        item for item in explicit_result["issues"] if "SE_NotRegistered" in item["message"]
    )
    bgm_directive_issue = next(
        item for item in explicit_result["issues"] if "BGM_NotRegistered" in item["message"]
    )
    assert ai_issue["severity"] == "warning"
    assert ai_issue["code"] == "optional_asset_suggestion"
    assert bgm_issue["severity"] == "warning"
    assert bgm_issue["code"] == "optional_asset_suggestion"
    assert directive_issue["severity"] == "error"
    assert directive_issue["code"] == "missing_custom_asset"
    assert bgm_directive_issue["severity"] == "error"
    assert bgm_directive_issue["code"] == "bgm_not_supported"


def test_explicit_background_with_no_available_file_is_not_builtin(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute("INSERT INTO bg(name,hash,label) VALUES('BG_Pending',NULL,'待复核背景')")
    con.commit()
    try:
        refs = webui._preflight_asset_refs(
            "@bg BG_Pending\n", {"backgrounds": [], "sounds": [], "bgms": []}, con
        )
    finally:
        con.close()

    assert [(item["name"], item["status"]) for item in refs] == [("BG_Pending", "missing")]


def test_usage_chain_exact_background_with_no_available_file_stays_missing(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute("INSERT INTO bg(name,hash,label) VALUES('BG_Pending',NULL,'待复核背景')")
    con.commit()
    try:
        chain, refs = webui._normalize_usage_chain([{
            "segment": "开场", "location": "街道", "start": "第1行", "end": "第1行",
            "evidence": "夜色中的街道。", "needs": [{
                "kind": "background", "name": "待复核背景", "location": "第1行",
                "reason": "夜景", "confidence": 0.9,
            }],
        }], {"backgrounds": [], "sounds": [], "bgms": []}, con)
    finally:
        con.close()

    need = chain[0]["needs"][0]
    assert need["status"] == "missing"
    assert "aa_key" not in need
    assert refs[0]["status"] == "missing"


def test_legacy_ai_asset_does_not_trust_background_with_no_available_file(tmp_path, monkeypatch):
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    con = assetdb.connect(database)
    con.execute("INSERT INTO bg(name,hash,label) VALUES('BG_Pending',NULL,'待复核背景')")
    con.commit()
    con.close()

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [], "issues": [], "usage_chain": [],
                "assets": [{
                    "kind": "background", "name": "BG_Pending", "status": "builtin",
                    "location": "开场", "reason": "夜景",
                }],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("旁白：夜色中的街道。\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    ref = next(item for item in result["assets"] if item["name"] == "BG_Pending")
    assert ref["status"] == "missing"
    assert ref["detected_by"] == "ai"


def test_usage_chain_suppresses_duplicate_model_asset_warnings(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO bg(name,hash,label,tags) VALUES(?,?,?,?)",
        ("BG_ShoppingDistrict", 101, "Shopping District", "shopping,district"),
    )
    con.commit()
    con.close()

    class Provider:
        def complete_json(self, *_args):
            return {
                "characters": [],
                "assets": [{
                    "kind": "background", "name": "商店街入口/钟塔",
                    "status": "missing", "location": "场景一", "reason": "旧素材清单别名",
                }],
                "usage_chain": [{
                    "segment": "场景一", "location": "商店街入口钟塔", "start": "开场",
                    "end": "集合后", "evidence": "众人在商店街入口集合。",
                    "needs": [{
                        "kind": "background", "name": "商店街入口钟塔",
                        "location": "场景一", "reason": "集合地点", "confidence": 0.95,
                        "candidates": [{
                            "aa_key": "BG_ShoppingDistrict", "confidence": 0.70,
                            "reason": "商店街近似背景",
                        }],
                    }],
                }],
                "issues": [{
                    "severity": "error", "code": "background_custom_assets_missing",
                    "message": "自定义背景缺失。", "action": "补充背景。",
                }],
            }

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("旁白：商店街入口。\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert [(item["kind"], item["name"], item["status"]) for item in result["assets"]] == [
        ("background", "商店街入口钟塔", "approximate")
    ]
    assert not any("自定义背景缺失" in item["message"] for item in result["issues"])
    assert not any(item["code"] == "background_asset_suggestion" for item in result["issues"])


def test_ai_failure_returns_safe_diagnostics_and_unavailable_usage_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))

    class Provider:
        name = "openai"
        model = "test-model"

        def complete_json(self, *_args):
            raise RuntimeError("HTTP 502: api_key=secret-value upstream timeout")

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("凯伊：你好\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["ai_status"] == "failed"
    assert result["usage_chain_status"] == "unavailable"
    assert result["usage_chain"] == []
    assert result["ai_diagnostics"]["stage"] == "model_call"
    assert "HTTP 502" in result["ai_diagnostics"]["message"]
    assert "secret-value" not in result["ai_diagnostics"]["message"]


def test_ai_retries_once_after_incompatible_structured_response(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))

    class Provider:
        def __init__(self):
            self.calls = 0

        def complete_json(self, *_args):
            self.calls += 1
            if self.calls == 1:
                return {"characters": [], "assets": [], "issues": []}
            return {
                "characters": [],
                "assets": [],
                "usage_chain": [{
                    "segment": "开场",
                    "location": "钟塔下",
                    "start": "第1行",
                    "end": "第2行",
                    "evidence": "旁白: 钟塔下。",
                    "needs": [{
                        "kind": "background", "name": "钟塔下", "location": "第1行",
                        "reason": "正文明确地点", "confidence": 0.9,
                    }],
                }],
                "issues": [],
            }

    provider = Provider()
    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: provider)
    script = tmp_path / "story.txt"
    script.write_text("旁白: 钟塔下。\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert provider.calls == 2
    assert result["ai_status"] == "completed"
    assert result["usage_chain_status"] == "completed"
    assert result["usage_chain"][0]["segment"] == "开场"


def test_ai_structured_failure_is_reported_separately_after_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))

    class Provider:
        def complete_json(self, *_args):
            return {"characters": [], "assets": [], "issues": []}

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("旁白: 钟塔下。\n", encoding="utf-8")

    result = webui._preflight_result(str(script), scope=str(tmp_path / "project"))

    assert result["ai_status"] == "failed"
    assert result["usage_chain_status"] == "unavailable"
    assert result["ai_diagnostics"]["stage"] == "structured_output"
    assert "结构化 JSON" in next(
        issue["action"] for issue in result["issues"] if issue["code"] == "ai_preflight_failed"
    )


def test_custom_background_candidate_normalization_is_story_scoped_and_labeled(tmp_path, monkeypatch):
    """Model output cannot promote an unlabeled, forged, or other-story custom key."""
    monkeypatch.setattr(webui, "_background_preview_available", lambda name: name == "BG_Official")
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO bg(name,hash,label) VALUES(?,?,?)",
        ("BG_Official", 101, "官方候车厅"),
    )
    con.commit()
    custom_assets = {
        "backgrounds": [{
            "aa_key": 9001, "name": "自定义雨夜候车厅", "preview_available": True,
            "labels": {"label": "雨夜候车厅", "place": "车站", "time": "夜晚"},
        }, {
            "aa_key": 9002, "name": "未标注图片", "preview_available": True,
        }],
        "sounds": [], "bgms": [],
    }
    try:
        chain, _refs = webui._normalize_usage_chain([{
            "segment": "开场", "location": "车站", "start": "第1行", "end": "第2行",
            "evidence": "雨夜的候车厅。", "needs": [{
                "kind": "background", "name": "雨夜候车厅", "location": "第1行",
                "reason": "正文明确场景", "confidence": 0.95,
                "candidates": [
                    {"aa_key": "9002", "confidence": 0.99, "reason": "没有语义"},
                    {"aa_key": "forged-other-story", "confidence": 0.98, "reason": "伪造"},
                    {"aa_key": "9001", "confidence": 0.88, "reason": "本章自定义雨夜车站"},
                    {"aa_key": "BG_Official", "confidence": 0.75, "reason": "官方候车厅近似"},
                ],
            }],
        }], custom_assets, con)
    finally:
        con.close()

    candidates = chain[0]["needs"][0]["candidates"]
    assert candidates == [{
        "aa_key": "9001", "label": "雨夜候车厅", "source": "custom",
        "preview_source": "story", "preview_available": True,
        "confidence": 0.88, "reason": "本章自定义雨夜车站",
    }, {
        "aa_key": "BG_Official", "label": "官方候车厅", "source": "official",
        "preview_source": "official", "preview_available": True,
        "confidence": 0.75, "reason": "官方候车厅近似",
    }]
    assert chain[0]["needs"][0]["suggested_aa_key"] == "9001"


def test_custom_background_candidate_model_input_excludes_unlabeled_and_other_scope(
    tmp_path, monkeypatch
):
    """Only labeled backgrounds registered in this story are semantic candidates sent to AI."""
    database = tmp_path / "assets.db"
    monkeypatch.setattr(webui, "DB", str(database))
    current_scope = str(tmp_path / "current")
    other_scope = str(tmp_path / "other")
    source = tmp_path / "background.png"
    source.write_bytes(b"preview")
    con = assetdb.connect(database)
    for scope, key, labels in (
        (current_scope, "current-labeled", {"label": "雨夜车站", "place": "车站"}),
        (current_scope, "current-unlabeled", {}),
        (other_scope, "other-labeled", {"label": "别章天台", "place": "天台"}),
    ):
        upsert_candidate(
            con,
            AssetCandidate(
                "background", source, key, key, "digest-" + key,
                {"catalog_source": "custom", "labels": labels},
            ),
            scope=scope, status="registered", install_path=str(source), display_name=key,
        )
    con.close()
    captured = {}

    class Provider:
        def complete_json(self, _static, volatile, _user, _schema):
            captured.update(json.loads(volatile))
            return {"characters": [], "assets": [], "usage_chain": [], "issues": []}

    monkeypatch.setattr(webui, "annotation_provider", lambda _profile=None: Provider())
    script = tmp_path / "story.txt"
    script.write_text("旁白：雨夜的车站。\n", encoding="utf-8")

    webui._preflight_result(str(script), scope=current_scope)

    assert captured["custom_backgrounds"] == [{
        "aa_key": "current-labeled", "label": "雨夜车站", "name": "current-labeled",
        "description": "", "place": "车站", "indoor_outdoor": "", "time": "",
        "weather": "", "season": "", "mood": "", "tags": "",
        "source": "custom", "preview_available": True,
    }]
    assert "current-unlabeled" not in json.dumps(captured["custom_backgrounds"])
    assert "other-labeled" not in json.dumps(captured)
    assert str(tmp_path) not in json.dumps(captured, ensure_ascii=False)
