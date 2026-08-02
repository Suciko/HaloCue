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
from draft_store import DraftStore


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
