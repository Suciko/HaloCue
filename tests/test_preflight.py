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
    assert codes >= {"speaker_unmapped", "missing_custom_asset"}
