# -*- coding: utf-8 -*-
"""Removing a workbench copy is scoped, reference-aware, and recoverable."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

import asset_catalog
import assetdb
from aa_registry import load_manifest, write_manifest_atomic
from asset_models import AssetCandidate
from asset_validation import validate_background
from draft_store import DraftStore
from history_assets import HistoryAssetBrowser, HistoryAssetError
from story_workspace import StoryContext, normalize_bgm_policy


def _context(aa_data: Path, chapter: str, draft_token: str | None = None) -> StoryContext:
    return StoryContext(
        story_token=f"story-{chapter}",
        project=chapter,
        project_dir=aa_data / "projects" / chapter,
        save_dir=aa_data / "saves" / chapter,
        source_path=None,
        latest_draft_token=draft_token,
        bgm_default=normalize_bgm_policy(None),
    )


@dataclass
class RemovalFixture:
    browser: HistoryAssetBrowser
    con: object
    store: DraftStore
    first: StoryContext
    tokens: dict[str, str]


def removal_fixture(tmp_path: Path, *, referenced: bool = False) -> RemovalFixture:
    aa_data = tmp_path / "aa-data"
    con = assetdb.connect(tmp_path / "assets.db")
    store = DraftStore(base_dir=str(tmp_path / "drafts"))
    first_draft = "draft-first" if referenced else None
    contexts = {
        "第一章": _context(aa_data, "第一章", first_draft),
        "第二章": _context(aa_data, "第二章"),
    }
    digest = ""
    for chapter, context in contexts.items():
        project_file = context.project_dir / "bgs" / "rain_roof.png"
        save_file = context.save_dir / "bgs" / "rain_roof.png"
        project_file.parent.mkdir(parents=True)
        save_file.parent.mkdir(parents=True)
        Image.new("RGB", (32, 18), "navy").save(project_file)
        save_file.write_bytes(project_file.read_bytes())
        for root in (context.project_dir, context.save_dir):
            write_manifest_atomic(root, {"BgOverrides": [r"bgs\rain_roof.png"]})
        validation = validate_background(project_file)
        digest = validation.candidate.sha256
        asset_catalog.upsert_candidate(
            con,
            AssetCandidate(
                "background",
                project_file,
                "rain_roof",
                "rain_roof",
                digest,
                metadata={"catalog_source": "history_import"},
            ),
            scope=str(context.project_dir),
            status="registered",
            install_path=str(project_file),
            display_name="雨夜天台",
        )
    if referenced:
        store.create_draft(
            token=first_draft,
            text="@bg rain_roof\n",
            project="第一章",
            story_token=contexts["第一章"].story_token,
        )
    browser = HistoryAssetBrowser(aa_data=aa_data)
    payload = browser.list_library(con, current_context=contexts["第一章"])
    copies = payload["backgrounds"][0]["copies"]
    return RemovalFixture(
        browser=browser,
        con=con,
        store=store,
        first=contexts["第一章"],
        tokens={copy["chapter"]: copy["copy_token"] for copy in copies},
    )


def test_remove_copy_is_blocked_when_current_draft_references_asset(tmp_path):
    """Deleting an in-use copy would leave the current draft uncompilable."""
    fixture = removal_fixture(tmp_path, referenced=True)

    with pytest.raises(HistoryAssetError) as error:
        fixture.browser.remove_copy(
            fixture.tokens["第一章"], con=fixture.con, draft_store=fixture.store
        )

    assert error.value.code == "asset_in_use"
    assert error.value.details["references"][0]["card_id"]
    assert load_manifest(fixture.first.project_dir)["BgOverrides"]


def test_remove_copy_only_removes_selected_chapter_and_keeps_profile(tmp_path):
    """A chapter removal must not become a series-wide delete."""
    fixture = removal_fixture(tmp_path)
    item = fixture.browser.list_library(
        fixture.con, current_context=fixture.first
    )["backgrounds"][0]
    asset_catalog.update_library_profile(
        fixture.con,
        kind="background",
        aa_key="rain_roof",
        sha256=item["sha256"],
        asset_role="series_shared",
        series_name="凯伊约会篇",
    )

    fixture.browser.remove_copy(
        fixture.tokens["第二章"], con=fixture.con, draft_store=fixture.store
    )
    payload = fixture.browser.list_library(fixture.con, current_context=fixture.first)

    assert payload["backgrounds"][0]["copy_count"] == 1
    assert payload["backgrounds"][0]["copies"][0]["chapter"] == "第一章"
    assert payload["backgrounds"][0]["series_name"] == "凯伊约会篇"
    assert fixture.con.execute(
        "SELECT count(*) FROM asset_install WHERE scope LIKE ?", ("%第二章",)
    ).fetchone()[0] == 0


def test_remove_copy_rejects_a_confirmation_for_another_chapter(tmp_path):
    """Client confirmation text cannot retarget an opaque chapter token."""
    fixture = removal_fixture(tmp_path)

    with pytest.raises(HistoryAssetError) as error:
        fixture.browser.remove_copy(
            fixture.tokens["第二章"],
            con=fixture.con,
            draft_store=fixture.store,
            confirm_chapter="第一章",
        )

    assert error.value.code == "copy_confirmation_mismatch"
