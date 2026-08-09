# -*- coding: utf-8 -*-
"""Historical AA assets are read-only inputs to a current-story import."""

from pathlib import Path
import shutil
import wave
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
import pytest
import aa_registry
import assetdb
import history_assets

from aa_registry import load_manifest, write_manifest_atomic
from history_assets import HistoryAssetBrowser, HistoryAssetError
from story_workspace import StoryContext, normalize_bgm_policy


def _story(project: str, aa_data: Path) -> StoryContext:
    return StoryContext(
        story_token="story-current",
        project=project,
        project_dir=aa_data / "projects" / project,
        save_dir=aa_data / "saves" / project,
        source_path=None,
        latest_draft_token=None,
        bgm_default=normalize_bgm_policy(None),
    )


def _background(path: Path, color: str = "navy") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), color).save(path)


def _sound(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\0\0" * 2205)


def _character(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "hero.skel").write_bytes(b"spine 4.2.33")
    (root / "hero.atlas").write_text(
        "hero.png\nsize: 32,32\nformat: RGBA8888\n\n00_default\n  rotate: false\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (32, 32), "white").save(root / "hero.png")
    Image.new("RGBA", (16, 16), "white").save(root / "hero-avatar.png")


def reusable_background_fixture(tmp_path):
    aa_data = tmp_path / "aa-data"
    source_project = aa_data / "projects" / "Source"
    source = source_project / "bgs" / "rain_roof.png"
    _background(source)
    write_manifest_atomic(source_project, {"BgOverrides": [r"bgs\rain_roof.png"]})
    con = assetdb.connect(tmp_path / "assets.db")
    digest = history_assets.validate_background(source).candidate.sha256
    history_assets.upsert_candidate(
        con,
        history_assets.AssetCandidate(
            "background", source, "rain_roof", "rain_roof", digest,
            metadata={"catalog_source": "history_import"},
        ),
        scope=str(source_project), status="registered", install_path=str(source),
        display_name="Rain Roof",
    )
    browser = HistoryAssetBrowser(aa_data=aa_data)
    current = _story("Current", aa_data)
    source_token = browser.list_library(con, current_context=current)["backgrounds"][0]["copies"][0]["copy_token"]
    return browser, con, source_token, current


def test_library_copy_reuses_history_transaction_and_is_idempotent(tmp_path):
    """Replacing the shared transaction would break both registration and duplicate detection."""
    browser, con, source_token, current = reusable_background_fixture(tmp_path)

    first = browser.copy_library_asset(source_token, current, con=con)
    second = browser.copy_library_asset(source_token, current, con=con)

    assert first["state"] == "registered"
    assert second["state"] == "already_registered"
    assert second["asset"]["aa_key"] == "rain_roof"


def test_history_copy_survives_history_project_removal(tmp_path):
    """Replacing a copy operation with a source reference would break after deletion."""
    aa_data = tmp_path / "aa-data"
    history_root = aa_data / "projects" / "History"
    _background(history_root / "bgs" / "night.png")
    write_manifest_atomic(history_root, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)

    history = browser.list_projects()[0]
    token = browser.asset_token(history, kind="background", key="night")
    result = browser.copy_to_story(token, _story("Current", aa_data))

    shutil.rmtree(history_root)
    assert Path(result["install_path"]).is_file()
    assert load_manifest(aa_data / "projects" / "Current")["BgOverrides"] == [r"bgs\night.png"]
    assert load_manifest(aa_data / "saves" / "Current")["BgOverrides"] == [r"bgs\night.png"]


def test_history_discovery_rejects_manifest_path_outside_project(tmp_path):
    """Dropping commonpath validation would expose an arbitrary local file."""
    aa_data = tmp_path / "aa-data"
    history_root = aa_data / "projects" / "History"
    history_root.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    _background(outside)
    write_manifest_atomic(history_root, {"BgOverrides": [str(outside)]})

    browser = HistoryAssetBrowser(aa_data=aa_data)
    history = browser.list_projects()[0]

    assert browser.list_assets(history["history_token"]) == []


def test_history_bgm_is_not_listed_or_copyable_without_native_contract(tmp_path):
    """Adding BgmOverrides to the browser before a verified contract is a bug."""
    aa_data = tmp_path / "aa-data"
    history_root = aa_data / "projects" / "History"
    audio = history_root / "bgms" / "theme.ogg"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"not a registered BGM contract")
    write_manifest_atomic(history_root, {"BgmOverrides": [r"bgms\theme.ogg"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    history = browser.list_projects()[0]

    assert browser.list_assets(history["history_token"]) == []
    try:
        browser.asset_token(history, kind="bgm", key="theme")
    except HistoryAssetError as exc:
        assert exc.code == "history_asset_not_found"
    else:
        raise AssertionError("history BGM was exposed despite the contract gate")


def test_history_copy_supports_manifested_sound_and_character_assets(tmp_path):
    """Treating every history record as a background would lose native AA types."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    _sound(history / "sounds" / "click.wav")
    _character(history / "characters" / "custom-hero")
    write_manifest_atomic(history, {
        "SoundOverrides": [r"sounds\click.wav"],
        "CharacterOverrides": [{
            "Identifier": "custom-hero", "Name": "Hero", "Nickname": "Archive",
            "SpinePortraitPath": r"characters\custom-hero\hero",
            "SmallPortraitPath": r"characters\custom-hero\hero-avatar.png",
        }],
    })
    browser = HistoryAssetBrowser(aa_data=aa_data)
    history_project = browser.list_projects()[0]
    assets = browser.list_assets(history_project["history_token"])
    tokens = {row["kind"]: row["history_asset_token"] for row in assets}

    browser.copy_to_story(tokens["sound"], _story("Current", aa_data))
    browser.copy_to_story(tokens["character"], _story("Current", aa_data))

    for root in (aa_data / "projects" / "Current", aa_data / "saves" / "Current"):
        manifest = load_manifest(root)
        assert manifest["SoundOverrides"] == [r"sounds\click.wav"]
        assert manifest["CharacterOverrides"][0]["Identifier"] == "custom-hero"
        assert (root / "sounds" / "click.wav").is_file()
        assert (root / "characters" / "custom-hero" / "hero.skel").is_file()


@pytest.mark.parametrize(
    ("portrait_path", "create_other"),
    [
        ("<absolute>", False),
        (r"..\..\outside.png", False),
        (r"characters\custom-hero\missing-avatar.png", False),
        (r"characters\custom-hero\other-avatar.png", True),
    ],
    ids=("absolute", "escaped", "missing", "does-not-match-spine-avatar"),
)
def test_history_character_requires_a_safe_existing_matching_small_portrait(
    tmp_path, portrait_path, create_other
):
    """Ignoring SmallPortraitPath lets malformed character manifests cross the UI boundary."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    character_root = history / "characters" / "custom-hero"
    _character(character_root)
    if create_other:
        Image.new("RGBA", (16, 16), "red").save(character_root / "other-avatar.png")
    if portrait_path == "<absolute>":
        portrait_path = str(tmp_path / "outside-avatar.png")
    write_manifest_atomic(history, {"CharacterOverrides": [{
        "Identifier": "custom-hero", "Name": "Hero", "Nickname": "Archive",
        "SpinePortraitPath": r"characters\custom-hero\hero",
        "SmallPortraitPath": portrait_path,
    }]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    project = browser.list_projects()[0]

    assert browser.list_assets(project["history_token"]) == []


def test_history_project_root_symlink_escaping_canonical_projects_is_skipped(tmp_path):
    """Trusting a projects child name without resolving it permits junction escapes."""
    aa_data = tmp_path / "aa-data"
    outside = tmp_path / "outside-project"
    _background(outside / "bgs" / "night.png")
    write_manifest_atomic(outside, {"BgOverrides": [r"bgs\night.png"]})
    projects = aa_data / "projects"
    projects.mkdir(parents=True)
    escaped = projects / "Escaped"
    try:
        escaped.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable in this environment: {exc}")

    browser = HistoryAssetBrowser(aa_data=aa_data)

    assert browser.list_projects() == []


@pytest.mark.parametrize("kind", ("background", "sound"))
def test_history_copy_uses_one_immutable_snapshot_when_source_changes_mid_copy(
    tmp_path, monkeypatch, kind
):
    """Reading the source separately for project and save would split the mirrored bytes."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    if kind == "background":
        source = history / "bgs" / "night.png"
        _background(source, "navy")
        manifest = {"BgOverrides": [r"bgs\night.png"]}
        changed = b"changed background bytes"
    else:
        source = history / "sounds" / "click.wav"
        _sound(source)
        manifest = {"SoundOverrides": [r"sounds\click.wav"]}
        changed = source.read_bytes() + b"changed sound bytes"
    original = source.read_bytes()
    write_manifest_atomic(history, manifest)
    browser = HistoryAssetBrowser(aa_data=aa_data)
    history_project = browser.list_projects()[0]
    token = browser.asset_token(history_project, kind=kind, key=source.stem)
    real_copy = aa_registry._copy_new_file_atomically
    copies = 0

    def copy_then_mutate(copy_source, destination):
        nonlocal copies
        real_copy(copy_source, destination)
        copies += 1
        if copies == 1:
            source.write_bytes(changed)

    monkeypatch.setattr(aa_registry, "_copy_new_file_atomically", copy_then_mutate)
    browser.copy_to_story(token, _story("Current", aa_data))

    for root in (aa_data / "projects" / "Current", aa_data / "saves" / "Current"):
        folder = "bgs" if kind == "background" else "sounds"
        assert (root / folder / source.name).read_bytes() == original


def test_history_asset_token_is_stable_under_concurrent_lookup(tmp_path):
    """Unsynchronized token issuance can race into different opaque handles."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    _background(history / "bgs" / "night.png")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    history_project = browser.list_projects()[0]

    with ThreadPoolExecutor(max_workers=12) as pool:
        tokens = list(pool.map(
            lambda _: browser.asset_token(history_project, kind="background", key="night"),
            range(100),
        ))

    assert len(set(tokens)) == 1


def test_history_character_copy_uses_the_validated_aggregate_snapshot(tmp_path, monkeypatch):
    """A character's aggregate hash must cover every staged Spine member."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    character = history / "characters" / "custom-hero"
    _character(character)
    write_manifest_atomic(history, {"CharacterOverrides": [{
        "Identifier": "custom-hero", "Name": "Hero", "Nickname": "",
        "SpinePortraitPath": r"characters\custom-hero\hero",
        "SmallPortraitPath": r"characters\custom-hero\hero-avatar.png",
    }]})
    original = (character / "hero.skel").read_bytes()
    browser = HistoryAssetBrowser(aa_data=aa_data)
    project = browser.list_projects()[0]
    token = browser.asset_token(project, kind="character", key="custom-hero")
    real_copy = aa_registry._copy_new_file_atomically
    copied = 0

    def copy_then_mutate(copy_source, destination):
        nonlocal copied
        real_copy(copy_source, destination)
        copied += 1
        if copied == 1:
            (character / "hero.skel").write_bytes(b"replaced after staging")

    monkeypatch.setattr(aa_registry, "_copy_new_file_atomically", copy_then_mutate)
    browser.copy_to_story(token, _story("Current", aa_data))

    for root in (aa_data / "projects" / "Current", aa_data / "saves" / "Current"):
        assert (root / "characters" / "custom-hero" / "hero.skel").read_bytes() == original


def test_history_asset_token_becomes_stale_when_manifested_bytes_change(tmp_path):
    """A token must bind source contents, not just a filename that can be replaced."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    source = history / "bgs" / "night.png"
    _background(source, "navy")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    history_project = browser.list_projects()[0]
    token = browser.asset_token(history_project, kind="background", key="night")
    _background(source, "red")

    with pytest.raises(HistoryAssetError) as raised:
        browser.copy_to_story(token, _story("Current", aa_data))

    assert raised.value.code == "history_asset_stale"
    assert raised.value.status == 410


def test_history_copy_rechecks_signed_content_after_record_lookup(tmp_path, monkeypatch):
    """Changing bytes in the lookup-to-validation window must not import a new asset under an old token."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    source = history / "bgs" / "night.png"
    _background(source, "navy")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    project = browser.list_projects()[0]
    token = browser.asset_token(project, kind="background", key="night")
    current_record = browser._current_record

    def lookup_then_replace(asset_token):
        record = current_record(asset_token)
        _background(source, "red")
        return record

    monkeypatch.setattr(browser, "_current_record", lookup_then_replace)
    with pytest.raises(HistoryAssetError) as raised:
        browser.copy_to_story(token, _story("Current", aa_data))

    assert raised.value.code == "history_asset_stale"
    assert raised.value.status == 410
    assert not (aa_data / "projects" / "Current" / "bgs" / "night.png").exists()


def test_history_copy_returns_410_when_source_disappears_after_record_lookup(tmp_path, monkeypatch):
    """A deletion between signed lookup and validation is a missing source, not an invalid asset."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    source = history / "bgs" / "night.png"
    _background(source, "navy")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    project = browser.list_projects()[0]
    token = browser.asset_token(project, kind="background", key="night")
    current_record = browser._current_record

    def lookup_then_remove(asset_token):
        record = current_record(asset_token)
        source.unlink()
        return record

    monkeypatch.setattr(browser, "_current_record", lookup_then_remove)
    with pytest.raises(HistoryAssetError) as raised:
        browser.copy_to_story(token, _story("Current", aa_data))

    assert raised.value.code == "history_source_missing"
    assert raised.value.status == 410


def test_history_asset_token_cache_is_bounded(tmp_path):
    """Unbounded historical token retention turns repeated scans into a server memory leak."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    for name in ("one", "two", "three"):
        _background(history / "bgs" / f"{name}.png")
    write_manifest_atomic(history, {"BgOverrides": [
        r"bgs\one.png", r"bgs\two.png", r"bgs\three.png",
    ]})
    browser = HistoryAssetBrowser(aa_data=aa_data, max_asset_tokens=2)
    project = browser.list_projects()[0]
    browser.list_assets(project["history_token"])

    assert len(browser._assets) == 2


def test_history_manifest_symlink_outside_project_is_not_scanned(tmp_path):
    """A manifest symlink is a source boundary too, not just an asset-path boundary."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    _background(history / "bgs" / "night.png")
    outside_manifest = tmp_path / "outside-manifest.json"
    outside_manifest.write_text('{"BgOverrides":["bgs\\\\night.png"]}', encoding="utf-8")
    history.mkdir(parents=True, exist_ok=True)
    try:
        (history / "manifest.json").symlink_to(outside_manifest)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable in this environment: {exc}")

    browser = HistoryAssetBrowser(aa_data=aa_data)

    assert browser.list_projects() == []


def test_catalog_failure_rolls_back_the_project_and_save_asset_transaction(tmp_path, monkeypatch):
    """A catalog write failure after registration must not leave an untracked AA asset."""
    aa_data = tmp_path / "aa-data"
    history = aa_data / "projects" / "History"
    _background(history / "bgs" / "night.png")
    write_manifest_atomic(history, {"BgOverrides": [r"bgs\night.png"]})
    browser = HistoryAssetBrowser(aa_data=aa_data)
    history_project = browser.list_projects()[0]
    token = browser.asset_token(history_project, kind="background", key="night")
    con = assetdb.connect(tmp_path / "assets.db")

    def broken_catalog(*args, **kwargs):
        raise RuntimeError("injected catalog failure")

    monkeypatch.setattr(history_assets, "upsert_candidate", broken_catalog)
    with pytest.raises(HistoryAssetError) as raised:
        browser.copy_to_story(token, _story("Current", aa_data), con=con)

    assert raised.value.code == "catalog_failed"
    for root in (aa_data / "projects" / "Current", aa_data / "saves" / "Current"):
        assert not (root / "bgs" / "night.png").exists()
        assert not (root / "manifest.json").exists()
