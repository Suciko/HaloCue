# -*- coding: utf-8 -*-
"""角色识别（guess_mapping）行为契约：跳过占位垃圾别名、精确名优先、保留 voice 别名。"""

import assetdb
import webui


def _make_con(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("桃井（防寒服-冬装）", "桃井", r"characters\NP0235_spr\NP0235_spr", "overrides"),
    )
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("???", "???", "", "observed"),
    )
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("45145456", None, None, "observed"),
    )
    # 高用量的占位垃圾别名（bug 来源）+ 真实 voice 别名
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('桃井','???','portrait',8)"
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('老师','45145456','voice',9)"
    )
    con.commit()
    return con


def test_guess_skips_placeholder_alias_and_prefers_exact_name(tmp_path, monkeypatch):
    """脚本里写「桃井」应命中用户导入的真实角色，而不是别名里的占位 ???。"""
    monkeypatch.setattr(webui, "db", lambda: _make_con(tmp_path))
    out = webui.guess_mapping([{"who": "桃井"}])
    assert out["桃井"]["id"] == "桃井（防寒服-冬装）"
    assert out["桃井"]["kind"] == "portrait"


def test_guess_treats_teacher_as_non_character_even_with_voice_alias(tmp_path, monkeypatch):
    """A teacher narration label must not be rebound through historical voice data."""
    monkeypatch.setattr(webui, "db", lambda: _make_con(tmp_path))
    out = webui.guess_mapping([{"who": "老师"}])
    assert out["老师"] == {"kind": "narrator"}


def test_guess_marks_unknown_speaker_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(webui, "db", lambda: _make_con(tmp_path))
    out = webui.guess_mapping([{"who": "神秘人"}])
    assert out["神秘人"] == {"kind": "unset"}


def test_guess_prefers_base_variant_over_learned_different_identity(tmp_path, monkeypatch):
    """「凯伊」应命中基础版（name='凯伊'），而不是被学到的别名带偏到变体。"""
    con = _make_con(tmp_path)
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("1516544", "凯伊", None, "custom"),
    )
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("626652156", "凯伊（约会服）", None, "custom"),
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('凯伊','626652156','portrait',8)"
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('凯伊','1516544','portrait',1)"
    )
    con.commit()
    monkeypatch.setattr(webui, "db", lambda: con)
    out = webui.guess_mapping([{"who": "凯伊"}])
    assert out["凯伊"]["id"] == "1516544"
    assert out["凯伊"]["name"] == "凯伊"


def test_guess_prefers_learned_official_character_over_exact_override_outfit(
    tmp_path, monkeypatch
):
    """Plain character names must not be captured by an imported outfit variant."""
    con = _make_con(tmp_path)
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("爱丽丝（防寒服-冬装）", "爱丽丝", "winter", "overrides"),
    )
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("아리스N", "愛麗絲", "official", "observed"),
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('爱丽丝','???N','portrait',8)"
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('爱丽丝','아리스N','portrait',4)"
    )
    con.commit()
    monkeypatch.setattr(webui, "db", lambda: con)

    out = webui.guess_mapping([{"who": "爱丽丝"}])

    assert out["爱丽丝"]["id"] == "아리스N"
    assert out["爱丽丝"]["name"] == "爱丽丝"


def test_guess_prefers_official_default_spine_when_alias_points_to_variant(
    tmp_path, monkeypatch
):
    """A translated plain name must resolve to the default official spine."""
    con = _make_con(tmp_path)
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("아리스", "愛麗絲", "CharacterSpine_aris", "observed"),
    )
    con.execute(
        "INSERT INTO character(ident,name,spine,source) VALUES(?,?,?,?)",
        ("아리스N", "愛麗絲", "CharacterSpine_aris_noweapon", "observed"),
    )
    con.execute(
        "INSERT INTO name_alias(script_name,ident,kind,uses) VALUES('爱丽丝','아리스N','portrait',8)"
    )
    con.commit()
    monkeypatch.setattr(webui, "db", lambda: con)

    out = webui.guess_mapping([{"who": "爱丽丝"}])

    assert out["爱丽丝"]["id"] == "아리스"
    assert out["爱丽丝"]["spine"] == "CharacterSpine_aris"


def test_non_character_speaker_is_not_a_blocking_unmapped_character(
    tmp_path, monkeypatch
):
    con = _make_con(tmp_path)
    monkeypatch.setattr(webui, "db", lambda: con)

    out = webui.guess_mapping([{"who": "系统消息"}])

    assert out["系统消息"] == {"kind": "narrator"}
    assert webui.is_non_character_speaker("系统消息") is True


def test_guess_lookup_does_not_seed_or_mutate_alias_table(tmp_path, monkeypatch):
    con = _make_con(tmp_path)
    before = con.execute("SELECT COUNT(*) FROM name_alias").fetchone()[0]
    monkeypatch.setattr(webui, "db", lambda: con)

    webui.guess_mapping([{"who": "桃井"}])

    after = con.execute("SELECT COUNT(*) FROM name_alias").fetchone()[0]
    assert after == before
