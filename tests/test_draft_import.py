# -*- coding: utf-8 -*-
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from draft_store import DraftStore
from picker_token import (
    TokenRegistry,
    register_file_token,
    resolve_file_token,
)


def test_register_and_resolve_file_token(tmp_path):
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello", encoding="utf-8")

    token = register_file_token(str(sample_file))
    assert token.startswith("ft-")

    resolved = resolve_file_token(token)
    assert resolved == str(sample_file.resolve())


def test_expired_file_token_returns_none(tmp_path):
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello", encoding="utf-8")

    registry = TokenRegistry(ttl_seconds=0.1)
    token = registry.register(str(sample_file))

    time.sleep(0.15)
    assert registry.resolve(token) is None


def test_invalid_or_fake_token_returns_none():
    assert resolve_file_token("ft-fake-non-exist-token") is None


def test_import_draft_via_file_token(tmp_path):
    sample_file = tmp_path / "sample.annotated.txt"
    sample_file.write_text("## 场景1\n凯伊: 你好！\n", encoding="utf-8")

    ft_token = register_file_token(str(sample_file))
    real_path = resolve_file_token(ft_token)
    assert real_path is not None

    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    content = Path(real_path).read_text(encoding="utf-8")
    draft_token = "draft-imported-1"

    res = store.create_draft(
        token=draft_token,
        text=content,
        project="导入测试项目",
        source_text=content,
    )
    assert res["session"]["draft_token"] == draft_token
    assert res["session"]["project"] == "导入测试项目"
    assert len(res["identities"]) == 2


def test_imported_draft_freezes_story_context(tmp_path):
    """Dropping the story token would let later project switches retarget a draft."""
    store = DraftStore(base_dir=str(tmp_path / "drafts"))

    result = store.create_draft(
        token="draft-story-context",
        text="## 场景1\n凯伊: 你好\n",
        project="第一章",
        story_token="story-opaque-1",
        bgm_policy={"enabled": False, "arrangement": "manual", "bgmId": 999},
        cast={"cast": {"凯伊": {"id": "kei"}}},
    )

    session = result["session"]
    assert session["project"] == "第一章"
    assert session["story_token"] == "story-opaque-1"
    assert session["bgm_policy"] == {
        "enabled": False,
        "arrangement": "manual",
        "bgmId": 999,
    }


def test_bgm_policy_normalization_merges_defaults_without_losing_valid_values(tmp_path):
    """Partial legacy sessions need safe defaults while complete policies stay intact."""
    from story_workspace import normalize_bgm_policy
    from webui import get_draft_detail_data

    assert normalize_bgm_policy(None) == {
        "enabled": False, "arrangement": "manual", "bgmId": 999,
    }
    assert normalize_bgm_policy({"enabled": True}) == {
        "enabled": True, "arrangement": "manual", "bgmId": 999,
    }
    full_policy = {"enabled": True, "arrangement": "ai", "bgmId": 7}
    assert normalize_bgm_policy(full_policy) == full_policy

    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    partial = store.create_draft(
        token="draft-partial-policy", text="## 场景1\n", project="第一章",
        bgm_policy={"enabled": True},
    )
    assert partial["session"]["bgm_policy"] == {
        "enabled": True, "arrangement": "manual", "bgmId": 999,
    }
    assert get_draft_detail_data("draft-partial-policy", store=store)["bgm_policy"] == {
        "enabled": True, "arrangement": "manual", "bgmId": 999,
    }
