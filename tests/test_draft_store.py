# -*- coding: utf-8 -*-
import os
import sys
import shutil
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore, _parse_draft_nodes


@pytest.fixture
def temp_draft_dir(tmp_path):
    store_dir = tmp_path / "drafts"
    store = DraftStore(base_dir=str(store_dir))
    return store


def test_create_and_load_draft(temp_draft_dir):
    store = temp_draft_dir
    token = "test-token-1"
    sample_text = "## 场景1\n凯伊: 你好，老师！\n"

    draft = store.create_draft(token=token, text=sample_text, project="测试项目")
    assert draft["session"]["draft_token"] == token
    assert draft["session"]["project"] == "测试项目"
    assert len(draft["identities"]) == 2
    assert draft["identity_rebuilt"] is False

    loaded = store.load_draft(token)
    assert loaded["session"]["draft_token"] == token
    assert loaded["edited_text"] == sample_text
    assert loaded["identity_rebuilt"] is False


def test_wrapped_cast_prevents_actor_unbound_diagnostics_after_create_and_edit(temp_draft_dir):
    """Using the persisted cast envelope must keep bound dialogue valid across edits."""
    store = temp_draft_dir
    token = "wrapped-cast-draft"
    cast = {
        "default_bg": "BG_Black",
        "cast": {
            "旁白": {"narrator": True},
            "凯伊": {"id": "kei", "name": "凯伊", "portrait": True},
        },
    }
    created = store.create_draft(
        token=token,
        text="旁白: 开场。\n凯伊: 出发。\n",
        project="演员映射测试",
        cast=cast,
    )
    assert not [d for d in created["diagnostics"] if d["code"] == "actor.unbound"]

    kei_card = created["identities"][1]
    updated = store.update_card_content(
        token=token,
        card_id=kei_card["card_id"],
        patch={"text": "现在出发。"},
        expected_draft_version=1,
    )
    assert not [d for d in updated["diagnostics"] if d["code"] == "actor.unbound"]


def test_loading_legacy_draft_recomputes_stale_diagnostics_without_writing_files(temp_draft_dir):
    """Existing drafts with persisted false positives must recover on read only."""
    store = temp_draft_dir
    token = "legacy-stale-diagnostics"
    store.create_draft(
        token=token,
        text="旁白: 开场。\n",
        project="旧诊断测试",
        cast={"cast": {"旁白": {"narrator": True}}},
    )
    diagnostics_file = store.get_draft_path(token) / "diagnostics.json"
    stale = [{
        "code": "actor.unbound",
        "severity": "error",
        "line_no": 1,
        "card_id": None,
        "message": "演员表里没有「旁白」，此行跳过",
    }]
    diagnostics_file.write_text(
        json.dumps(stale, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    before = diagnostics_file.stat().st_mtime_ns

    loaded = store.load_draft(token)

    assert loaded["diagnostics"] == []
    assert diagnostics_file.stat().st_mtime_ns == before
    assert json.loads(diagnostics_file.read_text(encoding="utf-8")) == stale


def test_markdown_thematic_break_is_preserved_without_blocking_diagnostic(temp_draft_dir):
    """A Markdown scene separator is content structure, not an unparsable line."""
    store = temp_draft_dir
    created = store.create_draft(
        token="markdown-separator-draft",
        text="旁白: 第一幕。\n---\n旁白: 第二幕。\n",
        project="分隔线测试",
        cast={"cast": {"旁白": {"narrator": True}}},
    )
    assert created["edited_text"] == "旁白: 第一幕。\n---\n旁白: 第二幕。\n"
    assert len(created["identities"]) == 3
    assert not [d for d in created["diagnostics"] if d["code"] == "line.unparsable"]


def test_create_draft_does_not_create_blank_cards(temp_draft_dir):
    created = temp_draft_dir.create_draft(
        token="blank-card-regression",
        text="旁白: 第一行。\n\n---\n\n旁白: 第二行。\n",
        project="结构测试",
        cast={"cast": {"旁白": {"narrator": True}}},
    )

    assert created["edited_text"] == "旁白: 第一行。\n\n---\n\n旁白: 第二行。\n"
    assert len(created["identities"]) == 3
    assert not any(
        diagnostic["code"] == "draft.blank_node"
        for diagnostic in created["diagnostics"]
    )


def test_partial_annotation_status_is_persisted_and_blocks_review_gate(temp_draft_dir):
    status = {
        "status": "partial",
        "completed_targets": 2,
        "total_targets": 4,
        "pending_targets": 2,
        "pending_start_line": 3,
        "pending_end_line": 4,
    }
    created = temp_draft_dir.create_draft(
        token="partial-annotation",
        text="旁白: 一\n旁白: 二\n",
        annotation_status=status,
    )

    assert created["session"]["annotation_status"] == status
    with pytest.raises(Exception) as exc_info:
        temp_draft_dir.assert_annotation_complete("partial-annotation")
    assert getattr(exc_info.value, "code", None) == "annotation_incomplete"


def test_list_sessions_derives_generation_from_project_and_source_without_writes(temp_draft_dir):
    """Same-source generations are v1/v2; a changed source starts a new lineage."""
    store = temp_draft_dir
    store.create_draft(
        token="same-source-one", text="旁白: 草稿一。\n", source_text="旁白: 原文。\n",
        project="同一工程",
    )
    store.create_draft(
        token="same-source-two", text="旁白: 草稿二。\n", source_text="旁白: 原文。\n",
        project="同一工程",
    )
    store.create_draft(
        token="changed-source", text="旁白: 新原文草稿。\n", source_text="旁白: 原文已修改。\n",
        project="同一工程",
    )

    sessions = {item["draft_token"]: item for item in store.list_sessions()}

    assert sessions["same-source-one"]["generation_version"] == 1
    assert sessions["same-source-two"]["generation_version"] == 2
    assert sessions["changed-source"]["generation_version"] == 1
    assert all(
        "generation_version" not in json.loads(
            (store.get_draft_path(token) / "session.json").read_text(encoding="utf-8")
        )
        for token in sessions
    )


def test_sha256_tamper_triggers_identity_rebuild(temp_draft_dir):
    store = temp_draft_dir
    token = "test-token-tamper"
    sample_text = "## 场景1\n凯伊: 第一句\n"

    store.create_draft(token=token, text=sample_text, project="测试项目")

    # 外部修改 edited.txt
    edited_file = Path(store.get_draft_path(token)) / "edited.txt"
    edited_file.write_text("## 场景1\n凯伊: 外部修改了台词！\n", encoding="utf-8")

    # 再次加载，校验失败，自动触发 identity 重建
    loaded = store.load_draft(token)
    assert loaded["identity_rebuilt"] is True
    assert "外部修改了台词" in loaded["edited_text"]
    # 检查 session.json 中新的 sha256 已被重写
    assert loaded["session"]["edited_sha256"] != ""


def test_normalization_rebuild_preserves_trusted_review_states(temp_draft_dir):
    from document import parse_document_lossless
    from draft_identity import assign_identity

    store = temp_draft_dir
    token = "legacy-reviewed-blank-cards"
    text = "旁白: 第一行。\n\n---\n\n旁白: 第二行。\n"
    store.create_draft(
        token=token,
        text=text,
        project="已审迁移测试",
        cast={"cast": {"旁白": {"narrator": True}}},
    )
    draft_dir = store.get_draft_path(token)

    legacy_identities = assign_identity(parse_document_lossless(text))
    for identity in legacy_identities:
        identity.review_state = "approved"
    identity_text = json.dumps(
        [identity.to_dict() for identity in legacy_identities],
        ensure_ascii=False,
        indent=2,
    )
    (draft_dir / "identity.json").write_text(identity_text, encoding="utf-8")
    session = json.loads((draft_dir / "session.json").read_text(encoding="utf-8"))
    session["identity_sha256"] = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
    (draft_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    loaded = store.load_draft(token)

    assert loaded["identity_rebuilt"] is True
    assert len(loaded["identities"]) == 3
    assert {card["review_state"] for card in loaded["identities"]} == {"approved"}


def test_resolving_redundant_background_request_keeps_draft_identity_consistent(
    temp_draft_dir,
):
    """Resolving to the active background must not defer an identity rebuild."""
    store = temp_draft_dir
    text = (
        "@bg BG_GameDevRoom\n"
        "Narrator: intro\n"
        "# \u5f85\u751f\u6210\u81ea\u5b9a\u4e49\u80cc\u666f\uff1afirst\n"
        "Narrator: middle\n"
        "# \u5f85\u751f\u6210\u81ea\u5b9a\u4e49\u80cc\u666f\uff1asecond\n"
        "Narrator: end\n"
    )
    created = store.create_draft(
        token="redundant-background-resolution",
        text=text,
        project="background consistency",
    )
    request_ids = [
        card["card_id"]
        for node, card in zip(
            _parse_draft_nodes(created["edited_text"]),
            created["identities"],
        )
        if node.kind == "background_request"
    ]

    first = store.resolve_background_request(
        token="redundant-background-resolution",
        card_id=request_ids[0],
        bg_name="BG_Black",
        expected_draft_version=1,
    )
    assert first["merged_backgrounds"] == 0
    second = store.resolve_background_request(
        token="redundant-background-resolution",
        card_id=request_ids[1],
        bg_name="BG_Black",
        expected_draft_version=first["session"]["draft_version"],
    )
    assert second["merged_backgrounds"] == 1

    resolved_nodes = _parse_draft_nodes(second["edited_text"])
    assert len(second["identities"]) == len(resolved_nodes)
    assert not any(node.kind == "background_request" for node in resolved_nodes)

    loaded = store.load_draft("redundant-background-resolution")
    assert loaded["identity_rebuilt"] is False
    assert [card["card_id"] for card in loaded["identities"]] == [
        card["card_id"] for card in second["identities"]
    ]


@pytest.mark.parametrize("unsafe_token", [
    "..\\outside",
    ".",
    "..",
    "\\\\server\\share",
    "CON",
])
def test_draft_path_rejects_unsafe_token_components(temp_draft_dir, unsafe_token):
    """A token must never be able to select a path outside the drafts root."""
    with pytest.raises(ValueError, match="draft token"):
        temp_draft_dir.get_draft_path(unsafe_token)


def test_draft_path_rejects_an_absolute_token_and_keeps_valid_token(tmp_path):
    """Joining an absolute token must not discard the configured drafts root."""
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    with pytest.raises(ValueError, match="draft token"):
        store.get_draft_path(str(tmp_path / "outside"))

    assert store.get_draft_path("draft-compatible-1") == (
        tmp_path / "drafts" / "draft-compatible-1"
    ).resolve()


def test_find_asset_references_reports_safe_card_locations_without_mutating_versions(tmp_path):
    """Dropping a scanned reference or exposing script text would make this fail."""
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    token = "asset-reference-draft"
    cast = {
        "cast": {
            "阿洛娜": {"kind": "character", "key": "custom_arona"},
        }
    }
    created = store.create_draft(
        token=token,
        text="@bg rain_roof\n@se door_open\n阿洛娜: 欢迎回来\n",
        cast=cast,
    )
    draft_dir = store.get_draft_path(token)
    cards = json.loads((draft_dir / "identity.json").read_text(encoding="utf-8"))
    for card, card_id in zip(cards, ("bg-1", "se-1", "line-1")):
        card["card_id"] = card_id
    identity_text = json.dumps(cards, ensure_ascii=False, indent=2)
    (draft_dir / "identity.json").write_text(identity_text, encoding="utf-8")
    session = json.loads((draft_dir / "session.json").read_text(encoding="utf-8"))
    session["identity_sha256"] = hashlib.sha256(
        identity_text.encode("utf-8")
    ).hexdigest()
    (draft_dir / "session.json").write_text(
        json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    before = dict(session)
    assert store.find_asset_references(
        token=token, kind="background", aa_key="rain_roof"
    ) == [{
        "card_id": "bg-1",
        "kind": "directive",
        "label": "@bg rain_roof",
        "line_hint": 1,
    }]
    assert store.find_asset_references(
        token=token, kind="sound", aa_key="door_open"
    ) == [{
        "card_id": "se-1",
        "kind": "directive",
        "label": "@se door_open",
        "line_hint": 2,
    }]
    assert store.find_asset_references(
        token=token, kind="character", aa_key="custom_arona"
    ) == [{
        "card_id": "line-1",
        "kind": "line",
        "label": "阿洛娜",
        "line_hint": 3,
    }]

    after = json.loads((draft_dir / "session.json").read_text(encoding="utf-8"))
    assert after["draft_version"] == before["draft_version"]
    assert after["content_revision"] == before["content_revision"]
    assert "欢迎回来" not in repr(store.find_asset_references(
        token=token, kind="character", aa_key="custom_arona"
    ))
    assert str(tmp_path) not in repr(store.find_asset_references(
        token=token, kind="background", aa_key="rain_roof"
    ))
